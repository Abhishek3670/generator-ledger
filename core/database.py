"""
Database connection and schema management.
"""

from __future__ import annotations

import logging
import os
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
        candidate = (database_url or "").strip() or DATABASE_URL or os.getenv("TEST_DATABASE_URL", "").strip()
        if candidate and "://" not in candidate:
            fallback = (
                os.getenv("DATABASE_URL", "").strip()
                or os.getenv("TEST_DATABASE_URL", "").strip()
            )
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
        cfg = Config(str(self._alembic_ini_path()))
        cfg.attributes["database_url"] = self.database_url
        cfg.attributes["configure_logger"] = False
        command.upgrade(cfg, "head")
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
