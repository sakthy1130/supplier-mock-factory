from unittest.mock import AsyncMock, MagicMock

import pytest

from app.integrations.hotel_mapping import (
    HotelMappingClient,
    HotelMappingError,
    _parse_single_supplier_response,
)


def test_parse_single_supplier_response_success():
    payload = {
        "errors": [],
        "statusCode": 200,
        "response": {
            "supplierCode": "HBS",
            "atgHotelId": "1446194",
            "supplierHotelId": "156652",
        },
    }
    assert _parse_single_supplier_response(payload, "HBS", "1446194") == "156652"


def test_parse_single_supplier_response_missing_id_raises():
    payload = {
        "errors": [],
        "statusCode": 200,
        "response": {"supplierCode": "HBS", "atgHotelId": "1446194"},
    }
    with pytest.raises(HotelMappingError, match="supplierHotelId"):
        _parse_single_supplier_response(payload, "HBS", "1446194")


def test_parse_single_supplier_response_errors_raises():
    payload = {"errors": ["not found"], "statusCode": 404, "response": {}}
    with pytest.raises(HotelMappingError, match="errors"):
        _parse_single_supplier_response(payload, "HBS", "1446194")


@pytest.mark.asyncio
async def test_resolve_supplier_hotel_id_calls_get_endpoint():
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "errors": [],
        "statusCode": 200,
        "response": {
            "supplierCode": "HBS",
            "atgHotelId": "1446194",
            "supplierHotelId": "156652",
        },
    }
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)

    mapping = HotelMappingClient(client=client)
    mapping.settings.mapping_service_url = "http://mapping.example"
    mapping.settings.mapping_api_key = "test-key"

    result = await mapping.resolve_supplier_hotel_id("1446194", "HBS")
    assert result == "156652"
    client.get.assert_awaited_once()
    url = client.get.await_args.args[0]
    assert url == "http://mapping.example/v2/supplier/HBS/1446194"
    assert client.get.await_args.kwargs["headers"]["x-api-key"] == "test-key"


@pytest.mark.asyncio
async def test_resolve_supplier_hotel_ids_multiple_suppliers():
    async def fake_resolve(atg_hotel_id: str, supplier_code: str) -> str:
        return {"HBS": "156652", "EXP": "50878533"}[supplier_code]

    mapping = HotelMappingClient(client=AsyncMock())
    mapping.resolve_supplier_hotel_id = fake_resolve  # type: ignore[method-assign]

    result = await mapping.resolve_supplier_hotel_ids("1446194", ["HBS", "EXP"])
    assert result == {"HBS": "156652", "EXP": "50878533"}
