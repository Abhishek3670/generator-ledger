import asyncio
import importlib
import sys

import pytest
from fastapi import HTTPException

from core.database import DatabaseManager
from core.models import RentalVendor
from core.repositories import RentalVendorRepository


@pytest.fixture
def app_module_and_conn(tmp_path, monkeypatch):
    db_path = tmp_path / "rental_vendor_management_api.db"
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


def test_create_rental_vendor_success_with_generated_id(app_module_and_conn):
    web_app_module, conn = app_module_and_conn
    payload = asyncio.run(
        web_app_module.api_create_rental_vendor(
            request_data=web_app_module.CreateVendorRequest(
                vendor_name="Royal Banquet",
                vendor_place="Civil Line",
                phone="111",
            ),
            conn=conn,
        )
    )

    assert payload["success"] is True
    assert payload["vendor_id"] == "RNV001"

    repo = RentalVendorRepository(conn)
    created = repo.get_by_id("RNV001")
    assert created is not None
    assert created.vendor_name == "Royal Banquet"
    assert created.vendor_place == "Civil Line"
    assert created.phone == "111"


def test_rental_vendors_list_returns_saved_rows(app_module_and_conn):
    web_app_module, conn = app_module_and_conn
    repo = RentalVendorRepository(conn)
    repo.save(RentalVendor(vendor_id="RNV001", vendor_name="Hotel One", vendor_place="Downtown", phone="222"))
    repo.save(RentalVendor(vendor_id="RNV002", vendor_name="Guest House Two", vendor_place="Station Road", phone="333"))

    payload = asyncio.run(web_app_module.api_rental_vendors(conn=conn))

    assert payload == [
        {"id": "RNV001", "name": "Hotel One", "place": "Downtown", "phone": "222"},
        {"id": "RNV002", "name": "Guest House Two", "place": "Station Road", "phone": "333"},
    ]


def test_update_rental_vendor_success(app_module_and_conn):
    web_app_module, conn = app_module_and_conn
    repo = RentalVendorRepository(conn)
    repo.save(RentalVendor(vendor_id="RNV001", vendor_name="Hotel One", vendor_place="Civil Line", phone="111"))

    payload = asyncio.run(
        web_app_module.api_update_rental_vendor(
            "RNV001",
            request_data=web_app_module.UpdateVendorRequest(
                vendor_name="Hotel Prime",
                vendor_place="Lake View",
                phone="+1-555-0101",
            ),
            conn=conn,
        )
    )

    assert payload["success"] is True
    assert payload["vendor"] == {
        "id": "RNV001",
        "name": "Hotel Prime",
        "place": "Lake View",
        "phone": "+1-555-0101",
    }

    updated = repo.get_by_id("RNV001")
    assert updated is not None
    assert updated.vendor_name == "Hotel Prime"
    assert updated.vendor_place == "Lake View"
    assert updated.phone == "+1-555-0101"


def test_update_rental_vendor_duplicate_name_returns_400(app_module_and_conn):
    web_app_module, conn = app_module_and_conn
    repo = RentalVendorRepository(conn)
    repo.save(RentalVendor(vendor_id="RNV001", vendor_name="Hotel One"))
    repo.save(RentalVendor(vendor_id="RNV002", vendor_name="Hotel Two"))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            web_app_module.api_update_rental_vendor(
                "RNV001",
                request_data=web_app_module.UpdateVendorRequest(
                    vendor_name="Hotel Two",
                    vendor_place="Civil Line",
                    phone="",
                ),
                conn=conn,
            )
        )

    assert exc_info.value.status_code == 400
    assert "already exists" in exc_info.value.detail


def test_delete_rental_vendor_success(app_module_and_conn):
    web_app_module, conn = app_module_and_conn
    repo = RentalVendorRepository(conn)
    repo.save(RentalVendor(vendor_id="RNV001", vendor_name="Hotel One"))

    payload = asyncio.run(web_app_module.api_delete_rental_vendor("RNV001", conn=conn))

    assert payload["success"] is True
    assert repo.get_by_id("RNV001") is None


def test_delete_rental_vendor_not_found_returns_404(app_module_and_conn):
    web_app_module, conn = app_module_and_conn

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(web_app_module.api_delete_rental_vendor("RNV404", conn=conn))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Rental vendor not found"
