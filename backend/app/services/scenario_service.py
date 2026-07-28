"""Scenario CRUD, background jobs, orchestrator integration."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.orchestrator import SupplierMockScenarioOrchestrator
from app.db.models import ScenarioRecord
from app.env_context import get_current_env, use_env
from app.integrations.mock_server import MockServerClient
from app.services import provisioning_log_cache
from app.models.scenario import (
    ScenarioBundle,
    ScenarioListItem,
    ScenarioRequest,
    ScenarioStatus,
    TeardownAllResponse,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def record_to_bundle(record: ScenarioRecord) -> ScenarioBundle:
    request_data = record.request_json or {}
    supplier_hotel_ids = request_data.get("supplier_hotel_ids") or {}
    if not isinstance(supplier_hotel_ids, dict):
        supplier_hotel_ids = {}
    crawla_export = request_data.get("crawla_export")
    if not isinstance(crawla_export, dict):
        crawla_export = None
    br_setup = request_data.get("br_setup")
    if not isinstance(br_setup, dict):
        br_setup = None
    # br_setup is appended onto request_json after create (see apply_bundle) and is
    # already surfaced separately as bundle.br_setup — exclude it here so `request`
    # reflects only what was actually submitted, not the provisioning result.
    original_request = {k: v for k, v in request_data.items() if k != "br_setup"} or None
    return ScenarioBundle(
        id=record.id,
        namespace=record.namespace,
        env=record.env,
        status=ScenarioStatus(record.status),
        api_key=record.api_key,
        api_key_id=record.api_key_id,
        contracts=record.contracts_json or {},
        booking_ids=record.booking_ids_json or {},
        check_in=record.check_in,
        check_out=record.check_out,
        atg_hotel_id=request_data.get("atg_hotel_id") or record.hotel_id,
        supplier_hotel_ids=supplier_hotel_ids,
        crawla_export=crawla_export,
        br_setup=br_setup,
        mock_server_base_url=record.mock_server_base_url,
        expectation_count=record.expectation_count,
        error_message=record.error_message,
        created_at=record.created_at,
        expires_at=record.expires_at,
        sb_config_id=record.sb_config_id,
        sb_group_id=record.sb_group_id,
        request=original_request,
    )


def record_to_list_item(record: ScenarioRecord) -> ScenarioListItem:
    return ScenarioListItem(
        id=record.id,
        namespace=record.namespace,
        env=record.env,
        status=ScenarioStatus(record.status),
        created_at=record.created_at,
        suppliers=record.suppliers_json or [],
    )


def get_record(db: Session, scenario_id: str) -> ScenarioRecord:
    record = db.get(ScenarioRecord, scenario_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return record


def create_pending(db: Session, request: ScenarioRequest, env: str | None = None) -> ScenarioRecord:
    """Create a pending scenario row, tagged with the env it should run against.

    ``env`` defaults to the active request env (contextvar, set by the X-SMF-Env
    middleware). Once persisted, this value is what every lifecycle op (run,
    refresh, teardown) resolves settings from — never the caller's current
    dropdown selection — so switching envs mid-run can't retarget a scenario.
    """
    existing = db.query(ScenarioRecord).filter(ScenarioRecord.namespace == request.namespace).first()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Scenario namespace already exists: {request.namespace}",
        )

    suppliers = [s.code.value for s in request.suppliers]
    record = ScenarioRecord(
        id=str(uuid.uuid4()),
        namespace=request.namespace,
        env=env or get_current_env(),
        status=ScenarioStatus.PENDING.value,
        request_json=request.model_dump(mode="json"),
        contracts_json={},
        booking_ids_json={},
        suppliers_json=suppliers,
        check_in=request.check_in,
        check_out=request.check_out,
        hotel_id=request.atg_hotel_id,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def apply_bundle(db: Session, record: ScenarioRecord, bundle: ScenarioBundle) -> ScenarioRecord:
    record.status = bundle.status.value
    record.api_key = bundle.api_key
    record.api_key_id = bundle.api_key_id
    record.contracts_json = bundle.contracts
    record.booking_ids_json = bundle.booking_ids
    request_json = dict(record.request_json or {})
    if bundle.br_setup is not None:
        request_json["br_setup"] = bundle.br_setup
        record.request_json = request_json
    record.mock_server_base_url = bundle.mock_server_base_url
    record.expectation_count = bundle.expectation_count
    record.error_message = bundle.error_message
    record.updated_at = _utcnow()
    if bundle.expires_at:
        record.expires_at = bundle.expires_at
    if bundle.sb_config_id is not None:
        record.sb_config_id = bundle.sb_config_id
    if bundle.sb_group_id is not None:
        record.sb_group_id = bundle.sb_group_id
    db.commit()
    db.refresh(record)
    return record


def get_session_factory_standalone():
    from app.db.database import get_session_factory

    return get_session_factory()


async def run_create_scenario(scenario_id: str) -> None:
    session = get_session_factory_standalone()()
    try:
        record = session.get(ScenarioRecord, scenario_id)
        if record is None:
            return
        request = ScenarioRequest.model_validate(record.request_json)
        try:
            with use_env(record.env):
                orchestrator = SupplierMockScenarioOrchestrator()
                bundle = await orchestrator.create_scenario(request)
            bundle.id = scenario_id
            apply_bundle(session, record, bundle)
            if bundle.provisioning_log:
                provisioning_log_cache.store(scenario_id, bundle.provisioning_log)
        except Exception as exc:
            logger.exception("Scenario create failed id=%s", scenario_id)
            record.status = ScenarioStatus.FAILED.value
            record.error_message = str(exc)
            record.updated_at = _utcnow()
            session.commit()
    finally:
        session.close()


async def run_refresh_booking_ids(scenario_id: str) -> None:
    session = get_session_factory_standalone()()
    try:
        record = session.get(ScenarioRecord, scenario_id)
        if record is None:
            return
        if record.status != ScenarioStatus.READY.value:
            return
        request = ScenarioRequest.model_validate(record.request_json)
        try:
            with use_env(record.env):
                orchestrator = SupplierMockScenarioOrchestrator()
                bundle = await orchestrator.refresh_booking_ids(request)
            bundle.id = scenario_id
            bundle.namespace = record.namespace
            bundle.contracts = record.contracts_json or {}
            bundle.api_key = record.api_key
            bundle.api_key_id = record.api_key_id
            bundle.mock_server_base_url = record.mock_server_base_url
            bundle.expectation_count = record.expectation_count
            bundle.check_in = record.check_in
            bundle.check_out = record.check_out
            bundle.atg_hotel_id = request.atg_hotel_id
            bundle.supplier_hotel_ids = request.supplier_hotel_ids
            bundle.status = ScenarioStatus.READY
            apply_bundle(session, record, bundle)
        except Exception as exc:
            logger.exception("Refresh booking ids failed id=%s", scenario_id)
            record.error_message = str(exc)
            record.updated_at = _utcnow()
            session.commit()
    finally:
        session.close()


_TEARABLE_STATUSES = frozenset(
    {
        ScenarioStatus.READY.value,
        ScenarioStatus.FAILED.value,
        ScenarioStatus.BUILDING_MOCKS.value,
        ScenarioStatus.REGISTERING.value,
        ScenarioStatus.CREATING_CONTRACTS.value,
        ScenarioStatus.CREATING_API_KEY.value,
    }
)


def list_tearable_records(db: Session, env: str | None = None) -> list[ScenarioRecord]:
    query = db.query(ScenarioRecord).filter(ScenarioRecord.status.in_(_TEARABLE_STATUSES))
    if env:
        query = query.filter(ScenarioRecord.env == env)
    return query.order_by(ScenarioRecord.created_at.desc()).all()


async def _teardown_record(session: Session, record: ScenarioRecord) -> None:
    # Always tear down against the env this scenario was created in — never the
    # caller's current env selection — so switching the dropdown mid-cleanup
    # can't send stg contract/apiKey ids to the dev Backoffice (or vice versa).
    with use_env(record.env):
        orchestrator = SupplierMockScenarioOrchestrator()
        bundle = await orchestrator.teardown_scenario(
            record.namespace,
            api_key_id=record.api_key_id,
            api_key=record.api_key,
            br_setup=(record.request_json or {}).get("br_setup"),
            contracts=record.contracts_json or {},
            suppliers=record.suppliers_json or [],
            sb_config_id=record.sb_config_id,
            sb_group_id=record.sb_group_id,
        )
    bundle.id = record.id
    bundle.namespace = record.namespace
    bundle.check_in = record.check_in
    bundle.check_out = record.check_out
    request = ScenarioRequest.model_validate(record.request_json)
    bundle.atg_hotel_id = request.atg_hotel_id
    bundle.supplier_hotel_ids = request.supplier_hotel_ids
    bundle.api_key = record.api_key
    bundle.api_key_id = record.api_key_id
    bundle.contracts = record.contracts_json or {}
    bundle.booking_ids = record.booking_ids_json or {}
    bundle.mock_server_base_url = record.mock_server_base_url
    bundle.expectation_count = record.expectation_count
    apply_bundle(session, record, bundle)


async def run_teardown(scenario_id: str) -> None:
    session = get_session_factory_standalone()()
    try:
        record = session.get(ScenarioRecord, scenario_id)
        if record is None:
            return
        try:
            await _teardown_record(session, record)
        except Exception as exc:
            logger.exception("Teardown failed id=%s (will still delete from DB)", scenario_id)
            record.error_message = str(exc)
            record.updated_at = _utcnow()

        # Always delete from DB, even if teardown fails
        # Backoffice errors shouldn't block database cleanup
        session.delete(record)
        session.commit()
    finally:
        session.close()


async def run_teardown_all(env: str | None = None) -> None:
    """Tear down every tearable scenario, scoped to ``env`` (None = all envs).

    The blanket MockServer clear runs once per env actually represented among the
    torn-down records — not once globally — so a mixed-env cleanup can't sweep the
    wrong MockServer instance (dev and stg have separate MockServer hosts).
    """
    session = get_session_factory_standalone()()
    try:
        records = list_tearable_records(session, env=env)
        torn_down_envs: set[str] = set()
        for record in records:
            try:
                await _teardown_record(session, record)
                torn_down_envs.add(record.env)
            except Exception as exc:
                logger.exception("Teardown failed id=%s namespace=%s (will still delete from DB)", record.id, record.namespace)
                record.error_message = str(exc)
                record.updated_at = _utcnow()

            # Always delete from DB, even if teardown fails
            # Backoffice errors shouldn't block database cleanup
            session.delete(record)
            session.commit()
        for torn_env in torn_down_envs:
            with use_env(torn_env):
                async with MockServerClient() as client:
                    await client.delete_all_expectations()
    finally:
        session.close()


def queue_teardown_all(db: Session, env: str | None = None) -> TeardownAllResponse:
    records = list_tearable_records(db, env=env)
    return TeardownAllResponse(
        queued=len(records),
        scenario_ids=[record.id for record in records],
    )


def list_records(db: Session, env: str | None = None) -> list[ScenarioRecord]:
    query = db.query(ScenarioRecord)
    if env:
        query = query.filter(ScenarioRecord.env == env)
    return query.order_by(ScenarioRecord.created_at.desc()).all()
