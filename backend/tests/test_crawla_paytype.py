import pytest

from app.integrations.crawla import CrawlaApiError, _filter_prepay_offers
from app.models.crawla import CrawlaHotelAnchorItem, CrawlaHotelOffer


def _offer(pid: str, pay):
    return CrawlaHotelOffer(room_id=pid, room_name="Room", total_amount=100.0, pay_at_property=pay)


def _hotel(*offers):
    return CrawlaHotelAnchorItem(atg_id="1", data=list(offers))


def test_all_postpay_raises():
    hotels = [_hotel(_offer("a", "Yes"), _offer("b", "Yes"))]
    with pytest.raises(CrawlaApiError, match="PostPay"):
        _filter_prepay_offers(hotels)


def test_mixed_keeps_only_prepay():
    hotels = [_hotel(_offer("a", "Yes"), _offer("b", "No"), _offer("c", "yes"))]
    _filter_prepay_offers(hotels)
    assert [o.room_id for o in hotels[0].data] == ["b"]


def test_all_prepay_keeps_all():
    hotels = [_hotel(_offer("a", "No"), _offer("b", "No"))]
    _filter_prepay_offers(hotels)
    assert [o.room_id for o in hotels[0].data] == ["a", "b"]


def test_empty_hotels_no_error():
    hotels = [_hotel()]
    _filter_prepay_offers(hotels)  # no offers → no error, nothing to filter
    assert hotels[0].data == []
