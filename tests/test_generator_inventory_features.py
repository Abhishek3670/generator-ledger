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
    db_path = tmp_path / "generator_inventory_features.db"
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


def test_create_generator_supports_emergency_inventory_type_via_api(app_client_and_conn):
    _web_app_module, client, conn = app_client_and_conn

    response = client.post(
        "/api/generators",
        headers=_auth_headers(client),
        json={
            "capacity_kva": 45,
            "type": "Silent",
            "identification": "Warehouse A",
            "notes": "Backup stock",
            "status": "Active",
            "inventory_type": GEN_INVENTORY_EMERGENCY,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["inventory_type"] == GEN_INVENTORY_EMERGENCY

    repo = GeneratorRepository(conn)
    created = repo.get_by_id(payload["generator_id"])
    assert created is not None
    assert created.inventory_type == GEN_INVENTORY_EMERGENCY


def test_generators_page_renders_retailer_and_emergency_sections(app_client_and_conn):
    _web_app_module, client, conn = app_client_and_conn

    generator_repo = GeneratorRepository(conn)
    vendor_repo = VendorRepository(conn)
    booking_repo = BookingRepository(conn)

    generator_repo.save(
        Generator(
            generator_id="RET-45-01",
            capacity_kva=45,
            type="Silent",
            inventory_type=GEN_INVENTORY_RETAILER,
        )
    )
    generator_repo.save(
        Generator(
            generator_id="EMG-45-01",
            capacity_kva=45,
            type="Silent",
            inventory_type=GEN_INVENTORY_EMERGENCY,
        )
    )
    vendor_repo.save(Vendor(vendor_id="VEN001", vendor_name="Vendor One"))
    booking_repo.save(
        Booking(
            booking_id="BKG-20260305-00001",
            vendor_id="VEN001",
            created_at="2026-03-05 08:00",
            status="Confirmed",
        )
    )
    booking_repo.save_item(
        BookingItem(
            booking_id="BKG-20260305-00001",
            generator_id="EMG-45-01",
            start_dt="2026-03-05 08:00",
            end_dt="2026-03-05 20:00",
            item_status="Confirmed",
        )
    )

    response = client.get("/generators?date=2026-03-05", headers=_auth_headers(client))

    assert response.status_code == 200
    html = response.text

    assert "Retailer Genset" in html
    assert "Emergency Genset" in html
    assert "RET-45-01" in html
    assert "EMG-45-01" in html
    assert 'data-inventory-type="retailer"' in html
    assert 'data-inventory-type="emergency"' in html
    assert html.count('class="generator-table-scroll"') == 2
    assert "+ Add New Genset" in html
    assert 'value="2026-03-05"' in html
    assert "Booked" in html
    assert "Free" in html


def test_init_schema_backfills_inventory_type_for_legacy_generators(tmp_path):
    db_path = tmp_path / "legacy_generator_inventory.db"
    db = DatabaseManager(str(db_path))
    conn = db.connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE generators (
                generator_id TEXT PRIMARY KEY,
                capacity_kva INTEGER NOT NULL,
                identification TEXT,
                type TEXT,
                status TEXT,
                notes TEXT
            )
            """
        )
        cur.execute(
            """
            INSERT INTO generators (generator_id, capacity_kva, identification, type, status, notes)
            VALUES ('LEG-45-01', 45, 'Legacy', 'Silent', 'Active', 'Old schema row')
            """
        )
        conn.commit()

        db.init_schema()

        cur.execute("PRAGMA table_info(generators)")
        columns = [row[1] for row in cur.fetchall()]
        assert "inventory_type" in columns

        repo = GeneratorRepository(conn)
        generator = repo.get_by_id("LEG-45-01")
        assert generator is not None
        assert generator.inventory_type == GEN_INVENTORY_RETAILER
    finally:
        db.close()
