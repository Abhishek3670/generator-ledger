import asyncio
import importlib
import sys

import pytest
from fastapi import HTTPException

from core.database import DatabaseManager
from core.models import Booking, BookingItem, Generator, Vendor
from core.repositories import BookingRepository, GeneratorRepository, VendorRepository


@pytest.fixture
def app_module_and_conn(tmp_path, monkeypatch):
    db_path = tmp_path / "vendor_bookings_api.db"
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
        yield web_app_module, conn
    finally:
        db.close()


def seed_vendor_bookings(conn) -> None:
    vendor_repo = VendorRepository(conn)
    generator_repo = GeneratorRepository(conn)
    booking_repo = BookingRepository(conn)

    vendor_repo.save(Vendor(vendor_id="VEN001", vendor_name="Vendor One"))
    vendor_repo.save(Vendor(vendor_id="VEN002", vendor_name="Vendor Two"))

    generator_repo.save(Generator(generator_id="GEN-1", capacity_kva=45))
    generator_repo.save(Generator(generator_id="GEN-2", capacity_kva=65))

    booking_repo.save(
        Booking(
            booking_id="BKG-20260212-00001",
            vendor_id="VEN001",
            created_at="2026-02-12 10:30",
            status="Confirmed",
        )
    )
    booking_repo.save_item(
        BookingItem(
            booking_id="BKG-20260212-00001",
            generator_id="GEN-1",
            start_dt="2026-02-14 00:00",
            end_dt="2026-02-14 23:59",
            item_status="Confirmed",
            remarks="Day one",
        )
    )

    booking_repo.save(
        Booking(
            booking_id="BKG-20260212-00002",
            vendor_id="VEN001",
            created_at="2026-02-12 11:30",
            status="Cancelled",
        )
    )
    booking_repo.save_item(
        BookingItem(
            booking_id="BKG-20260212-00002",
            generator_id="GEN-2",
            start_dt="2026-02-15 00:00",
            end_dt="2026-02-15 23:59",
            item_status="Cancelled",
            remarks="Cancelled item",
        )
    )

    booking_repo.save(
        Booking(
            booking_id="BKG-20260212-00003",
            vendor_id="VEN001",
            created_at="2026-02-12 12:30",
            status="Pending",
        )
    )
    booking_repo.save_item(
        BookingItem(
            booking_id="BKG-20260212-00003",
            generator_id="GEN-2",
            start_dt="2026-02-16 00:00",
            end_dt="2026-02-16 23:59",
            item_status="Pending",
            remarks="Pending item",
        )
    )


def test_vendor_bookings_returns_all_statuses(app_module_and_conn):
    web_app_module, conn = app_module_and_conn
    seed_vendor_bookings(conn)

    payload = asyncio.run(web_app_module.api_vendor_bookings("VEN001", conn=conn))
    assert payload["vendor_id"] == "VEN001"
    assert payload["vendor_name"] == "Vendor One"
    assert payload["total_bookings"] == 3
    assert payload["status_counts"]["Confirmed"] == 1
    assert payload["status_counts"]["Pending"] == 1
    assert payload["status_counts"]["Cancelled"] == 1

    booking_ids = [booking["booking_id"] for booking in payload["bookings"]]
    assert booking_ids == [
        "BKG-20260212-00003",
        "BKG-20260212-00002",
        "BKG-20260212-00001",
    ]

    newest_booking = payload["bookings"][0]
    assert newest_booking["status"] == "Pending"
    assert newest_booking["item_count"] == 1
    assert newest_booking["booked_dates"] == ["2026-02-16"]
    assert newest_booking["items"][0]["capacity_kva"] == 65


def test_vendor_bookings_returns_empty_for_vendor_without_bookings(app_module_and_conn):
    web_app_module, conn = app_module_and_conn
    seed_vendor_bookings(conn)

    payload = asyncio.run(web_app_module.api_vendor_bookings("VEN002", conn=conn))
    assert payload["vendor_id"] == "VEN002"
    assert payload["total_bookings"] == 0
    assert payload["bookings"] == []
    assert payload["status_counts"] == {
        "Confirmed": 0,
        "Pending": 0,
        "Cancelled": 0,
    }


def test_vendor_bookings_returns_404_for_unknown_vendor(app_module_and_conn):
    web_app_module, conn = app_module_and_conn
    seed_vendor_bookings(conn)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(web_app_module.api_vendor_bookings("VEN404", conn=conn))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Vendor not found"
