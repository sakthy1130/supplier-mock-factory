"""CHC (Choice) supplier plugin.

Choice reaches Enigma through the shared Derby BTS adapter, so all the mutation logic
lives in :mod:`app.plugins.derby_bts`; this module only pins Choice's identity.
"""

from __future__ import annotations

from app.plugins.derby_bts import (
    CONFIRMED_ORDER_STATUS,
    LOG_TYPES,
    VALID_MEAL_PLANS,
    DerbyBtsMockPlugin,
    _apply_cancel_policy,
)


class ChcMockPlugin(DerbyBtsMockPlugin):
    code = "CHC"
    payload_supplier_id = "CHOICE"


__all__ = [
    "ChcMockPlugin",
    # Re-exported so the historical import sites keep working.
    "CONFIRMED_ORDER_STATUS",
    "LOG_TYPES",
    "VALID_MEAL_PLANS",
    "_apply_cancel_policy",
]
