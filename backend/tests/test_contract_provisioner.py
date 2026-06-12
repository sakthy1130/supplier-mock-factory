from unittest.mock import AsyncMock

import pytest

from app.core.contract_provisioner import ContractProvisioner
from app.models.scenario import PackageSpec, ScenarioRequest, SupplierCode, SupplierScenario


def _request() -> ScenarioRequest:
    return ScenarioRequest(
        namespace="qa-p4-001",
        check_in="2026-09-01",
        check_out="2026-09-03",
        atg_hotel_id="1446194",
        supplier_hotel_ids={"HBS": "156652"},
        suppliers=[
            SupplierScenario(
                code=SupplierCode.HBS,
                packages=PackageSpec(count=1, room_basis="RO", prices=[100.0]),
            )
        ],
    )


@pytest.mark.asyncio
async def test_create_contracts_uses_minimal_body_when_no_reference():
    backoffice = AsyncMock()
    backoffice.__aenter__ = AsyncMock(return_value=backoffice)
    backoffice.__aexit__ = AsyncMock(return_value=None)
    backoffice.create_contract = AsyncMock(return_value="mongo-hbs-1")

    provisioner = ContractProvisioner(backoffice=backoffice)
    provisioner.settings.hbs_reference_contract_id = ""
    provisioner.settings.mock_server_url = "http://mockserver-staging.tajawal.io"

    contract_ids = await provisioner.create_contracts(
        _request(),
        {"HBS": {"Search": "/hotel-api/1.2/hotels", "Booking": "/hotel-api/1.2/bookings"}},
        "http://mockserver-staging.tajawal.io",
    )

    assert contract_ids == {"HBS": "mongo-hbs-1"}
    body = backoffice.create_contract.await_args.args[0]
    assert body["supplierId"] == "5fd5fefb1a4e866f7b3cea44"
    assert body["dynamicMarketType"] == "DynamicMarkupTarget"
    assert body["opt"]["searchUrl"].endswith("/hotel-api/1.0/hotels/search")
    assert body["opt"]["availabilityUrl"].endswith("/hotel-api/1.0/hotels/package/availability")
    assert body["opt"]["prebookingUrl"].endswith("/hotel-api/1.0/checkrates/preBooking")
    assert body["opt"]["bookingUrl"].endswith("/hotel-api/1.2/bookings/booking")
    assert body["opt"]["orderUrl"].endswith("/hotel-api/1.2/bookings/GetOrderBooking")
    assert body["opt"]["cancelBookingUrl"].endswith("/hotel-api/1.2/bookings/cancelBooking")
    assert body["opt"]["availabilityTimeoutSeconds"] == "50"
    assert body["supplierAutoId"] == "100004"


@pytest.mark.asyncio
async def test_create_contracts_clones_reference_contract():
    backoffice = AsyncMock()
    backoffice.__aenter__ = AsyncMock(return_value=backoffice)
    backoffice.__aexit__ = AsyncMock(return_value=None)
    backoffice.get_contract = AsyncMock(
        return_value={
            "_id": "ref-1",
            "autoId": "99",
            "uid": "old-uid",
            "opt": {"searchUrl": "http://old/search"},
            "supplierId": "100004",
        }
    )
    backoffice.create_contract = AsyncMock(return_value="mongo-hbs-clone")

    provisioner = ContractProvisioner(backoffice=backoffice)
    provisioner.settings.hbs_reference_contract_id = "ref-1"

    contract_ids = await provisioner.create_contracts(
        _request(),
        {"HBS": {"Search": "/hotel-api/1.2/hotels"}},
        "http://mockserver-staging.tajawal.io",
    )

    assert contract_ids == {"HBS": "mongo-hbs-clone"}
    body = backoffice.create_contract.await_args.args[0]
    assert "_id" not in body
    assert body["uid"] == "smf-qa-p4-001-hbs"
    assert body["dynamicMarketType"] == "DynamicMarkupTarget"
    assert body["opt"]["searchUrl"] == (
        "http://mockserver-staging.tajawal.io/hotel-api/1.0/hotels/search"
    )
    assert body["opt"]["availabilityTimeoutSeconds"] == "50"


@pytest.mark.asyncio
async def test_create_contracts_hbs_overwrites_zero_timeout_from_reference():
    backoffice = AsyncMock()
    backoffice.__aenter__ = AsyncMock(return_value=backoffice)
    backoffice.__aexit__ = AsyncMock(return_value=None)
    backoffice.get_contract = AsyncMock(
        return_value={
            "_id": "ref-1",
            "autoId": "99",
            "uid": "old-uid",
            "opt": {
                "searchUrl": "http://old/search",
                "availabilityTimeoutSeconds": "0",
                "cancellationPoliciesTimeoutSeconds": "",
            },
            "supplierId": "100004",
        }
    )
    backoffice.create_contract = AsyncMock(return_value="mongo-hbs-clone")

    provisioner = ContractProvisioner(backoffice=backoffice)
    provisioner.settings.hbs_reference_contract_id = "ref-1"
    provisioner.settings.mock_server_url = "http://mockserver-staging.tajawal.io"

    await provisioner.create_contracts(_request(), {"HBS": {}}, "http://mockserver-staging.tajawal.io")

    body = backoffice.create_contract.await_args.args[0]
    assert body["opt"]["availabilityTimeoutSeconds"] == "50"
    assert body["opt"]["cancellationPoliciesTimeoutSeconds"] == "10"


