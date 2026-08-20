"""Apply a supplier's contract ``opt`` defaults.

One function replacing ``apply_{hbs,exp,chc,ext}_contract_opt_defaults``, which were
four copies of the same shape differing only in their data: which keys to fill, whether
a "0"/"" counts as missing, which keys to force regardless, and whether to stamp
``mockServerUrl``. All of that is now ``MockConfig`` fields on the supplier row.
"""

from __future__ import annotations

from typing import Any

from app.models.supplier import MockConfig


def apply_contract_opt_defaults(
    opt: dict[str, Any],
    mock_config: MockConfig,
    mock_base_url: str,
) -> dict[str, Any]:
    """Fill adapter-required opt fields in place and return the same dict."""
    for key, value in mock_config.opt_defaults.items():
        current = opt.get(key)
        if mock_config.opt_defaults_fill == "missing":
            # EXP's looser rule: only a genuine None counts as unset.
            if current is None:
                opt[key] = value
            continue
        # "blank": a cloned reference contract may carry "" or "0" for a timeout,
        # which the adapter reads as an immediate timeout.
        if current is None or str(current).strip() in ("", "0"):
            opt[key] = value

    # Re-forced even when the contract had a usable value (HBS/EXT timeouts).
    for key in mock_config.always_enforce_opt:
        if key in mock_config.opt_defaults:
            opt[key] = mock_config.opt_defaults[key]

    # Always overwritten, whatever the reference contract carried.
    opt.update(mock_config.forced_opt)

    if mock_config.set_mock_server_url:
        opt["mockServerUrl"] = f"{mock_base_url.rstrip('/')}/"
    return opt
