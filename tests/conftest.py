"""
Test configuration and fixtures for the Generator Ledger test suite.

SAFETY: This file enforces strict database isolation per SAFETY.md.
Tests will REFUSE to run against production databases.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

import pytest

from core.database import DatabaseManager


# ---------------------------------------------------------------------------
# Known production hosts — tests MUST NEVER connect to these.
# Update this set if production infrastructure changes.
# ---------------------------------------------------------------------------
PRODUCTION_HOSTS = frozenset({
    "192.168.29.71",
})


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


# ---------------------------------------------------------------------------
# Production guard — the most important function in this file.
# ---------------------------------------------------------------------------
def _assert_not_production(url: str) -> None:
    """Refuse to run tests against a production database.

    Raises RuntimeError (hard crash, not skip) if the URL matches
    a known production host or if the database name does not contain 'test'.

    See: /home/aatish/app/genset/SAFETY.md — rules S1, S2, S5.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    # Check 1: Block known production hosts
    for prod_host in PRODUCTION_HOSTS:
        if prod_host in hostname or prod_host in url:
            raise RuntimeError(
                f"\n{'='*70}\n"
                f"  REFUSING TO RUN TESTS — PRODUCTION HOST DETECTED\n"
                f"{'='*70}\n"
                f"  TEST_DATABASE_URL contains production host: {prod_host}\n"
                f"  This would destroy production data.\n\n"
                f"  Fix: Set TEST_DATABASE_URL to a dedicated test database.\n"
                f"  Example: postgresql://genset_test_user:pass@localhost:7899/ledger_db_test\n"
                f"  See: SAFETY.md rule S1\n"
                f"{'='*70}\n"
            )

    # Check 2: Database name must contain 'test'
    db_name = parsed.path.lstrip("/") if parsed.path else ""
    if "test" not in db_name.lower():
        raise RuntimeError(
            f"\n{'='*70}\n"
            f"  REFUSING TO RUN TESTS — DATABASE NAME MISSING 'test'\n"
            f"{'='*70}\n"
            f"  Database name: '{db_name}'\n"
            f"  Test database names MUST contain the word 'test'\n"
            f"  to prevent accidental production data loss.\n\n"
            f"  Fix: Use a database named like 'ledger_db_test'.\n"
            f"  See: SAFETY.md rule S1\n"
            f"{'='*70}\n"
        )


def _truncate_all(conn) -> None:
    conn.execute(
        "TRUNCATE TABLE " + ", ".join(TRUNCATE_TABLES) + " RESTART IDENTITY CASCADE"
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Return the test database URL. NEVER falls back to DATABASE_URL.

    If TEST_DATABASE_URL is not set, tests are skipped.
    If it points to production, tests crash with RuntimeError.
    """
    database_url = os.getenv("TEST_DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip(
            "TEST_DATABASE_URL is required to run the test suite. "
            "NEVER use DATABASE_URL or production credentials for testing. "
            "See SAFETY.md rule S1."
        )
    _assert_not_production(database_url)
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
