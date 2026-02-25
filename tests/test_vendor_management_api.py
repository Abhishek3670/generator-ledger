import asyncio
import importlib
import sys

import pytest
from fastapi import HTTPException

from core.database import DatabaseManager
from core.models import Booking, Vendor
from core.repositories import BookingRepository, VendorRepository


@pytest.fixture
def app_module_and_conn(tmp_path, monkeypatch):
    db_path = tmp_path / "vendor_management_api.db"
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


def test_update_vendor_success(app_module_and_conn):
    web_app_module, conn = app_module_and_conn
    vendor_repo = VendorRepository(conn)
    vendor_repo.save(Vendor(vendor_id="VEN001", vendor_name="Vendor One", vendor_place="Civil Line", phone="111"))

    payload = asyncio.run(
        web_app_module.api_update_vendor(
            "VEN001",
            request_data=web_app_module.UpdateVendorRequest(
                vendor_name="Vendor Prime",
                vendor_place="Downtown",
                phone="+1-555-0100",
            ),
            conn=conn,
        )
    )

    assert payload["success"] is True
    assert payload["vendor"] == {
        "id": "VEN001",
        "name": "Vendor Prime",
        "place": "Downtown",
        "phone": "+1-555-0100",
    }

    updated = vendor_repo.get_by_id("VEN001")
    assert updated is not None
    assert updated.vendor_name == "Vendor Prime"
    assert updated.vendor_place == "Downtown"
    assert updated.phone == "+1-555-0100"


def test_update_vendor_not_found_returns_404(app_module_and_conn):
    web_app_module, conn = app_module_and_conn

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            web_app_module.api_update_vendor(
                "VEN404",
                request_data=web_app_module.UpdateVendorRequest(
                    vendor_name="Missing Vendor",
                    vendor_place="Civil Line",
                    phone="",
                ),
                conn=conn,
            )
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Vendor not found"


def test_update_vendor_duplicate_name_returns_400(app_module_and_conn):
    web_app_module, conn = app_module_and_conn
    vendor_repo = VendorRepository(conn)
    vendor_repo.save(Vendor(vendor_id="VEN001", vendor_name="Vendor One"))
    vendor_repo.save(Vendor(vendor_id="VEN002", vendor_name="Vendor Two"))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            web_app_module.api_update_vendor(
                "VEN001",
                request_data=web_app_module.UpdateVendorRequest(
                    vendor_name="Vendor Two",
                    vendor_place="Civil Line",
                    phone="",
                ),
                conn=conn,
            )
        )

    assert exc_info.value.status_code == 400
    assert "already exists" in exc_info.value.detail


def test_update_vendor_blank_place_defaults_to_civil_line(app_module_and_conn):
    web_app_module, conn = app_module_and_conn
    vendor_repo = VendorRepository(conn)
    vendor_repo.save(Vendor(vendor_id="VEN001", vendor_name="Vendor One", vendor_place="Old Place", phone="123"))

    payload = asyncio.run(
        web_app_module.api_update_vendor(
            "VEN001",
            request_data=web_app_module.UpdateVendorRequest(
                vendor_name="Vendor One Updated",
                vendor_place="   ",
                phone="321",
            ),
            conn=conn,
        )
    )

    assert payload["vendor"]["place"] == "Civil Line"
    updated = vendor_repo.get_by_id("VEN001")
    assert updated is not None
    assert updated.vendor_place == "Civil Line"


def test_delete_vendor_success_when_unused(app_module_and_conn):
    web_app_module, conn = app_module_and_conn
    vendor_repo = VendorRepository(conn)
    vendor_repo.save(Vendor(vendor_id="VEN001", vendor_name="Vendor One"))

    payload = asyncio.run(web_app_module.api_delete_vendor("VEN001", conn=conn))

    assert payload["success"] is True
    assert vendor_repo.get_by_id("VEN001") is None


def test_delete_vendor_blocked_when_bookings_exist_returns_409(app_module_and_conn):
    web_app_module, conn = app_module_and_conn
    vendor_repo = VendorRepository(conn)
    booking_repo = BookingRepository(conn)

    vendor_repo.save(Vendor(vendor_id="VEN001", vendor_name="Vendor One"))
    booking_repo.save(
        Booking(
            booking_id="BKG-20260225-00001",
            vendor_id="VEN001",
            created_at="2026-02-25 09:30",
            status="Confirmed",
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(web_app_module.api_delete_vendor("VEN001", conn=conn))

    assert exc_info.value.status_code == 409
    assert "booking(s) reference it" in exc_info.value.detail


def test_delete_vendor_not_found_returns_404(app_module_and_conn):
    web_app_module, conn = app_module_and_conn

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(web_app_module.api_delete_vendor("VEN404", conn=conn))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Vendor not found"
