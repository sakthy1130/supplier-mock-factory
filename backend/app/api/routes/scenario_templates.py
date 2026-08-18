"""REST API for user-saved scenario package templates."""

from fastapi import APIRouter, Depends

from app.db.database import get_db
from app.db.repository import MongoStore
from app.models.scenario_template import ScenarioTemplate, ScenarioTemplateCreate
from app.services import scenario_template_service

router = APIRouter(prefix="/scenario-templates", tags=["scenario-templates"])


@router.get("", response_model=list[ScenarioTemplate])
def list_scenario_templates(db: MongoStore = Depends(get_db)) -> list[ScenarioTemplate]:
    return scenario_template_service.list_templates(db)


@router.post("", response_model=ScenarioTemplate, status_code=201)
def create_scenario_template(
    payload: ScenarioTemplateCreate,
    db: MongoStore = Depends(get_db),
) -> ScenarioTemplate:
    return scenario_template_service.create_template(db, payload)


@router.put("/{template_id}", response_model=ScenarioTemplate)
def update_scenario_template(
    template_id: str,
    payload: ScenarioTemplateCreate,
    db: MongoStore = Depends(get_db),
) -> ScenarioTemplate:
    return scenario_template_service.update_template(db, template_id, payload)


@router.delete("/{template_id}", status_code=204)
def delete_scenario_template(template_id: str, db: MongoStore = Depends(get_db)) -> None:
    scenario_template_service.delete_template(db, template_id)
