from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "supplier-mock-factory"


def test_list_suppliers():
    """Every configured supplier is listed — EXT included.

    The old hardcoded response omitted EXT, so a supplier SMF could actually mock was
    invisible to the dashboard and to the template import dropdown.
    """
    response = client.get("/api/suppliers")
    assert response.status_code == 200
    suppliers = response.json()
    codes = {s["code"] for s in suppliers}
    assert codes == {"HBS", "EXP", "RHK", "CHC", "EXT"}
    assert all(s["log_types"] for s in suppliers)
