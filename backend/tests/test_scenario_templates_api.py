def _template_payload(label: str = "Scenario1") -> dict:
    return {
        "label": label,
        "description": "HBS + EXP bedding variations",
        "atg_hotel_id": "1010102",
        "suppliers": [
            {
                "supplier": "HBS",
                "packages": [
                    {"room_name": "Mobile Home, 2 Bedrooms 2 king beds", "price": 300, "room_basis": "RO", "refundable": True},
                    {"room_name": "Mobile Home, 2 Bedrooms 2 Twin Beds", "price": 100, "room_basis": "ro", "refundable": True},
                ],
            },
            {
                "supplier": "EXP",
                "packages": [
                    {"room_name": "Mobile Home, 2 Bedrooms 2 king beds", "price": 310, "room_basis": "RO", "refundable": True},
                ],
            },
        ],
    }


class TestScenarioTemplatesApi:
    def test_create_and_list(self, api_client):
        created = api_client.post("/api/scenario-templates", json=_template_payload()).json()
        assert created["label"] == "Scenario1"
        assert created["atg_hotel_id"] == "1010102"
        assert [s["supplier"] for s in created["suppliers"]] == ["HBS", "EXP"]
        # room_basis is normalized to uppercase regardless of input casing
        assert created["suppliers"][0]["packages"][1]["room_basis"] == "RO"

        items = api_client.get("/api/scenario-templates").json()
        assert len(items) == 1
        assert items[0]["id"] == created["id"]

    def test_create_rejects_empty_packages(self, api_client):
        payload = _template_payload()
        payload["suppliers"][0]["packages"] = []
        response = api_client.post("/api/scenario-templates", json=payload)
        assert response.status_code == 422

    def test_create_rejects_empty_suppliers(self, api_client):
        payload = _template_payload()
        payload["suppliers"] = []
        response = api_client.post("/api/scenario-templates", json=payload)
        assert response.status_code == 422

    def test_create_rejects_duplicate_supplier(self, api_client):
        payload = _template_payload()
        payload["suppliers"].append(dict(payload["suppliers"][0]))
        response = api_client.post("/api/scenario-templates", json=payload)
        assert response.status_code == 422

    def test_create_rejects_blank_hotel_id(self, api_client):
        # A silently-blank hotel id used to fall back to the wizard's default
        # when the template was later opened, reading as "my hotel id didn't
        # import" rather than "I never set one" — reject it up front instead.
        for blank in ("", "   "):
            payload = _template_payload()
            payload["atg_hotel_id"] = blank
            response = api_client.post("/api/scenario-templates", json=payload)
            assert response.status_code == 422

    def test_update_replaces_fields(self, api_client):
        created = api_client.post("/api/scenario-templates", json=_template_payload()).json()
        template_id = created["id"]

        updated_payload = _template_payload(label="Scenario1 renamed")
        updated_payload["atg_hotel_id"] = "9999999"
        updated_payload["suppliers"] = [
            {
                "supplier": "RHK",
                "packages": [{"room_name": "Only room", "price": 50, "room_basis": "BB", "refundable": False}],
            }
        ]
        response = api_client.put(f"/api/scenario-templates/{template_id}", json=updated_payload)
        assert response.status_code == 200
        updated = response.json()
        assert updated["id"] == template_id
        assert updated["label"] == "Scenario1 renamed"
        assert updated["atg_hotel_id"] == "9999999"
        assert [s["supplier"] for s in updated["suppliers"]] == ["RHK"]

        items = api_client.get("/api/scenario-templates").json()
        assert len(items) == 1
        assert items[0]["label"] == "Scenario1 renamed"

    def test_update_missing_returns_404(self, api_client):
        response = api_client.put("/api/scenario-templates/missing-id", json=_template_payload())
        assert response.status_code == 404

    def test_delete_removes_it(self, api_client):
        created = api_client.post("/api/scenario-templates", json=_template_payload()).json()
        template_id = created["id"]

        response = api_client.delete(f"/api/scenario-templates/{template_id}")
        assert response.status_code == 204
        assert api_client.get("/api/scenario-templates").json() == []

    def test_delete_missing_returns_404(self, api_client):
        assert api_client.delete("/api/scenario-templates/missing-id").status_code == 404
