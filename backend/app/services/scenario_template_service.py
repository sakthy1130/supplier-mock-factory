"""CRUD for user-saved scenario package templates."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import HTTPException

from app.db.models import ScenarioTemplateRecord
from app.db.repository import MongoStore
from app.env_context import get_current_env
from app.integrations.business_rules import has_template_child_condition
from app.models.scenario_template import ScenarioTemplate, ScenarioTemplateCreate


def _record_to_model(record: ScenarioTemplateRecord) -> ScenarioTemplate:
    # Pre-multi-supplier rows only have the legacy supplier/packages_json
    # columns — synthesize a one-entry suppliers list from those so old
    # templates keep working without a data migration.
    suppliers = record.suppliers_json or [
        {
            "supplier": record.supplier,
            "supplier_currency": "SAR",
            "contract_currency": "USD",
            "packages": record.packages_json,
            "assignment_target": "apikey",
        }
    ]
    return ScenarioTemplate(
        id=record.id,
        label=record.label,
        description=record.description,
        function=record.function,
        atg_hotel_id=record.atg_hotel_id,
        suppliers=suppliers,
        sb_enabled=bool(record.sb_enabled),
        created_at=record.created_at,
        has_br_child_condition=has_template_child_condition(record.id, get_current_env()),
    )


def list_templates(db: MongoStore) -> list[ScenarioTemplate]:
    return [_record_to_model(r) for r in db.templates.list()]


def _apply_payload(record: ScenarioTemplateRecord, payload: ScenarioTemplateCreate) -> None:
    first = payload.suppliers[0]
    record.label = payload.label.strip()
    record.description = payload.description.strip()
    record.function = payload.function
    record.atg_hotel_id = payload.atg_hotel_id.strip()
    record.supplier = str(first.supplier)
    record.packages_json = [row.model_dump() for row in first.packages]
    record.sb_enabled = payload.sb_enabled
    # model_dump(mode="json") rather than listing fields by hand: the hand-written
    # version silently dropped prebooking_status/prebooking_changed_price when they were
    # added, and would drop the next field too. "json" keeps the enums as their wire
    # strings, which is what the document stores and what _record_to_model reads back.
    record.suppliers_json = [entry.model_dump(mode="json") for entry in payload.suppliers]


def create_template(db: MongoStore, payload: ScenarioTemplateCreate) -> ScenarioTemplate:
    record = ScenarioTemplateRecord(id=str(uuid.uuid4()))
    _apply_payload(record, payload)
    db.templates.save(record)
    return _record_to_model(record)


def update_template(db: MongoStore, template_id: str, payload: ScenarioTemplateCreate) -> ScenarioTemplate:
    record = db.templates.get(template_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Template not found")
    _apply_payload(record, payload)
    db.templates.save(record)
    return _record_to_model(record)


def delete_template(db: MongoStore, template_id: str) -> None:
    record = db.templates.get(template_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Template not found")
    db.templates.delete(record)


def suppliers_from_request(request: dict) -> list:
    """Invert a ScenarioRequest's packages into template supplier entries.

    A scenario stores packages as parallel ARRAYS (prices[i], room_names[i], …); a
    template stores a list of ROWS. Both the save-a-scenario path and the
    save-from-the-wizard path go through here, so the two can never produce different
    templates for the same scenario — which is exactly how the earlier drift happened.
    """
    from app.models.scenario_template import SupplierTemplatePackages, TemplatePackageRow

    suppliers_in = request.get("suppliers") or []
    if not suppliers_in:
        raise HTTPException(
            status_code=409, detail="No suppliers in the request to build a template from"
        )

    def at(values: object, index: int, fallback: object) -> object:
        return values[index] if isinstance(values, list) and index < len(values) else fallback

    suppliers = []
    for entry in suppliers_in:
        packages = entry.get("packages") or {}
        prices = packages.get("prices") or []
        count = packages.get("count") or len(prices)
        # Both or neither, per PackageSpec's validator — an all-or-nothing split.
        split = packages.get("original_price_with_vat") or []
        markup = packages.get("markup") or []
        has_split = len(split) == count and len(markup) == count

        rows = [
            TemplatePackageRow(
                room_name=str(at(packages.get("room_names"), i, "Room")),
                room_basis=str(at(packages.get("room_basis"), i, "RO")),
                price=float(at(prices, i, 0.0)),
                refundable=bool(at(packages.get("refundable"), i, True)),
                original_price_with_vat=float(split[i]) if has_split else None,
                markup=float(markup[i]) if has_split else None,
            )
            for i in range(count)
        ]
        suppliers.append(
            SupplierTemplatePackages(
                supplier=entry.get("code"),
                supplier_currency=packages.get("supplier_currency") or "SAR",
                contract_currency=entry.get("contract_currency") or "USD",
                packages=rows,
                assignment_target=entry.get("assignment_target") or "apikey",
                prebooking_status=packages.get("prebooking_status") or "available",
                prebooking_changed_price=packages.get("prebooking_changed_price"),
                can_prebook=packages.get("can_prebook"),
                prebook_url=packages.get("prebook_url"),
                supplier_prebooking=packages.get("supplier_prebooking"),
                booking_package_index=packages.get("booking_package_index"),
                adults=packages.get("adults") or 2,
                child_ages=list(packages.get("child_ages") or []),
                room_count=packages.get("room_count") or 1,
            )
        )
    return suppliers


def template_from_request(
    db: MongoStore,
    request: dict,
    label: str,
    description: str = "",
    function: Optional[str] = None,
) -> ScenarioTemplate:
    """Save a ScenarioRequest as a template — what the wizard's template mode posts."""
    from app.models.scenario_template import ScenarioTemplateCreate

    return create_template(
        db,
        ScenarioTemplateCreate(
            label=label,
            description=description,
            function=function,
            atg_hotel_id=str(request.get("atg_hotel_id") or ""),
            suppliers=suppliers_from_request(request),
            sb_enabled=bool(request.get("sb_enabled")),
        ),
    )


def update_template_from_request(
    db: MongoStore,
    template_id: str,
    request: dict,
    label: str,
    description: str = "",
    function: Optional[str] = None,
) -> ScenarioTemplate:
    """Rewrite an existing template from a ScenarioRequest, KEEPING ITS ID.

    The id is the contract with automation — scenario_id_labels.json maps labels to
    ids and the Java suite drives POST /run-template/{id}. Delete-then-create would
    silently break every mapped scenario, so editing updates in place.
    """
    from app.models.scenario_template import ScenarioTemplateCreate

    return update_template(
        db,
        template_id,
        ScenarioTemplateCreate(
            label=label,
            description=description,
            function=function,
            atg_hotel_id=str(request.get("atg_hotel_id") or ""),
            suppliers=suppliers_from_request(request),
            sb_enabled=bool(request.get("sb_enabled")),
        ),
    )


def template_from_scenario(
    db: MongoStore,
    scenario_id: str,
    label: str,
    description: str = "",
    function: Optional[str] = None,
) -> ScenarioTemplate:
    """Save an already-provisioned scenario as a template.

    Thin wrapper over template_from_request: the stored request IS a ScenarioRequest,
    so both entry points share one inversion.
    """
    record = db.scenarios.get(scenario_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    if record.status != "READY":
        raise HTTPException(
            status_code=409,
            detail=f"Scenario must be READY to save as a template (it is {record.status})",
        )
    request = record.request_json or {}
    if not (request.get("suppliers") or []):
        raise HTTPException(
            status_code=409, detail="Scenario has no stored request to build a template from"
        )
    return template_from_request(db, request, label, description, function)
