import asyncio
import importlib
import sys

import pytest
from fastapi import HTTPException

from config import GEN_INVENTORY_EMERGENCY
from core.database import DatabaseManager
from core.models import Booking, BookingItem, Generator, Vendor
from core.repositories import BookingRepository, GeneratorRepository, VendorRepository


@pytest.fixture
def app_module_and_conn(tmp_path, monkeypatch):
    db_path = tmp_path / "billing_lines_api.db"
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


def seed_billing_data(conn) -> None:
    vendor_repo = VendorRepository(conn)
    generator_repo = GeneratorRepository(conn)
    booking_repo = BookingRepository(conn)

    vendor_repo.save(Vendor(vendor_id="VEN001", vendor_name="Alpha Vendor"))
    vendor_repo.save(Vendor(vendor_id="VEN002", vendor_name="Beta Vendor"))

    generator_repo.save(Generator(generator_id="GEN-45", capacity_kva=45))
    generator_repo.save(
        Generator(
            generator_id="GEN-65",
            capacity_kva=65,
            inventory_type=GEN_INVENTORY_EMERGENCY,
        )
    )

    booking_repo.save(
        Booking(
            booking_id="BKG-20260210-00001",
            vendor_id="VEN001",
            created_at="2026-02-10 09:00",
            status="Confirmed",
        )
    )
    booking_repo.save_item(
        BookingItem(
            booking_id="BKG-20260210-00001",
            generator_id="GEN-45",
            start_dt="2026-02-21 00:00",
            end_dt="2026-02-21 23:59",
            item_status="Confirmed",
            remarks="included",
        )
    )
    booking_repo.save_item(
        BookingItem(
            booking_id="BKG-20260210-00001",
            generator_id="GEN-65",
            start_dt="2026-02-22 00:00",
            end_dt="2026-02-22 23:59",
            item_status="Confirmed",
            remarks="included",
        )
    )
    booking_repo.save_item(
        BookingItem(
            booking_id="BKG-20260210-00001",
            generator_id="GEN-45",
            start_dt="2026-02-23 00:00",
            end_dt="2026-02-23 23:59",
            item_status="Confirmed",
            remarks="out-of-range",
        )
    )

    booking_repo.save(
        Booking(
            booking_id="BKG-20260210-00002",
            vendor_id="VEN002",
            created_at="2026-02-10 10:00",
            status="Confirmed",
        )
    )
    booking_repo.save_item(
        BookingItem(
            booking_id="BKG-20260210-00002",
            generator_id="GEN-65",
            start_dt="2026-02-20 00:00",
            end_dt="2026-02-20 23:59",
            item_status="Confirmed",
            remarks="included-boundary",
        )
    )

    booking_repo.save(
        Booking(
            booking_id="BKG-20260210-00003",
            vendor_id="VEN001",
            created_at="2026-02-10 11:00",
            status="Pending",
        )
    )
    booking_repo.save_item(
        BookingItem(
            booking_id="BKG-20260210-00003",
            generator_id="GEN-45",
            start_dt="2026-02-21 00:00",
            end_dt="2026-02-21 23:59",
            item_status="Confirmed",
            remarks="excluded-booking-status",
        )
    )

    booking_repo.save(
        Booking(
            booking_id="BKG-20260210-00004",
            vendor_id="VEN001",
            created_at="2026-02-10 12:00",
            status="Confirmed",
        )
    )
    booking_repo.save_item(
        BookingItem(
            booking_id="BKG-20260210-00004",
            generator_id="GEN-45",
            start_dt="2026-02-21 00:00",
            end_dt="2026-02-21 23:59",
            item_status="Cancelled",
            remarks="excluded-item-status",
        )
    )


def test_billing_lines_filters_confirmed_only_and_range_inclusive(app_module_and_conn):
    web_app_module, conn = app_module_and_conn
    seed_billing_data(conn)

    payload = asyncio.run(
        web_app_module.api_billing_lines(
            from_date="2026-02-20",
            to_date="2026-02-22",
            conn=conn,
        )
    )

    assert payload["from"] == "2026-02-20"
    assert payload["to"] == "2026-02-22"
    assert payload["count"] == 3
    assert payload["capacities"] == [45, 65]

    ordered_rows = [
        (
            row["vendor_id"],
            row["vendor_name"],
            row["booking_id"],
            row["booked_date"],
            row["generator_id"],
            row["capacity_kva"],
            row["inventory_type"],
        )
        for row in payload["rows"]
    ]
    assert ordered_rows == [
        ("VEN001", "Alpha Vendor", "BKG-20260210-00001", "2026-02-21", "GEN-45", 45, "retailer"),
        ("VEN001", "Alpha Vendor", "BKG-20260210-00001", "2026-02-22", "GEN-65", 65, GEN_INVENTORY_EMERGENCY),
        ("VEN002", "Beta Vendor", "BKG-20260210-00002", "2026-02-20", "GEN-65", 65, GEN_INVENTORY_EMERGENCY),
    ]


def test_billing_lines_rejects_invalid_date_format(app_module_and_conn):
    web_app_module, conn = app_module_and_conn
    seed_billing_data(conn)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            web_app_module.api_billing_lines(
                from_date="2026/02/20",
                to_date="2026-02-22",
                conn=conn,
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid date format (YYYY-MM-DD)"


def test_billing_lines_rejects_inverted_date_range(app_module_and_conn):
    web_app_module, conn = app_module_and_conn
    seed_billing_data(conn)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            web_app_module.api_billing_lines(
                from_date="2026-02-23",
                to_date="2026-02-22",
                conn=conn,
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == '"from" cannot be later than "to"'
