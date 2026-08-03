"""Cancellation-policy date derivation shared across supplier plugins.

Cancellation dates are derived from the scenario's stay instead of hardcoded
sample values: a refundable rate is free to cancel until FREE_CANCEL_DAYS_BEFORE_CHECKIN
days before check-in, then penalized; a non-refundable rate is penalized from the
start. Refundability itself is NOT decided here — it stays driven by the
per-package Refundable flag; this module only shapes the dates.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

# Refundable rates are free to cancel until this many days before check-in.
FREE_CANCEL_DAYS_BEFORE_CHECKIN = 2

# Non-refundable rates must have their penalty active before any possible booking
# date, so this stays a fixed far-past sentinel by design — deriving it from
# check-in would make it a future deadline for far-out bookings and read as
# "free until then" (i.e. refundable).
PENALTY_ALWAYS_FROM = date(2000, 1, 1)

# Every supplier must emit the free-cancel deadline as the SAME instant so a
# rebooker comparing `dateFrom` across HBS/EXP/EXT sees no difference. EXT's date
# is rendered by the adapter at midnight +05:30 (its fixed default for the
# relative daysBeforeArrival penalty); HBS/EXP format their absolute deadline
# with the same offset so all three resolve to one UTC instant.
CANCEL_TZ_OFFSET = "+05:30"


def format_cancel_from(d: date, tz_offset: str = CANCEL_TZ_OFFSET) -> str:
    """A cancellation `from`/`start` timestamp at midnight in the shared offset."""
    return f"{d:%Y-%m-%d}T00:00:00.000{tz_offset}"


def free_cancel_deadline(check_in: str, days_before: int = FREE_CANCEL_DAYS_BEFORE_CHECKIN) -> date:
    """The date a refundable rate's free-cancellation window ends: check_in − days_before."""
    return datetime.strptime(check_in, "%Y-%m-%d").date() - timedelta(days=days_before)


def penalty_start_date(check_in: str, is_refundable: bool) -> date:
    """When the cancellation penalty starts applying: the free-cancel deadline for
    a refundable rate, or the far-past sentinel for a non-refundable one."""
    return free_cancel_deadline(check_in) if is_refundable else PENALTY_ALWAYS_FROM
