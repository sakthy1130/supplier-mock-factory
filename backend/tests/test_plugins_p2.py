from app.models.scenario import PackageSpec
from app.plugins.exp import ExpMockPlugin
from app.plugins.hbs import HbsMockPlugin
from app.plugins.json_utils import deep_copy


HBS_PACKAGES = {
    "httpRequest": {
        "body": {
            "json": {
                "stay": {"checkIn": "2026-08-13", "checkOut": "2026-08-18"},
                "hotels": {"hotel": [156652]},
            }
        }
    },
    "httpResponse": {
        "body": {
            "hotels": {
                "hotels": [
                    {
                        "code": 156652,
                        "rooms": [
                            {
                                "rates": [
                                    {
                                        "rateKey": "20260813|20260818|W|148|156652|DBL.ST|RO|RO||1~1~0",
                                        "net": "89.25",
                                        "boardCode": "RO",
                                        "rateClass": "NRF",
                                    },
                                    {
                                        "rateKey": "20260813|20260818|W|148|156652|DBL.ST|RO|RO||2~1~0",
                                        "net": "99.25",
                                        "boardCode": "RO",
                                        "rateClass": "NRF",
                                    },
                                ]
                            }
                        ],
                    }
                ]
            }
        }
    },
}


def test_hbs_mutate_dates_updates_checkin_and_ratekey():
    plugin = HbsMockPlugin()
    result = plugin.mutate_dates(HBS_PACKAGES, "2026-09-01", "2026-09-03")
    assert result["httpRequest"]["body"]["json"]["stay"]["checkIn"] == "2026-09-01"
    rate_key = result["httpResponse"]["body"]["hotels"]["hotels"][0]["rooms"][0]["rates"][0]["rateKey"]
    assert rate_key.startswith("20260901|20260903|")


HBS_SEARCH = {
    "httpRequest": {
        "body": {
            "json": {
                "stay": {"checkIn": "2026-08-13", "checkOut": "2026-08-18"},
                "hotels": {"hotel": [162651, 731321]},
            }
        }
    },
    "httpResponse": {
        "body": {
            "hotels": {
                "total": 2,
                "hotels": [
                    {"code": 162651, "name": "Hotel A", "rooms": [{"rates": [{"rateKey": "x|162651|y"}]}]},
                    {"code": 731321, "name": "Hotel B", "rooms": [{"rates": [{"rateKey": "x|731321|y"}]}]},
                ],
            }
        }
    },
}


def test_hbs_mutate_search_returns_single_hotel():
    plugin = HbsMockPlugin()
    spec = PackageSpec(count=1, room_basis="RO", prices=[100.0], refundable=[True])
    result = plugin.mutate_packages(
        HBS_SEARCH,
        spec,
        "156652",
        "2026-09-10",
        "2026-09-12",
        "Search",
    )
    hotels = result["httpResponse"]["body"]["hotels"]["hotels"]
    assert len(hotels) == 1
    assert hotels[0]["code"] == 156652
    assert result["httpRequest"]["body"]["json"]["hotels"]["hotel"] == [156652]
    assert result["httpResponse"]["body"]["hotels"]["total"] == 1


HBS_PREBOOK = {
    "httpRequest": {
        "body": {
            "json": {
                "rooms": [{"rateKey": "old-rate-key"}],
            }
        }
    },
    "httpResponse": {
        "body": {
            "hotel": {
                "rooms": [
                    {
                        "rates": [
                            {
                                "rateKey": "old-rate-key",
                                "net": "89.25",
                                "boardCode": "RO",
                                "rateClass": "NRF",
                                "cancellationPolicies": [{"amount": "89.25"}],
                            }
                        ]
                    }
                ]
            }
        }
    },
}


HBS_GET_ORDER = {
    "httpResponse": {
        "body": {
            "booking": {
                "status": "CANCELLED",
                "modificationPolicies": {"cancellation": False, "modification": False},
                "hotel": {
                    "status": "CANCELLED",
                    "rooms": [{"status": "CANCELLED"}],
                },
            }
        }
    }
}