@pytest.mark.asyncio
async def test_create_contracts_exp_uses_override_urls():
    backoffice = AsyncMock()
    backoffice.__aenter__ = AsyncMock(return_value=backoffice)
    backoffice.__aexit__ = AsyncMock(return_value=None)
    backoffice.create_contract = AsyncMock(return_value="mongo-exp-1")

    provisioner = ContractProvisioner(backoffice=backoffice)
    provisioner.settings.exp_reference_contract_id = ""

    request = ScenarioRequest(
        namespace="qa-p4-exp",
        check_in="2026-09-01",
        check_out="2026-09-03",
        atg_hotel_id="1446194",
        supplier_hotel_ids={"HBS": "156652"},
        suppliers=[
            SupplierScenario(
                code=SupplierCode.EXP,
                packages=PackageSpec(count=1, room_basis="RO", prices=[100.0]),
            )
        ],
    )
    contract_ids = await provisioner.create_contracts(
        request,
        {
            "EXP": {
                "Search": "/v3/properties/availability",
                "Packages": "/v3/properties/1/availability",
                "Booking": "/v3/itineraries",
                "GetOrder": "/v3/itineraries/1",
                "CancelOrder": "/v3/itineraries/1/rooms/1",
            }
        },
        "http://mockserver-staging.tajawal.io",
    )

    assert contract_ids == {"EXP": "mongo-exp-1"}
    body = backoffice.create_contract.await_args.args[0]
    assert body["supplierId"] == "5fb648d84b949648780c1b74"
    assert body["dynamicMarketType"] == "MarketPriceSource"
    assert body["opt"]["overrideSearchUrl"].endswith("/v3/properties/availability")
    assert body["opt"]["overridePackagesUrl"].endswith("/v3/properties/1/availability")
    assert body["opt"]["overrideBookingUrl"].endswith("/v3/itineraries")
    assert body["opt"]["overrideRetrieveBookingUrl"].endswith("/v3/itineraries/1")
    assert body["opt"]["overrideCancelBookingUrl"].endswith("/v3/itineraries/1/rooms/1")
    assert "searchUrl" not in body["opt"]


@pytest.mark.asyncio
async def test_create_contracts_exp_clones_reference_contract():
    backoffice = AsyncMock()
    backoffice.__aenter__ = AsyncMock(return_value=backoffice)
    backoffice.__aexit__ = AsyncMock(return_value=None)
    backoffice.get_contract = AsyncMock(
        return_value={
            "_id": "61f0158ffea990015b258dd2",
            "autoId": "77",
            "uid": "exp-mock-contract-1",
            "supplierId": "5fb648d84b949648780c1b74",
            "dynamicMarketType": "marketPriceSource",
            "opt": {
                "overrideSearchUrl": "http://mockserver-staging.tajawal.io/old-ns/search",
                "overridePackagesUrl": "http://mockserver-staging.tajawal.io/old-ns/package",
                "enableAdapterTransformedLog": True,
                "availabilityTimeoutSeconds": "7",
            },
        }
    )
    backoffice.create_contract = AsyncMock(return_value="mongo-exp-clone")

    provisioner = ContractProvisioner(backoffice=backoffice)
    provisioner.settings.exp_reference_contract_id = "61f0158ffea990015b258dd2"

    request = ScenarioRequest(
        namespace="qa-exp-clone",
        check_in="2026-09-01",
        check_out="2026-09-03",
        atg_hotel_id="1446194",
        supplier_hotel_ids={},
        suppliers=[
            SupplierScenario(
                code=SupplierCode.EXP,
                packages=PackageSpec(count=1, room_basis="RO", prices=[100.0]),
            )
        ],
    )
    contract_ids = await provisioner.create_contracts(
        request,
        {"EXP": {"Search": "/new-ns/search", "Packages": "/new-ns/package"}},
        "http://mockserver-staging.tajawal.io",
    )

    assert contract_ids == {"EXP": "mongo-exp-clone"}
    body = backoffice.create_contract.await_args.args[0]
    assert "_id" not in body
    assert body["uid"] == "smf-qa-exp-clone-exp"
    assert body["dynamicMarketType"] == "MarketPriceSource"
    assert body["opt"]["overrideSearchUrl"].endswith("/new-ns/search")
    assert body["opt"]["overridePackagesUrl"].endswith("/new-ns/package")
    assert body["opt"]["enableAdapterTransformedLog"] is True
