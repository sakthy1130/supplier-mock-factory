"""Pydantic models for scenario DSL and orchestrator output."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


class SupplierCode(str, Enum):
    HBS = "HBS"
    EXP = "EXP"
    RHK = "RHK"
    CHC = "CHC"


class SBGroupConfiguration(BaseModel):
    """Controls which attributes SB enforces when matching packages."""

    board: bool = Field(default=False, description="Enforce matching meal basis")
    cancellation_policy: bool = Field(default=False, description="Enforce matching refundability")
    survey1_class: bool = Field(default=True)
    survey1_type: bool = Field(default=True)
    survey1_view: bool = Field(default=True)
    survey1_bedding: bool = Field(default=True)


class SBScenarioConfig(BaseModel):
    """Smart Booking provisioning config — attached to ScenarioRequest when SB tests need it."""

    enable_profitable_sb: bool = Field(default=True, description="Enable SB feature on the apiKey")
    enable_retry_sb: bool = Field(default=False, description="Configure retry SB error codes")
    forfeit_amount: float = Field(default=50.0, description="ignoreDeltaProfitAmount — flat forfeit threshold")
    price_margin_percentage: str = Field(default="0", description="priceMarginPercentage")
    consider_original_package: bool = Field(default=False)
    winning_packages_enabled: bool = Field(default=False)
    fetch_cancellation_policy_for_excluded: bool = Field(default=True)
    consider_same_vat_groups: str = Field(default="")
    enable_new_session: bool = Field(default=True)
    group_configuration: SBGroupConfiguration = Field(default_factory=SBGroupConfiguration)
    retry_error_codes: list[str] = Field(
        default_factory=list,
        description="Error codes that trigger Retry SB — registered in SB error code config",
    )
    booking_fail_error_code: Optional[str] = Field(
        default=None,
        description="When set, the Booking mock returns this error code to simulate a failed booking",
    )


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
    room_names: list[str] = Field(
        default_factory=lambda: ["1 Double Bed, Nonsmoking"],
        min_length=1,
        description="Room display name per package (HBS mock; CHC uses content cache by roomId)",
    )
    supplier_currency: str = Field(
        default="SAR",
        min_length=3,
        max_length=3,
        description="ISO currency on supplier rate payloads (e.g. CHC availRoomRates.currency)",
    )
    prices: list[float] = Field(min_length=1, description="Price per package")
    refundable: list[bool] = Field(
        default_factory=list,
        description="Refundable flag per package; defaults to false if shorter than count",
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_room_name(cls, data: Any) -> Any:
        if isinstance(data, dict) and "room_names" not in data and "room_name" in data:
            legacy = data.pop("room_name")
            if isinstance(legacy, str) and legacy.strip():
                data["room_names"] = [legacy.strip()]
        return data

    @field_validator("supplier_currency")
    @classmethod
    def _upper_currency(cls, value: str) -> str:
        return value.strip().upper()


class SupplierScenario(BaseModel):
    code: SupplierCode
    packages: PackageSpec


class SupplierMutation(BaseModel):
    search_price: Optional[float] = None
    package_price: Optional[float] = None
    room_name: Optional[str] = None
    search_room_name: Optional[str] = None  # overrides room_name for Search log_type only
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
    # SB config — Optional. When absent, existing flow runs unchanged.
    sb_config: Optional[SBScenarioConfig] = Field(
        default=None,
        description="Smart Booking provisioning config. Omit for non-SB scenarios.",
    )

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
    # SB-specific fields — None for non-SB scenarios
    sb_config_id: Optional[str] = Field(default=None, description="Created SB configuration ID for teardown")
    sb_config_name: Optional[str] = Field(default=None, description="Created SB configuration name")
    sb_group_id: Optional[str] = Field(default=None, description="Created SB group ID for teardown")
    sb_group_name: Optional[str] = Field(default=None, description="Created SB group name")
    # Provisioning log — one entry per step, visible in the SMF dashboard
    provisioning_log: list[str] = Field(default_factory=list)


class ScenarioListItem(BaseModel):
    id: str
    namespace: str
    status: ScenarioStatus
    created_at: Optional[datetime] = None
    suppliers: list[str] = Field(default_factory=list)


class TeardownAllResponse(BaseModel):
    queued: int
    scenario_ids: list[str] = Field(default_factory=list)
