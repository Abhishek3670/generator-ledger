"""
Observability helpers for request/database instrumentation.
"""

from __future__ import annotations

import contextvars
import logging
import re
import time
from typing import Any, Callable, Optional, Sequence, Tuple

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import tuple_row
from psycopg_pool import ConnectionPool

from config import DB_SLOW_QUERY_MS

logger = logging.getLogger("observability.db")

DatabaseError = psycopg.Error

_QMARK_PATTERN = re.compile(r"\?")

_request_label_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_label",
    default="background",
)
_request_query_count_var: contextvars.ContextVar[int] = contextvars.ContextVar(
    "request_query_count",
    default=0,
)
_request_query_ms_var: contextvars.ContextVar[float] = contextvars.ContextVar(
    "request_query_ms",
    default=0.0,
)


def begin_request_observation(
    label: str,
) -> Tuple[contextvars.Token, contextvars.Token, contextvars.Token]:
    """
    Start per-request DB metrics context.
    """
    label_token = _request_label_var.set(label)
    count_token = _request_query_count_var.set(0)
    ms_token = _request_query_ms_var.set(0.0)
    return label_token, count_token, ms_token


def end_request_observation(
    tokens: Tuple[contextvars.Token, contextvars.Token, contextvars.Token]
) -> None:
    """
    Restore previous request observation context.
    """
    label_token, count_token, ms_token = tokens
    _request_label_var.reset(label_token)
    _request_query_count_var.reset(count_token)
    _request_query_ms_var.reset(ms_token)


def get_request_db_metrics() -> Tuple[int, float]:
    """
    Return current request DB metrics as (query_count, total_query_ms).
    """
    return _request_query_count_var.get(), _request_query_ms_var.get()


def _translate_sql(sql: str) -> str:
    stripped = (sql or "").strip()
    if stripped.upper() == "BEGIN IMMEDIATE":
        return "BEGIN"
    return _QMARK_PATTERN.sub("%s", sql)


def _record_query(sql: str, elapsed_ms: float) -> None:
    count = _request_query_count_var.get() + 1
    _request_query_count_var.set(count)
    _request_query_ms_var.set(_request_query_ms_var.get() + elapsed_ms)

    if elapsed_ms < DB_SLOW_QUERY_MS:
        return

    condensed_sql = " ".join((sql or "").strip().split())
    if len(condensed_sql) > 240:
        condensed_sql = f"{condensed_sql[:237]}..."

    logger.warning(
        "Slow SQL query | context=%s",
        {
            "request": _request_label_var.get(),
            "duration_ms": round(elapsed_ms, 2),
            "threshold_ms": DB_SLOW_QUERY_MS,
            "sql": condensed_sql,
        },
    )


class ObservedCursor:
    """
    Cursor wrapper that records query counts and duration while translating
    SQLite-style qmark placeholders to psycopg's pyformat placeholders.
    """

    def __init__(self, raw_cursor: Any):
        self._raw_cursor = raw_cursor

    def _run_and_track(
        self,
        sql: str,
        runner: Callable[..., Any],
        *args: Any,
    ) -> Any:
        translated_sql = _translate_sql(sql)
        started = time.perf_counter()
        try:
            return runner(translated_sql, *args)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            _record_query(translated_sql, elapsed_ms)

    def execute(self, sql: str, parameters: Sequence[Any] | None = None) -> "ObservedCursor":
        self._run_and_track(sql, self._raw_cursor.execute, tuple(parameters or ()))
        return self

    def executemany(
        self,
        sql: str,
        seq_of_parameters: Sequence[Sequence[Any]],
    ) -> "ObservedCursor":
        self._run_and_track(sql, self._raw_cursor.executemany, seq_of_parameters)
        return self

    def fetchone(self) -> Any:
        return self._raw_cursor.fetchone()

    def fetchall(self) -> list[Any]:
        return list(self._raw_cursor.fetchall())

    def close(self) -> None:
        self._raw_cursor.close()

    def __iter__(self):
        return iter(self._raw_cursor)

    def __enter__(self) -> "ObservedCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @property
    def description(self) -> Any:
        return self._raw_cursor.description

    @property
    def rowcount(self) -> int:
        return self._raw_cursor.rowcount


class DBConnection:
    """
    Thin psycopg connection wrapper matching the subset of sqlite3 usage in the app.
    """

    def __init__(
        self,
        raw_connection: Any,
        *,
        close_callback: Optional[Callable[[Any], None]] = None,
    ):
        self._raw_connection = raw_connection
        self._close_callback = close_callback
        self._closed = False

    def cursor(self) -> ObservedCursor:
        return ObservedCursor(self._raw_connection.cursor())

    def execute(
        self,
        sql: str,
        parameters: Sequence[Any] | None = None,
    ) -> ObservedCursor:
        cur = self.cursor()
        cur.execute(sql, parameters)
        return cur

    def commit(self) -> None:
        self._raw_connection.commit()

    def rollback(self) -> None:
        self._raw_connection.rollback()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._close_callback:
            self._close_callback(self._raw_connection)
        else:
            self._raw_connection.close()

    @property
    def in_transaction(self) -> bool:
        return self._raw_connection.info.transaction_status != TransactionStatus.IDLE

    @property
    def raw_connection(self) -> Any:
        return self._raw_connection


def connect_db(
    database_url: str,
    *,
    connect_timeout: int = 10,
    sslmode: Optional[str] = None,
) -> DBConnection:
    """
    Create an instrumented PostgreSQL connection.
    """
    connect_kwargs: dict[str, Any] = {
        "row_factory": tuple_row,
        "connect_timeout": connect_timeout,
    }
    if sslmode:
        connect_kwargs["sslmode"] = sslmode

    raw_connection = psycopg.connect(database_url, **connect_kwargs)
    return DBConnection(raw_connection)


class DatabasePool:
    """
    PostgreSQL connection pool returning instrumented DBConnection wrappers.
    """

    def __init__(
        self,
        database_url: str,
        *,
        min_size: int = 1,
        max_size: int = 10,
        connect_timeout: int = 10,
        sslmode: Optional[str] = None,
    ):
        pool_kwargs: dict[str, Any] = {
            "row_factory": tuple_row,
            "connect_timeout": connect_timeout,
        }
        if sslmode:
            pool_kwargs["sslmode"] = sslmode

        self._pool = ConnectionPool(
            conninfo=database_url,
            min_size=min_size,
            max_size=max_size,
            kwargs=pool_kwargs,
            open=False,
        )

    def open(self) -> None:
        self._pool.open()
        self._pool.wait()

    def close(self) -> None:
        self._pool.close()

    def get_connection(self) -> DBConnection:
        raw_connection = self._pool.getconn()
        return DBConnection(
            raw_connection,
            close_callback=self._pool.putconn,
        )

