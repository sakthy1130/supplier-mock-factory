"""CHC (Choice / Derby BTS) contract opt defaults."""

from __future__ import annotations

from typing import Any

# Derby BTS adapter reads ``isCancellationPolicyOneSlot`` from contract additional data.
# When true, multi-part cancel codes (e.g. ``4PM1D100P_100P``) collapse to one fee tier.
CHC_CONTRACT_OPT_DEFAULTS: dict[str, Any] = {
    "isCancellationPolicyOneSlot": True,
    "availabilityTimeoutSeconds": "30",
    "enableAdapterTransformedLog": True,
}


def apply_chc_contract_opt_defaults(opt: dict[str, Any], mock_base_url: str) -> dict[str, Any]:
    """Ensure CHC Derby BTS contract opt has adapter-required flags."""
    for key, value in CHC_CONTRACT_OPT_DEFAULTS.items():
        if key == "isCancellationPolicyOneSlot":
            opt[key] = True
            continue
        current = opt.get(key)
        if current is None or str(current).strip() in ("", "0"):
            opt[key] = value
    opt["mockServerUrl"] = f"{mock_base_url.rstrip('/')}/"
    return opt
