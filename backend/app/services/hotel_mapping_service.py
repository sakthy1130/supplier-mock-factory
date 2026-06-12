"""Resolve ATG hotel id to per-supplier hotel ids for scenario create."""

from __future__ import annotations

from fastapi import HTTPException

from app.integrations.hotel_mapping import HotelMappingClient, HotelMappingError
from app.models.scenario import ScenarioRequest


async def resolve_scenario_hotel_ids(request: ScenarioRequest) -> ScenarioRequest:
    """Fill supplier_hotel_ids from mapping service; validate all selected suppliers."""
    supplier_codes = [s.code.value for s in request.suppliers]
    async with HotelMappingClient() as client:
        try:
            mapping = await client.resolve_supplier_hotel_ids(request.atg_hotel_id, supplier_codes)
        except HotelMappingError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    data = request.model_dump(mode="json")
    data["supplier_hotel_ids"] = mapping
    return ScenarioRequest.model_validate(data)
