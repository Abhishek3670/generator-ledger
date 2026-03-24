from __future__ import annotations

import os

import pytest

from core.database import DatabaseManager


TRUNCATE_TABLES = (
    "user_permission_overrides",
    "booking_items",
    "bookings",
    "booking_history",
    "sessions",
    "revoked_tokens",
    "users",
    "generators",
    "rental_vendors",
    "vendors",
    "booking_id_seq",
    "vendor_id_seq",
    "rental_vendor_id_seq",
)


def _truncate_all(conn) -> None:
    conn.execute(
        "TRUNCATE TABLE " + ", ".join(TRUNCATE_TABLES) + " RESTART IDENTITY CASCADE"
    )
    conn.commit()


@pytest.fixture(scope="session")
def test_database_url() -> str:
    database_url = os.getenv("TEST_DATABASE_URL", "").strip() or os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is required to run the PostgreSQL-backed test suite.")
    return database_url


@pytest.fixture(scope="session", autouse=True)
def initialize_test_schema(test_database_url: str) -> None:
    os.environ.setdefault("DATABASE_URL", test_database_url)
    os.environ.setdefault("SESSION_SECRET", "test-session-secret")
    os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
    os.environ.setdefault("OWNER_USERNAME", "owner")
    os.environ.setdefault("OWNER_PASSWORD", "Qwerty@345")
    os.environ.setdefault("LOAD_SEED_DATA", "false")
    os.environ.setdefault("DEBUG", "true")

    db = DatabaseManager(test_database_url)
    db.init_schema()
    db.close()


@pytest.fixture(autouse=True)
def configured_test_env(test_database_url: str, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("OWNER_USERNAME", "owner")
    monkeypatch.setenv("OWNER_PASSWORD", "Qwerty@345")
    monkeypatch.setenv("LOAD_SEED_DATA", "false")
    monkeypatch.setenv("DEBUG", "true")

    db = DatabaseManager(test_database_url)
    conn = db.connect()
    try:
        _truncate_all(conn)
        yield
        _truncate_all(conn)
    finally:
        db.close()
