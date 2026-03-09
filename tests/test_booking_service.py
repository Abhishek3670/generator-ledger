import pytest

from config import GEN_INVENTORY_EMERGENCY, GEN_INVENTORY_RETAILER
from core import (
    DatabaseManager,
    BookingService,
    GeneratorRepository,
    VendorRepository,
    BookingRepository,
)
from core.models import Generator, Vendor
from core.services import RetailerOutOfStockError


@pytest.fixture
def conn():
    db = DatabaseManager(":memory:")
    conn = db.connect()
    db.init_schema()
    yield conn
    db.close()


def seed_minimal(conn, generators, vendors):
    gen_repo = GeneratorRepository(conn)
    vendor_repo = VendorRepository(conn)
    for gen in generators:
        gen_repo.save(gen)
    for vendor in vendors:
        vendor_repo.save(vendor)


def test_create_booking_auto_assign(conn):
    seed_minimal(
        conn,
        generators=[Generator(generator_id="GEN-1", capacity_kva=45)],
        vendors=[Vendor(vendor_id="VEN001", vendor_name="Vendor One")],
    )

    service = BookingService(conn)
    booking_id = service.create_booking(
        "VEN001",
        [{"capacity_kva": 45, "date": "2026-01-15", "remarks": ""}]
    )

    booking_repo = BookingRepository(conn)
    items = booking_repo.get_items(booking_id)
    assert len(items) == 1
    assert items[0].generator_id == "GEN-1"


def test_create_booking_invalid_vendor(conn):
    seed_minimal(
        conn,
        generators=[Generator(generator_id="GEN-1", capacity_kva=45)],
        vendors=[],
    )

    service = BookingService(conn)
    with pytest.raises(ValueError, match="Vendor 'VEN404' does not exist"):
        service.create_booking(
            "VEN404",
            [{"capacity_kva": 45, "date": "2026-01-15"}]
        )


def test_create_booking_merges_by_vendor_and_date(conn):
    seed_minimal(
        conn,
        generators=[
            Generator(generator_id="GEN-1", capacity_kva=45),
            Generator(generator_id="GEN-2", capacity_kva=45),
        ],
        vendors=[Vendor(vendor_id="VEN001", vendor_name="Vendor One")],
    )

    service = BookingService(conn)
    booking_id_first = service.create_booking(
        "VEN001",
        [{"capacity_kva": 45, "date": "2026-01-15"}]
    )
    booking_id_second = service.create_booking(
        "VEN001",
        [{"capacity_kva": 45, "date": "2026-01-15"}]
    )

    assert booking_id_second == booking_id_first
    booking_repo = BookingRepository(conn)
    items = booking_repo.get_items(booking_id_first)
    assert len(items) == 2


def test_create_booking_conflict_same_generator(conn):
    seed_minimal(
        conn,
        generators=[Generator(generator_id="GEN-1", capacity_kva=45)],
        vendors=[
            Vendor(vendor_id="VEN001", vendor_name="Vendor One"),
            Vendor(vendor_id="VEN002", vendor_name="Vendor Two"),
        ],
    )

    service = BookingService(conn)
    service.create_booking(
        "VEN001",
        [{"generator_id": "GEN-1", "date": "2026-01-15"}]
    )

    with pytest.raises(RuntimeError, match="Generator GEN-1 not available"):
        service.create_booking(
            "VEN002",
            [{"generator_id": "GEN-1", "date": "2026-01-15"}]
        )


def test_create_booking_auto_assign_prefers_retailer_inventory(conn):
    seed_minimal(
        conn,
        generators=[
            Generator(
                generator_id="AAA-EMERGENCY-45",
                capacity_kva=45,
                inventory_type=GEN_INVENTORY_EMERGENCY,
            ),
            Generator(
                generator_id="ZZZ-RETAIL-45",
                capacity_kva=45,
                inventory_type=GEN_INVENTORY_RETAILER,
            ),
        ],
        vendors=[Vendor(vendor_id="VEN001", vendor_name="Vendor One")],
    )

    service = BookingService(conn)
    booking_id = service.create_booking(
        "VEN001",
        [{"capacity_kva": 45, "date": "2026-01-15"}]
    )

    booking_repo = BookingRepository(conn)
    items = booking_repo.get_items(booking_id)
    assert len(items) == 1
    assert items[0].generator_id == "ZZZ-RETAIL-45"


def test_create_booking_auto_assign_returns_emergency_suggestions_when_retailer_out(conn):
    seed_minimal(
        conn,
        generators=[
            Generator(
                generator_id="AAA-EMERGENCY-45",
                capacity_kva=45,
                inventory_type=GEN_INVENTORY_EMERGENCY,
            ),
            Generator(
                generator_id="ZZZ-RETAIL-45",
                capacity_kva=45,
                inventory_type=GEN_INVENTORY_RETAILER,
            ),
        ],
        vendors=[
            Vendor(vendor_id="VEN001", vendor_name="Vendor One"),
            Vendor(vendor_id="VEN002", vendor_name="Vendor Two"),
        ],
    )

    service = BookingService(conn)
    first_booking_id = service.create_booking(
        "VEN001",
        [{"generator_id": "ZZZ-RETAIL-45", "date": "2026-01-15"}]
    )

    booking_repo = BookingRepository(conn)
    first_items = booking_repo.get_items(first_booking_id)

    assert first_items[0].generator_id == "ZZZ-RETAIL-45"

    with pytest.raises(RetailerOutOfStockError) as exc_info:
        service.create_booking(
            "VEN002",
            [{"capacity_kva": 45, "date": "2026-01-15"}]
        )

    payload = exc_info.value.payload
    assert payload["error_code"] == "retailer_out_of_stock"
    assert payload["affected_dates"] == [
        {
            "item_index": 0,
            "date": "2026-01-15",
            "capacity_kva": 45,
            "suggested_generator_id": "AAA-EMERGENCY-45",
            "emergency_options": [
                {
                    "generator_id": "AAA-EMERGENCY-45",
                    "capacity_kva": 45,
                    "identification": "",
                    "type": "",
                    "notes": "",
                    "inventory_type": GEN_INVENTORY_EMERGENCY,
                }
            ],
        }
    ]


def test_create_booking_auto_assign_blocks_when_retailer_and_emergency_unavailable(conn):
    seed_minimal(
        conn,
        generators=[
            Generator(
                generator_id="RET-45-01",
                capacity_kva=45,
                inventory_type=GEN_INVENTORY_RETAILER,
            ),
            Generator(
                generator_id="EMG-45-01",
                capacity_kva=45,
                inventory_type=GEN_INVENTORY_EMERGENCY,
            ),
        ],
        vendors=[
            Vendor(vendor_id="VEN001", vendor_name="Vendor One"),
            Vendor(vendor_id="VEN002", vendor_name="Vendor Two"),
            Vendor(vendor_id="VEN003", vendor_name="Vendor Three"),
        ],
    )

    service = BookingService(conn)
    service.create_booking(
        "VEN001",
        [{"generator_id": "RET-45-01", "date": "2026-01-15"}]
    )
    service.create_booking(
        "VEN002",
        [{"generator_id": "EMG-45-01", "date": "2026-01-15"}]
    )

    with pytest.raises(RuntimeError, match="No retailer or emergency 45 kVA generator is available"):
        service.create_booking(
            "VEN003",
            [{"capacity_kva": 45, "date": "2026-01-15"}]
        )
