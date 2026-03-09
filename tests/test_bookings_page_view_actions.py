import importlib
import re
import sys

import pytest
from fastapi.testclient import TestClient

from config import GEN_INVENTORY_EMERGENCY
from core.database import DatabaseManager
from core.models import Booking, BookingItem, Generator, Vendor
from core.repositories import BookingRepository, GeneratorRepository, VendorRepository


@pytest.fixture
def app_client_and_conn(tmp_path, monkeypatch):
    db_path = tmp_path / "bookings_page_view_actions.db"
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


def seed_bookings_page_data(conn) -> None:
    vendor_repo = VendorRepository(conn)
    generator_repo = GeneratorRepository(conn)
    booking_repo = BookingRepository(conn)

    vendor_repo.save(Vendor(vendor_id="VEN001", vendor_name="Vendor One"))
    vendor_repo.save(Vendor(vendor_id="VEN002", vendor_name="Vendor Two"))

    generator_repo.save(Generator(generator_id="GEN-45-01", capacity_kva=45))
    generator_repo.save(Generator(generator_id="GEN-45-02", capacity_kva=45))
    generator_repo.save(Generator(generator_id="GEN-65-01", capacity_kva=65))

    booking_repo.save(
        Booking(
            booking_id="BKG-20260220-00001",
            vendor_id="VEN001",
            created_at="2026-02-20 10:30",
            status="Confirmed",
        )
    )
    booking_repo.save_item(
        BookingItem(
            booking_id="BKG-20260220-00001",
            generator_id="GEN-45-01",
            start_dt="2026-02-21 00:00",
            end_dt="2026-02-21 23:59",
            item_status="Confirmed",
            remarks="date-a",
        )
    )
    booking_repo.save_item(
        BookingItem(
            booking_id="BKG-20260220-00001",
            generator_id="GEN-65-01",
            start_dt="2026-02-22 00:00",
            end_dt="2026-02-22 23:59",
            item_status="Confirmed",
            remarks="date-b",
        )
    )

    booking_repo.save(
        Booking(
            booking_id="BKG-20260220-00002",
            vendor_id="VEN001",
            created_at="2026-02-20 11:30",
            status="Pending",
        )
    )
    booking_repo.save_item(
        BookingItem(
            booking_id="BKG-20260220-00002",
            generator_id="GEN-45-02",
            start_dt="2026-02-23 00:00",
            end_dt="2026-02-23 23:59",
            item_status="Pending",
            remarks="single-row",
        )
    )

    booking_repo.save(
        Booking(
            booking_id="BKG-20260220-00003",
            vendor_id="VEN002",
            created_at="2026-02-20 12:30",
            status="Confirmed",
        )
    )
    booking_repo.save_item(
        BookingItem(
            booking_id="BKG-20260220-00003",
            generator_id="GEN-45-01",
            start_dt="not-a-date",
            end_dt="not-a-date",
            item_status="Confirmed",
            remarks="invalid-date-row",
        )
    )


def _auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/login",
        json={"username": "owner", "password": "Qwerty@345"},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _booking_row_dates(html: str, booking_id: str) -> list[str]:
    pattern = (
        rf'<tr[^>]*class="js-booking-row[^"]*"[^>]*'
        rf'data-booking-id="{re.escape(booking_id)}"[^>]*'
        rf'data-booked-date="([^"]+)"'
    )
    return re.findall(pattern, html)


def test_bookings_page_renders_interactive_row_per_date_row(app_client_and_conn):
    _web_app_module, client, conn = app_client_and_conn
    seed_bookings_page_data(conn)

    response = client.get("/bookings", headers=_auth_headers(client))

    assert response.status_code == 200
    html = response.text

    row_count = len(re.findall(r'<tr[^>]*class="js-booking-row[^"]*"', html))
    interactive_row_count = len(
        re.findall(r'<tr[^>]*class="js-booking-row[^"]*"[^>]*tabindex="0"', html)
    )
    assert row_count == 4
    assert interactive_row_count == row_count
    assert 'class="js-view-booking' not in html


def test_bookings_page_rows_match_booking_date_rows(app_client_and_conn):
    _web_app_module, client, conn = app_client_and_conn
    seed_bookings_page_data(conn)

    response = client.get("/bookings", headers=_auth_headers(client))

    assert response.status_code == 200
    html = response.text

    assert _booking_row_dates(html, "BKG-20260220-00001") == [
        "2026-02-21",
        "2026-02-22",
    ]
    assert _booking_row_dates(html, "BKG-20260220-00002") == ["2026-02-23"]
    assert _booking_row_dates(html, "BKG-20260220-00003") == ["N/A"]
    assert 'aria-label="View booking BKG-20260220-00001 for 2026-02-21"' in html


def test_bookings_page_does_not_render_action_column_or_grouped_action_cell(app_client_and_conn):
    _web_app_module, client, conn = app_client_and_conn
    seed_bookings_page_data(conn)

    response = client.get("/bookings", headers=_auth_headers(client))

    assert response.status_code == 200
    html = response.text

    assert 'id="overlayBookedDate"' in html
    assert ">Action<" not in html
    assert "js-booking-action-cell" not in html
    assert 'class="js-view-booking' not in html


def test_bookings_page_marks_emergency_generators_in_red(app_client_and_conn):
    _web_app_module, client, conn = app_client_and_conn

    vendor_repo = VendorRepository(conn)
    generator_repo = GeneratorRepository(conn)
    booking_repo = BookingRepository(conn)

    vendor_repo.save(Vendor(vendor_id="VEN010", vendor_name="Emergency Vendor"))
    generator_repo.save(
        Generator(
            generator_id="EMG-65-01",
            capacity_kva=65,
            inventory_type=GEN_INVENTORY_EMERGENCY,
        )
    )
    booking_repo.save(
        Booking(
            booking_id="BKG-20260301-00001",
            vendor_id="VEN010",
            created_at="2026-03-01 10:30",
            status="Confirmed",
        )
    )
    booking_repo.save_item(
        BookingItem(
            booking_id="BKG-20260301-00001",
            generator_id="EMG-65-01",
            start_dt="2026-03-02 00:00",
            end_dt="2026-03-02 23:59",
            item_status="Confirmed",
            remarks="Emergency assignment",
        )
    )

    response = client.get("/bookings", headers=_auth_headers(client))

    assert response.status_code == 200
    html = response.text
    assert 'data-generator-inventory="emergency"' in html
    assert "font-semibold text-rose-700" in html