def test_hbs_propagate_package_linkage_syncs_search_rates():
    plugin = HbsMockPlugin()
    spec = PackageSpec(count=1, room_basis="RO", prices=[100.0], refundable=[True])
    packages = plugin.mutate_packages(HBS_PACKAGES, spec, "156652", "2026-09-10", "2026-09-12", "Packages")
    search = plugin.mutate_packages(HBS_SEARCH, spec, "156652", "2026-09-10", "2026-09-12", "Search")
    expectations = {"Packages": packages, "PreBooking": deep_copy(HBS_PREBOOK), "Search": search}
    plugin.propagate_package_linkage(expectations, spec)
    pkg_rate = packages["httpResponse"]["body"]["hotels"]["hotels"][0]["rooms"][0]["rates"][0]
    search_rate = expectations["Search"]["httpResponse"]["body"]["hotels"]["hotels"][0]["rooms"][0]["rates"][0]
    assert search_rate["rateKey"] == pkg_rate["rateKey"]
    assert search_rate["net"] == pkg_rate["net"]


def test_hbs_propagate_package_linkage_syncs_prebook_price():
    plugin = HbsMockPlugin()
    spec = PackageSpec(count=1, room_basis="RO", prices=[100.0], refundable=[True])
    packages = plugin.mutate_packages(
        HBS_PACKAGES,
        spec,
        "156652",
        "2026-09-10",
        "2026-09-12",
        "Packages",
    )
    expectations = {"Packages": packages, "PreBooking": deep_copy(HBS_PREBOOK)}
    plugin.propagate_package_linkage(expectations, spec)
    prebook = expectations["PreBooking"]
    pkg_rate_key = packages["httpResponse"]["body"]["hotels"]["hotels"][0]["rooms"][0]["rates"][0]["rateKey"]
    prebook_rate = prebook["httpResponse"]["body"]["hotel"]["rooms"][0]["rates"][0]
    assert prebook["httpRequest"]["body"]["json"]["rooms"][0]["rateKey"] == pkg_rate_key
    assert prebook_rate["rateKey"] == pkg_rate_key
    assert prebook_rate["net"] == "100.0"
    assert prebook_rate["cancellationPolicies"][0]["amount"] == "100.0"


def test_hbs_applies_uniform_room_name_on_search_packages_prebook():
    plugin = HbsMockPlugin()
    room_name = "1 Double Bed, Nonsmoking"
    spec = PackageSpec(
        count=2,
        room_basis="RO",
        prices=[100.0, 200.0],
        room_names=[room_name, room_name],
        refundable=[True, False],
    )
    packages = plugin.mutate_packages(HBS_PACKAGES, spec, "156652", "2026-09-10", "2026-09-12", "Packages")
    search = plugin.mutate_packages(HBS_SEARCH, spec, "156652", "2026-09-10", "2026-09-12", "Search")
    prebook = deep_copy(HBS_PREBOOK)
    expectations = {"Packages": packages, "PreBooking": prebook, "Search": search}
    plugin.propagate_package_linkage(expectations, spec)

    for log_type in ("Search", "Packages", "PreBooking"):
        body = expectations[log_type]["httpResponse"]["body"]
        if log_type == "PreBooking":
            rooms = body["hotel"]["rooms"]
        else:
            rooms = body["hotels"]["hotels"][0]["rooms"]
        assert all(room["name"] == room_name for room in rooms), log_type


def test_package_spec_default_room_names():
    assert PackageSpec(count=1, prices=[100.0]).room_names == ["1 Double Bed, Nonsmoking"]


def test_package_spec_coerces_legacy_room_name():
    spec = PackageSpec.model_validate({"count": 2, "prices": [100.0, 200.0], "room_name": "Classic Room"})
    assert spec.room_names == ["Classic Room"]


def test_hbs_applies_per_package_room_names_when_distinct():
    plugin = HbsMockPlugin()
    names = ["Double Room", "Twin Room"]
    spec = PackageSpec(count=2, room_basis="RO", prices=[100.0, 200.0], room_names=names, refundable=[True, False])
    packages = plugin.mutate_packages(HBS_PACKAGES, spec, "156652", "2026-09-10", "2026-09-12", "Packages")
    rooms = packages["httpResponse"]["body"]["hotels"]["hotels"][0]["rooms"]
    assert len(rooms) == 2
    assert len(rooms[0]["rates"]) == 1
    assert len(rooms[1]["rates"]) == 1

    search = plugin.mutate_packages(HBS_SEARCH, spec, "156652", "2026-09-10", "2026-09-12", "Search")
    prebook = deep_copy(HBS_PREBOOK)
    expectations = {"Packages": packages, "PreBooking": prebook, "Search": search}
    plugin.propagate_package_linkage(expectations, spec)

    pkg_rooms = expectations["Packages"]["httpResponse"]["body"]["hotels"]["hotels"][0]["rooms"]
    assert [room["name"] for room in pkg_rooms] == names
    search_rooms = expectations["Search"]["httpResponse"]["body"]["hotels"]["hotels"][0]["rooms"]
    assert [room["name"] for room in search_rooms] == names


