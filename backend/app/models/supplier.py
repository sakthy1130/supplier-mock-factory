"""Pydantic models for supplier configuration — the data that used to be Python.

``MockConfig`` and ``MutationConfig`` are the two escape hatches that let a supplier
be added from the UI: the first drives contract/opt/path shaping (what the per-supplier
``*_paths.py`` modules and the ``if supplier_code ==`` chains used to do), the second
drives GenericMockPlugin (what a hand-written ``plugins/<code>.py`` used to do).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.namespace import ALL_SCENARIO_LOG_TYPES

SupplierType = Literal["net", "gross"]
DynamicMarketType = Literal["DynamicMarkupTarget", "MarketPriceSource", "NotParticipating"]


class MockConfig(BaseModel):
    """How this supplier's mocks are addressed and how its contract opt is built."""

    model_config = ConfigDict(extra="allow")

    # Canonical API path roots per log type, plus a suffix that disambiguates log
    # types sharing a path (MockServer matches on path + method only).
    canonical_base: dict[str, str] = Field(default_factory=dict)
    mock_path_suffix: dict[str, str] = Field(default_factory=dict)

    # log type -> contract opt field (e.g. Search -> searchUrl, or EXP's overrideSearchUrl).
    opt_field_map: dict[str, str] = Field(default_factory=dict)

    # "canonical" builds opt URLs from canonical_base + mock_path_suffix and ignores
    # the ingested template paths (HBS). "ingested" uses the paths the built
    # expectations actually carry (everyone else).
    opt_source: Literal["canonical", "ingested"] = "ingested"

    # Rewrite httpRequest.path to canonical_base + mock_path_suffix before register.
    path_rewrite: bool = False
    # Prefix the path with the scenario namespace instead — /{namespace}/search (EXP).
    path_namespaced: bool = False
    # Unwrap an adapter-log body envelope ({"body": [...]} -> [...]) on Search/Packages.
    unwrap_adapter_log_body: bool = False

    # Filled into contract opt when absent. "blank" also replaces "" and "0";
    # "missing" only fills a genuine None (EXP's looser rule).
    opt_defaults: dict[str, Any] = Field(default_factory=dict)
    opt_defaults_fill: Literal["blank", "missing"] = "blank"
    # Always overwritten, whatever the cloned reference contract carried.
    forced_opt: dict[str, Any] = Field(default_factory=dict)
    # Keys re-forced from opt_defaults even if the contract had a usable value.
    always_enforce_opt: list[str] = Field(default_factory=list)
    # Set opt.mockServerUrl to the MockServer base (with trailing slash).
    set_mock_server_url: bool = False

    # Net suppliers receive the borrowed market price; gross suppliers provide it.
    dynamic_market_type: Optional[DynamicMarketType] = None

    # The GetOrder mock is addressed as <GetOrder path>/<bookingId> (HBS), so the path
    # has to be rewritten whenever a fresh booking id is injected.
    booking_id_in_get_order_path: bool = False

    def mock_path(self, log_type: str) -> str | None:
        base = self.canonical_base.get(log_type)
        suffix = self.mock_path_suffix.get(log_type)
        if not base or not suffix:
            return None
        return f"{base}/{suffix}"


class MutationConfig(BaseModel):
    """GenericMockPlugin input — which JSON keys carry what, and where rates live."""

    model_config = ConfigDict(extra="allow")

    # Dotted path to the array of rates/rooms/accommodations that gets cloned to
    # the requested package count. Numeric segments index into lists:
    # "httpResponse.body.body.0.accommodations".
    packages_path: str = ""
    check_in_keys: list[str] = Field(default_factory=list)
    check_out_keys: list[str] = Field(default_factory=list)
    price_keys: list[str] = Field(default_factory=list)
    board_key: str = ""
    room_name_key: str = ""
    currency_key: str = ""
    hotel_id_key: str = ""
    package_id_key: str = ""
    refundable_key: str = ""
    # Board codes this supplier accepts; anything else falls back to the first entry.
    board_values: list[str] = Field(default_factory=list)
    # Substring that identifies this supplier's adapter in Enigma log sources.
    adapter_source_match: str = ""

    # ── Booking id handling (was hardcoded per supplier in booking_id_injector) ──
    # JSON key names that carry the booking id; field-map generation walks the
    # templates for these and records every path it finds.
    booking_id_keys: list[str] = Field(default_factory=list)
    # Tried after field_map paths when extracting the template's booking id.
    booking_id_fallback_paths: list[str] = Field(default_factory=list)
    # Suppliers whose booking id lives somewhere different per log type (RHK).
    booking_id_paths_by_log_type: dict[str, list[str]] = Field(default_factory=dict)
    # digits: same-width numeric string. prefix_digits: keep "PREFIX-" and renumber
    # (HBS). prefix_hex: keep the prefix and append 32 hex chars (RHK).
    booking_id_format: Literal["digits", "prefix_digits", "prefix_hex"] = "digits"

    @property
    def is_usable(self) -> bool:
        """True when the generic mutator can actually clone packages for this supplier."""
        return bool(self.packages_path)


