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
    EXT = "EXT"


class AssignmentTarget(str, Enum):
    """Where a supplier's contract is attached when SmartBooking is enabled."""

    apikey = "apikey"
    sbgroup = "sbgroup"
    both = "both"


class SBGroupConfiguration(BaseModel):
    """Controls which attributes SB enforces when matching packages. These drive
    the TOP-LEVEL config fields the SB engine reads; defaults mirror the known-
    working reference config (survey type/view off so a differently-typed group
    package can still be matched)."""

    board: bool = Field(default=True, description="Enforce matching meal basis")
    cancellation_policy: bool = Field(default=True, description="Enforce matching refundability")
    survey1_class: bool = Field(default=True)
    survey1_type: bool = Field(default=False)
    survey1_view: bool = Field(default=False)
    survey1_bedding: bool = Field(default=True)


class SBScenarioConfig(BaseModel):
    """Smart Booking provisioning config — attached to ScenarioRequest when SB tests need it."""

    enable_profitable_sb: bool = Field(default=True, description="Enable SB feature on the apiKey")
    enable_retry_sb: bool = Field(default=False, description="Configure retry SB error codes")
    forfeit_amount: float = Field(default=0.0, description="ignoreDeltaProfitAmount — flat forfeit threshold")
    price_margin_percentage: str = Field(default="50", description="priceMarginPercentage")
    consider_original_package: bool = Field(default=True)
    winning_packages_enabled: bool = Field(default=False)
    fetch_cancellation_policy_for_excluded: bool = Field(default=True)
    consider_same_vat_groups: str = Field(default="")
    enable_new_session: bool = Field(default=True)
    include_new_session: bool = Field(default=False, description="includeNewSession (distinct from enableNewSession)")
    price_margin_to_upgrade: str = Field(default="50", description="priceMarginToUpgrade (nested price block)")
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
    room_basis: list[str] = Field(
        default_factory=lambda: ["RO"],
        min_length=1,
        description=(
            "Board code per package (RO, BB, HB, FB, ...), same indexing as room_names. "
            "A single string applies to every package; a shorter list pads with its last value."
        ),
    )
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
    booking_package_index: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "0-based index of the package the Booking/GetOrder flow links to. "
            "None means no booking flow is created for this supplier — only "
            "Search/Packages (and PreBooking/CancellationPolicy where present)."
        ),
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

    @field_validator("room_basis", mode="before")
    @classmethod
    def _coerce_room_basis(cls, value: Any) -> Any:
        """Accept a plain string (applies to every package) or a list (per-package)."""
        if isinstance(value, str):
            return [value]
        return value

    @model_validator(mode="after")
    def _validate_booking_package_index(self) -> "PackageSpec":
        if self.booking_package_index is not None and self.booking_package_index >= self.count:
            raise ValueError(
                f"booking_package_index {self.booking_package_index} out of range "
                f"for {self.count} package(s)"
            )
        return self


def instance_key_for(supplier_code: str, instance: int) -> str:
    """Key that identifies one supplier ENTRY in a scenario.

    A scenario may carry the same supplier more than once (e.g. two EXP contracts
    at different prices), so supplier code alone can no longer key contracts,
    expectation ids or mock paths. The first instance keeps the bare code, which
    means every single-instance scenario — including every record already stored —
    keeps byte-identical ids, paths and contract uids.
    """
    if instance <= 1:
        return supplier_code
    return f"{supplier_code}-{instance}"


