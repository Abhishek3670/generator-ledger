import asyncio
import importlib
import sys
from datetime import datetime, date, timedelta

import pytest
from starlette.requests import Request

from core.database import DatabaseManager
from core.models import Booking, BookingItem, BookingHistory, Generator, Vendor
from core.repositories import (
    BookingHistoryRepository,
    BookingRepository,
    GeneratorRepository,
    VendorRepository,
)


@pytest.fixture
def app_module_and_conn(tmp_path, monkeypatch):
    db_path = tmp_path / "history_gitlens_view.db"
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


def test_history_event_category_mapping(app_module_and_conn):
    web_app_module, _conn = app_module_and_conn

    assert web_app_module._history_event_category("booking_created") == "added"
    assert web_app_module._history_event_category("booking_items_updated") == "updated"
    assert web_app_module._history_event_category("booking_cancelled") == "cancelled"
    assert web_app_module._history_event_category("booking_deleted") == "removed"
    assert web_app_module._history_event_category("unknown_event_type") == "other"


def test_history_short_hash_stability(app_module_and_conn):
    web_app_module, _conn = app_module_and_conn

    assert web_app_module._history_short_hash(431, "2026-02-25 10:30", "booking_created", "BKG-1") == "00001af"

    fallback_a = web_app_module._history_short_hash(None, "2026-02-25 10:30", "booking_created", "BKG-1")
    fallback_b = web_app_module._history_short_hash(None, "2026-02-25 10:30", "booking_created", "BKG-1")
    assert len(fallback_a) == 7
    assert fallback_a == fallback_b


def test_history_grouping_by_date_labels(app_module_and_conn):
    web_app_module, _conn = app_module_and_conn

    today_dt = datetime.combine(date.today(), datetime.min.time())
    yesterday_dt = datetime.combine(date.today() - timedelta(days=1), datetime.min.time())
    older_dt = datetime(2026, 2, 20, 9, 0, 0)

    entries = [
        {"summary": "Today event", "_event_dt": today_dt},
        {"summary": "Yesterday event", "_event_dt": yesterday_dt},
        {"summary": "Older event", "_event_dt": older_dt},
        {"summary": "Unknown event", "_event_dt": None},
    ]

    groups = web_app_module._history_group_entries(entries)
    labels = [group["date_label"] for group in groups]

    assert "Today" in labels
    assert "Yesterday" in labels
    assert "20 Feb 2026" in labels
    assert "Unknown Date" in labels
    assert "_event_dt" not in groups[0]["entries"][0]


def test_history_extract_items_parsing_and_fallback(app_module_and_conn):
    web_app_module, _conn = app_module_and_conn

    parsed = web_app_module._history_extract_items("items=GEN-1|2026-02-10;GEN-2|2026-02-11")
    assert parsed == [
        {"generator_id": "GEN-1", "date": "2026-02-10"},
        {"generator_id": "GEN-2", "date": "2026-02-11"},
    ]

    fallback = web_app_module._history_extract_items("generators=GEN-3,GEN-4")
    assert fallback == [
        {"generator_id": "GEN-3", "date": ""},
        {"generator_id": "GEN-4", "date": ""},
    ]

    assert web_app_module._history_extract_items("") == []


def test_history_page_includes_view_link_when_booking_id_exists(app_module_and_conn):
    web_app_module, conn = app_module_and_conn

    vendor_repo = VendorRepository(conn)
    generator_repo = GeneratorRepository(conn)
    booking_repo = BookingRepository(conn)
    history_repo = BookingHistoryRepository(conn)

    vendor_repo.save(Vendor(vendor_id="VEN001", vendor_name="Vendor One"))
    generator_repo.save(Generator(generator_id="GEN-45-01", capacity_kva=45))

    booking_repo.save(
        Booking(
            booking_id="BKG-20260225-00001",
            vendor_id="VEN001",
            created_at="2026-02-25 09:30",
            status="Confirmed",
        )
    )
    booking_repo.save_item(
        BookingItem(
            booking_id="BKG-20260225-00001",
            generator_id="GEN-45-01",
            start_dt="2026-02-25 00:00",
            end_dt="2026-02-25 23:59",
            item_status="Confirmed",
            remarks="",
        )
    )

    history_repo.save(
        BookingHistory(
            event_time="2026-02-25 10:10",
            event_type="booking_created",
            booking_id="BKG-20260225-00001",
            vendor_id="VEN001",
            user="owner",
            summary="Created booking",
            details="items=GEN-45-01|2026-02-25",
        )
    )
    history_repo.save(
        BookingHistory(
            event_time="2026-02-25 10:20",
            event_type="booking_items_updated",
            booking_id=None,
            vendor_id="VEN001",
            user="owner",
            summary="Vendor-level update",
            details="generators=GEN-45-01",
        )
    )

    request = Request({"type": "http", "method": "GET", "path": "/history", "headers": []})
    response = asyncio.run(web_app_module.history_page(request, conn=conn))

    groups = response.context["history_groups"]
    entries = [entry for group in groups for entry in group["entries"]]

    with_booking = next(entry for entry in entries if entry["booking_id"] == "BKG-20260225-00001")
    without_booking = next(entry for entry in entries if not entry["booking_id"])

    assert with_booking["view_link"] == "/booking/BKG-20260225-00001"
    assert without_booking["view_link"] is None
