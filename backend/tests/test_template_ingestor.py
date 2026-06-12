import json
from pathlib import Path

import pytest

from app.ingest.template_ingestor import TemplateIngestor


SEARCH_DETAIL = {
    "request": {
        "method": "POST",
        "url": "https://supplier.example.com/hotel-api/1.0/hotels",
        "body": {
            "header": {"token": "session"},
            "stayRange": {"checkIn": "2026-08-01", "checkOut": "2026-08-03"},
            "hotels": {"hotel": [{"code": "12345"}]},
        },
    },
    "response": {
        "body": {
            "hotels": {"hotel": [{"code": "12345", "name": "Test Hotel"}]},
            "stay": {"checkIn": "2026-08-01", "checkOut": "2026-08-03"},
        }
    },
}

PACKAGES_DETAIL = {
    "request": {
        "method": "POST",
        "url": "https://supplier.example.com/hotel-api/1.0/checkrates",
        "body": {"stayRange": {"checkIn": "2026-08-01", "checkOut": "2026-08-03"}},
    },
    "response": {"body": {"rooms": [{"code": "DBL"}]}},
}

LIST_JSON = {
    "details": [
        {
            "logType": "Search",
            "source": "hotel-connectivity-hbs-adapter",
            "logUrl": "logs/sid/Search_HBS.json.gz",
        },
        {
            "logType": "Packages",
            "source": "hotel-connectivity-hbs-adapter",
            "logUrl": "logs/sid/Packages_HBS.json.gz",
        },
        {
            "logType": "PackagesResponse",
            "source": "hotel-connectivity-hbs-adapter",
            "logUrl": "logs/sid/PackagesResponse_HBS.json.gz",
        },
        {
            "logType": "Packages",
            "source": "hotels-exp-adapter-service-staging",
            "logUrl": "logs/sid/Packages_EXP.json.gz",
        },
    ]
}

DETAIL_BY_URL = {
    "logs/sid/Search_HBS.json.gz": SEARCH_DETAIL,
    "logs/sid/Packages_HBS.json.gz": PACKAGES_DETAIL,
}


async def _mock_fetch(log_url: str) -> dict:
    if log_url not in DETAIL_BY_URL:
        raise KeyError(log_url)
    return DETAIL_BY_URL[log_url]


@pytest.mark.asyncio
async def test_ingest_writes_templates_and_field_map(tmp_path: Path):
    templates_dir = tmp_path / "templates"
    field_maps_dir = tmp_path / "field-maps"
    ingestor = TemplateIngestor(templates_dir=templates_dir, field_maps_dir=field_maps_dir)

    count = await ingestor.ingest_from_list_json(
        "HBS",
        "test-sid",
        LIST_JSON,
        fetch_detail=_mock_fetch,
    )

    assert count == 2
    search_path = templates_dir / "HBS" / "Search" / "v1.json"
    packages_path = templates_dir / "HBS" / "Packages" / "v1.json"
    field_map_path = field_maps_dir / "HBS.json"

    assert search_path.exists()
    assert packages_path.exists()
    assert field_map_path.exists()

    search = json.loads(search_path.read_text())
    assert search["httpRequest"]["path"] == "/hotel-api/1.0/hotels"
    assert search["priority"] == 1000
    assert "body" not in search["httpRequest"]

    field_map = json.loads(field_map_path.read_text())
    assert field_map["supplier"] == "HBS"
    assert "Search" in field_map["log_types"]
    assert any("checkIn" in p for p in field_map["paths"]["check_in"])


GET_ORDER_DETAIL_OLD = {
    "request": {
        "method": "GET",
        "url": "https://supplier.example.com/hotel-api/1.2/bookings/OLD",
        "body": {},
    },
    "response": {"body": {"booking": {"status": "OLD"}}},
}

GET_ORDER_DETAIL_NEW = {
    "request": {
        "method": "GET",
        "url": "https://supplier.example.com/hotel-api/1.2/bookings/NEW",
        "body": {},
    },
    "response": {"body": {"booking": {"status": "NEW"}}},
}

GET_ORDER_LIST = {
    "details": [
        {
            "logType": "GetOrderResponse",
            "source": "hotel-connectivity-hbs-adapter",
            "logUrl": "logs/sid/GetOrderResponse_old.json.gz",
            "timestamp": "2026-06-05T18:15:49.388329000",
        },
        {
            "logType": "GetOrder",
            "source": "hotel-connectivity-hbs-adapter",
            "logUrl": "logs/sid/GetOrder_old.json.gz",
            "timestamp": "2026-06-05T18:15:49.379479000",
        },
        {
            "logType": "GetOrderResponse",
            "source": "hotel-connectivity-hbs-adapter",
            "logUrl": "logs/sid/GetOrderResponse_new.json.gz",
            "timestamp": "2026-06-05T18:16:43.759043000",
        },
        {
            "logType": "GetOrder",
            "source": "hotel-connectivity-hbs-adapter",
            "logUrl": "logs/sid/GetOrder_new.json.gz",
            "timestamp": "2026-06-05T18:16:43.757236000",
        },
    ]
}


@pytest.mark.asyncio
async def test_ingest_picks_latest_get_order_response_pair(tmp_path: Path):
    templates_dir = tmp_path / "templates"
    field_maps_dir = tmp_path / "field-maps"
    ingestor = TemplateIngestor(templates_dir=templates_dir, field_maps_dir=field_maps_dir)

    async def fetch(log_url: str) -> dict:
        mapping = {
            "logs/sid/GetOrder_old.json.gz": GET_ORDER_DETAIL_OLD,
            "logs/sid/GetOrder_new.json.gz": GET_ORDER_DETAIL_NEW,
            "logs/sid/GetOrderResponse_old.json.gz": {"response": {"body": {}}},
            "logs/sid/GetOrderResponse_new.json.gz": {"response": {"body": {}}},
        }
        return mapping[log_url]

    count = await ingestor.ingest_from_list_json(
        "HBS",
        "test-sid",
        GET_ORDER_LIST,
        fetch_detail=fetch,
    )

    assert count == 1
    get_order = json.loads((templates_dir / "HBS" / "GetOrder" / "v1.json").read_text())
    assert get_order["httpRequest"]["path"] == "/hotel-api/1.2/bookings/NEW"
    assert get_order["httpResponse"]["body"]["booking"]["status"] == "NEW"


@pytest.mark.asyncio
async def test_ingest_maps_cancel_booking_to_cancel_order(tmp_path: Path):
    templates_dir = tmp_path / "templates"
    field_maps_dir = tmp_path / "field-maps"
    ingestor = TemplateIngestor(templates_dir=templates_dir, field_maps_dir=field_maps_dir)
    cancel_detail = {
        "request": {
            "method": "DELETE",
            "url": "https://supplier.example.com/hotel-api/1.2/bookings/148-6069492",
            "body": {},
        },
        "response": {"body": {"status": "CANCELLED"}},
    }

    async def fetch(_log_url: str) -> dict:
        return cancel_detail

    count = await ingestor.ingest_from_list_json(
        "HBS",
        "test-sid",
        {
            "details": [
                {
                    "logType": "CancelBooking",
                    "source": "hotel-connectivity-hbs-adapter",
                    "logUrl": "logs/sid/CancelBooking.json.gz",
                    "timestamp": "2026-06-05T18:15:57.590569000",
                }
            ]
        },
        fetch_detail=fetch,
    )

    assert count == 1
    assert (templates_dir / "HBS" / "CancelOrder" / "v1.json").exists()
