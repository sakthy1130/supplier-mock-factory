"""Hotel mapping API models."""

from pydantic import BaseModel, Field


class HotelMappingResponse(BaseModel):
    atg_hotel_id: str
    supplier_hotel_ids: dict[str, str] = Field(default_factory=dict)
