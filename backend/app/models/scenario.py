"""Pydantic models for scenario DSL and orchestrator output."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import core_schema


class SupplierCode(str):
    """A supplier code.

    Was a closed Enum; supplier codes now live in the ``suppliers`` table so QA can
    add one from the Suppliers screen without a code change. This stays a real type
    (rather than a bare ``str``) so the built-in codes keep working as attributes —
    ``SupplierCode.HBS``, ``SupplierCode("HBS")`` and ``.value`` all behave as before.
    Whether a code is *configured* is checked where the config is actually needed
    (see app/services/supplier_service.py), not by this type.
    """

    HBS = "HBS"
    EXP = "EXP"
    RHK = "RHK"
    CHC = "CHC"
    EXT = "EXT"

    @property
    def value(self) -> str:
        return str(self)

    @classmethod
    def __get_pydantic_core_schema__(cls, _source: Any, _handler: Any) -> core_schema.CoreSchema:
        """Validate as a non-blank upper-case string, then wrap in SupplierCode."""
        return core_schema.no_info_after_validator_function(
            cls._validate,
            core_schema.str_schema(min_length=1, max_length=8, strip_whitespace=True),
            serialization=core_schema.plain_serializer_function_ser_schema(str),
        )

    @classmethod
    def _validate(cls, value: str) -> "SupplierCode":
        code = value.strip().upper()
        if not code:
            raise ValueError("supplier code must not be blank")
        return cls(code)


class AssignmentTarget(str, Enum):
    """Where a supplier's contract is attached when SmartBooking is enabled."""

    apikey = "apikey"
    sbgroup = "sbgroup"
    both = "both"


class ProvisioningDepth(str, Enum):
    """How far scenario creation goes past the mocks and contracts.

    ``full`` is the historical behaviour and stays the default, so existing callers
    (wizard, automation API, saved templates) keep working with no payload change.
    """

    contract_only = "contract_only"  # mocks + contract
    contract_br = "contract_br"      # mocks + contract, contract assigned to the BR rules
    full = "full"                    # mocks + contract + a NEW apiKey (+ apiKey -> BR)


