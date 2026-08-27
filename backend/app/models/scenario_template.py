"""Pydantic models for user-saved scenario package templates (paste-JSON presets)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.scenario import AssignmentTarget, PreBookingStatus, SupplierCode


# What a saved template is FOR. Drives the two tabs on the Templates screen. The field
# already existed on the model, unused; these are the values it now carries. A template
# saved before this (function=None) reads as bedding, which is what they all are.
TEMPLATE_KIND_BEDDING = "templateBeddingMock"
TEMPLATE_KIND_PREBOOKING = "preBookingMock"
TEMPLATE_KINDS = (TEMPLATE_KIND_BEDDING, TEMPLATE_KIND_PREBOOKING)


class TemplatePackageRow(BaseModel):
    room_name: str = Field(min_length=1)
    room_basis: str = "RO"
    price: float
    refundable: bool = True
    # EXP explicit pricing: the split of `price` into pre-markup + markup (see
    # PackageSpec.original_price_with_vat / markup). Optional so every template saved before
    # this existed keeps loading; the two travel together and must add up to `price`, which
    # PackageSpec's validator enforces once they reach a scenario.
    original_price_with_vat: Optional[float] = None
    markup: Optional[float] = None

    @field_validator("room_basis")
    @classmethod
    def _upper_basis(cls, value: str) -> str:
        return value.strip().upper() or "RO"


class SupplierTemplatePackages(BaseModel):
    supplier: SupplierCode
    supplier_currency: str = Field(default="SAR", min_length=3, max_length=3)
    contract_currency: str = Field(default="USD", min_length=3, max_length=3)
    packages: list[TemplatePackageRow] = Field(min_length=1)
    assignment_target: AssignmentTarget = AssignmentTarget.apikey
    # Per SUPPLIER, mirroring where these live on PackageSpec — one price check per
    # supplier, not per package row. Defaulted so every template saved before this keeps
    # loading. Deliberately NOT re-validated here: PackageSpec already rejects
    # price_changed with no price, a price on any other status, and sold_out with a
    # booking index, and a template is only ever realised through a PackageSpec.
    prebooking_status: PreBookingStatus = PreBookingStatus.available
    prebooking_changed_price: Optional[float] = Field(default=None, gt=0)
    # Contract permission. Unset leaves the reference contract's own value.
    can_prebook: Optional[bool] = None
    prebook_url: Optional[bool] = None
    # Which package the booking flow is built for. Without this a template could not
    # reproduce the scenario it came from: the scenario booked a package, the template
    # forgot, and running it gave search+packages only.
    booking_package_index: Optional[int] = Field(default=None, ge=0)
    # Occupancy. Defaults match PackageSpec, so a template saved at the default
    # occupancy is unchanged; a 2-adults-plus-child scenario now survives the round trip.
    adults: int = Field(default=2, ge=1, le=10)
    child_ages: list[int] = Field(default_factory=list)
    room_count: int = Field(default=1, ge=1, le=8)


class ScenarioTemplateCreate(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    description: str = ""
    function: Optional[str] = Field(default=None, max_length=64, description="Template function/purpose (e.g., templateBeddingMock, importTemplate)")
    # Required: an empty hotel id silently falls back to the wizard's generic
    # default when the template is opened, which reads as "the hotel id I gave
    # didn't import" rather than "I never set one" — reject it up front instead.
    atg_hotel_id: str = Field(min_length=1)
    # A supplier MAY appear more than once: each entry becomes its own scenario
    # supplier instance ("EXP" then "EXP-2"), with its own packages and contract.
    # See app.models.scenario.instance_key_for.
    suppliers: list[SupplierTemplatePackages] = Field(min_length=1)
    sb_enabled: bool = False

    @field_validator("atg_hotel_id")
    @classmethod
    def _strip_hotel_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("atg_hotel_id must not be blank")
        return stripped


class ScenarioTemplate(BaseModel):
    id: str
    label: str
    description: str
    function: Optional[str] = None
    atg_hotel_id: str
    suppliers: list[SupplierTemplatePackages]
    sb_enabled: bool = False
    created_at: datetime
    has_br_child_condition: bool = Field(
        default=False,
        description="True if this template has a per-template child BR condition configured for the current env.",
    )
