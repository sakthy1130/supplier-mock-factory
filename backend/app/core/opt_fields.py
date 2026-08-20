"""Log type -> contract ``opt`` field names.

A leaf module on purpose: the supplier seed and the supplier service both need these
maps, and importing them from ``mock_urls`` would drag in ``scenario_engine`` (and
through it the whole plugin registry) during ``init_db``.
"""

from __future__ import annotations

LOG_TYPE_TO_OPT_FIELD: dict[str, str] = {
    "Search": "searchUrl",
    "Packages": "availabilityUrl",
    "CancellationPolicy": "cancellationPolicyUrl",
    "PreBooking": "prebookingUrl",
    "Booking": "bookingUrl",
    "GetOrder": "orderUrl",
    "CancelOrder": "cancelBookingUrl",
}

# EXP contracts route traffic via opt override URLs (backoffice UI labels).
EXP_LOG_TYPE_TO_OVERRIDE_FIELD: dict[str, str] = {
    "Search": "overrideSearchUrl",
    "Packages": "overridePackagesUrl",
    "Booking": "overrideBookingUrl",
    "GetOrder": "overrideRetrieveBookingUrl",
    "CancelOrder": "overrideCancelBookingUrl",
}

# Fields that fall back to another resolved URL rather than being left unset.
OPT_FALLBACK_FIELDS: tuple[str, ...] = (
    "cancellationPolicyUrl",
    "cancellationUrl",
    "statusUrl",
    "prebookingUrl",
    "orderUrl",
    "bookingUrl",
    "cancelBookingUrl",
)
