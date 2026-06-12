"""SQLAlchemy models for scenario persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ScenarioRecord(Base):
    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    namespace: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
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
