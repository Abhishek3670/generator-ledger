"""
Database connection and schema management.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional

from alembic import command
from alembic.config import Config

from config import (
    DATABASE_URL,
    DB_CONNECT_TIMEOUT,
    DB_POOL_MAX_SIZE,
    DB_POOL_MIN_SIZE,
    PGSSLMODE,
)
from .observability import DBConnection, DatabasePool, connect_db


class DatabaseManager:
    """Manages PostgreSQL connections and schema initialization."""

    def __init__(self, database_url: Optional[str] = None):
        self.database_url = self._resolve_database_url(database_url)
        self.conn: Optional[DBConnection] = None
        self.logger = logging.getLogger(self.__class__.__name__)

    def _resolve_database_url(self, database_url: Optional[str]) -> str:
        # SAFETY: Production code NEVER reads TEST_DATABASE_URL.
        # See SAFETY.md rule S3.
        candidate = (database_url or "").strip() or DATABASE_URL or ""
        if candidate and "://" not in candidate:
            fallback = os.getenv("DATABASE_URL", "").strip()
            if fallback:
                self.logger = logging.getLogger(self.__class__.__name__)
                self.logger.warning(
                    "Legacy SQLite path ignored in favor of PostgreSQL URL | context=%s",
                    {"legacy_value": candidate},
                )
                return fallback
            raise RuntimeError(
                "SQLite database paths are no longer supported. "
                "Set DATABASE_URL or the DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME variables."
            )
        if not candidate:
            raise RuntimeError(
                "PostgreSQL configuration is required. "
                "Set DATABASE_URL or the DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME variables."
            )
        return candidate

    def connect(self) -> DBConnection:
        """Create and return a database connection."""
        self.conn = connect_db(
            self.database_url,
            connect_timeout=DB_CONNECT_TIMEOUT,
            sslmode=PGSSLMODE or None,
        )
        self.logger.info(
            "Database connected | context=%s",
            {"database_url": self.redacted_url},
        )
        return self.conn

    def create_pool(self) -> DatabasePool:
        """Create a pooled connection manager."""
        pool = DatabasePool(
            self.database_url,
            min_size=DB_POOL_MIN_SIZE,
            max_size=DB_POOL_MAX_SIZE,
            connect_timeout=DB_CONNECT_TIMEOUT,
            sslmode=PGSSLMODE or None,
        )
        return pool

    def close(self) -> None:
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
            self.logger.info("Database connection closed")

    def init_schema(self) -> None:
        """Apply Alembic migrations to the target database."""
        self.logger.info("Initializing schema (applying migrations if needed)...")
        
        # 1. Quick check: Is migration even needed?
        current_revision = None
        try:
            self.logger.info("Checking current migration version...")
            conn = self.connect()
            cur = conn.cursor()
            cur.execute("SELECT version_num FROM alembic_version")
            row = cur.fetchone()
            if row:
                current_revision = row[0]
            conn.close()
            self.logger.info(f"Current database version: {current_revision}")
        except Exception as e:
            self.logger.info(f"Could not check version (maybe table doesn't exist): {e}")

        # Note: In this project, the latest version is '20260323_0001'
        if current_revision == '20260323_0001':
            self.logger.info("Database is already at latest version. Skipping Alembic upgrade.")
            return

        # 2. Run Alembic upgrade if needed or if version check failed
        cfg = Config(str(self._alembic_ini_path()))
        cfg.attributes["database_url"] = self.database_url
        cfg.attributes["configure_logger"] = False
        
        self.logger.info("Starting alembic upgrade head...")
        started = time.perf_counter()
        try:
            command.upgrade(cfg, "head")
            duration = time.perf_counter() - started
            self.logger.info(f"Alembic upgrade completed in {duration:.2f}s.")
        except Exception as e:
            self.logger.error(f"Alembic upgrade failed: {e}")
            raise

        self.logger.info(
            "Database migrations applied | context=%s",
            {"database_url": self.redacted_url},
        )

    @property
    def redacted_url(self) -> str:
        return redact_database_url(self.database_url)

    @staticmethod
    def _alembic_ini_path() -> Path:
        return Path(__file__).resolve().parent.parent / "alembic.ini"


def redact_database_url(database_url: str) -> str:
    """Return a DSN safe for logs and API payloads."""
    if not database_url:
        return ""
    if "@" not in database_url:
        return database_url

    scheme_and_auth, host_part = database_url.split("@", 1)
    if ":" not in scheme_and_auth:
        return f"{scheme_and_auth}@{host_part}"

    scheme, _auth = scheme_and_auth.rsplit(":", 1)
    return f"{scheme}:***@{host_part}"