class SupplierScenario(BaseModel):
    code: SupplierCode
    # Assigned server-side by ScenarioRequest._assign_supplier_instances: 1 for the
    # first entry of a code, 2 for the second, and so on. Callers do not set it.
    instance: int = Field(default=1, ge=1, description="Occurrence of this supplier code (1-based)")
    packages: PackageSpec
    contract_currency: str = Field(
        default="USD",
        min_length=3,
        max_length=3,
        description="ISO 4217 currency code for the contract; defaults to USD",
    )
    assignment_target: AssignmentTarget = Field(
        default=AssignmentTarget.apikey,
        description=(
            "Where this supplier's contract is attached when SmartBooking is on: "
            "apikey (only the apiKey), sbgroup (only the SB group), or both. "
            "Ignored when SB is off (contract always goes to the apiKey)."
        ),
    )

    @field_validator("contract_currency")
    @classmethod
    def _upper_contract_currency(cls, value: str) -> str:
        return value.strip().upper()

    @property
    def instance_key(self) -> str:
        return instance_key_for(self.code.value, self.instance)


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
    # Simple UI toggle: when true (and sb_config is not explicitly supplied), a
    # default SBScenarioConfig is materialized so the existing sb_config-gated
    # provisioning path runs. Advanced callers can still pass a full sb_config.
    sb_enabled: bool = Field(
        default=False,
        description="Create the apiKey with SmartBooking enabled (materializes a default sb_config).",
    )
    # SB config — Optional. When absent, existing flow runs unchanged.
    sb_config: Optional[SBScenarioConfig] = Field(
        default=None,
        description="Smart Booking provisioning config. Omit for non-SB scenarios.",
    )
    assign_to_br: bool = Field(
        default=True,
        description=(
            "Assign the created apiKey to the Static/Dynamic Markup BR rules on create "
            "(cleaned up on teardown). Crawla-exported and SB scenarios always assign "
            "regardless of this flag; it only gates the plain scenario-wizard flow."
        ),
    )
    template_id: Optional[str] = Field(
        default=None,
        description=(
            "Scenario template id this request originated from, if any (set by the "
            "run-template automation API or the UI's create-from-custom-template flow). "
            "Used to look up per-template child BR conditions in field-maps/br_child_conditions.json."
        ),
    )

    @model_validator(mode="after")
    def _assign_supplier_instances(self) -> "ScenarioRequest":
        """Number repeated supplier codes 1, 2, 3… in the order they were sent.

        Always recomputed from position so a caller cannot hand us colliding
        instance numbers, and so an old payload (no instance field) still lands on
        instance=1 and keeps its existing keys.
        """
        seen: dict[str, int] = {}
        for supplier in self.suppliers:
            code = supplier.code.value
            seen[code] = seen.get(code, 0) + 1
            supplier.instance = seen[code]
        return self

    @model_validator(mode="after")
    def _resolve_smart_booking(self) -> "ScenarioRequest":
        # Materialize a default SB config when the simple toggle is on.
        if self.sb_enabled and self.sb_config is None:
            self.sb_config = SBScenarioConfig()
        # When SB is active, at least one supplier must feed the SB group, or the
        # group would be created empty.
        if self.sb_config is not None:
            has_group_member = any(
                supplier.assignment_target in (AssignmentTarget.sbgroup, AssignmentTarget.both)
                for supplier in self.suppliers
            )
            if not has_group_member:
                raise ValueError(
                    "SmartBooking is enabled but no supplier targets the SB group; "
                    "set at least one supplier's assignment_target to 'sbgroup' or 'both'."
                )
        return self

    def hotel_id_for_supplier(self, supplier_code: str) -> str:
        return self.supplier_hotel_ids.get(supplier_code, self.atg_hotel_id)

    def apikey_contract_codes(self) -> list[str]:
        """Supplier codes whose contract should attach to the apiKey.

        With SB off, every supplier's contract goes to the apiKey (unchanged
        behavior). With SB on, only apikey/both targets do.
        """
        if self.sb_config is None:
            return [s.instance_key for s in self.suppliers]
        return [
            s.instance_key
            for s in self.suppliers
            if s.assignment_target in (AssignmentTarget.apikey, AssignmentTarget.both)
        ]

    def sbgroup_contract_codes(self) -> list[str]:
        """Instance keys whose contract should attach to the SB group."""
        return [
            s.instance_key
            for s in self.suppliers
            if s.assignment_target in (AssignmentTarget.sbgroup, AssignmentTarget.both)
        ]

    def instance_keys(self) -> list[str]:
        """Every supplier entry's key, for teardown and persistence."""
        return [s.instance_key for s in self.suppliers]

    def mutation_for(self, supplier: SupplierScenario) -> Optional[SupplierMutation]:
        """Crawla mutations are addressed by instance key, falling back to the bare
        supplier code so existing single-instance callers keep working."""
        return self.supplier_mutations.get(supplier.instance_key) or (
            self.supplier_mutations.get(supplier.code.value) if supplier.instance == 1 else None
        )


class ScenarioBundle(BaseModel):
    id: Optional[str] = None
    namespace: str
    env: str = "stg"
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
    # Original create request (namespace/dates/hotel id/suppliers/package specs) as
    # submitted — lets GET /api/scenarios/{id} answer "what was this scenario asked
    # to create", not just its provisioning result.
    request: Optional[dict[str, Any]] = None


class ScenarioListItem(BaseModel):
    id: str
    namespace: str
    env: str = "stg"
    status: ScenarioStatus
    created_at: Optional[datetime] = None
    suppliers: list[str] = Field(default_factory=list)


class TeardownAllResponse(BaseModel):
    queued: int
    scenario_ids: list[str] = Field(default_factory=list)
