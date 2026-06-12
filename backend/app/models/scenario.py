"""Pydantic models for scenario DSL and orchestrator output."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class SupplierCode(str, Enum):
    HBS = "HBS"
    EXP = "EXP"
    RHK = "RHK"


class ScenarioStatus(str, Enum):
    PENDING = "PENDING"
    BUILDING_MOCKS = "BUILDING_MOCKS"
    REGISTERING = "REGISTERING"
    CREATING_CONTRACTS = "CREATING_CONTRACTS"
    CREATING_API_KEY = "CREATING_API_KEY"
    READY = "READY"
    FAILED = "FAILED"
    TORN_DOWN = "TORN_DOWN"


class PackageSpec(BaseModel):
    count: int = Field(ge=1, le=20, description="Number of packages in response")
    room_basis: str = Field(default="RO", description="e.g. RO, BB")
    prices: list[float] = Field(min_length=1, description="Price per package")
    refundable: list[bool] = Field(
        default_factory=list,
        description="Refundable flag per package; defaults to false if shorter than count",
    )


class SupplierScenario(BaseModel):
    code: SupplierCode
    packages: PackageSpec


class SupplierMutation(BaseModel):
    search_price: Optional[float] = None
    package_price: Optional[float] = None
    room_name: Optional[str] = None
    room_basis: Optional[str] = None
    bed_groups_description: Optional[str] = None
    exclude_hotel: bool = False


class ScenarioRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    namespace: str = Field(
        min_length=3,
        max_length=64,
        description="Unique isolation key for shared MockServer",
    )
    check_in: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    check_out: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    atg_hotel_id: str = Field(
        validation_alias=AliasChoices("atg_hotel_id", "hotel_id"),
        description="ATG hotel id from UI; supplier ids resolved via mapping service",
    )
    supplier_hotel_ids: dict[str, str] = Field(
        default_factory=dict,
        description="Filled server-side: supplierCode -> supplierHotelId",
    )
    suppliers: list[SupplierScenario] = Field(min_length=1)
    supplier_mutations: dict[str, SupplierMutation] = Field(default_factory=dict)
    crawla_export: Optional[dict[str, Any]] = None

    def hotel_id_for_supplier(self, supplier_code: str) -> str:
        return self.supplier_hotel_ids.get(supplier_code, self.atg_hotel_id)


class ScenarioBundle(BaseModel):
    id: Optional[str] = None
    namespace: str
    status: ScenarioStatus = ScenarioStatus.PENDING
    api_key: Optional[str] = None
    api_key_id: Optional[str] = None
    contracts: dict[str, str] = Field(default_factory=dict)
    booking_ids: dict[str, str] = Field(default_factory=dict)
    check_in: str
    check_out: str
    atg_hotel_id: str
    supplier_hotel_ids: dict[str, str] = Field(default_factory=dict)
    crawla_export: Optional[dict[str, Any]] = None
    br_setup: Optional[dict[str, Any]] = None
    mock_server_base_url: Optional[str] = None
    expectation_count: int = 0
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class ScenarioListItem(BaseModel):
    id: str
    namespace: str
    status: ScenarioStatus
    created_at: Optional[datetime] = None
    suppliers: list[str] = Field(default_factory=list)


class TeardownAllResponse(BaseModel):
    queued: int
    scenario_ids: list[str] = Field(default_factory=list)
