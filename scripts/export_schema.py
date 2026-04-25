#!/usr/bin/env python3
"""
Export the current database schema to a human-readable Markdown file.

Usage:
    python scripts/export_schema.py [--output docs/SCHEMA.md] [--database-url URL]

Safety:
    - Performs READ-ONLY operations (information_schema queries only)
    - Logs a warning when connecting to production
    - See SAFETY.md for database access rules

Output:
    docs/SCHEMA.md — versioned schema documentation with tables, columns,
    types, constraints, indexes, and foreign keys.
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known production hosts — log warning when connecting
# ---------------------------------------------------------------------------
PRODUCTION_HOSTS = frozenset({"192.168.29.71"})


def _is_production(url: str) -> bool:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    return any(h in hostname or h in url for h in PRODUCTION_HOSTS)


def _get_database_url(cli_url: str | None) -> str:
    url = cli_url or os.getenv("DATABASE_URL", "").strip()
    if not url:
        print("ERROR: No database URL provided.", file=sys.stderr)
        print("  Use --database-url or set DATABASE_URL environment variable.", file=sys.stderr)
        sys.exit(1)
    return url


def _query_tables(conn) -> list[dict]:
    """Get all user tables from the public schema."""
    rows = conn.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """).fetchall()
    return [{"table_name": r[0]} for r in rows]


def _query_columns(conn, table_name: str) -> list[dict]:
    """Get columns for a given table."""
    rows = conn.execute("""
        SELECT
            column_name,
            data_type,
            character_maximum_length,
            is_nullable,
            column_default
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %s
        ORDER BY ordinal_position
    """, (table_name,)).fetchall()
    result = []
    for r in rows:
        col_type = r[1]
        if r[2]:  # character_maximum_length
            col_type = f"{col_type}({r[2]})"
        result.append({
            "name": r[0],
            "type": col_type,
            "nullable": r[3] == "YES",
            "default": r[4],
        })
    return result


def _query_primary_keys(conn, table_name: str) -> list[str]:
    """Get primary key columns for a table."""
    rows = conn.execute("""
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_schema = 'public'
          AND tc.table_name = %s
        ORDER BY kcu.ordinal_position
    """, (table_name,)).fetchall()
    return [r[0] for r in rows]


def _query_foreign_keys(conn, table_name: str) -> list[dict]:
    """Get foreign key constraints for a table."""
    rows = conn.execute("""
        SELECT
            kcu.column_name,
            ccu.table_name AS foreign_table,
            ccu.column_name AS foreign_column,
            tc.constraint_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = tc.constraint_name
         AND ccu.table_schema = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema = 'public'
          AND tc.table_name = %s
        ORDER BY kcu.column_name
    """, (table_name,)).fetchall()
    return [
        {
            "column": r[0],
            "references_table": r[1],
            "references_column": r[2],
            "constraint_name": r[3],
        }
        for r in rows
    ]


def _query_indexes(conn, table_name: str) -> list[dict]:
    """Get indexes for a table."""
    rows = conn.execute("""
        SELECT
            i.relname AS index_name,
            ix.indisunique AS is_unique,
            array_agg(a.attname ORDER BY array_position(ix.indkey, a.attnum)) AS columns
        FROM pg_index ix
        JOIN pg_class t ON t.oid = ix.indrelid
        JOIN pg_class i ON i.oid = ix.indexrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
        WHERE n.nspname = 'public'
          AND t.relname = %s
          AND NOT ix.indisprimary
        GROUP BY i.relname, ix.indisunique
        ORDER BY i.relname
    """, (table_name,)).fetchall()
    return [
        {
            "name": r[0],
            "unique": r[1],
            "columns": r[2],
        }
        for r in rows
    ]


def _query_row_count(conn, table_name: str) -> int:
    """Get approximate row count (fast, from pg stats)."""
    rows = conn.execute("""
        SELECT reltuples::bigint
        FROM pg_class
        WHERE relname = %s
    """, (table_name,)).fetchall()
    return max(0, rows[0][0]) if rows else 0


