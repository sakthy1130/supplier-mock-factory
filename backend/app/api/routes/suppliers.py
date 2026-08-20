"""REST API for supplier configuration — what the Suppliers screen talks to.

Everything here is scoped to the active env (X-SMF-Env), because dev and stg have
separate Backoffice supplier records and separate reference contracts.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.env_context import get_current_env
from app.models.supplier import (
    IngestRequest,
    IngestResultModel,
    ProbeResult,
    SupplierConfig,
    SupplierConfigCreate,
    SupplierListItem,
    SupplierReadiness,
    TemplateUploadResult,
)
from app.services import supplier_service

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.get("", response_model=list[SupplierListItem])
def list_suppliers(db: Session = Depends(get_db)) -> list[SupplierListItem]:
    return supplier_service.list_items(db)


@router.get("/configs", response_model=list[SupplierConfig])
def list_supplier_configs(db: Session = Depends(get_db)) -> list[SupplierConfig]:
    """Full configs for the Suppliers screen (the list endpoint stays lightweight)."""
    return supplier_service.list_configs(db)


@router.post("", response_model=SupplierConfig, status_code=201)
def create_supplier(
    payload: SupplierConfigCreate,
    db: Session = Depends(get_db),
) -> SupplierConfig:
    return supplier_service.create_config(db, payload)


@router.get("/{code}", response_model=SupplierConfig)
def get_supplier(code: str, db: Session = Depends(get_db)) -> SupplierConfig:
    return supplier_service.get_config(db, code)


@router.put("/{code}", response_model=SupplierConfig)
def update_supplier(
    code: str,
    payload: SupplierConfigCreate,
    db: Session = Depends(get_db),
) -> SupplierConfig:
    return supplier_service.update_config(db, code, payload)


@router.delete("/{code}", status_code=204)
def delete_supplier(code: str, db: Session = Depends(get_db)) -> None:
    supplier_service.delete_config(db, code)


@router.get("/{code}/readiness", response_model=SupplierReadiness)
def get_supplier_readiness(code: str, db: Session = Depends(get_db)) -> SupplierReadiness:
    return supplier_service.get_readiness(db, code)


@router.post("/{code}/templates/{log_type}", response_model=TemplateUploadResult)
def upload_supplier_template(
    code: str,
    log_type: str,
    expectation: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
) -> TemplateUploadResult:
    """Save a MockServer expectation as templates/{CODE}/{LogType}/v1.json."""
    config = supplier_service.get_config(db, code)
    path, size = supplier_service.write_template(config.code, log_type, expectation)
    return TemplateUploadResult(
        code=config.code,
        log_type=log_type,
        path=str(path.relative_to(supplier_service.REPO_ROOT)),
        bytes_written=size,
    )


@router.post("/{code}/ingest", response_model=IngestResultModel)
async def ingest_supplier_templates(
    code: str,
    payload: IngestRequest,
    db: Session = Depends(get_db),
) -> IngestResultModel:
    """Build this supplier's templates from a SID's adapter logs.

    Rows are attributed to a supplier by matching its ``adapter_source_match`` against
    the log's ``source``, so a supplier with that field empty can never match anything —
    we say so explicitly instead of returning a silent empty result.
    """
    import httpx

    from app.config import get_settings
    from app.ingest.template_ingestor import TemplateIngestor

    config = supplier_service.get_config(db, code)
    if not config.mutation_config.adapter_source_match:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{config.code} has no adapter log source match configured, so no log row "
                "can be attributed to it. Set it under Mutation rules first "
                "(e.g. 'extranet' matches hotels-extranet-search)."
            ),
        )

    env = get_current_env()
    if not get_settings(env).logs_api_url:
        raise HTTPException(
            status_code=400,
            detail=(
                f"LOGS_API_URL is not configured for {env}, so SID logs can't be fetched. "
                f"Set it in backend/.env.{env} (or .env.shared) and restart the backend."
            ),
        )

    try:
        result = await TemplateIngestor().ingest_sid(config.code, payload.sid)
    except ValueError as exc:
        # No logs for the SID, or nothing usable in them.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        # Unreachable, timed out, or a non-2xx from the logs API.
        raise HTTPException(
            status_code=502,
            detail=f"Could not read logs for SID {payload.sid}: {type(exc).__name__}: {exc}",
        ) from exc

    warning: str | None = None
    if not result.written:
        matched = config.mutation_config.adapter_source_match
        warning = (
            f"No log rows for SID {payload.sid} matched '{matched}'. "
            f"Sources in this SID: {', '.join(result.sources_seen) or 'none'}."
        )
    elif result.missing:
        warning = f"No usable log rows for: {', '.join(result.missing)}."

    # Templates on disk changed, so readiness for this supplier has too.
    supplier_service.invalidate_cache(config.env)
    return IngestResultModel(
        supplier_code=result.supplier_code,
        sid=result.sid,
        written=result.written,
        missing=result.missing,
        unresolved=result.unresolved,
        paths=result.paths,
        field_map_paths=result.field_map_paths,
        sources_seen=result.sources_seen,
        warning=warning,
    )


@router.post("/{code}/field-map/generate")
def generate_supplier_field_map(code: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Infer field-map paths from the templates already on disk and save them."""
    import json

    from app.ingest.field_map_generator import FieldMapGenerator

    config = supplier_service.get_config(db, code)
    templates: dict[str, dict] = {}
    for log_type in config.log_types:
        path = supplier_service.TEMPLATES_DIR / config.code / log_type / "v1.json"
        if path.exists():
            templates[log_type] = json.loads(path.read_text(encoding="utf-8"))

    field_map = FieldMapGenerator().generate(config.code, templates, config.mutation_config)
    payload = SupplierConfigCreate(**{**config.model_dump(), "field_map": field_map})
    supplier_service.update_config(db, config.code, payload)
    return field_map


