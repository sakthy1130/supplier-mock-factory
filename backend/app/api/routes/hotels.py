"""Hotel id mapping helpers for UI."""

from fastapi import APIRouter, HTTPException, Query

from app.integrations.hotel_mapping import HotelMappingClient, HotelMappingError
from app.models.hotel_mapping import HotelMappingResponse

router = APIRouter(prefix="/hotels", tags=["hotels"])


@router.get("/mapping", response_model=HotelMappingResponse)
async def resolve_hotel_mapping(
    atg_hotel_id: str = Query(min_length=1),
    suppliers: str = Query(description="Comma-separated supplier codes, e.g. HBS,EXP"),
) -> HotelMappingResponse:
    """Resolve ATG hotel id to supplier hotel ids (preview before scenario create)."""
    supplier_codes = [s.strip().upper() for s in suppliers.split(",") if s.strip()]
    if not supplier_codes:
        raise HTTPException(status_code=400, detail="At least one supplier required")

    async with HotelMappingClient() as client:
        try:
            mapping = await client.resolve_supplier_hotel_ids(atg_hotel_id, supplier_codes)
        except HotelMappingError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return HotelMappingResponse(atg_hotel_id=atg_hotel_id.strip(), supplier_hotel_ids=mapping)
