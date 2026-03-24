"""
One-time SQLite to PostgreSQL migration utility.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
from pathlib import Path
from typing import Iterable

from core.database import DatabaseManager, redact_database_url
from core.utils import transaction

logger = logging.getLogger("sqlite_to_postgres")

TABLE_COLUMN_ORDER: dict[str, tuple[str, ...]] = {
    "vendors": ("vendor_id", "vendor_name", "vendor_place", "phone"),
    "rental_vendors": ("rental_vendor_id", "vendor_name", "vendor_place", "phone"),
    "generators": (
        "generator_id",
        "capacity_kva",
        "identification",
        "type",
        "status",
        "notes",
        "inventory_type",
        "rental_vendor_id",
    ),
    "users": ("id", "username", "password_hash", "role", "is_active", "created_at", "last_login"),
    "bookings": ("booking_id", "vendor_id", "created_at", "status"),
    "booking_items": ("id", "booking_id", "generator_id", "start_dt", "end_dt", "item_status", "remarks"),
    "booking_history": (
        "id",
        "event_time",
        "event_type",
        "booking_id",
        "vendor_id",
        "user",
        "summary",
        "details",
    ),
    "user_permission_overrides": ("user_id", "capability_key", "is_allowed"),
    "sessions": (
        "session_id",
        "user_id",
        "csrf_token",
        "created_at",
        "expires_at",
        "last_seen",
        "ip_address",
        "user_agent",
    ),
    "revoked_tokens": ("jti", "expires_at"),
    "vendor_id_seq": ("id", "next_val"),
    "rental_vendor_id_seq": ("id", "next_val"),
    "booking_id_seq": ("booking_date", "next_val"),
}

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate Generator Booking Ledger data from SQLite to PostgreSQL."
    )
    parser.add_argument(
        "--sqlite-path",
        required=True,
        help="Path to the source SQLite database file.",
    )
    parser.add_argument(
        "--database-url",
        required=True,
        help="Target PostgreSQL connection string.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify row counts after import.",
    )
    return parser.parse_args()


def open_sqlite_readonly(sqlite_path: str) -> sqlite3.Connection:
    db_path = Path(sqlite_path).expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def fetch_rows(sqlite_conn: sqlite3.Connection, table_name: str, columns: Iterable[str]) -> list[tuple]:
    query = f"SELECT {', '.join(columns)} FROM {table_name}"
    cur = sqlite_conn.cursor()
    cur.execute(query)
    return cur.fetchall()


def truncate_target(conn) -> None:
    conn.execute(
        "TRUNCATE TABLE " + ", ".join(TRUNCATE_TABLES) + " RESTART IDENTITY CASCADE"
    )


def load_table(sqlite_conn: sqlite3.Connection, pg_conn, table_name: str, columns: tuple[str, ...]) -> int:
    rows = fetch_rows(sqlite_conn, table_name, columns)
    if not rows:
        return 0

    placeholders = ", ".join("?" for _ in columns)
    quoted_columns = ", ".join(f'"{column}"' for column in columns)
    pg_conn.cursor().executemany(
        f'INSERT INTO "{table_name}" ({quoted_columns}) VALUES ({placeholders})',
        rows,
    )
    return len(rows)


def sync_identity_sequence(conn, table_name: str, column_name: str) -> None:
    conn.execute(
        f"""
        SELECT setval(
            pg_get_serial_sequence('{table_name}', '{column_name}'),
            COALESCE((SELECT MAX({column_name}) FROM {table_name}), 1),
            COALESCE((SELECT MAX({column_name}) FROM {table_name}), 0) > 0
        )
        """
    )


def verify_counts(sqlite_conn: sqlite3.Connection, pg_conn) -> None:
    for table_name, columns in TABLE_COLUMN_ORDER.items():
        sqlite_count = len(fetch_rows(sqlite_conn, table_name, columns))
        pg_count = pg_conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        if int(pg_count) != sqlite_count:
            raise RuntimeError(
                f"Count mismatch for {table_name}: sqlite={sqlite_count}, postgres={pg_count}"
            )


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    logger.info("Starting SQLite to PostgreSQL migration")
    logger.info("Target database: %s", redact_database_url(args.database_url))

    sqlite_conn = open_sqlite_readonly(args.sqlite_path)
    db_manager = DatabaseManager(args.database_url)
    db_manager.init_schema()
    pg_conn = db_manager.connect()

    try:
        with transaction(pg_conn):
            truncate_target(pg_conn)

            inserted_counts = {}
            for table_name, columns in TABLE_COLUMN_ORDER.items():
                inserted_counts[table_name] = load_table(sqlite_conn, pg_conn, table_name, columns)

            sync_identity_sequence(pg_conn, "booking_items", "id")
            sync_identity_sequence(pg_conn, "booking_history", "id")
            sync_identity_sequence(pg_conn, "users", "id")

        if args.verify:
            verify_counts(sqlite_conn, pg_conn)

        logger.info("Migration completed successfully")
        for table_name, count in inserted_counts.items():
            logger.info("Copied %s row(s) into %s", count, table_name)
    finally:
        sqlite_conn.close()
        db_manager.close()


if __name__ == "__main__":
    main()
