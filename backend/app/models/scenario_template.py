"""Pydantic models for user-saved scenario package templates (paste-JSON presets)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.scenario import SupplierCode


class TemplatePackageRow(BaseModel):
    room_name: str = Field(min_length=1)
    room_basis: str = "RO"
    price: float
    refundable: bool = True

    @field_validator("room_basis")
    @classmethod
    def _upper_basis(cls, value: str) -> str:
        return value.strip().upper() or "RO"


class SupplierTemplatePackages(BaseModel):
    supplier: SupplierCode
    supplier_currency: str = Field(default="SAR", min_length=3, max_length=3)
    contract_currency: str = Field(default="USD", min_length=3, max_length=3)
    packages: list[TemplatePackageRow] = Field(min_length=1)


class ScenarioTemplateCreate(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    description: str = ""
    function: Optional[str] = Field(default=None, max_length=64, description="Template purpose/function (e.g., templateBeddingMock, importTemplate)")
    # Required: an empty hotel id silently falls back to the wizard's generic
    # default when the template is opened, which reads as "the hotel id I gave
    # didn't import" rather than "I never set one" — reject it up front instead.
    atg_hotel_id: str = Field(min_length=1)
    suppliers: list[SupplierTemplatePackages] = Field(min_length=1)

    @field_validator("atg_hotel_id")
    @classmethod
    def _strip_hotel_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("atg_hotel_id must not be blank")
        return stripped

    @field_validator("suppliers")
    @classmethod
    def _unique_suppliers(cls, value: list[SupplierTemplatePackages]) -> list[SupplierTemplatePackages]:
        codes = [entry.supplier for entry in value]
        if len(set(codes)) != len(codes):
            raise ValueError("each supplier can only appear once per template")
        return value


class ScenarioTemplate(BaseModel):
    id: str
    label: str
    description: str
    function: Optional[str] = None
    atg_hotel_id: str
    suppliers: list[SupplierTemplatePackages]
    created_at: datetime
