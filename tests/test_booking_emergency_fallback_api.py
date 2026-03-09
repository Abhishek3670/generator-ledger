import importlib
import sys

import pytest
from fastapi.testclient import TestClient

from config import GEN_INVENTORY_EMERGENCY, GEN_INVENTORY_RETAILER
from core.database import DatabaseManager
from core.models import Booking, BookingItem, Generator, Vendor
from core.repositories import BookingRepository, GeneratorRepository, VendorRepository


@pytest.fixture
def app_client_and_conn(tmp_path, monkeypatch):
    db_path = tmp_path / "booking_emergency_fallback_api.db"
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


def seed_booking_fallback_data(conn) -> None:
    vendor_repo = VendorRepository(conn)
    generator_repo = GeneratorRepository(conn)

    vendor_repo.save(Vendor(vendor_id="VEN001", vendor_name="Vendor One"))
    vendor_repo.save(Vendor(vendor_id="VEN002", vendor_name="Vendor Two"))
    vendor_repo.save(Vendor(vendor_id="VEN003", vendor_name="Vendor Three"))

    generator_repo.save(
        Generator(
            generator_id="RET-45-01",
            capacity_kva=45,
            type="Silent",
            identification="Retailer Yard",
            inventory_type=GEN_INVENTORY_RETAILER,
        )
    )
    generator_repo.save(
        Generator(
            generator_id="EMG-45-01",
            capacity_kva=45,
            type="Silent",
            identification="Warehouse A",
            notes="Backup stock",
            inventory_type=GEN_INVENTORY_EMERGENCY,
        )
    )


def block_generator_for_date(
    conn,
    *,
    booking_id: str,
    vendor_id: str,
    generator_id: str,
    booking_date: str,
) -> None:
    booking_repo = BookingRepository(conn)
    booking_repo.save(
        Booking(
            booking_id=booking_id,
            vendor_id=vendor_id,
            created_at=f"{booking_date} 08:00",
            status="Confirmed",
        )
    )
    booking_repo.save_item(
        BookingItem(
            booking_id=booking_id,
            generator_id=generator_id,
            start_dt=f"{booking_date} 00:00",
            end_dt=f"{booking_date} 23:59",
            item_status="Confirmed",
            remarks="Seeded booking",
        )
    )


def test_create_booking_returns_retailer_out_of_stock_payload_for_capacity_booking(app_client_and_conn):
    _web_app_module, client, conn = app_client_and_conn
    seed_booking_fallback_data(conn)
    block_generator_for_date(
        conn,
        booking_id="BKG-20260309-00001",
        vendor_id="VEN001",
        generator_id="RET-45-01",
        booking_date="2026-03-10",
    )

    response = client.post(
        "/api/bookings",
        headers=_auth_headers(client),
        json={
            "vendor_id": "VEN002",
            "items": [{"capacity_kva": 45, "date": "2026-03-10", "remarks": "Need standby"}],
        },
    )

    assert response.status_code == 409
    payload = response.json()
    assert payload["success"] is False
    assert payload["error_code"] == "retailer_out_of_stock"
    assert len(payload["affected_dates"]) == 1
    suggestion = payload["affected_dates"][0]
    assert suggestion["date"] == "2026-03-10"
    assert suggestion["capacity_kva"] == 45
    assert suggestion["suggested_generator_id"] == "EMG-45-01"
    assert suggestion["emergency_options"] == [
        {
            "generator_id": "EMG-45-01",
            "capacity_kva": 45,
            "identification": "Warehouse A",
            "type": "Silent",
            "notes": "Backup stock",
            "inventory_type": GEN_INVENTORY_EMERGENCY,
        }
    ]


def test_create_booking_returns_blocking_error_when_no_emergency_available(app_client_and_conn):
    _web_app_module, client, conn = app_client_and_conn
    seed_booking_fallback_data(conn)
    block_generator_for_date(
        conn,
        booking_id="BKG-20260309-00001",
        vendor_id="VEN001",
        generator_id="RET-45-01",
        booking_date="2026-03-11",
    )
    block_generator_for_date(
        conn,
        booking_id="BKG-20260309-00002",
        vendor_id="VEN002",
        generator_id="EMG-45-01",
        booking_date="2026-03-11",
    )

    response = client.post(
        "/api/bookings",
        headers=_auth_headers(client),
        json={
            "vendor_id": "VEN003",
            "items": [{"capacity_kva": 45, "date": "2026-03-11", "remarks": ""}],
        },
    )

    assert response.status_code == 400
    assert "No retailer or emergency 45 kVA generator is available" in response.json()["detail"]


def test_create_booking_accepts_resubmitted_explicit_emergency_generator_and_exposes_inventory_metadata(app_client_and_conn):
    _web_app_module, client, conn = app_client_and_conn
    seed_booking_fallback_data(conn)
    block_generator_for_date(
        conn,
        booking_id="BKG-20260309-00001",
        vendor_id="VEN001",
        generator_id="RET-45-01",
        booking_date="2026-03-12",
    )

    response = client.post(
        "/api/bookings",
        headers=_auth_headers(client),
        json={
            "vendor_id": "VEN002",
            "items": [{"generator_id": "EMG-45-01", "date": "2026-03-12", "remarks": "Confirmed emergency use"}],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    booking_id = payload["booking_id"]

    detail_response = client.get(f"/api/bookings/{booking_id}", headers=_auth_headers(client))
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["items"][0]["generator_id"] == "EMG-45-01"
    assert detail_payload["items"][0]["inventory_type"] == GEN_INVENTORY_EMERGENCY
    assert detail_payload["items"][0]["is_emergency"] is True

    vendor_bookings_response = client.get("/api/vendors/VEN002/bookings", headers=_auth_headers(client))
    assert vendor_bookings_response.status_code == 200
    vendor_payload = vendor_bookings_response.json()
    assert vendor_payload["bookings"][0]["items"][0]["inventory_type"] == GEN_INVENTORY_EMERGENCY
    assert vendor_payload["bookings"][0]["items"][0]["is_emergency"] is True


def test_create_booking_page_renders_emergency_fallback_modal(app_client_and_conn):
    _web_app_module, client, _conn = app_client_and_conn

    response = client.get("/create-booking", headers=_auth_headers(client))

    assert response.status_code == 200
    html = response.text
    assert 'id="retailerOutOfStockOverlay"' in html
    assert "Emergency Genset Suggestions" in html
    assert "Use Emergency Genset(s)" in html


def test_booking_detail_and_edit_pages_render_emergency_generator_in_red(app_client_and_conn):
    _web_app_module, client, conn = app_client_and_conn
    seed_booking_fallback_data(conn)
    block_generator_for_date(
        conn,
        booking_id="BKG-20260309-00003",
        vendor_id="VEN002",
        generator_id="EMG-45-01",
        booking_date="2026-03-13",
    )

    detail_response = client.get("/booking/BKG-20260309-00003", headers=_auth_headers(client))
    assert detail_response.status_code == 200
    assert 'data-generator-inventory="emergency"' in detail_response.text
    assert "font-semibold text-rose-700" in detail_response.text

    edit_response = client.get("/booking/BKG-20260309-00003/edit", headers=_auth_headers(client))
    assert edit_response.status_code == 200
    assert 'data-generator-inventory="emergency"' in edit_response.text
    assert "font-semibold text-rose-700" in edit_response.text
