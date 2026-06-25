from app.core.chc_paths import apply_chc_contract_opt_defaults


def test_apply_chc_contract_opt_defaults_forces_one_slot_cancel_policy():
    opt = {"isCancellationPolicyOneSlot": False, "searchUrl": "http://mock/search"}
    apply_chc_contract_opt_defaults(opt, "http://mockserver-staging.tajawal.io")
    assert opt["isCancellationPolicyOneSlot"] is True
    assert opt["availabilityTimeoutSeconds"] == "30"
    assert opt["mockServerUrl"] == "http://mockserver-staging.tajawal.io/"