@router.post("/{code}/probe", response_model=ProbeResult)
def probe_supplier(code: str, db: Session = Depends(get_db)) -> ProbeResult:
    """Build expectations for a throwaway 2-package scenario without registering them.

    This is the screen's "Test scenario" button: it exercises template loading,
    mutation and linkage validation — everything that would fail at scenario-create
    time — but never touches MockServer, Backoffice or the database.
    """
    from app.core.scenario_engine import ScenarioEngine
    from app.models.scenario import PackageSpec, ScenarioRequest, SupplierScenario
    from app.models.supplier import ProbeLogTypeResult
    from app.plugins import PLUGINS

    config = supplier_service.get_config(db, code)
    plugin_name = f"plugins/{config.code.lower()}.py" if config.code in PLUGINS else "generic"

    request = ScenarioRequest(
        namespace=f"smf-probe-{config.code.lower()}",
        check_in="2026-09-01",
        check_out="2026-09-03",
        atg_hotel_id="1446194",
        suppliers=[
            SupplierScenario(
                code=config.code,
                contract_currency=config.default_contract_currency,
                packages=PackageSpec(
                    count=2,
                    room_basis=["RO", "BB"],
                    room_names=["Probe Room A", "Probe Room B"],
                    supplier_currency=config.default_supplier_currency,
                    prices=[100.0, 200.0],
                    refundable=[True, False],
                ),
            )
        ],
    )

    try:
        built = ScenarioEngine().build_expectations(request)
    except Exception as exc:  # noqa: BLE001 — the point is to report any failure
        return ProbeResult(
            code=config.code,
            env=get_current_env(),
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
            plugin=plugin_name,
        )

    results = [
        ProbeLogTypeResult(
            log_type=item.log_type,
            ok=True,
            path=item.expectation.get("httpRequest", {}).get("path"),
        )
        for item in built
    ]
    missing = [lt for lt in config.log_types if lt not in {r.log_type for r in results}]
    results.extend(
        ProbeLogTypeResult(log_type=lt, ok=False, error="no expectation built") for lt in missing
    )
    return ProbeResult(
        code=config.code,
        env=get_current_env(),
        ok=not missing,
        plugin=plugin_name,
        log_types=results,
    )
