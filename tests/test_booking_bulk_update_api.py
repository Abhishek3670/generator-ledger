import asyncio
import importlib
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from core.database import DatabaseManager
from core.models import Booking, BookingItem, Generator, Vendor
from core.repositories import BookingRepository, GeneratorRepository, VendorRepository


@pytest.fixture
def app_module_and_conn(tmp_path, monkeypatch):
    db_path = tmp_path / "booking_bulk_update_api.db"
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


def _request(username: str = "tester"):
    return SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(username=username)))


def _seed_booking_with_items(conn):
    vendor_repo = VendorRepository(conn)
    generator_repo = GeneratorRepository(conn)
    booking_repo = BookingRepository(conn)

    vendor_repo.save(Vendor(vendor_id="VEN001", vendor_name="Vendor One"))
    generator_repo.save(Generator(generator_id="GEN-45", capacity_kva=45))
    generator_repo.save(Generator(generator_id="GEN-65", capacity_kva=65))

    booking = Booking(
        booking_id="BKG-20260226-00001",
        vendor_id="VEN001",
        created_at="2026-02-26 10:15",
        status="Confirmed",
    )
    booking_repo.save(booking)
    booking_repo.save_item(
        BookingItem(
            booking_id=booking.booking_id,
            generator_id="GEN-45",
            start_dt="2026-02-27 00:00",
            end_dt="2026-02-27 23:59",
            item_status="Confirmed",
            remarks="first",
        )
    )
    booking_repo.save_item(
        BookingItem(
            booking_id=booking.booking_id,
            generator_id="GEN-65",
            start_dt="2026-02-28 00:00",
            end_dt="2026-02-28 23:59",
            item_status="Confirmed",
            remarks="second",
        )
    )
    return booking.booking_id


def test_bulk_update_rejects_removing_all_items(app_module_and_conn):
    web_app_module, conn = app_module_and_conn
    booking_repo = BookingRepository(conn)
    booking_id = _seed_booking_with_items(conn)
    existing_items = booking_repo.get_items(booking_id)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            web_app_module.api_bulk_update_items(
                request=_request(),
                booking_id=booking_id,
                request_data={
                    "updates": [],
                    "removes": [item.id for item in existing_items],
                },
                conn=conn,
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Cannot remove all booking items. Use Delete Booking to remove this booking."
    assert len(booking_repo.get_items(booking_id)) == 2


def test_bulk_update_allows_partial_remove(app_module_and_conn):
    web_app_module, conn = app_module_and_conn
    booking_repo = BookingRepository(conn)
    booking_id = _seed_booking_with_items(conn)
    existing_items = booking_repo.get_items(booking_id)
    keep_item = existing_items[0]
    remove_item = existing_items[1]

    payload = asyncio.run(
        web_app_module.api_bulk_update_items(
            request=_request(),
            booking_id=booking_id,
            request_data={
                "updates": [
                    {
                        "id": keep_item.id,
                        "start_dt": keep_item.start_dt,
                        "end_dt": keep_item.end_dt,
                        "remarks": keep_item.remarks,
                    }
                ],
                "removes": [remove_item.id],
            },
            conn=conn,
        )
    )

    assert payload["success"] is True
    remaining = booking_repo.get_items(booking_id)
    assert len(remaining) == 1
    assert remaining[0].id == keep_item.id
