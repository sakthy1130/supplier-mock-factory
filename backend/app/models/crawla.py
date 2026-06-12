"""Crawla anchor and scenario models."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CrawlaBucket(str, Enum):
    CRAWLA_LOWER = "CRAWLA_LOWER"
    EXPEDIA_LOWER = "EXPEDIA_LOWER"
    EQUAL = "EQUAL"
    ONLY_EXPEDIA = "ONLY_EXPEDIA"
    ONLY_CRAWLA = "ONLY_CRAWLA"


class CrawlaAnchorRequest(BaseModel):
    check_in: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    check_out: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    atg_hotel_ids: list[str] = Field(min_length=1)


class CrawlaSearchAnchorItem(BaseModel):
    atg_id: str
    min_price: Optional[float] = None
    total_amount: Optional[float] = None
    room_name: Optional[str] = None
    base_amount: Optional[float] = None
    tax_amount: Optional[float] = None
    currency: Optional[str] = None


class CrawlaHotelOffer(BaseModel):
    room_id: str
    room_name: str
    total_amount: float
    room_basis: Optional[str] = None
    meal: Optional[str] = None
    refundability: Optional[str] = None
    bed_type: Optional[str] = None


class CrawlaHotelAnchorItem(BaseModel):
    atg_id: str
    min_price: Optional[float] = None
    status: Optional[str] = None
    data: list[CrawlaHotelOffer] = Field(default_factory=list)


class CrawlaAnchorSearchResponse(BaseModel):
    data: list[CrawlaSearchAnchorItem] = Field(default_factory=list)


class CrawlaAnchorPackagesResponse(BaseModel):
    hotels: list[CrawlaHotelAnchorItem] = Field(default_factory=list)


class CrawlaPricePanel(BaseModel):
    crawla_total: float
    exp_mode: str = "INCLUDE_HOTEL"
    exp_price: float
    hbs_price: float


class CrawlaPackagePriceMode(str, Enum):
    SAME = "SAME"
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"


class CrawlaPackagesPanel(CrawlaPricePanel):
    package_count: int = Field(default=1, ge=1, le=20)
    package_price_mode: CrawlaPackagePriceMode = CrawlaPackagePriceMode.SAME
    package_price_step: float = Field(default=0.0, ge=0.0)
    crawla_room_id: str
    crawla_room_name: str
    room_basis: str = "RO"
    meal: str = "RO"
    refundability: str = "NO"
    bed_type: Optional[str] = None


class CrawlaScenarioRequest(BaseModel):
    namespace: str = Field(min_length=3, max_length=64)
    check_in: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    check_out: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    atg_hotel_id: str = Field(min_length=1)
    bucket: CrawlaBucket
    search: CrawlaPricePanel
    packages: CrawlaPackagesPanel


class CrawlaScenarioExport(BaseModel):
    bucket: CrawlaBucket
    namespace: str
    api_key: Optional[str] = None
    atg_hotel_id: str
    check_in: str
    check_out: str
    search: CrawlaPricePanel
    packages: CrawlaPackagesPanel


class CrawlaRunScenarioResponse(BaseModel):
    scenario_id: str
    search_s_id: str
    search_status: str
    search_hotel_id: str
    package_p_id: str
    package_status: str
    error_message: Optional[str] = None
    logs: list[dict[str, str]] = Field(default_factory=list)