class SupplierConfigBase(BaseModel):
    code: str = Field(min_length=2, max_length=8)
    name: str = Field(min_length=1, max_length=64)
    supplier_type: SupplierType = "net"

    supplier_id: str = Field(default="", max_length=64)
    auto_id: int = 0
    reference_contract_id: str = Field(default="", max_length=64)

    default_supplier_currency: str = Field(default="USD", min_length=3, max_length=3)
    default_contract_currency: str = Field(default="USD", min_length=3, max_length=3)

    log_types: list[str] = Field(min_length=1)
    package_log_types: list[str] = Field(default_factory=lambda: ["Packages"])

    ui_color: str = Field(default="", max_length=16)

    mock_config: MockConfig = Field(default_factory=MockConfig)
    mutation_config: MutationConfig = Field(default_factory=MutationConfig)
    field_map: Optional[dict[str, Any]] = None

    @field_validator("code")
    @classmethod
    def _upper_code(cls, value: str) -> str:
        code = value.strip().upper()
        if not code.isalnum():
            raise ValueError("supplier code must be alphanumeric, e.g. HBS")
        return code

    @field_validator("default_supplier_currency", "default_contract_currency")
    @classmethod
    def _upper_currency(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("log_types", "package_log_types")
    @classmethod
    def _known_log_types(cls, value: list[str]) -> list[str]:
        unknown = [lt for lt in value if lt not in ALL_SCENARIO_LOG_TYPES]
        if unknown:
            raise ValueError(
                f"unknown log types {unknown}; expected any of {ALL_SCENARIO_LOG_TYPES}"
            )
        # Preserve the caller's order but drop duplicates.
        return list(dict.fromkeys(value))


class SupplierConfigCreate(SupplierConfigBase):
    """Payload for POST/PUT. ``env`` comes from the X-SMF-Env header, not the body."""


class SupplierConfig(SupplierConfigBase):
    id: str
    env: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @property
    def supplier_detail(self) -> dict[str, Any]:
        """The nested supplierDetail block Backoffice contracts expect."""
        return {"code": self.code, "name": self.name, "autoId": self.auto_id}


class ReadinessCheck(BaseModel):
    key: str
    label: str
    ok: bool
    detail: str = ""
    # Informational checks never block scenario creation (e.g. "has a custom plugin").
    blocking: bool = True
    # Which UI action fixes it, when there is one.
    fix: Optional[str] = None


class SupplierReadiness(BaseModel):
    code: str
    env: str
    ready: bool
    checks: list[ReadinessCheck]

    @property
    def missing(self) -> list[str]:
        return [c.label for c in self.checks if c.blocking and not c.ok]


class SupplierListItem(BaseModel):
    """The shape GET /api/suppliers returns — superset of the old hardcoded payload."""

    code: str
    name: str
    log_types: list[str]
    status: str
    env: str
    supplier_type: str
    ui_color: str = ""
    default_supplier_currency: str = "USD"
    default_contract_currency: str = "USD"
    ready: bool = True
    missing_count: int = 0


class TemplateUploadResult(BaseModel):
    code: str
    log_type: str
    path: str
    bytes_written: int


class ProbeLogTypeResult(BaseModel):
    log_type: str
    ok: bool
    error: Optional[str] = None
    path: Optional[str] = None
    package_count: Optional[int] = None


class IngestRequest(BaseModel):
    sid: str = Field(min_length=1, description="Enigma SID whose adapter logs to build templates from")

    @field_validator("sid")
    @classmethod
    def _strip_sid(cls, value: str) -> str:
        sid = value.strip()
        if not sid:
            raise ValueError("sid must not be blank")
        return sid


class IngestResultModel(BaseModel):
    supplier_code: str
    sid: str
    written: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    unresolved: int = 0
    paths: dict[str, str] = Field(default_factory=dict)
    field_map_paths: int = 0
    sources_seen: list[str] = Field(default_factory=list)
    # Set when nothing matched, explaining why rather than just returning empty lists.
    warning: Optional[str] = None


class ProbeResult(BaseModel):
    code: str
    env: str
    ok: bool
    error: Optional[str] = None
    plugin: str
    log_types: list[ProbeLogTypeResult] = Field(default_factory=list)
