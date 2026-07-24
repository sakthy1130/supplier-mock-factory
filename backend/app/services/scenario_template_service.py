"""CRUD for user-saved scenario package templates."""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ScenarioTemplateRecord
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
        }
    ]
    return ScenarioTemplate(
        id=record.id,
        label=record.label,
        description=record.description,
        atg_hotel_id=record.atg_hotel_id,
        suppliers=suppliers,
        created_at=record.created_at,
    )


def list_templates(db: Session) -> list[ScenarioTemplate]:
    records = db.scalars(
        select(ScenarioTemplateRecord).order_by(ScenarioTemplateRecord.created_at.desc())
    ).all()
    return [_record_to_model(r) for r in records]


def _apply_payload(record: ScenarioTemplateRecord, payload: ScenarioTemplateCreate) -> None:
    first = payload.suppliers[0]
    record.label = payload.label.strip()
    record.description = payload.description.strip()
    record.atg_hotel_id = payload.atg_hotel_id.strip()
    record.supplier = first.supplier.value
    record.packages_json = [row.model_dump() for row in first.packages]
    record.suppliers_json = [
        {
            "supplier": entry.supplier.value,
            "supplier_currency": entry.supplier_currency,
            "contract_currency": entry.contract_currency,
            "packages": [row.model_dump() for row in entry.packages],
        }
        for entry in payload.suppliers
    ]


def create_template(db: Session, payload: ScenarioTemplateCreate) -> ScenarioTemplate:
    record = ScenarioTemplateRecord(id=str(uuid.uuid4()))
    _apply_payload(record, payload)
    db.add(record)
    db.commit()
    db.refresh(record)
    return _record_to_model(record)


def update_template(db: Session, template_id: str, payload: ScenarioTemplateCreate) -> ScenarioTemplate:
    record = db.get(ScenarioTemplateRecord, template_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Template not found")
    _apply_payload(record, payload)
    db.commit()
    db.refresh(record)
    return _record_to_model(record)


def delete_template(db: Session, template_id: str) -> None:
    record = db.get(ScenarioTemplateRecord, template_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Template not found")
    db.delete(record)
    db.commit()
