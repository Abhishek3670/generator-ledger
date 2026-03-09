import importlib
import sys

import pytest
from fastapi.testclient import TestClient

from core.database import DatabaseManager
from core.models import RentalVendor, Vendor
from core.repositories import RentalVendorRepository, VendorRepository


@pytest.fixture
def app_client_and_conn(tmp_path, monkeypatch):
    db_path = tmp_path / "vendors_page_sections.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("OWNER_USERNAME", "owner")
    monkeypatch.setenv("OWNER_PASSWORD", "Qwerty@345")
    monkeypatch.setenv("LOAD_SEED_DATA", "false")
    monkeypatch.setenv("DEBUG", "true")

    import config as config_module

    importlib.reload(config_module)
    sys.modules.pop("web.app", None)
    sys.modules.pop("web", None)
    web_app_module = importlib.import_module("web.app")

    db = DatabaseManager(str(db_path))
    conn = db.connect()
    db.init_schema()

    try:
        with TestClient(web_app_module.app) as client:
            yield web_app_module, client, conn
    finally:
        db.close()


def _auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/login",
        json={"username": "owner", "password": "Qwerty@345"},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_vendors_page_renders_refined_retailer_and_rental_sections(app_client_and_conn):
    _web_app_module, client, conn = app_client_and_conn

    vendor_repo = VendorRepository(conn)
    rental_vendor_repo = RentalVendorRepository(conn)
    vendor_repo.save(Vendor(vendor_id="VEN001", vendor_name="Retail Partner", vendor_place="Civil Line", phone="111"))
    rental_vendor_repo.save(
        RentalVendor(
            rental_vendor_id="RNV001",
            vendor_name="Hotel Residency",
            vendor_place="Downtown",
            phone="222",
        )
    )

    response = client.get("/vendors", headers=_auth_headers(client))

    assert response.status_code == 200
    html = response.text

    assert "Retailer Vendor" in html
    assert "Rental Vendors" in html
    assert "Retail Vendor records of marriage functions or similar on site functions" in html
    assert "Rental Vendor records of marriage halls, guest houses, and hotels." in html
    assert "Retail Partner" in html
    assert "Hotel Residency" in html
    assert 'data-vendor-kind="retailer"' in html
    assert 'data-vendor-kind="rental"' in html
    assert 'data-rental-vendor-id="RNV001"' in html
    assert "+ Add Retailer Vendor" in html
    assert "+ Add Rental Vendor" in html
    assert "Rental Vendor ID" in html
    assert "Property Name" in html
    assert 'class="vendor-table-scroll"' in html