def _render_markdown(tables_data: list[dict], db_url: str) -> str:
    """Render the schema as Markdown."""
    parsed = urlparse(db_url)
    db_name = parsed.path.lstrip("/") if parsed.path else "unknown"
    host = parsed.hostname or "unknown"
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        "# Database Schema Documentation",
        "",
        f"> **Generated**: {generated_at}  ",
        f"> **Database**: `{db_name}` @ `{host}`  ",
        f"> **Tables**: {len(tables_data)}",
        "",
        "---",
        "",
        "## Table of Contents",
        "",
    ]

    # TOC
    for td in tables_data:
        tn = td["table_name"]
        lines.append(f"- [{tn}](#{tn}) ({td['row_count']} rows)")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Each table
    for td in tables_data:
        tn = td["table_name"]
        pk_set = set(td["primary_keys"])

        lines.append(f"## {tn}")
        lines.append("")
        lines.append(f"**Rows (approx)**: {td['row_count']}")
        if td["primary_keys"]:
            lines.append(f"**Primary Key**: `{'`, `'.join(td['primary_keys'])}`")
        lines.append("")

        # Columns table
        lines.append("| Column | Type | Nullable | Default | PK |")
        lines.append("|--------|------|----------|---------|:--:|")
        for col in td["columns"]:
            nullable = "✓" if col["nullable"] else "✗"
            default = f"`{col['default']}`" if col["default"] else "—"
            pk = "🔑" if col["name"] in pk_set else ""
            lines.append(
                f"| `{col['name']}` | `{col['type']}` | {nullable} | {default} | {pk} |"
            )
        lines.append("")

        # Foreign keys
        if td["foreign_keys"]:
            lines.append("**Foreign Keys**:")
            lines.append("")
            for fk in td["foreign_keys"]:
                lines.append(
                    f"- `{fk['column']}` → `{fk['references_table']}.{fk['references_column']}` "
                    f"(`{fk['constraint_name']}`)"
                )
            lines.append("")

        # Indexes
        if td["indexes"]:
            lines.append("**Indexes**:")
            lines.append("")
            for idx in td["indexes"]:
                unique_label = " (UNIQUE)" if idx["unique"] else ""
                cols = ", ".join(idx["columns"])
                lines.append(f"- `{idx['name']}`{unique_label}: ({cols})")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Export database schema to Markdown documentation"
    )
    parser.add_argument(
        "--output", "-o",
        default="docs/SCHEMA.md",
        help="Output file path (default: docs/SCHEMA.md)",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Database URL (defaults to DATABASE_URL env var)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    db_url = _get_database_url(args.database_url)

    if _is_production(db_url):
        logger.warning(
            "⚠️  PRODUCTION DATABASE DETECTED — This script performs READ-ONLY "
            "operations, but please verify you intend to connect to production."
        )

    # Import here to avoid import errors when just checking --help
    from core.database import DatabaseManager

    logger.info("Connecting to database...")
    db = DatabaseManager(db_url)
    conn = db.connect()

    try:
        tables = _query_tables(conn)
        logger.info("Found %d tables", len(tables))

        tables_data = []
        for table in tables:
            tn = table["table_name"]
            td = {
                "table_name": tn,
                "columns": _query_columns(conn, tn),
                "primary_keys": _query_primary_keys(conn, tn),
                "foreign_keys": _query_foreign_keys(conn, tn),
                "indexes": _query_indexes(conn, tn),
                "row_count": _query_row_count(conn, tn),
            }
            tables_data.append(td)
            logger.info("  %-35s %3d columns, ~%d rows", tn, len(td["columns"]), td["row_count"])

        markdown = _render_markdown(tables_data, db_url)

        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")

        logger.info("Schema exported to %s (%d bytes)", output_path, len(markdown))

    finally:
        db.close()


if __name__ == "__main__":
    main()
