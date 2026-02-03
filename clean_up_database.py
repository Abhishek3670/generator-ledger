import re
from datetime import datetime
import sqlite3
def _parse_day_month_to_full(s: str, default_time: str, current_year: int) -> str:
    """
    Convert strings like:
      - '25-11'
      - '25/11'
      - '25-11 09:30'
      - '25-11-2025'
      - '2025-11-25'
    into 'YYYY-MM-DD HH:MM' using given default_time and current_year when needed.
    """
    if s is None:
        raise ValueError("Empty date")
    s = str(s).strip()
    if not s:
        raise ValueError("Empty date")

    # Normalise separators
    s = s.replace("/", "-")
    parts = s.split()
    date_part = parts[0]
    time_part = parts[1] if len(parts) > 1 else None

    chunks = date_part.split("-")

    # Cases:
    #  DD-MM           -> use current_year
    #  DD-MM-YYYY      -> use given year
    #  YYYY-MM-DD      -> normal ISO order
    if len(chunks) == 2:
        day, month = chunks
        year = current_year
    elif len(chunks) == 3:
        a, b, c = chunks
        if len(a) == 4:
            # YYYY-MM-DD
            year, month, day = a, b, c
        else:
            # DD-MM-YYYY
            day, month, year = a, b, c
    else:
        raise ValueError(f"Unsupported date format: {s}")

    if time_part is None:
        time_part = default_time

    dt_str = f"{int(year):04d}-{int(month):02d}-{int(day):02d} {time_part}"
    # Validate
    datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
    return dt_str


def _normalize_single_value(raw_val: str, default_time: str, current_year: int) -> str:
    """
    Normalize a single start_dt / end_dt value to 'YYYY-MM-DD HH:MM'.
    - If already in that format, returns as-is.
    - If 'YYYY-MM-DD' (no time), adds default_time.
    - Else tries day-month style via _parse_day_month_to_full().
    """
    if raw_val is None:
        return None
    val = str(raw_val).strip()
    if not val:
        return None

    # Already full format?
    try:
        datetime.strptime(val, "%Y-%m-%d %H:%M")
        return val
    except ValueError:
        pass

    # Pure date 'YYYY-MM-DD'?
    if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", val):
        dt_str = f"{val} {default_time}"
        datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        return dt_str

    # Try day-month / day-month-year variations
    return _parse_day_month_to_full(val, default_time=default_time, current_year=current_year)


def cleanup_booking_item_dates(conn, start_default="08:00", end_default="23:00"):
    """
    Clean up existing rows in booking_items table:
      - start_dt, end_dt -> normalized to 'YYYY-MM-DD HH:MM'
      - Uses current calendar year when date has no year (DD-MM / DD/MM)
      - start_dt uses start_default time (default '08:00')
      - end_dt uses end_default time   (default '23:00')

    Usage:
        import sqlite3
        conn = sqlite3.connect("ledger.db")
        cleanup_booking_item_dates(conn)
        conn.close()
    """
    cur = conn.cursor()
    now_year = datetime.now().year

    # Check table exists
    cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='booking_items'
    """)
    if not cur.fetchone():
        print("Table 'booking_items' not found. Nothing to clean.")
        return

    cur.execute("SELECT id, start_dt, end_dt FROM booking_items")
    rows = cur.fetchall()

    updated_count = 0
    print("Starting cleanup of booking_items datetime fields...")

    for row_id, start_dt, end_dt in rows:
        new_start = start_dt
        new_end = end_dt

        try:
            new_start = _normalize_single_value(start_dt, start_default, now_year)
        except Exception as e:
            print(f"[WARN] Could not normalize start_dt (id={row_id}, value={start_dt!r}): {e}")

        try:
            new_end = _normalize_single_value(end_dt, end_default, now_year)
        except Exception as e:
            print(f"[WARN] Could not normalize end_dt (id={row_id}, value={end_dt!r}): {e}")

        # Only update if changed
        if new_start != start_dt or new_end != end_dt:
            cur.execute(
                "UPDATE booking_items SET start_dt = ?, end_dt = ? WHERE id = ?",
                (new_start, new_end, row_id),
            )
            updated_count += 1
            print(f"[UPDATED] id={row_id}: "
                  f"{start_dt!r} -> {new_start!r}, {end_dt!r} -> {new_end!r}")

    conn.commit()
    print(f"Cleanup complete. Rows updated: {updated_count}")


cleanup_booking_item_dates(sqlite3.connect("ledger.db"))