"""HIL (Hilton) supplier plugin.

Hilton reaches Enigma through the same Derby BTS adapter as Choice — verified
field-by-field against templates/HIL (``body.roomRates`` with ``amountBeforeTax`` /
``amountAfterTax`` arrays, ``mealPlan``, ``roomId``/``rateId``, ``cancelPolicy.code``) —
so it reuses that mutator wholesale and only pins Hilton's identity.

``payload_supplier_id`` is the adapter's ``SupplierId`` enum name (``HILTON("HIL")``),
which is what lands in ``header.supplierId`` on every Derby request and response.
"""

from __future__ import annotations

from app.plugins.derby_bts import DerbyBtsMockPlugin


class HilMockPlugin(DerbyBtsMockPlugin):
    code = "HIL"
    payload_supplier_id = "HILTON"


__all__ = ["HilMockPlugin"]
