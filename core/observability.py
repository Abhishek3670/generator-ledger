"""
Observability helpers for request/database instrumentation.
"""

from __future__ import annotations

import contextvars
import logging
import sqlite3
import time
from typing import Optional, Tuple

from config import DB_SLOW_QUERY_MS

logger = logging.getLogger("observability.db")

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


class ObservedCursor(sqlite3.Cursor):
    """
    Cursor that records query counts and duration.
    """

    def _run_and_track(self, sql: str, fn, *args):
        started = time.perf_counter()
        try:
            return fn(*args)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            _record_query(sql, elapsed_ms)

    def execute(self, sql, parameters=()):  # type: ignore[override]
        return self._run_and_track(sql, super().execute, sql, parameters)

    def executemany(self, sql, seq_of_parameters):  # type: ignore[override]
        return self._run_and_track(sql, super().executemany, sql, seq_of_parameters)

    def executescript(self, sql_script):  # type: ignore[override]
        return self._run_and_track(sql_script, super().executescript, sql_script)


class ObservedConnection(sqlite3.Connection):
    """
    Connection that creates observed cursors by default.
    """

    def cursor(self, factory: Optional[type] = None):  # type: ignore[override]
        return super().cursor(factory or ObservedCursor)


def connect_sqlite(
    db_path: str,
    *,
    detect_types: int = sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
    check_same_thread: bool = True,
) -> sqlite3.Connection:
    """
    Create an instrumented SQLite connection.
    """
    return sqlite3.connect(
        db_path,
        detect_types=detect_types,
        check_same_thread=check_same_thread,
        factory=ObservedConnection,
    )
