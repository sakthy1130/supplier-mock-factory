from app.core.crawla_mutations import apply_supplier_mutation
from app.models.scenario import SupplierMutation


def test_apply_supplier_mutation_updates_hbs_price_fields():
    expectation = {
        "id": "smf-test-hbs-search",
        "httpResponse": {
            "body": {
                "hotels": {
                    "hotels": [
                        {
                            "code": 156652,
                            "minRate": "89.25",
                            "maxRate": "89.25",
                            "rooms": [
                                {
                                    "rates": [
                                        {
                                            "net": "89.25",
                                            "cancellationPolicies": [{"amount": "89.25"}],
                                        }
                                    ]
                                }
                            ],
                        }
                    ]
                }
            }
        },
    }

    result = apply_supplier_mutation(
        expectation,
        supplier_code="HBS",
        log_type="Search",
        hotel_id="156652",
        mutation=SupplierMutation(search_price=123.45, package_price=0.0),
    )

    hotel = result["httpResponse"]["body"]["hotels"]["hotels"][0]
    rate = hotel["rooms"][0]["rates"][0]
    assert result["id"] == "smf-test-hbs-search"
    assert hotel["minRate"] == "123.45"
    assert hotel["maxRate"] == "123.45"
    assert rate["net"] == "123.45"
    assert rate["cancellationPolicies"][0]["amount"] == "123.45"


def test_apply_supplier_mutation_updates_hbs_room_name_from_crawla():
    expectation = {
        "id": "smf-test-hbs-packages",
        "httpResponse": {
            "body": {
                "hotels": {
                    "hotels": [
                        {
                            "code": 156652,
                            "rooms": [
                                {
                                    "name": "Old HBS Room",
                                    "originalRoomName": "Old HBS Room",
                                    "roomName": {"en": "Old HBS Room"},
                                    "rates": [{"net": "89.25"}],
                                }
                            ],
                        }
                    ]
                }
            }
        },
    }

    result = apply_supplier_mutation(
        expectation,
        supplier_code="HBS",
        log_type="Packages",
        hotel_id="156652",
        mutation=SupplierMutation(room_name="Crawla Classic Room"),
    )

    room = result["httpResponse"]["body"]["hotels"]["hotels"][0]["rooms"][0]
    assert room["name"] == "Crawla Classic Room"
    assert room["originalRoomName"] == "Crawla Classic Room"
    assert room["roomName"]["en"] == "Crawla Classic Room"


