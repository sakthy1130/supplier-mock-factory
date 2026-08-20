"""CRUD and lookups for supplier configuration.

``get_supplier_config(code, env)`` is the replacement for the old
``get_supplier_registry(env)[code]`` and is called from the hot path (contract
provisioning, expectation building, teardown), so configs are cached in-process and
invalidated explicitly on every write — no lru_cache, because a UI edit has to be
visible on the very next scenario build.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.namespace import ALL_SCENARIO_LOG_TYPES
from app.db.database import get_session_factory
from app.db.models import SupplierRecord
from app.env_context import get_current_env
from app.ingest.expectation_builder import OPTIONAL_TEMPLATE_LOG_TYPES
from app.models.supplier import (
    ReadinessCheck,
    SupplierConfig,
    SupplierConfigCreate,
    SupplierListItem,
    SupplierReadiness,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATES_DIR = REPO_ROOT / "templates"

# (code, env) -> SupplierConfig
_CACHE: dict[tuple[str, str], SupplierConfig] = {}
# env -> ordered codes
_CODES_CACHE: dict[str, list[str]] = {}


def invalidate_cache(env: str | None = None) -> None:
    if env is None:
        _CACHE.clear()
        _CODES_CACHE.clear()
        return
    for key in [k for k in _CACHE if k[1] == env]:
        _CACHE.pop(key, None)
    _CODES_CACHE.pop(env, None)


def _record_to_model(record: SupplierRecord) -> SupplierConfig:
    return SupplierConfig(
        id=record.id,
        code=record.code,
        env=record.env,
        name=record.name,
        supplier_type=record.supplier_type,
        supplier_id=record.supplier_id or "",
        auto_id=record.auto_id or 0,
        reference_contract_id=record.reference_contract_id or "",
        default_supplier_currency=record.default_supplier_currency or "USD",
        default_contract_currency=record.default_contract_currency or "USD",
        log_types=list(record.log_types_json or ["Packages"]),
        package_log_types=list(record.package_log_types_json or ["Packages"]),
        ui_color=record.ui_color or "",
        mock_config=record.mock_config_json or {},
        mutation_config=record.mutation_config_json or {},
        field_map=record.field_map_json,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _apply_payload(record: SupplierRecord, payload: SupplierConfigCreate) -> None:
    record.code = payload.code
    record.name = payload.name.strip()
    record.supplier_type = payload.supplier_type
    record.supplier_id = payload.supplier_id.strip()
    record.auto_id = payload.auto_id
    record.reference_contract_id = payload.reference_contract_id.strip()
    record.default_supplier_currency = payload.default_supplier_currency
    record.default_contract_currency = payload.default_contract_currency
    record.log_types_json = payload.log_types
    # Package mutation can only run on log types the supplier actually serves.
    record.package_log_types_json = [
        lt for lt in payload.package_log_types if lt in payload.log_types
    ]
    record.ui_color = payload.ui_color.strip()
    record.mock_config_json = payload.mock_config.model_dump(exclude_none=False)
    record.mutation_config_json = payload.mutation_config.model_dump()
    record.field_map_json = payload.field_map


# ── Reads ──────────────────────────────────────────────────────────────────────


def list_configs(db: Session, env: str | None = None) -> list[SupplierConfig]:
    """Configured suppliers for the env.

    Falls back to the built-in seed definitions when the table can't answer (a database
    that predates the suppliers table, or one that was never initialised), so the
    Suppliers screen and the dashboard show the built-ins instead of an error.
    """
    resolved = env or get_current_env()
    try:
        records = db.scalars(
            select(SupplierRecord)
            .where(SupplierRecord.env == resolved)
            .order_by(SupplierRecord.created_at.asc(), SupplierRecord.code.asc())
        ).all()
    except SQLAlchemyError:
        db.rollback()
        records = []
    if records:
        return [_record_to_model(r) for r in records]
    return [c for c in (_config_from_seed(code, resolved) for code in _seed_codes()) if c]


def _seed_codes() -> list[str]:
    from app.db.seed_suppliers import SEED_SUPPLIERS

    return [spec["code"] for spec in SEED_SUPPLIERS]


def list_items(db: Session, env: str | None = None) -> list[SupplierListItem]:
    """The GET /api/suppliers payload — a superset of the old hardcoded list."""
    items: list[SupplierListItem] = []
    for config in list_configs(db, env):
        readiness = readiness_for(config)
        items.append(
            SupplierListItem(
                code=config.code,
                name=config.name,
                log_types=config.log_types,
                status="v1",
                env=config.env,
                supplier_type=config.supplier_type,
                ui_color=config.ui_color,
                default_supplier_currency=config.default_supplier_currency,
                default_contract_currency=config.default_contract_currency,
                ready=readiness.ready,
                missing_count=len(readiness.missing),
            )
        )
    return items


def get_config(db: Session, code: str, env: str | None = None) -> SupplierConfig:
    resolved = env or get_current_env()
    record = db.scalars(
        select(SupplierRecord).where(
            SupplierRecord.code == code.upper(), SupplierRecord.env == resolved
        )
    ).first()
    if record is None:
        raise HTTPException(
            status_code=404, detail=f"Supplier {code.upper()} is not configured in {resolved}"
        )
    return _record_to_model(record)


class UnknownSupplierError(ValueError):
    """Raised on the non-HTTP path (scenario build, teardown) for an unconfigured code."""


def _config_from_seed(code: str, env: str) -> SupplierConfig | None:
    """Build a config for a built-in supplier straight from the seed definitions.

    Covers the two cases where the table can't answer: a database that hasn't been
    initialised yet, and unit tests that exercise the engine without one. Built-in
    suppliers therefore behave identically with or without a database; only
    UI-added suppliers require the table.
    """
    from app.config import get_settings
    from app.db.seed_suppliers import _BACKOFFICE_IDS, SEED_SUPPLIERS

    spec = next((s for s in SEED_SUPPLIERS if s["code"] == code), None)
    if spec is None:
        return None
    supplier_id, auto_id = _BACKOFFICE_IDS.get(env, _BACKOFFICE_IDS["stg"])[code]
    settings = get_settings(env)
    reference_contract_id = getattr(settings, f"{code.lower()}_reference_contract_id", "") or ""
    return SupplierConfig(
        id=f"seed-{code}-{env}",
        code=code,
        env=env,
        name=spec["name"],
        supplier_type=spec["supplier_type"],
        supplier_id=supplier_id,
        auto_id=auto_id,
        reference_contract_id=reference_contract_id,
        default_supplier_currency=spec["default_supplier_currency"],
        default_contract_currency=spec["default_contract_currency"],
        log_types=list(spec["log_types"]),
        package_log_types=list(spec["package_log_types"]),
        ui_color=spec["ui_color"],
        mock_config=spec["mock_config"],
        mutation_config=spec["mutation_config"],
    )


def get_supplier_config(code: str, env: str | None = None) -> SupplierConfig:
    """Cached config lookup for the scenario-build hot path.

    Opens its own short-lived session so core modules don't need a request-scoped
    ``Session`` threaded through them, exactly as ``get_supplier_registry`` needed
    no session at all.
    """
    resolved = env or get_current_env()
    upper = code.upper()
    key = (upper, resolved)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    config: SupplierConfig | None = None
    try:
        with get_session_factory()() as session:
            record = session.scalars(
                select(SupplierRecord).where(
                    SupplierRecord.code == upper, SupplierRecord.env == resolved
                )
            ).first()
            if record is not None:
                config = _record_to_model(record)
    except SQLAlchemyError:
        # No database (or no suppliers table yet) — fall through to the seed.
        config = None

    if config is None:
        config = _config_from_seed(upper, resolved)
    if config is None:
        raise UnknownSupplierError(
            f"Supplier {upper} is not configured in {resolved}. Add it on the Suppliers screen."
        )
    _CACHE[key] = config
    return config


def configured_codes(env: str | None = None) -> list[str]:
    """Every supplier code configured for the env — teardown and validation use this."""
    resolved = env or get_current_env()
    cached = _CODES_CACHE.get(resolved)
    if cached is not None:
        return cached
    codes: list[str] = []
    try:
        with get_session_factory()() as session:
            codes = list(
                session.scalars(
                    select(SupplierRecord.code)
                    .where(SupplierRecord.env == resolved)
                    .order_by(SupplierRecord.created_at.asc())
                ).all()
            )
    except SQLAlchemyError:
        codes = []
    if not codes:
        from app.db.seed_suppliers import SEED_SUPPLIERS

        codes = [spec["code"] for spec in SEED_SUPPLIERS]
    _CODES_CACHE[resolved] = codes
    return codes


# ── Readiness ──────────────────────────────────────────────────────────────────


def _template_path(code: str, log_type: str) -> Path:
    return TEMPLATES_DIR / code / log_type / "v1.json"


def missing_templates(config: SupplierConfig) -> list[str]:
    return [
        lt
        for lt in config.log_types
        if lt not in OPTIONAL_TEMPLATE_LOG_TYPES and not _template_path(config.code, lt).exists()
    ]


def readiness_for(config: SupplierConfig) -> SupplierReadiness:
    """What still blocks this supplier from building a scenario."""
    from app.plugins import PLUGINS  # local import — plugins import this module

    absent = missing_templates(config)
    present = len(config.log_types) - len(absent)
    plugin = PLUGINS.get(config.code)
    mutation = config.mutation_config

    checks = [
        ReadinessCheck(
            key="backoffice",
            label="Backoffice supplier linked",
            ok=bool(config.supplier_id and config.auto_id),
            detail=(
                f"{config.supplier_id} · autoId {config.auto_id}"
                if config.supplier_id and config.auto_id
                else "supplier ID and auto ID are empty — contract creation will fail"
            ),
            fix="identity",
        ),
        ReadinessCheck(
            key="reference_contract",
            label="Reference contract",
            ok=bool(config.reference_contract_id),
            # Not fatal: _build_contract_body falls back to a minimal body. Still
            # flagged, because a minimal contract misses adapter-specific fields.
            blocking=False,
            detail=(
                config.reference_contract_id
                or "empty — a minimal contract body is built instead of cloning"
            ),
            fix="backoffice",
        ),
        ReadinessCheck(
            key="templates",
            label="Mock templates",
            ok=not absent,
            detail=(
                f"{present} of {len(config.log_types)} log types on disk"
                if not absent
                else f"missing: {', '.join(absent)}"
            ),
            fix="templates",
        ),
        ReadinessCheck(
            key="mutation",
            label="Mutation config",
            # A hand-written plugin does its own mutation, so packages_path is only
            # required when the generic mutator is what will run.
            ok=bool(plugin) or mutation.is_usable,
            detail=(
                f"plugins/{config.code.lower()}.py handles mutation"
                if plugin
                else mutation.packages_path
                or "no packages path — rates cannot be cloned to the requested count"
            ),
            fix="mutation",
        ),
        ReadinessCheck(
            key="linkage",
            label="Linkage check",
            ok=True,
            blocking=False,
            detail=(
                f"board compared on {mutation.board_key}"
                if mutation.board_key
                else "rate-count check only — board is not verified"
            ),
            fix="mutation",
        ),
        ReadinessCheck(
            key="plugin",
            label="Custom Python plugin",
            ok=bool(plugin),
            blocking=False,
            detail=(
                f"plugins/{config.code.lower()}.py overrides the generic mutator"
                if plugin
                else "using the generic mutator — fine for most suppliers"
            ),
        ),
    ]
    return SupplierReadiness(
        code=config.code,
        env=config.env,
        ready=all(c.ok for c in checks if c.blocking),
        checks=checks,
    )


def get_readiness(db: Session, code: str, env: str | None = None) -> SupplierReadiness:
    return readiness_for(get_config(db, code, env))


# ── Writes ─────────────────────────────────────────────────────────────────────


def create_config(db: Session, payload: SupplierConfigCreate, env: str | None = None) -> SupplierConfig:
    resolved = env or get_current_env()
    clash = db.scalars(
        select(SupplierRecord).where(
            SupplierRecord.code == payload.code, SupplierRecord.env == resolved
        )
    ).first()
    if clash is not None:
        raise HTTPException(
            status_code=409, detail=f"Supplier {payload.code} already exists in {resolved}"
        )
    record = SupplierRecord(id=str(uuid.uuid4()), env=resolved)
    _apply_payload(record, payload)
    db.add(record)
    db.commit()
    db.refresh(record)
    invalidate_cache(resolved)
    return _record_to_model(record)


def update_config(
    db: Session,
    code: str,
    payload: SupplierConfigCreate,
    env: str | None = None,
) -> SupplierConfig:
    resolved = env or get_current_env()
    record = db.scalars(
        select(SupplierRecord).where(
            SupplierRecord.code == code.upper(), SupplierRecord.env == resolved
        )
    ).first()
    if record is None:
        raise HTTPException(
            status_code=404, detail=f"Supplier {code.upper()} is not configured in {resolved}"
        )
    if payload.code != record.code:
        raise HTTPException(
            status_code=400,
            detail="Supplier code cannot be changed — delete and re-add instead",
        )
    _apply_payload(record, payload)
    db.commit()
    db.refresh(record)
    invalidate_cache(resolved)
    return _record_to_model(record)


def delete_config(db: Session, code: str, env: str | None = None) -> None:
    from app.db.models import ScenarioRecord

    resolved = env or get_current_env()
    record = db.scalars(
        select(SupplierRecord).where(
            SupplierRecord.code == code.upper(), SupplierRecord.env == resolved
        )
    ).first()
    if record is None:
        raise HTTPException(
            status_code=404, detail=f"Supplier {code.upper()} is not configured in {resolved}"
        )

    # A scenario still referencing this code would lose its teardown path — the
    # expectation ids and contracts are keyed by supplier code.
    in_use = [
        r.namespace
        for r in db.scalars(
            select(ScenarioRecord).where(
                ScenarioRecord.env == resolved, ScenarioRecord.status != "TORN_DOWN"
            )
        ).all()
        if record.code in (r.suppliers_json or [])
    ]
    if in_use:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{record.code} is still used by {len(in_use)} active scenario(s): "
                f"{', '.join(in_use[:5])}. Tear them down first."
            ),
        )

    db.delete(record)
    db.commit()
    invalidate_cache(resolved)


def write_template(code: str, log_type: str, expectation: dict) -> tuple[Path, int]:
    """Write templates/{CODE}/{LogType}/v1.json, creating the directories."""
    import json

    if log_type not in ALL_SCENARIO_LOG_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown log type {log_type}")
    if not isinstance(expectation, dict) or "httpResponse" not in expectation:
        raise HTTPException(
            status_code=400,
            detail="Not a MockServer expectation — expected an object with an httpResponse key",
        )
    path = _template_path(code.upper(), log_type)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(expectation, indent=2, ensure_ascii=False)
    path.write_text(body, encoding="utf-8")
    return path, len(body.encode("utf-8"))
