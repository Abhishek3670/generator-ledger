"""
Utility functions and helpers for the Generator Booking Ledger system.
"""

import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, Iterator

from config import DATETIME_FORMAT, DEFAULT_TIME


def now_ts() -> int:
    """Return current UTC timestamp in seconds."""
    return int(datetime.utcnow().timestamp())


class DateTimeParser:
    """Utility class for parsing various datetime formats."""
    
    logger = logging.getLogger("DateTimeParser")

    @staticmethod
    def parse_day_month_to_full(date_str: str, default_time: str = DEFAULT_TIME) -> Optional[str]:
        """Parse a day-month or full date string into standardized datetime format."""
        date_str = date_str.strip()
        if not date_str:
            return None
        
        # Normalize separators
        date_str = date_str.replace("/", "-")
        parts = date_str.split()
        date_part = parts[0]
        time_part = parts[1] if len(parts) > 1 else default_time
        
        now = datetime.now()
        date_chunks = date_part.split("-")
        
        try:
            if len(date_chunks) == 2:
                # Format: DD-MM (assume current year)
                day, month = date_chunks
                year = now.year
            elif len(date_chunks) == 3:
                # Format: YYYY-MM-DD or DD-MM-YYYY
                a, b, c = date_chunks
                if len(a) == 4:
                    year, month, day = a, b, c
                else:
                    day, month, year = a, b, c
            else:
                raise ValueError(f"Unsupported date format: {date_str}")
            
            # Construct and validate datetime string
            dt_str = f"{int(year):04d}-{int(month):02d}-{int(day):02d} {time_part}"
            
            datetime.strptime(dt_str, DATETIME_FORMAT)
            return dt_str

        except ValueError as e:
            DateTimeParser.logger.warning(f"Date parsing failed | context={{'input': '{date_str}', 'error': '{e}'}}")
            raise ValueError(f"Invalid date/time values in '{date_str}': {e}")
    
    @staticmethod
    def parse(date_str: Optional[str], default_time: str = DEFAULT_TIME) -> Optional[str]:
        """Try to parse full datetime first; if that fails, try day-month formats."""
        if not date_str or not date_str.strip():
            return None
        
        date_str = date_str.strip()
        
        try:
            dt = datetime.strptime(date_str, DATETIME_FORMAT)
            return dt.strftime(DATETIME_FORMAT)
        except ValueError:
            return DateTimeParser.parse_day_month_to_full(date_str, default_time=default_time)
    
    @staticmethod
    def validate_period(start_dt: str, end_dt: str) -> None:
        """Validate that a time period is valid."""
        start = datetime.strptime(start_dt, DATETIME_FORMAT)
        end = datetime.strptime(end_dt, DATETIME_FORMAT)
        
        if start >= end:
            DateTimeParser.logger.warning(f"Invalid period detected | context={{'start': '{start_dt}', 'end': '{end_dt}'}}")
            raise ValueError("Start time must be before end time")
    
    @staticmethod
    def periods_overlap(start1: str, end1: str, start2: str, end2: str) -> bool:
        """Check if two time periods overlap."""
        s1 = datetime.strptime(start1, DATETIME_FORMAT)
        e1 = datetime.strptime(end1, DATETIME_FORMAT)
        s2 = datetime.strptime(start2, DATETIME_FORMAT)
        e2 = datetime.strptime(end2, DATETIME_FORMAT)
        
        return s1 < e2 and e1 > s2


@contextmanager
def transaction(conn) -> Iterator[None]:
    """Run a block inside a DB transaction (commit or rollback)."""
    try:
        conn.execute("BEGIN")
        yield
        conn.commit()
    except Exception:
        conn.rollback()
        raise