class PreBookingStatus(str, Enum):
    """Which PreBooking (price-check) response the supplier mock returns.

    The values are Expedia's own wire strings, so the scenario field and the mock body
    say the same thing and there is no translation layer. Each maps to a template file
    beside the supplier's PreBooking template — ``available`` is the historical
    ``v1.json``, so an unset scenario builds byte-identical mocks to before.

    ``partial_sold_out`` is deliberately absent: on EXP that is a different API
    (``POST /v3/properties/{id}/rooms``, per-room status) which the core only calls for
    a 2+ room search, and SMF has no multi-room concept yet.
    """

    available = "available"
    price_changed = "price_changed"
    sold_out = "sold_out"


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
    prebooking_status: PreBookingStatus = Field(
        default=PreBookingStatus.available,
        description=(
            "Which price-check response this supplier's PreBooking mock returns. "
            "'available' (default) is today's behaviour. 'sold_out' also skips the "
            "Booking/GetOrder/CancelOrder mocks — the supplier body carries no book "
            "link, so the chain genuinely stops there."
        ),
    )
    can_prebook: Optional[bool] = Field(
        default=None,
        description=(
            "Override the contract's canPrebook permission. Unset (default) leaves "
            "whatever the reference contract carries. Affects the PERMISSION only — "
            "use prebook_url to control the URL."
        ),
    )
    supplier_prebooking: Optional[bool] = Field(
        default=None,
        description=(
            "Override endpointsSupported.prebooking on the SUPPLIER record. Unset "
            "leaves it alone. WARNING: that record is shared by every contract and "
            "every concurrent scenario in the env — while this is off, prebooking is "
            "off for all of them. SMF restores the previous value on teardown."
        ),
    )
    prebook_url: Optional[bool] = Field(
        default=None,
        description=(
            "Whether the contract gets overridePrebookUrl. Unset (default) writes it, "
            "as before. False omits it, leaving the contract with no prebook override "
            "while the PreBooking mock is still registered. Independent of "
            "can_prebook, so permission-on/url-off and permission-off/url-on are both "
            "expressible."
        ),
    )
    prebooking_changed_price: Optional[float] = Field(
        default=None,
        gt=0,
        description=(
            "Only with prebooking_status='price_changed': the price the price-check "
            "comes back with, in supplier currency. Search/Packages keep the package "
            "price; PreBooking, Booking and GetOrder use this one."
        ),
    )
    # EXP explicit pricing. `prices` IS the gross total (totals.inclusive) — there is no
    # separate total field, because two inputs for one number only invited disagreement.
    # What `prices` alone cannot express is the split: EXP runs with no business rules, so
    # the markup a package carries comes from the payload itself
    # (occupancy_pricing.totals.marketing_fee) and was whatever ratio the captured template
    # happened to have. Both amounts are in supplier currency, both or neither per package,
    # and price must equal original_price_with_vat + markup.
    original_price_with_vat: list[float] = Field(
        default_factory=list,
        description="EXP only: pre-markup price per package, i.e. the package price minus markup.",
    )
    markup: list[float] = Field(
        default_factory=list,
        description="EXP only: markup AMOUNT per package in supplier currency (totals.marketing_fee).",
    )
    # Occupancy the mocked rates advertise. Derby BTS drops every rate whose occupancy
    # does not match the search request (adultCount + childCount + childAges), returning
    # zero results and no error, so this has to line up with how the search is run.
    # Defaults to 2 adults because that is the default search.
    adults: int = Field(default=2, ge=1, le=10, description="Adults per room the rates are for")
    child_ages: list[int] = Field(
        default_factory=list,
        description="Age per child; length is the child count. Empty means adults only.",
    )
    room_count: int = Field(default=1, ge=1, le=8, description="Rooms the rates are for")
    supplier_room_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Derby room ids valid for this hotel, resolved from the adapter's room "
            "catalogue before the mock is built. Not user input: the orchestrator fills "
            "it for Derby suppliers (HIL, CHC), and it is empty for everyone else."
        ),
    )

    @property
    def room_criteria(self) -> dict[str, Any]:
        """Derby BTS ``roomCriteria`` for this spec's occupancy."""
        return {
            "roomCount": self.room_count,
            "adultCount": self.adults,
            "childCount": len(self.child_ages),
            "childAges": list(self.child_ages),
        }

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

    @model_validator(mode="after")
    def _validate_prebooking_status(self) -> "PackageSpec":
        """The changed price and the status travel together, and sold_out cannot book.

        Each of these is rejected rather than quietly ignored: a QA who typed a changed
        price and saw it do nothing would have no way to tell it was dropped.
        """
        is_price_changed = self.prebooking_status is PreBookingStatus.price_changed
        if is_price_changed and self.prebooking_changed_price is None:
            raise ValueError(
                "prebooking_status='price_changed' needs prebooking_changed_price — "
                "the price the check comes back with, in supplier currency"
            )
        if not is_price_changed and self.prebooking_changed_price is not None:
            raise ValueError(
                f"prebooking_changed_price only applies to prebooking_status="
                f"'price_changed', not '{self.prebooking_status.value}'"
            )
        if self.can_prebook is False and self.prebooking_status is not PreBookingStatus.available:
            raise ValueError(
                f"can_prebook=false means the supplier never price-checks, so "
                f"prebooking_status='{self.prebooking_status.value}' can never be "
                "observed — pick one or the other"
            )
        if self.prebook_url is False and self.prebooking_status is not PreBookingStatus.available:
            raise ValueError(
                f"prebook_url=false leaves the contract with no prebook override, so "
                f"prebooking_status='{self.prebooking_status.value}' is not reachable "
                "through it — pick one or the other"
            )
        # sold_out USED to reject booking_package_index, on the grounds that a scenario
        # which stops at PreBooking has nothing to book. It is allowed now because the
        # index answers a second question the sold-out case needs: WHICH package went
        # away. EXT expresses sold_out structurally, by dropping that one accommodation
        # from the price check, and without an index it could not know which. Read the
        # field as "the package under test" rather than "the package that gets booked".
        # No booking mock is built either way — scenario_engine drops the whole booking
        # flow whenever the status is sold_out, index or not.
        return self

    @model_validator(mode="after")
    def _validate_explicit_pricing(self) -> "PackageSpec":
        """original_price_with_vat and markup arrive together and must add up to the price.

        The package price is the gross total, so the split has to reconcile with it.
        Rejected rather than back-solved: a set that does not add up means one of the
        numbers was mistyped, and silently recomputing it would mock a price the tester did
        not ask for. The 0.01 tolerance is for float arithmetic on 2-decimal money.
        """
        if not (self.original_price_with_vat or self.markup):
            return self

        lengths = {
            "original_price_with_vat": len(self.original_price_with_vat),
            "markup": len(self.markup),
        }
        missing = [name for name, length in lengths.items() if length == 0]
        if missing:
            raise ValueError(
                "original_price_with_vat and markup must be given together; "
                f"missing: {', '.join(sorted(missing))}"
            )
        if len(set(lengths.values())) != 1:
            raise ValueError(
                f"original_price_with_vat and markup must be the same length, got {lengths}"
            )
        if lengths["markup"] > len(self.prices):
            raise ValueError(
                f"original_price_with_vat and markup cover {lengths['markup']} package(s) "
                f"but only {len(self.prices)} price(s) were given"
            )

        for index, (original, markup) in enumerate(
            zip(self.original_price_with_vat, self.markup)
        ):
            price = self.prices[index]
            if min(original, markup) < 0:
                raise ValueError(f"package {index + 1}: prices and markup must not be negative")
            if abs(price - (original + markup)) >= 0.01:
                raise ValueError(
                    f"package {index + 1}: price {price} must equal "
                    f"original_price_with_vat {original} + markup {markup} "
                    f"(= {round(original + markup, 2)})"
                )
        return self

    @property
    def has_explicit_pricing(self) -> bool:
        """Whether this spec splits its price into originalPriceWithVAT + markup.
        The validator guarantees both are present, aligned and reconciled when either is."""
        return bool(self.markup)


