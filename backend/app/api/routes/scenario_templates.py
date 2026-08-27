"""REST API for user-saved scenario package templates."""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

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


class SaveScenarioAsTemplate(BaseModel):
    """What the caller supplies; everything else comes from the scenario itself."""

    label: str = Field(min_length=1, max_length=120)
    description: str = ""
    function: Optional[str] = Field(
        default=None,
        description=(
            "Which Templates tab this belongs under: 'templateBeddingMock' or "
            "'preBookingMock'. Omitted reads as bedding, like every template saved "
            "before the two kinds existed."
        ),
    )


class SaveRequestAsTemplate(SaveScenarioAsTemplate):
    """The wizard's template mode: a full ScenarioRequest plus the template's label."""

    request: dict


@router.post("/from-request", response_model=ScenarioTemplate, status_code=201)
def save_request_as_template(
    payload: SaveRequestAsTemplate,
    db: MongoStore = Depends(get_db),
) -> ScenarioTemplate:
    """Save a scenario the wizard just composed, without provisioning it.

    Shares suppliers_from_request with from-scenario, so a template authored in the
    wizard and one saved off a live scenario are identical for the same input.
    """
    return scenario_template_service.template_from_request(
        db,
        payload.request,
        label=payload.label,
        description=payload.description,
        function=payload.function,
    )


@router.post("/from-scenario/{scenario_id}", response_model=ScenarioTemplate, status_code=201)
def save_scenario_as_template(
    scenario_id: str,
    payload: SaveScenarioAsTemplate,
    db: MongoStore = Depends(get_db),
) -> ScenarioTemplate:
    """Turn a READY scenario into a reusable template, settings and all."""
    return scenario_template_service.template_from_scenario(
        db,
        scenario_id,
        label=payload.label,
        description=payload.description,
        function=payload.function,
    )


@router.delete("/{template_id}", status_code=204)
def delete_scenario_template(template_id: str, db: MongoStore = Depends(get_db)) -> None:
    scenario_template_service.delete_template(db, template_id)
