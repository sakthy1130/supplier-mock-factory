"""Persistence records for scenarios and templates.

Plain dataclasses, not an ORM: the storage layer is MongoDB and each record maps to
one document, with the record's ``id`` stored as the document ``_id`` (no duplicate
key). Field names are unchanged from the previous SQLAlchemy models so the service
layer keeps reading and writing the same attributes.

BSON has no timezone: a datetime written as aware UTC reads back NAIVE and rounded
to milliseconds. ``from_doc`` re-attaches UTC so ``expires_at`` comparisons and API
serialisation behave as they did on SQLite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: Any) -> Optional[datetime]:
    """Re-attach UTC to a datetime read back from BSON (which drops tzinfo)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return value


@dataclass
class ScenarioRecord:
    id: str
    namespace: str
    check_in: str
    check_out: str
    hotel_id: str
    request_json: dict
    status: str = "PENDING"
    # Which env (dev|stg) this scenario was created in. Lifecycle ops (run, refresh,
    # teardown) always resolve settings from THIS value, never the caller's current
    # dropdown selection — see app/services/scenario_service.py.
    env: str = "stg"
    api_key: Optional[str] = None
    api_key_id: Optional[str] = None
    # True when api_key is a pre-existing apiKey this scenario only attached contracts
    # to. Teardown detaches instead of deleting — see orchestrator.teardown_scenario.
    api_key_is_external: bool = False
    contracts_json: dict = field(default_factory=dict)
    booking_ids_json: dict = field(default_factory=dict)
    suppliers_json: list = field(default_factory=list)
    mock_server_base_url: Optional[str] = None
    expectation_count: int = 0
    error_message: Optional[str] = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    expires_at: Optional[datetime] = None
    # SB-specific — None for non-SB scenarios
    sb_config_id: Optional[str] = None
    sb_group_id: Optional[str] = None

    def to_doc(self) -> dict:
        doc = {key: value for key, value in self.__dict__.items() if key != "id"}
        doc["_id"] = self.id
        return doc

    @classmethod
    def from_doc(cls, doc: dict) -> "ScenarioRecord":
        data = dict(doc)
        data["id"] = data.pop("_id")
        for key in ("created_at", "updated_at", "expires_at"):
            if key in data:
                data[key] = _as_utc(data[key])
        return cls(**_known_fields(cls, data))


@dataclass
class ScenarioTemplateRecord:
    """A saved supplier package preset — pasted in via the Template Bedding Mock UI
    so a known package layout (room names/prices/board/refundability) can be reused
    to seed the scenario wizard without retyping it each time."""

    id: str
    label: str = ""
    description: str = ""
    function: Optional[str] = None
    atg_hotel_id: str = ""
    # Legacy (pre-multi-supplier) fields — kept so templates created before
    # suppliers_json existed still read back correctly; see _record_to_model in
    # scenario_template_service.py. New rows populate the first supplier here too,
    # for anything that might still read the old shape.
    supplier: str = ""
    packages_json: list = field(default_factory=list)
    # Full multi-supplier payload: [{"supplier": "HBS", "packages": [...],
    # "assignment_target": "apikey"}, ...]. A supplier may repeat — each entry
    # becomes its own scenario instance.
    suppliers_json: Optional[list] = None
    # Create the apiKey with SmartBooking enabled when this template is used.
    sb_enabled: Optional[bool] = False
    created_at: datetime = field(default_factory=_utcnow)

    def to_doc(self) -> dict:
        doc = {key: value for key, value in self.__dict__.items() if key != "id"}
        doc["_id"] = self.id
        return doc

    @classmethod
    def from_doc(cls, doc: dict) -> "ScenarioTemplateRecord":
        data = dict(doc)
        data["id"] = data.pop("_id")
        if "created_at" in data:
            data["created_at"] = _as_utc(data["created_at"])
        return cls(**_known_fields(cls, data))


@dataclass
class SupplierRecord:
    """Everything SMF needs to mock one supplier, per environment.

    Replaces what used to be spread across a Python enum, two module-level registry
    dicts, five Settings fields, and a dozen ``if supplier_code == "XXX"`` branches.
    Documents are seeded from those constants on first boot (app/db/seed_suppliers.py)
    and are editable from the Suppliers screen, so adding a supplier is a UI action.

    Env-scoped because dev and stg do NOT share Backoffice supplier records — a dev
    contract referencing stg's supplier _id NPEs in hotel-connectivity-core. Uniqueness
    of (code, env) was a SQLite constraint; it is a Mongo unique index now, created in
    app/db/database.py.
    """

    id: str
    code: str
    name: str
    env: str = "stg"
    supplier_type: str = "net"

    # Backoffice identity — supplier_id is the Mongo _id, auto_id the numeric autoId.
    supplier_id: str = ""
    auto_id: int = 0
    # Contract cloned for every scenario; empty means build a minimal body instead.
    reference_contract_id: str = ""

    default_supplier_currency: str = "USD"
    default_contract_currency: str = "USD"

    # Which log types this supplier serves, and which of them get package mutation.
    log_types_json: list = field(default_factory=list)
    package_log_types_json: list = field(default_factory=list)

    ui_color: str = ""

    # canonical_base, mock_path_suffix, opt_field_map, opt_defaults, opt_source,
    # path_namespaced, dynamic_market_type — see app/models/supplier.py.
    mock_config_json: dict = field(default_factory=dict)
    # GenericMockPlugin input: packages_path, date_keys, price_keys, board_key, ...
    mutation_config_json: dict = field(default_factory=dict)
    # Inline copy of field-maps/{CODE}.json (booking-id extraction paths).
    field_map_json: Optional[dict] = None

    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def to_doc(self) -> dict:
        doc = {key: value for key, value in self.__dict__.items() if key != "id"}
        doc["_id"] = self.id
        return doc

    @classmethod
    def from_doc(cls, doc: dict) -> "SupplierRecord":
        data = dict(doc)
        data["id"] = data.pop("_id")
        for key in ("created_at", "updated_at"):
            if key in data:
                data[key] = _as_utc(data[key])
        return cls(**_known_fields(cls, data))


def _known_fields(record_cls, data: dict) -> dict:
    """Drop unknown keys so a document written by a newer/older build still loads."""
    allowed = set(record_cls.__dataclass_fields__)
    return {key: value for key, value in data.items() if key in allowed}