def test_hbs_mutate_packages_trims_and_prices():
    plugin = HbsMockPlugin()
    spec = PackageSpec(count=1, room_basis="BB", prices=[300.0], refundable=[True])
    result = plugin.mutate_packages(
        HBS_PACKAGES,
        spec,
        "12345",
        "2026-09-01",
        "2026-09-03",
        "Packages",
    )
    rooms = result["httpResponse"]["body"]["hotels"]["hotels"][0]["rooms"]
    assert len(rooms) == 1
    rates = rooms[0]["rates"]
    assert len(rates) == 1
    assert rates[0]["net"] == "300.0"
    assert rates[0]["boardCode"] == "BB"
    assert rates[0]["rateClass"] == "REF"
    assert rates[0]["cancellationPolicies"][0]["amount"] == "0"
    assert result["httpRequest"]["body"]["json"]["hotels"]["hotel"] == [12345]


def test_hbs_non_refundable_cancellation_is_immediate():
    plugin = HbsMockPlugin()
    template = deep_copy(HBS_PACKAGES)
    template["httpResponse"]["body"]["hotels"]["hotels"][0]["rooms"][0]["rates"][0][
        "cancellationPolicies"
    ] = [{"amount": "89.25", "from": "2026-06-04T23:59:00+04:00"}]
    result = plugin.mutate_packages(
        template,
        PackageSpec(count=1, room_basis="RO", prices=[100.0], refundable=[False]),
        "12345",
        "2026-09-01",
        "2026-09-03",
        "Packages",
    )
    rate = result["httpResponse"]["body"]["hotels"]["hotels"][0]["rooms"][0]["rates"][0]
    assert rate["rateClass"] == "NRF"
    assert rate["cancellationPolicies"][0]["amount"] == "100.0"
    assert rate["cancellationPolicies"][0]["from"].startswith("2000-01-01")


def test_hbs_get_order_mutation_forces_confirmed_status():
    plugin = HbsMockPlugin()
    spec = PackageSpec(count=1, room_basis="RO", prices=[300.0], refundable=[True])
    result = plugin.mutate_packages(
        HBS_GET_ORDER,
        spec,
        "12345",
        "2026-09-01",
        "2026-09-03",
        "GetOrder",
    )
    booking = result["httpResponse"]["body"]["booking"]
    assert booking["status"] == "CONFIRMED"
    assert booking["modificationPolicies"] == {"cancellation": True, "modification": True}
    assert booking["hotel"]["status"] == "CONFIRMED"
    assert booking["hotel"]["rooms"][0]["status"] == "CONFIRMED"


EXP_PACKAGES = {
    "httpRequest": {"path": "/v3/properties/1723385/availability"},
    "httpResponse": {
        "body": {
            "body": [
                {
                    "property_id": "1723385",
                    "rooms": [
                        {
                            "id": "201836237",
                            "rates": [
                                {"id": "209336313", "refundable": False, "netPrice": 10.0},
                                {"id": "209336314", "refundable": False, "netPrice": 20.0},
                            ],
                        }
                    ],
                }
            ]
        }
    },
}


