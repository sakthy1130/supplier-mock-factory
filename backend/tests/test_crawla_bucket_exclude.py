from app.api.routes.crawla import _build_scenario_request
from app.models.crawla import (
    CrawlaBucket,
    CrawlaPackagesPanel,
    CrawlaPricePanel,
    CrawlaScenarioRequest,
)


def _req(bucket: CrawlaBucket) -> CrawlaScenarioRequest:
    return CrawlaScenarioRequest(
        namespace="crawla-test-abcd",
        check_in="2026-07-16",
        check_out="2026-07-18",
        atg_hotel_id="1043546",
        bucket=bucket,
        search=CrawlaPricePanel(crawla_total=800.0, exp_price=900.0, hbs_price=850.0),
        packages=CrawlaPackagesPanel(
            crawla_total=800.0,
            exp_price=900.0,
            hbs_price=850.0,
            crawla_room_id="crw-1",
            crawla_room_name="Double Room 2 twin beds",
        ),
    )


def _supplier_codes(scenario_request):
    return {s.code.value for s in scenario_request.suppliers}


def test_only_crawla_drops_exp_supplier_and_mutation():
    sr = _build_scenario_request(_req(CrawlaBucket.ONLY_CRAWLA))
    # EXP absent from suppliers → no EXP mock and no EXP contract are provisioned.
    assert _supplier_codes(sr) == {"HBS"}
    assert "EXP" not in sr.supplier_mutations


def test_other_buckets_keep_both_suppliers():
    for bucket in (
        CrawlaBucket.CRAWLA_LOWER,
        CrawlaBucket.EXPEDIA_LOWER,
        CrawlaBucket.EQUAL,
        CrawlaBucket.ONLY_EXPEDIA,
        CrawlaBucket.CHEAPEST_L2_GROSS,
    ):
        sr = _build_scenario_request(_req(bucket))
        assert _supplier_codes(sr) == {"HBS", "EXP"}, bucket
        assert "EXP" in sr.supplier_mutations, bucket
