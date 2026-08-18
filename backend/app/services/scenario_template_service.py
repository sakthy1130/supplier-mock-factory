"""CRUD for user-saved scenario package templates."""

from __future__ import annotations

import uuid

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
    record.supplier = first.supplier.value
    record.packages_json = [row.model_dump() for row in first.packages]
    record.sb_enabled = payload.sb_enabled
    record.suppliers_json = [
        {
            "supplier": entry.supplier.value,
            "supplier_currency": entry.supplier_currency,
            "contract_currency": entry.contract_currency,
            "packages": [row.model_dump() for row in entry.packages],
            "assignment_target": entry.assignment_target.value,
        }
        for entry in payload.suppliers
    ]


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