EXP_PACKAGES_OCCUPANCY = {
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
                                    "refundable": False,
                                    "bed_groups": {
                                        "37321": {
                                            "id": "37321",
                                            "links": {
                                                "price_check": {
                                                    "method": "GET",
                                                    "href": "/v3/properties/1723385/rooms/201836237/rates/209336313?token=test-token",
                                                }
                                            },
                                        }
                                    },
                                    "occupancy_pricing": {
                                        "1": {
                                            "nightly": [
                                                [
                                                    {"type": "base_rate", "value": "86.00", "currency": "AED"},
                                                ]
                                            ],
                                            "totals": {
                                                "inclusive": {
                                                    "request_currency": {"value": "526.75", "currency": "AED"},
                                                    "billable_currency": {"value": "526.75", "currency": "AED"},
                                                },
                                                "exclusive": {
                                                    "request_currency": {"value": "430.00", "currency": "AED"},
                                                    "billable_currency": {"value": "430.00", "currency": "AED"},
                                                },
                                            },
                                        }
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


def test_exp_mutate_packages_updates_occupancy_pricing_total():
    plugin = ExpMockPlugin()
    spec = PackageSpec(count=1, room_basis="RO", prices=[200.0], refundable=[True])
    result = plugin.mutate_packages(
        EXP_PACKAGES_OCCUPANCY,
        spec,
        "55555",
        "2026-09-01",
        "2026-09-03",
        "Packages",
    )
    totals = (
        result["httpResponse"]["body"]["body"][0]["rooms"][0]["rates"][0]["occupancy_pricing"]["2"]["totals"]
    )
    assert totals["inclusive"]["request_currency"]["value"] == "200.00"
    assert totals["exclusive"]["request_currency"]["value"] == "163.27"


def test_exp_mutate_packages_sets_distribution_and_v3_price_check():
    plugin = ExpMockPlugin()
    spec = PackageSpec(count=1, room_basis="RO", prices=[175.5], refundable=[True])
    payload = deep_copy(EXP_PACKAGES_OCCUPANCY)
    result = plugin.mutate_packages(
        payload,
        spec,
        "55555",
        "2026-09-01",
        "2026-09-03",
        "Packages",
    )
    rate = result["httpResponse"]["body"]["body"][0]["rooms"][0]["rates"][0]
    assert rate["sale_scenario"]["distribution"] is True
    bed_group = next(iter(rate["bed_groups"].values()))
    href = bed_group["links"]["price_check"]["href"]
    assert href.startswith("/v3/properties/55555/rooms/")
    assert "/rates/" in href
    assert "token=test-token" in href


def test_exp_mutate_search_returns_single_rate():
    plugin = ExpMockPlugin()
    spec = PackageSpec(count=3, room_basis="RO", prices=[100.0, 200.0, 300.0], refundable=[True, True, False])
    result = plugin.mutate_packages(
        deep_copy(EXP_PACKAGES),
        spec,
        "55555",
        "2026-09-01",
        "2026-09-03",
        "Search",
    )
    rates = result["httpResponse"]["body"]["body"][0]["rooms"][0]["rates"]
    assert len(rates) == 1


def test_exp_mutate_packages_trims_rates_and_sets_refundable():
    plugin = ExpMockPlugin()
    spec = PackageSpec(count=1, room_basis="RO", prices=[175.5], refundable=[True])
    result = plugin.mutate_packages(
        EXP_PACKAGES,
        spec,
        "55555",
        "2026-09-01",
        "2026-09-03",
        "Packages",
    )
    rates = result["httpResponse"]["body"]["body"][0]["rooms"][0]["rates"]
    assert len(rates) == 1
    assert rates[0]["refundable"] is True
    assert rates[0]["netPrice"] == 175.5
    assert result["httpResponse"]["body"]["body"][0]["property_id"] == "55555"


# Search template uses different room/rate ids than Packages — simulates the real
# template mismatch that causes the EXP adapter to drop rates.
_EXP_SEARCH_DIFFERENT_IDS = {
    "httpResponse": {
        "body": {
            "body": [
                {
                    "property_id": "8697404",
                    "rooms": [
                        {
                            "id": "216919865",  # different from Packages template id
                            "rates": [
                                {
                                    "id": "397499896",  # different from Packages template id
                                    "bed_groups": {
                                        "37321": {
                                            "links": {
                                                "price_check": {
                                                    "method": "GET",
                                                    "href": "/v3/properties/8697404/rooms/216919865/rates/397499896?token=SEARCH-TOKEN",
                                                }
                                            }
                                        }
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

_EXP_PACKAGES_DIFFERENT_IDS = {
    "httpResponse": {
        "body": {
            "body": [
                {
                    "property_id": "2001358",
                    "rooms": [
                        {
                            "id": "201836237",  # Packages room id
                            "rates": [
                                {
                                    "id": "209336313",  # Packages rate id
                                    "bed_groups": {
                                        "37316": {
                                            "links": {
                                                "price_check": {
                                                    "method": "GET",
                                                    "href": "/v3/properties/2001358/rooms/201836237/rates/209336313?token=PKG-TOKEN",
                                                }
                                            }
                                        }
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


_EXP_PACKAGES_TWO_ROOMS = {
    "httpRequest": {"path": "/v3/properties/1723385/availability"},
    "httpResponse": {
        "body": {
            "body": [
                {
                    "property_id": "1723385",
                    "rooms": [
                        {
                            "id": "201836237",
                            "rates": [
                                {"id": "209336313", "refundable": False, "netPrice": 10.0},
                                {"id": "209336314", "refundable": False, "netPrice": 20.0},
                            ],
                        },
                        {
                            "id": "201836238",
                            "rates": [
                                {"id": "209336315", "refundable": False, "netPrice": 30.0},
                                {"id": "209336316", "refundable": False, "netPrice": 40.0},
                            ],
                        },
                    ],
                }
            ]
        }
    },
}


_EXP_PACKAGES_TWO_BED_GROUPS = {
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
                                    "refundable": False,
                                    "bed_groups": {
                                        "37316": {"id": "37316", "links": {"price_check": {"method": "GET", "href": "/v3/properties/1723385/rooms/201836237/rates/209336313?token=t1"}}},
                                        "37341": {"id": "37341", "links": {"price_check": {"method": "GET", "href": "/v3/properties/1723385/rooms/201836237/rates/209336313?token=t2"}}},
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


def test_exp_mutate_packages_trims_bed_groups_to_one():
    plugin = ExpMockPlugin()
    spec = PackageSpec(count=1, room_basis="RO", prices=[150.0], refundable=[True])
    result = plugin.mutate_packages(
        deep_copy(_EXP_PACKAGES_TWO_BED_GROUPS),
        spec,
        "55555",
        "2026-09-01",
        "2026-09-03",
        "Packages",
    )
    bed_groups = result["httpResponse"]["body"]["body"][0]["rooms"][0]["rates"][0]["bed_groups"]
    assert len(bed_groups) == 1


def test_exp_trim_bed_groups_sets_description_to_one_bed():
    plugin = ExpMockPlugin()
    spec = PackageSpec(count=1, room_basis="RO", prices=[150.0], refundable=[True])
    result = plugin.mutate_packages(
        deep_copy(_EXP_PACKAGES_TWO_BED_GROUPS),
        spec,
        "55555",
        "2026-09-01",
        "2026-09-03",
        "Packages",
    )
    bed_groups = result["httpResponse"]["body"]["body"][0]["rooms"][0]["rates"][0]["bed_groups"]
    assert len(bed_groups) == 1
    kept = next(iter(bed_groups.values()))
    assert kept["description"] == "1 Bed"


def test_exp_trim_single_bed_group_also_sets_description():
    plugin = ExpMockPlugin()
    spec = PackageSpec(count=1, room_basis="RO", prices=[150.0], refundable=[True])
    single_bg_payload = deep_copy(_EXP_PACKAGES_TWO_BED_GROUPS)
    # remove second bed_group so only one exists
    rates = single_bg_payload["httpResponse"]["body"]["body"][0]["rooms"][0]["rates"]
    rates[0]["bed_groups"] = {"37316": rates[0]["bed_groups"]["37316"]}
    result = plugin.mutate_packages(single_bg_payload, spec, "55555", "2026-09-01", "2026-09-03", "Packages")
    bed_groups = result["httpResponse"]["body"]["body"][0]["rooms"][0]["rates"][0]["bed_groups"]
    assert len(bed_groups) == 1
    assert next(iter(bed_groups.values()))["description"] == "1 Bed"


def test_exp_mutate_packages_trims_to_one_room():
    plugin = ExpMockPlugin()
    spec = PackageSpec(count=1, room_basis="RO", prices=[150.0], refundable=[True])
    result = plugin.mutate_packages(
        deep_copy(_EXP_PACKAGES_TWO_ROOMS),
        spec,
        "55555",
        "2026-09-01",
        "2026-09-03",
        "Packages",
    )
    rooms = result["httpResponse"]["body"]["body"][0]["rooms"]
    assert len(rooms) == 1
    assert len(rooms[0]["rates"]) == 1


def test_exp_mutate_search_trims_to_one_room():
    plugin = ExpMockPlugin()
    spec = PackageSpec(count=3, room_basis="RO", prices=[100.0, 200.0, 300.0], refundable=[True, True, False])
    result = plugin.mutate_packages(
        deep_copy(_EXP_PACKAGES_TWO_ROOMS),
        spec,
        "55555",
        "2026-09-01",
        "2026-09-03",
        "Search",
    )
    rooms = result["httpResponse"]["body"]["body"][0]["rooms"]
    assert len(rooms) == 1
    assert len(rooms[0]["rates"]) == 1


def test_exp_propagate_package_linkage_aligns_search_room_rate_ids():
    """Search body room/rate ids must match the ids in price_check.href after propagation.

    Before the fix, Search kept template ids (216919865/397499896) while
    price_check.href used Packages ids (201836237/209336313), causing the EXP
    adapter to drop the rate and produce no adapted log.
    """
    plugin = ExpMockPlugin()
    spec = PackageSpec(count=1, room_basis="RO", prices=[100.0], refundable=[True])
    search = deep_copy(_EXP_SEARCH_DIFFERENT_IDS)
    packages = deep_copy(_EXP_PACKAGES_DIFFERENT_IDS)
    prebook = {"httpRequest": {"path": "/v3/properties/8697404/rooms/216919865/rates/397499896"}}
    expectations = {"Search": search, "Packages": packages, "PreBooking": prebook}

    plugin.propagate_package_linkage(expectations, spec)

    search_room = search["httpResponse"]["body"]["body"][0]["rooms"][0]
    search_rate = search_room["rates"][0]
    price_check_href = search_rate["bed_groups"]["37321"]["links"]["price_check"]["href"]

    # room/rate ids in Search body must match what is in price_check.href
    assert search_room["id"] == "201836237"
    assert search_rate["id"] == "209336313"
    assert "/rooms/201836237/" in price_check_href
    assert "/rates/209336313" in price_check_href
    assert "token=PKG-TOKEN" in price_check_href


def test_hbs_applies_supplier_currency_on_packages():
    plugin = HbsMockPlugin()
    payload = deep_copy(HBS_PACKAGES)
    payload["httpResponse"]["body"]["hotels"]["hotels"][0]["currency"] = "EUR"
    spec = PackageSpec(count=1, room_basis="RO", prices=[100.0], refundable=[True], supplier_currency="SAR")
    result = plugin.mutate_packages(payload, spec, "156652", "2026-09-01", "2026-09-03", "Packages")
    hotel = result["httpResponse"]["body"]["hotels"]["hotels"][0]
    assert hotel["currency"] == "SAR"


def test_exp_applies_supplier_currency_on_packages():
    plugin = ExpMockPlugin()
    spec = PackageSpec(count=1, room_basis="RO", prices=[200.0], refundable=[True], supplier_currency="USD")
    result = plugin.mutate_packages(
        deep_copy(EXP_PACKAGES_OCCUPANCY),
        spec,
        "55555",
        "2026-09-01",
        "2026-09-03",
        "Packages",
    )
    totals = (
        result["httpResponse"]["body"]["body"][0]["rooms"][0]["rates"][0]["occupancy_pricing"]["2"]["totals"]
    )
    assert totals["inclusive"]["request_currency"]["currency"] == "USD"
    assert totals["exclusive"]["billable_currency"]["currency"] == "USD"


def test_exp_applies_room_names_per_package_count():
    plugin = ExpMockPlugin()
    names = ["Deluxe Room", "Suite Room"]
    spec = PackageSpec(
        count=2,
        room_basis="RO",
        prices=[100.0, 200.0],
        refundable=[True, False],
        room_names=names,
    )
    payload = deep_copy(EXP_PACKAGES)
    payload["httpResponse"]["body"]["body"][0]["rooms"][0]["room_name"] = "Original"
    result = plugin.mutate_packages(payload, spec, "55555", "2026-09-01", "2026-09-03", "Packages")
    rooms = result["httpResponse"]["body"]["body"][0]["rooms"]
    assert len(rooms) == 2
    assert [room["room_name"] for room in rooms] == names