def test_apply_supplier_mutation_updates_hbs_room_basis_from_crawla():
    expectation = {
        "id": "smf-test-hbs-packages",
        "httpResponse": {
            "body": {
                "hotels": {
                    "hotels": [
                        {
                            "code": 156652,
                            "rooms": [
                                {
                                    "roomBasis": "RO",
                                    "rates": [
                                        {
                                            "boardCode": "RO",
                                            "boardName": "ROOM ONLY",
                                            "net": "89.25",
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }
            }
        },
    }

    result = apply_supplier_mutation(
        expectation,
        supplier_code="HBS",
        log_type="Packages",
        hotel_id="156652",
        mutation=SupplierMutation(room_basis="BB"),
    )

    room = result["httpResponse"]["body"]["hotels"]["hotels"][0]["rooms"][0]
    rate = room["rates"][0]
    assert room["roomBasis"] == "BB"
    assert rate["roomBasis"] == "BB"
    assert rate["boardCode"] == "BB"
    assert rate["boardName"] == "BED AND BREAKFAST"


def test_apply_supplier_mutation_updates_hbs_search_like_packages():
    expectation = {
        "id": "smf-test-hbs-search",
        "httpResponse": {
            "body": {
                "hotels": {
                    "hotels": [
                        {
                            "code": 156652,
                            "rooms": [
                                {
                                    "name": "Old HBS Room",
                                    "originalRoomName": "Old HBS Room",
                                    "roomName": {"en": "Old HBS Room"},
                                    "roomBasis": "RO",
                                    "rates": [
                                        {
                                            "net": "89.25",
                                            "boardCode": "RO",
                                            "boardName": "ROOM ONLY",
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }
            }
        },
    }

    result = apply_supplier_mutation(
        expectation,
        supplier_code="HBS",
        log_type="Search",
        hotel_id="156652",
        mutation=SupplierMutation(room_name="Crawla Search Room", room_basis="HB"),
    )

    room = result["httpResponse"]["body"]["hotels"]["hotels"][0]["rooms"][0]
    rate = room["rates"][0]
    assert room["name"] == "Crawla Search Room"
    assert room["originalRoomName"] == "Crawla Search Room"
    assert room["roomName"]["en"] == "Crawla Search Room"
    assert room["roomBasis"] == "HB"
    assert rate["roomBasis"] == "HB"
    assert rate["boardCode"] == "HB"
    assert rate["boardName"] == "HALF BOARD"


def test_apply_supplier_mutation_excludes_exp_hotel():
    expectation = {
        "id": "smf-test-exp-search",
        "httpResponse": {
            "body": {
                "body": [
                    {"property_id": "111", "rooms": []},
                    {"property_id": "222", "rooms": []},
                ]
            }
        },
    }

    result = apply_supplier_mutation(
        expectation,
        supplier_code="EXP",
        log_type="Search",
        hotel_id="111",
        mutation=SupplierMutation(exclude_hotel=True),
    )

    hotels = result["httpResponse"]["body"]["body"]
    assert [hotel["property_id"] for hotel in hotels] == ["222"]


def test_apply_supplier_mutation_updates_exp_room_name_wrapped():
    expectation = {
        "httpResponse": {
            "body": {
                "body": [
                    {
                        "property_id": "1723385",
                        "rooms": [{"id": "201836237", "room_name": "Deluxe Room"}],
                    }
                ]
            }
        }
    }

    result = apply_supplier_mutation(
        expectation,
        supplier_code="EXP",
        log_type="Packages",
        hotel_id="1723385",
        mutation=SupplierMutation(room_name="Deluxe Double Room"),
    )

    room = result["httpResponse"]["body"]["body"][0]["rooms"][0]
    assert room["room_name"] == "Deluxe Double Room"


def test_apply_supplier_mutation_updates_exp_room_name_search():
    expectation = {
        "httpResponse": {
            "body": {
                "body": [
                    {
                        "property_id": "8697404",
                        "rooms": [{"id": "216919865", "room_name": "Deluxe Room, 1 King Bed, City View"}],
                    }
                ]
            }
        }
    }

    result = apply_supplier_mutation(
        expectation,
        supplier_code="EXP",
        log_type="Search",
        hotel_id="8697404",
        mutation=SupplierMutation(room_name="Deluxe Double Room"),
    )

    room = result["httpResponse"]["body"]["body"][0]["rooms"][0]
    assert room["room_name"] == "Deluxe Double Room"


def test_apply_supplier_mutation_updates_exp_room_basis_bb():
    expectation = {
        "httpResponse": {
            "body": {
                "body": [
                    {
                        "property_id": "1723385",
                        "rooms": [{"id": "201836237", "rates": [{"id": "209336313"}]}],
                    }
                ]
            }
        }
    }

    result = apply_supplier_mutation(
        expectation,
        supplier_code="EXP",
        log_type="Packages",
        hotel_id="1723385",
        mutation=SupplierMutation(room_basis="BB"),
    )

    rate = result["httpResponse"]["body"]["body"][0]["rooms"][0]["rates"][0]
    assert "meal_plan" not in rate
    assert rate["amenities"]["2098"] == {"id": "2098", "name": "Free Breakfast"}


def test_apply_supplier_mutation_updates_exp_room_basis_hb():
    expectation = {
        "httpResponse": {
            "body": {
                "body": [
                    {
                        "property_id": "1723385",
                        "rooms": [{"id": "201836237", "rates": [{"id": "209336313"}]}],
                    }
                ]
            }
        }
    }

    result = apply_supplier_mutation(
        expectation,
        supplier_code="EXP",
        log_type="Packages",
        hotel_id="1723385",
        mutation=SupplierMutation(room_basis="HB"),
    )

    rate = result["httpResponse"]["body"]["body"][0]["rooms"][0]["rates"][0]
    assert rate["amenities"]["2206"] == {"id": "2206", "name": "Half Board"}


def test_apply_supplier_mutation_exp_ro_removes_meal_amenities():
    expectation = {
        "httpResponse": {
            "body": {
                "body": [
                    {
                        "property_id": "1723385",
                        "rooms": [
                            {
                                "id": "201836237",
                                "rates": [
                                    {
                                        "id": "209336313",
                                        "amenities": {
                                            "2098": {"id": "2098", "name": "Free Breakfast"},
                                            "2192": {"id": "2192", "name": "Free WiFi"},
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        }
    }

    result = apply_supplier_mutation(
        expectation,
        supplier_code="EXP",
        log_type="Packages",
        hotel_id="1723385",
        mutation=SupplierMutation(room_basis="RO"),
    )

    rate = result["httpResponse"]["body"]["body"][0]["rooms"][0]["rates"][0]
    assert "2098" not in rate["amenities"]
    assert "2192" in rate["amenities"]


def test_apply_supplier_mutation_excludes_exp_hotel_from_unwrapped_search():
    expectation = {
        "id": "smf-test-exp-search",
        "httpResponse": {
            "body": [
                {"property_id": "111", "rooms": []},
                {"property_id": "222", "rooms": []},
            ]
        },
    }

    result = apply_supplier_mutation(
        expectation,
        supplier_code="EXP",
        log_type="Search",
        hotel_id="111",
        mutation=SupplierMutation(exclude_hotel=True),
    )

    hotels = result["httpResponse"]["body"]
    assert [hotel["property_id"] for hotel in hotels] == ["222"]