def _trim_number(value: float) -> str:
    """10.0 -> "10", 12.5 -> "12.5" — BR shows these verbatim, so no stray decimals."""
    return str(int(value)) if value == int(value) else str(value)


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
    code: SupplierCode = Field(description="Supplier code as configured in the suppliers table")
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
    provisioning_depth: ProvisioningDepth = Field(
        default=ProvisioningDepth.full,
        description=(
            "How far provisioning goes: contract_only (mocks + contract), contract_br "
            "(also assigns the contract to the BR rules), or full (also creates a new "
            "apiKey and assigns THAT to BR). Default full = historical behaviour."
        ),
    )
    existing_api_key: Optional[str] = Field(
        default=None,
        description=(
            "Optional apiKey (uid) that already exists: the scenario's contracts are "
            "attached to it instead of creating a new apiKey. Only used by the "
            "contract_only / contract_br depths; ignored for full. SMF never deletes "
            "an apiKey it did not create — teardown just detaches the contracts."
        ),
    )
    assign_to_br: bool = Field(
        default=True,
        description=(
            "Assign the created apiKey to the Static/Dynamic Markup BR rules on create "
            "(cleaned up on teardown). Crawla-exported and SB scenarios always assign "
            "regardless of this flag; it only gates the plain scenario-wizard flow."
        ),
    )
    # BR markup output values for this scenario. Every scenario used to get 10% static and
    # 15%-25% dynamic, so testing another markup meant editing source. Unset keeps those
    # defaults (see business_rules.DEFAULT_STATIC_MARKUP / DEFAULT_DYNAMIC_MARKUP).
    static_markup: Optional[str] = Field(
        default=None,
        description=(
            "Static Markup (rule 3) output value, e.g. '10' or '10%'. Normalized to '10%'. "
            "Omit for the default 10%."
        ),
    )
    dynamic_markup: Optional[str] = Field(
        default=None,
        description=(
            "Dynamic Markup (rule 4) output value, e.g. '10%-15%' or '10-15'. Normalized to "
            "'10%-15%'. Omit for the default 15%-25%."
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

    @field_validator("static_markup", "dynamic_markup", mode="before")
    @classmethod
    def _normalize_markup(cls, value: Any) -> Any:
        """Accept a bare number or a range, with or without the % signs, and canonicalize.

        BR stores these as '10%' and '15%-25%'. QAs type them either way, so `10`, `10%`,
        `10-15` and `10%-15%` all land on the shape BR wants rather than being rejected for
        punctuation. Blank means "not asked for" — the default applies.
        """
        if value is None:
            return None
        text = str(value).strip().replace(" ", "")
        if not text:
            return None
        parts = text.split("-")
        if len(parts) > 2:
            raise ValueError(
                f"markup {value!r} is not a percentage or percentage range "
                "(expected e.g. '10' or '10%-15%')"
            )
        numbers: list[float] = []
        for part in parts:
            number = part[:-1] if part.endswith("%") else part
            try:
                parsed = float(number)
            except ValueError:
                raise ValueError(
                    f"markup {value!r} is not a percentage or percentage range "
                    "(expected e.g. '10' or '10%-15%')"
                ) from None
            if parsed < 0:
                raise ValueError(f"markup {value!r} must not be negative")
            numbers.append(parsed)
        if len(numbers) == 2 and numbers[0] > numbers[1]:
            raise ValueError(f"markup range {value!r} is reversed — low bound must come first")
        return "-".join(f"{_trim_number(n)}%" for n in numbers)

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
    def _validate_provisioning_depth(self) -> "ScenarioRequest":
        """Reject depth/flag combinations that cannot be honoured.

        Silently ignoring them is worse than failing: a dropped sb_enabled reads as
        "SmartBooking is broken" rather than "that depth has no apiKey to put it on".
        """
        if self.provisioning_depth is not ProvisioningDepth.full:
            if self.sb_enabled or self.sb_config is not None:
                raise ValueError(
                    "SmartBooking needs a new apiKey to attach to — it requires "
                    "provisioning_depth='full'."
                )
            if self.crawla_export:
                # Crawla scenarios drive BR off the apiKey (see orchestrator step 6).
                raise ValueError("Crawla-exported scenarios require provisioning_depth='full'.")
        elif self.existing_api_key:
            raise ValueError(
                "existing_api_key only applies to provisioning_depth "
                "'contract_only' or 'contract_br' — 'full' creates its own apiKey."
            )
        if self.provisioning_depth is ProvisioningDepth.contract_only and (
            self.static_markup or self.dynamic_markup
        ):
            raise ValueError(
                "static_markup / dynamic_markup need BR provisioning — use "
                "provisioning_depth 'full' or 'contract_br'."
            )
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
    # True when api_key refers to a PRE-EXISTING apiKey the scenario only attached its
    # contracts to. Teardown must then detach instead of deleting — this flag is the
    # only thing standing between a cleanup and someone else's shared apiKey.
    api_key_is_external: bool = False
    contracts: dict[str, str] = Field(default_factory=dict)
    booking_ids: dict[str, str] = Field(default_factory=dict)
    check_in: str
    check_out: str
    atg_hotel_id: str
    supplier_hotel_ids: dict[str, str] = Field(default_factory=dict)
    crawla_export: Optional[dict[str, Any]] = None
    br_setup: Optional[dict[str, Any]] = None
    # {supplier code: previous endpointsSupported.prebooking} for scenarios that
    # changed the shared supplier record. None means the key was absent and must be
    # restored as absence. Teardown reads this; losing it leaves the env altered.
    supplier_prebooking_restore: Optional[dict[str, Any]] = None
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
