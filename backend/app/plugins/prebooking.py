"""What a price check comes back at — shared by every supplier that has one.

The rule is the same wherever PreBooking exists, so it lives here rather than being
restated per plugin: a re-quote when the scenario asked for one, otherwise the price of
the package actually being booked.

Takes the already-normalized price list rather than reading ``spec.prices`` itself, since
each plugin pads that list its own way.
"""

from __future__ import annotations

from app.models.scenario import PackageSpec, PreBookingStatus


def prebooking_effective_price(spec: PackageSpec, prices: list[float]) -> float | None:
    """The price the PreBooking body should quote, or None with nothing to price from.

    For ``price_changed`` this is deliberately DIFFERENT from the package price: Search
    and Packages keep the original, and the disagreement is the thing under test.
    """
    if spec.prebooking_status is PreBookingStatus.price_changed:
        return spec.prebooking_changed_price
    if not prices:
        return None
    idx = spec.booking_package_index if spec.booking_package_index is not None else 0
    return prices[idx] if idx < len(prices) else prices[0]
