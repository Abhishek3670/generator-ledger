import importlib
import sys

import pytest

from core.database import DatabaseManager
from core.models import Booking, BookingItem, Generator, Vendor
from core.repositories import BookingRepository, GeneratorRepository, VendorRepository


@pytest.fixture
def app_module_and_conn(tmp_path, monkeypatch):
    db_path = tmp_path / "bookings_tree_rows.db"
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


def test_booking_tree_block_groups_dates_and_formats_kva(app_module_and_conn):
    web_app_module, conn = app_module_and_conn

    vendor_repo = VendorRepository(conn)
    generator_repo = GeneratorRepository(conn)
    booking_repo = BookingRepository(conn)

    vendor_repo.save(Vendor(vendor_id="VEN001", vendor_name="Vendor One"))
    generator_repo.save(Generator(generator_id="GEN-45-01", capacity_kva=45))
    generator_repo.save(Generator(generator_id="GEN-45-02", capacity_kva=45))
    generator_repo.save(Generator(generator_id="GEN-65-01", capacity_kva=65))

    booking = Booking(
        booking_id="BKG-20260220-00001",
        vendor_id="VEN001",
        created_at="2026-02-20 10:30",
        status="Confirmed",
    )
    booking_repo.save(booking)

    # Insert out of date order to confirm ascending grouping.
    booking_repo.save_item(
        BookingItem(
            booking_id=booking.booking_id,
            generator_id="GEN-65-01",
            start_dt="2026-02-22 00:00",
            end_dt="2026-02-22 23:59",
            item_status="Confirmed",
            remarks="date-b",
        )
    )
    booking_repo.save_item(
        BookingItem(
            booking_id=booking.booking_id,
            generator_id="GEN-45-01",
            start_dt="2026-02-21 00:00",
            end_dt="2026-02-21 23:59",
            item_status="Confirmed",
            remarks="date-a-first",
        )
    )
    booking_repo.save_item(
        BookingItem(
            booking_id=booking.booking_id,
            generator_id="GEN-45-02",
            start_dt="2026-02-21 00:00",
            end_dt="2026-02-21 23:59",
            item_status="Confirmed",
            remarks="date-a-second",
        )
    )

    block = web_app_module._build_booking_tree_block(conn, booking)

    assert block["rowspan"] == 2
    assert len(block["date_rows"]) == 2
    assert block["date_rows"][0]["date"] == "2026-02-21"
    assert block["date_rows"][1]["date"] == "2026-02-22"

    first_date_labels = [entry["label"] for entry in block["date_rows"][0]["gensets"]]
    second_date_labels = [entry["label"] for entry in block["date_rows"][1]["gensets"]]

    assert first_date_labels == ["GEN-45-01 (45 kVA)", "GEN-45-02 (45 kVA)"]
    assert second_date_labels == ["GEN-65-01 (65 kVA)"]
    assert block["date_rows"][0]["status_label"] == "Confirmed"
    assert block["date_rows"][0]["status_tone"] == "confirmed"
    assert block["date_rows"][1]["status_label"] == "Confirmed"
    assert block["date_rows"][1]["status_tone"] == "confirmed"


def test_booking_tree_block_falls_back_to_na_for_invalid_dates(app_module_and_conn):
    web_app_module, conn = app_module_and_conn

    vendor_repo = VendorRepository(conn)
    booking_repo = BookingRepository(conn)

    vendor_repo.save(Vendor(vendor_id="VEN001", vendor_name="Vendor One"))

    booking = Booking(
        booking_id="BKG-20260221-00001",
        vendor_id="VEN001",
        created_at="2026-02-21 10:30",
        status="Confirmed",
    )
    booking_repo.save(booking)
    booking_repo.save_item(
        BookingItem(
            booking_id=booking.booking_id,
            generator_id="GEN-UNKNOWN",
            start_dt="not-a-date",
            end_dt="not-a-date",
            item_status="Confirmed",
            remarks="",
        )
    )

    block = web_app_module._build_booking_tree_block(conn, booking)
    assert block["rowspan"] == 1
    assert len(block["date_rows"]) == 1
    assert block["date_rows"][0]["date"] == "N/A"
    assert block["date_rows"][0]["gensets"][0]["label"] == "GEN-UNKNOWN"
    assert block["date_rows"][0]["status_label"] == "Confirmed"
    assert block["date_rows"][0]["status_tone"] == "confirmed"


def test_booking_tree_block_sets_mixed_status_for_same_date(app_module_and_conn):
    web_app_module, conn = app_module_and_conn

    vendor_repo = VendorRepository(conn)
    generator_repo = GeneratorRepository(conn)
    booking_repo = BookingRepository(conn)

    vendor_repo.save(Vendor(vendor_id="VEN001", vendor_name="Vendor One"))
    generator_repo.save(Generator(generator_id="GEN-45-01", capacity_kva=45))
    generator_repo.save(Generator(generator_id="GEN-45-02", capacity_kva=45))

    booking = Booking(
        booking_id="BKG-20260222-00001",
        vendor_id="VEN001",
        created_at="2026-02-22 10:30",
        status="Confirmed",
    )
    booking_repo.save(booking)
    booking_repo.save_item(
        BookingItem(
            booking_id=booking.booking_id,
            generator_id="GEN-45-01",
            start_dt="2026-02-23 00:00",
            end_dt="2026-02-23 23:59",
            item_status="Confirmed",
            remarks="",
        )
    )
    booking_repo.save_item(
        BookingItem(
            booking_id=booking.booking_id,
            generator_id="GEN-45-02",
            start_dt="2026-02-23 00:00",
            end_dt="2026-02-23 23:59",
            item_status="Pending",
            remarks="",
        )
    )

    block = web_app_module._build_booking_tree_block(conn, booking)
    assert block["rowspan"] == 1
    assert block["date_rows"][0]["date"] == "2026-02-23"
    assert block["date_rows"][0]["status_label"] == "Confirmed / Pending"
    assert block["date_rows"][0]["status_tone"] == "mixed"
