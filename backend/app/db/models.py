"""SQLAlchemy models for scenario persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SupplierRecord(Base):
    """Everything SMF needs to mock one supplier, per environment.

    Replaces what used to be spread across a Python enum, two module-level registry
    dicts, five Settings fields, and a dozen ``if supplier_code == "XXX"`` branches.
    Rows are seeded from those constants on first boot (app/db/seed_suppliers.py) and
    are editable from the Suppliers screen, so adding a supplier is a UI action.

    Env-scoped because dev and stg do NOT share Backoffice supplier records — a dev
    contract referencing stg's supplier _id NPEs in hotel-connectivity-core.
    """

    __tablename__ = "suppliers"
    __table_args__ = (UniqueConstraint("code", "env", name="uq_supplier_code_env"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(8), index=True)
    env: Mapped[str] = mapped_column(String(16), default="stg", index=True)
    name: Mapped[str] = mapped_column(String(64))
    supplier_type: Mapped[str] = mapped_column(String(8), default="net")

    # Backoffice identity — supplier_id is the Mongo _id, auto_id the numeric autoId.
    supplier_id: Mapped[str] = mapped_column(String(64), default="")
    auto_id: Mapped[int] = mapped_column(Integer, default=0)
    # Contract cloned for every scenario; empty means build a minimal body instead.
    reference_contract_id: Mapped[str] = mapped_column(String(64), default="")

    default_supplier_currency: Mapped[str] = mapped_column(String(3), default="USD")
    default_contract_currency: Mapped[str] = mapped_column(String(3), default="USD")

    # Which log types this supplier serves, and which of them get package mutation.
    log_types_json: Mapped[list] = mapped_column(JSON, default=list)
    package_log_types_json: Mapped[list] = mapped_column(JSON, default=list)

    ui_color: Mapped[str] = mapped_column(String(16), default="")

    # canonical_base, mock_path_suffix, opt_field_map, opt_defaults, opt_source,
    # path_namespaced, dynamic_market_type — see app/models/supplier.py.
    mock_config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    # GenericMockPlugin input: packages_path, date_keys, price_keys, board_key, ...
    mutation_config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    # Inline copy of field-maps/{CODE}.json (booking-id extraction paths).
    field_map_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class ScenarioRecord(Base):
    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    namespace: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    # Which env (dev|stg) this scenario was created in. Lifecycle ops (run, refresh,
    # teardown) always resolve settings from THIS value, never the caller's current
    # dropdown selection — see app/services/scenario_service.py.
    env: Mapped[str] = mapped_column(String(16), default="stg", index=True)
    request_json: Mapped[dict] = mapped_column(JSON)
    api_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    api_key_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    contracts_json: Mapped[dict] = mapped_column(JSON)
    booking_ids_json: Mapped[dict] = mapped_column(JSON)
    suppliers_json: Mapped[list] = mapped_column(JSON)
    check_in: Mapped[str] = mapped_column(String(10))
    check_out: Mapped[str] = mapped_column(String(10))
    hotel_id: Mapped[str] = mapped_column(String(64))
    mock_server_base_url: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    expectation_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # SB-specific — null for non-SB scenarios
    sb_config_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sb_group_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class ScenarioTemplateRecord(Base):
    """A saved supplier package preset — pasted in via the Template Bedding Mock UI
    so a known package layout (room names/prices/board/refundability) can be reused
    to seed the scenario wizard without retyping it each time."""

    __tablename__ = "scenario_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(500), default="")
    function: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    atg_hotel_id: Mapped[str] = mapped_column(String(64), default="")
    # Legacy (pre-multi-supplier) columns — kept so templates created before
    # suppliers_json existed still read back correctly; see _record_to_model
    # in scenario_template_service.py. New rows populate the first supplier
    # here too, for anything that might still read the old shape.
    supplier: Mapped[str] = mapped_column(String(8))
    packages_json: Mapped[list] = mapped_column(JSON)
    # Full multi-supplier payload: [{"supplier": "HBS", "packages": [...]}, ...]
    suppliers_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
