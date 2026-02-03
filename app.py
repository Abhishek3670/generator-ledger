"""
Generator Booking Ledger System - Object-Oriented Design

A database-backed system for managing generator rental bookings with
availability checking and conflict resolution.
"""

import sqlite3
import pandas as pd
import os
import logging
import sys
from typing import Optional, List, Dict, Tuple, Any
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
from logging.handlers import RotatingFileHandler

# --- Logging Configuration ---
def setup_logging():
    """Configures the application-wide logger to write to file and console."""
    
    # Define the log format
    log_formatter = logging.Formatter("[%(levelname)s] %(name)s.%(funcName)s - %(message)s")
    
    # --- Handler 1: File Handler ---
    # Writes to 'application.log'. 
    # Rotates when file reaches 5MB. Keeps 3 backup files.
    file_handler = RotatingFileHandler(
        "application.log", 
        mode='a',
        maxBytes=5*1024*1024, 
        backupCount=3,
        encoding='utf-8'
    )
    file_handler.setFormatter(log_formatter)
    
    # --- Handler 2: Console Handler ---
    # Prints to terminal so you can still see what's happening
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)

    # Apply Configuration
    logging.basicConfig(
        level=logging.INFO,
        handlers=[
            file_handler,
            console_handler 
        ]
    )

# Initialize logging immediately
setup_logging()

# Configuration constants
DB_PATH = "ledger.db"
GENERATOR_DB_PATH = "Data/Generator_Dataset.xlsx"
GENERATOR_DB = "Generator_Dataset.csv"
VENDOR_DB_PATH = "Data/Vendor_Dataset.xlsx"
VENDOR_DB = "Vendor_Dataset.csv"
BOOKINGS_PATH = "bookings.csv"
BOOKING_ITEMS_PATH = "booking_items.csv"
DEFAULT_TIME = "08:00"
DATETIME_FORMAT = "%Y-%m-%d %H:%M"


class BookingStatus(Enum):
    """Booking status enumeration."""
    CONFIRMED = "Confirmed"
    CANCELLED = "Cancelled"
    PENDING = "Pending"


class GeneratorStatus(Enum):
    """Generator status enumeration."""
    ACTIVE = "Active"
    INACTIVE = "Inactive"
    MAINTENANCE = "Maintenance"


@dataclass
class Generator:
    """Generator data model."""
    generator_id: str
    capacity_kva: int
    identification: str = ""
    type: str = ""
    status: str = GeneratorStatus.ACTIVE.value
    notes: str = ""


@dataclass
class Vendor:
    """Vendor data model."""
    vendor_id: str
    vendor_name: str
    vendor_place: str = ""
    phone: str = ""


@dataclass
class BookingItem:
    """Booking item data model."""
    booking_id: str
    generator_id: str
    start_dt: str
    end_dt: str
    item_status: str = BookingStatus.CONFIRMED.value
    remarks: str = ""
    id: Optional[int] = None


@dataclass
class Booking:
    """Booking data model."""
    booking_id: str
    vendor_id: str
    created_at: str
    status: str = BookingStatus.CONFIRMED.value


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
            # We treat parsing errors as warnings here as they are often user input errors handled higher up
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


class DatabaseManager:
    """Manages database connections and schema initialization."""
    
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def connect(self) -> sqlite3.Connection:
        """Create and return a database connection."""
        try:
            self.conn = sqlite3.connect(
                self.db_path,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
            )
            self.logger.info(f"Database connected | context={{'db_path': '{self.db_path}'}}")
            return self.conn
        except sqlite3.Error as e:
            self.logger.error(f"Failed to connect to database | context={{'db_path': '{self.db_path}'}}", exc_info=True)
            raise

    def close(self) -> None:
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
            self.logger.info("Database connection closed")
    
    def init_schema(self) -> None:
        """Initialize database schema with all required tables."""
        if not self.conn:
            self.logger.error("Attempted schema init without connection")
            raise RuntimeError("Database not connected")
        
        try:
            cur = self.conn.cursor()
            cur.executescript("""
            CREATE TABLE IF NOT EXISTS generators (
                generator_id TEXT PRIMARY KEY,
                capacity_kva INTEGER NOT NULL,
                identification TEXT,
                type TEXT,
                status TEXT DEFAULT 'Active',
                notes TEXT
            );
            
            CREATE TABLE IF NOT EXISTS vendors (
                vendor_id TEXT PRIMARY KEY,
                vendor_name TEXT NOT NULL,
                vendor_place TEXT,
                phone TEXT
            );
            
            CREATE TABLE IF NOT EXISTS bookings (
                booking_id TEXT PRIMARY KEY,
                vendor_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT DEFAULT 'Confirmed',
                FOREIGN KEY(vendor_id) REFERENCES vendors(vendor_id)
            );

            CREATE TABLE IF NOT EXISTS booking_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_id TEXT NOT NULL,
                generator_id TEXT NOT NULL,
                start_dt TEXT NOT NULL,
                end_dt TEXT NOT NULL,
                item_status TEXT DEFAULT 'Confirmed',
                remarks TEXT,
                FOREIGN KEY(booking_id) REFERENCES bookings(booking_id),
                FOREIGN KEY(generator_id) REFERENCES generators(generator_id)
            );

            CREATE INDEX IF NOT EXISTS idx_booking_items_generator 
                ON booking_items(generator_id, item_status);

            CREATE INDEX IF NOT EXISTS idx_booking_items_booking 
                ON booking_items(booking_id);
            """)
            self.conn.commit()
            self.logger.info("Database schema initialized successfully")
        except sqlite3.Error as e:
            self.logger.error("Schema initialization failed", exc_info=True)
            raise
    
    def __enter__(self):
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class GeneratorRepository:
    """Repository for generator data access."""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def get_by_id(self, generator_id: str) -> Optional[Generator]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM generators WHERE generator_id = ?", (generator_id,))
        row = cur.fetchone()
        
        if not row:
            return None
        
        return Generator(
            generator_id=row[0],
            capacity_kva=row[1],
            identification=row[2] or "",
            type=row[3] or "",
            status=row[4] or GeneratorStatus.ACTIVE.value,
            notes=row[5] or ""
        )
    
    def find_by_capacity(self, capacity_kva: int, status: str = GeneratorStatus.ACTIVE.value) -> List[Generator]:
        cur = self.conn.cursor()
        cur.execute(
            """SELECT * FROM generators 
               WHERE capacity_kva = ? AND status = ?
               ORDER BY generator_id""",
            (capacity_kva, status)
        )
        
        generators = []
        for row in cur.fetchall():
            generators.append(Generator(
                generator_id=row[0],
                capacity_kva=row[1],
                identification=row[2] or "",
                type=row[3] or "",
                status=row[4] or GeneratorStatus.ACTIVE.value,
                notes=row[5] or ""
            ))
        return generators
    
    def save(self, generator: Generator) -> None:
        try:
            cur = self.conn.cursor()
            cur.execute(
                """INSERT OR REPLACE INTO generators
                (generator_id, capacity_kva, identification, type, status, notes)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (generator.generator_id, generator.capacity_kva, generator.identification,
                 generator.type, generator.status, generator.notes)
            )
            self.conn.commit()
        except sqlite3.Error:
            self.logger.error(f"Failed to save generator | context={{'id': '{generator.generator_id}'}}", exc_info=True)
            raise
    
    def get_all(self) -> List[Generator]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM generators ORDER BY generator_id")
        generators = []
        for row in cur.fetchall():
            generators.append(Generator(
                generator_id=row[0],
                capacity_kva=row[1],
                identification=row[2] or "",
                type=row[3] or "",
                status=row[4] or GeneratorStatus.ACTIVE.value,
                notes=row[5] or ""
            ))
        return generators


class VendorRepository:
    """Repository for vendor data access."""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def get_by_id(self, vendor_id: str) -> Optional[Vendor]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM vendors WHERE vendor_id = ?", (vendor_id,))
        row = cur.fetchone()
        
        if not row:
            return None
        
        return Vendor(
            vendor_id=row[0],
            vendor_name=row[1],
            vendor_place=row[2] or "",
            phone=row[3] or ""
        )
    
    def save(self, vendor: Vendor) -> None:
        try:
            cur = self.conn.cursor()
            cur.execute(
                """INSERT OR REPLACE INTO vendors
                (vendor_id, vendor_name, vendor_place, phone)
                VALUES (?, ?, ?, ?)""",
                (vendor.vendor_id, vendor.vendor_name, vendor.vendor_place, vendor.phone)
            )
            self.conn.commit()
        except sqlite3.Error:
            self.logger.error(f"Failed to save vendor | context={{'id': '{vendor.vendor_id}'}}", exc_info=True)
            raise
    
    def get_all(self) -> List[Vendor]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM vendors ORDER BY vendor_id")
        vendors = []
        for row in cur.fetchall():
            vendors.append(Vendor(
                vendor_id=row[0],
                vendor_name=row[1],
                vendor_place=row[2] or "",
                phone=row[3] or ""
            ))
        return vendors


class BookingRepository:
    """Repository for booking data access."""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def get_by_id(self, booking_id: str) -> Optional[Booking]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM bookings WHERE booking_id = ?", (booking_id,))
        row = cur.fetchone()
        
        if not row:
            return None
        
        return Booking(
            booking_id=row[0],
            vendor_id=row[1],
            created_at=row[2],
            status=row[3]
        )
    
    def save(self, booking: Booking) -> None:
        try:
            cur = self.conn.cursor()
            cur.execute(
                """INSERT OR REPLACE INTO bookings
                (booking_id, vendor_id, created_at, status)
                VALUES (?, ?, ?, ?)""",
                (booking.booking_id, booking.vendor_id, booking.created_at, booking.status)
            )
            self.conn.commit()
            self.logger.info(f"Booking saved | context={{'booking_id': '{booking.booking_id}'}}")
        except sqlite3.Error:
            self.logger.error(f"Failed to save booking | context={{'booking_id': '{booking.booking_id}'}}", exc_info=True)
            raise
    
    def get_items(self, booking_id: str) -> List[BookingItem]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM booking_items WHERE booking_id = ?", (booking_id,))
        items = []
        for row in cur.fetchall():
            items.append(BookingItem(
                id=row[0],
                booking_id=row[1],
                generator_id=row[2],
                start_dt=row[3],
                end_dt=row[4],
                item_status=row[5],
                remarks=row[6] or ""
            ))
        return items
    
    def save_item(self, item: BookingItem) -> None:
        try:
            cur = self.conn.cursor()
            cur.execute(
                """INSERT INTO booking_items
                (booking_id, generator_id, start_dt, end_dt, item_status, remarks)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (item.booking_id, item.generator_id, item.start_dt, item.end_dt, item.item_status, item.remarks)
            )
            self.conn.commit()
        except sqlite3.Error:
            self.logger.error(f"Failed to save booking item | context={{'booking_id': '{item.booking_id}', 'gen_id': '{item.generator_id}'}}", exc_info=True)
            raise
    
    def get_all(self) -> List[Booking]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM bookings ORDER BY created_at DESC")
        bookings = []
        for row in cur.fetchall():
            bookings.append(Booking(
                booking_id=row[0],
                vendor_id=row[1],
                created_at=row[2],
                status=row[3]
            ))
        return bookings


class AvailabilityChecker:
    """Checks generator availability and finds conflicts."""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def is_available(
        self,
        generator_id: str,
        start_dt: str,
        end_dt: str,
        exclude_booking_id: Optional[str] = None
    ) -> Tuple[bool, Optional[Dict[str, str]]]:
        """Check if a generator is available for a given time period."""
        DateTimeParser.validate_period(start_dt, end_dt)
        
        cur = self.conn.cursor()
        
        if exclude_booking_id:
            query = """
            SELECT bi.booking_id, bi.start_dt, bi.end_dt
            FROM booking_items bi
            JOIN bookings b ON bi.booking_id = b.booking_id
            WHERE bi.generator_id = ?
              AND bi.booking_id != ?
              AND bi.item_status = 'Confirmed' 
              AND b.status = 'Confirmed'
            """
            cur.execute(query, (generator_id, exclude_booking_id))
        else:
            query = """
            SELECT bi.booking_id, bi.start_dt, bi.end_dt
            FROM booking_items bi
            JOIN bookings b ON bi.booking_id = b.booking_id
            WHERE bi.generator_id = ?
              AND bi.item_status = 'Confirmed' 
              AND b.status = 'Confirmed'
            """
            cur.execute(query, (generator_id,))
        
        rows = cur.fetchall()
        
        for row in rows:
            if DateTimeParser.periods_overlap(start_dt, end_dt, row[1], row[2]):
                self.logger.debug(f"Conflict detected | context={{'generator_id': '{generator_id}', 'conflicting_booking': '{row[0]}'}}" )
                return False, {
                    "conflict_with": row[0],
                    "existing_start": row[1],
                    "existing_end": row[2]
                }
        
        return True, None
    
    def find_available(
        self,
        capacity_kva: int,
        start_dt: str,
        end_dt: str,
        needed: int = 1
    ) -> List[str]:
        """Find available generators of specified capacity."""
        gen_repo = GeneratorRepository(self.conn)
        candidates = gen_repo.find_by_capacity(capacity_kva, GeneratorStatus.ACTIVE.value)
        
        available = []
        for gen in candidates:
            is_avail, _ = self.is_available(gen.generator_id, start_dt, end_dt)
            if is_avail:
                available.append(gen.generator_id)
                if len(available) >= needed:
                    break
        
        if not available:
            self.logger.info(f"No available generators found | context={{'capacity': {capacity_kva}, 'start': '{start_dt}'}}")
            
        return available


class BookingService:
    """Business logic for booking operations."""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.booking_repo = BookingRepository(conn)
        self.vendor_repo = VendorRepository(conn)
        self.generator_repo = GeneratorRepository(conn)
        self.availability = AvailabilityChecker(conn)
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def create_booking(
        self,
        booking_id: str,
        vendor_id: str,
        items: List[Dict[str, Any]]
    ) -> None:
        """Create a new booking with items."""
        self.logger.info(f"Starting booking creation | context={{'booking_id': '{booking_id}', 'item_count': {len(items)}}}")
        
        # Validate vendor exists
        vendor = self.vendor_repo.get_by_id(vendor_id)
        if not vendor:
            self.logger.warning(f"Booking creation failed: Invalid vendor | context={{'vendor_id': '{vendor_id}'}}")
            raise ValueError(f"Vendor '{vendor_id}' does not exist")
        
        # Check booking doesn't exist
        if self.booking_repo.get_by_id(booking_id):
            self.logger.warning(f"Booking creation failed: Duplicate ID | context={{'booking_id': '{booking_id}'}}")
            raise ValueError(f"Booking '{booking_id}' already exists")
        
        # Create booking
        booking = Booking(
            booking_id=booking_id,
            vendor_id=vendor_id,
            created_at=datetime.now().strftime(DATETIME_FORMAT),
            status=BookingStatus.CONFIRMED.value
        )
        self.booking_repo.save(booking)
        
        # Process items
        for idx, item_spec in enumerate(items):
            generator_id = item_spec.get("generator_id")
            start_dt = item_spec.get("start_dt")
            end_dt = item_spec.get("end_dt")
            remarks = item_spec.get("remarks", "")
            
            if not start_dt or not end_dt:
                self.logger.error(f"Item validation failed | context={{'index': {idx}, 'reason': 'missing dates'}}")
                raise ValueError(f"Item {idx + 1}: start_dt and end_dt required")
            
            # Auto-assign or validate specific generator
            if generator_id is None:
                capacity_kva = item_spec.get("capacity_kva")
                if capacity_kva is None:
                    raise ValueError(f"Item {idx + 1}: Provide generator_id or capacity_kva")
                
                available = self.availability.find_available(
                    int(capacity_kva), start_dt, end_dt, needed=1
                )
                if not available:
                    self.logger.warning(f"Auto-assign failed | context={{'capacity': {capacity_kva}, 'start': '{start_dt}'}}")
                    raise RuntimeError(
                        f"Item {idx + 1}: No available {capacity_kva} kVA generator "
                        f"for {start_dt} - {end_dt}"
                    )
                generator_id = available[0]
            else:
                # Validate generator exists
                if not self.generator_repo.get_by_id(generator_id):
                    self.logger.warning(f"Item validation failed | context={{'generator_id': '{generator_id}', 'reason': 'not found'}}")
                    raise ValueError(f"Item {idx + 1}: Generator '{generator_id}' not found")
                
                is_avail, conflict = self.availability.is_available(
                    generator_id, start_dt, end_dt
                )
                if not is_avail:
                    self.logger.warning(f"Availability conflict | context={{'generator_id': '{generator_id}', 'conflict': {conflict}}}")
                    raise RuntimeError(
                        f"Item {idx + 1}: Generator {generator_id} not available. "
                        f"Conflict: {conflict}"
                    )
            
            # Save item
            booking_item = BookingItem(
                booking_id=booking_id,
                generator_id=generator_id,
                start_dt=start_dt,
                end_dt=end_dt,
                item_status=BookingStatus.CONFIRMED.value,
                remarks=remarks
            )
            self.booking_repo.save_item(booking_item)
            
        self.logger.info(f"Booking created successfully | context={{'booking_id': '{booking_id}'}}")
    
    def add_generator(
        self,
        booking_id: str,
        generator_id: Optional[str] = None,
        capacity_kva: Optional[int] = None,
        start_dt: Optional[str] = None,
        end_dt: Optional[str] = None,
        remarks: str = "Added"
    ) -> Tuple[bool, str]:
        """Add a generator to an existing booking."""
        if not start_dt or not end_dt:
            return False, "start_dt and end_dt are required"
        
        # Validate booking
        booking = self.booking_repo.get_by_id(booking_id)
        if not booking:
            self.logger.warning(f"Add generator failed | context={{'booking_id': '{booking_id}', 'reason': 'not found'}}")
            return False, f"Booking '{booking_id}' not found"
        
        if booking.status == BookingStatus.CANCELLED.value:
            self.logger.warning(f"Add generator failed | context={{'booking_id': '{booking_id}', 'reason': 'cancelled booking'}}")
            return False, f"Cannot add to cancelled booking"
        
        # Auto-assign or validate
        if generator_id is None:
            if capacity_kva is None:
                return False, "Provide generator_id or capacity_kva"
            
            available = self.availability.find_available(
                int(capacity_kva), start_dt, end_dt, needed=1
            )
            if not available:
                return False, f"No available {capacity_kva} kVA generator"
            generator_id = available[0]
        else:
            if not self.generator_repo.get_by_id(generator_id):
                return False, f"Generator '{generator_id}' not found"
            
            is_avail, conflict = self.availability.is_available(
                generator_id, start_dt, end_dt
            )
            if not is_avail:
                return False, f"Generator not available: {conflict}"
        
        # Save item
        item = BookingItem(
            booking_id=booking_id,
            generator_id=generator_id,
            start_dt=start_dt,
            end_dt=end_dt,
            item_status=BookingStatus.CONFIRMED.value,
            remarks=remarks
        )
        self.booking_repo.save_item(item)
        self.logger.info(f"Generator added to booking | context={{'booking_id': '{booking_id}', 'generator_id': '{generator_id}'}}")
        
        return True, generator_id
    
    def modify_times(
        self,
        booking_id: str,
        new_start_dt: str,
        new_end_dt: str
    ) -> Tuple[bool, str]:
        """Modify booking times for all items."""
        self.logger.info(f"Modifying booking times | context={{'booking_id': '{booking_id}'}}")
        booking = self.booking_repo.get_by_id(booking_id)
        if not booking:
            return False, f"Booking '{booking_id}' not found"
        
        if booking.status == BookingStatus.CANCELLED.value:
            return False, "Cannot modify cancelled booking"
        
        try:
            DateTimeParser.validate_period(new_start_dt, new_end_dt)
        except ValueError as e:
            return False, str(e)
        
        # Get all items
        items = self.booking_repo.get_items(booking_id)
        confirmed_items = [
            item for item in items 
            if item.item_status == BookingStatus.CONFIRMED.value
        ]
        
        # Check availability for all generators
        for item in confirmed_items:
            is_avail, conflict = self.availability.is_available(
                item.generator_id,
                new_start_dt,
                new_end_dt,
                exclude_booking_id=booking_id
            )
            if not is_avail:
                msg = f"Generator {item.generator_id} conflicts with booking {conflict['conflict_with']}"
                self.logger.warning(f"Modify times failed | context={{'booking_id': '{booking_id}', 'conflict': '{msg}'}}")
                return False, msg
        
        # Update all items
        cur = self.conn.cursor()
        cur.execute(
            """UPDATE booking_items 
               SET start_dt = ?, end_dt = ?
               WHERE booking_id = ? AND item_status = 'Confirmed'""",
            (new_start_dt, new_end_dt, booking_id)
        )
        self.conn.commit()
        self.logger.info(f"Booking times modified successfully | context={{'booking_id': '{booking_id}'}}")
        
        return True, "Updated successfully"
    
    def cancel_booking(
        self,
        booking_id: str,
        reason: str = "Cancelled"
    ) -> Tuple[bool, str]:
        """Cancel a booking."""
        self.logger.info(f"Cancelling booking | context={{'booking_id': '{booking_id}', 'reason': '{reason}'}}")
        booking = self.booking_repo.get_by_id(booking_id)
        if not booking:
            self.logger.warning(f"Cancellation failed | context={{'booking_id': '{booking_id}', 'reason': 'not found'}}")
            return False, f"Booking '{booking_id}' not found"
        
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE bookings SET status = 'Cancelled' WHERE booking_id = ?",
            (booking_id,)
        )
        cur.execute(
            """UPDATE booking_items 
               SET item_status = 'Cancelled', remarks = ? 
               WHERE booking_id = ?""",
            (reason, booking_id)
        )
        self.conn.commit()
        self.logger.info(f"Booking cancelled | context={{'booking_id': '{booking_id}'}}")
        
        return True, "Cancelled successfully"

def archive_all_bookings(
    conn: sqlite3.Connection,
    archive_dir: str = "archives"
) -> Tuple[bool, str]:
    """
    Archive all current bookings to CSV files with current month suffix,
    then clear all bookings and booking items from the database.
    """
    try:
        os.makedirs(archive_dir, exist_ok=True)
        current_month = datetime.now().strftime("%Y_%m")
        
        bookings_archive = os.path.join(archive_dir, f"bookings_{current_month}.csv")
        items_archive = os.path.join(archive_dir, f"booking_items_{current_month}.csv")
        
        # Add timestamp if files exist
        if os.path.exists(bookings_archive) or os.path.exists(items_archive):
            timestamp = datetime.now().strftime("%Y_%m_%d_%H%M%S")
            bookings_archive = os.path.join(archive_dir, f"bookings_{current_month}_{timestamp}.csv")
            items_archive = os.path.join(archive_dir, f"booking_items_{current_month}_{timestamp}.csv")
        
        # Export to CSV
        bookings_df = pd.read_sql_query("SELECT * FROM bookings", conn)
        items_df = pd.read_sql_query("SELECT * FROM booking_items", conn)
        
        if bookings_df.empty and items_df.empty:
            return False, "No bookings to archive"
        
        bookings_df.to_csv(bookings_archive, index=False)
        items_df.to_csv(items_archive, index=False)
        
        # Clear tables
        cur = conn.cursor()
        cur.execute("DELETE FROM booking_items")
        cur.execute("DELETE FROM bookings")
        conn.commit()
        
        message = (
            f"✓ Archived {len(bookings_df)} bookings and {len(items_df)} items\n"
            f"  Bookings: {bookings_archive}\n"
            f"  Items: {items_archive}\n"
            f"  Database cleared for new bookings"
        )
        return True, message
        
    except Exception as e:
        return False, f"Archive failed: {str(e)}"
def create_vendor(
    conn: sqlite3.Connection,
    vendor_id: str,
    vendor_name: str,
    vendor_place: str = "",
    phone: str = ""
) -> Tuple[bool, str]:
    """
    Create a new vendor, ensuring no conflict with existing vendors.
    """
    cur = conn.cursor()
    
    # Check if vendor ID already exists
    cur.execute("SELECT vendor_id FROM vendors WHERE vendor_id = ?", (vendor_id,))
    if cur.fetchone():
        return False, f"Vendor ID '{vendor_id}' already exists"
    
    # Check if vendor name already exists (case-insensitive)
    cur.execute(
        "SELECT vendor_id FROM vendors WHERE LOWER(vendor_name) = LOWER(?)",
        (vendor_name,)
    )
    duplicate = cur.fetchone()
    if duplicate:
        return False, f"Vendor name '{vendor_name}' already exists with ID '{duplicate[0]}'"
    
    # Create the new vendor
    cur.execute(
        """INSERT INTO vendors (vendor_id, vendor_name, vendor_place, phone)
        VALUES (?, ?, ?, ?)""",
        (vendor_id, vendor_name, vendor_place, phone)
    )
    conn.commit()
    
    return True, f"✓ Created vendor '{vendor_id}' - {vendor_name}"
class DataLoader:
    """Loads sample data from Excel files."""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.generator_repo = GeneratorRepository(conn)
        self.vendor_repo = VendorRepository(conn)
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def load_from_excel(self) -> None:
        """Load sample data from Excel files."""
        # Load generators
        self.logger.info(f"Attempting to load generators | context={{'path': '{GENERATOR_DB_PATH}'}}")
        if os.path.exists(GENERATOR_DB_PATH):
            try:
                gdf = pd.read_excel(GENERATOR_DB_PATH)
                self.logger.info(f"Read generator file | context={{'shape': {gdf.shape}}}")
                
                gdf.to_csv(GENERATOR_DB, index=False)
                
                loaded_count = 0
                for idx, row in gdf.iterrows():
                    try:
                        generator = Generator(
                            generator_id=str(row["Generator_ID"]),
                            capacity_kva=int(row["Capacity_KVA"]),
                            identification=str(row.get("Identification", "")) or "",
                            type=str(row.get("Type", "")) or "",
                            status=str(row.get("Status", GeneratorStatus.ACTIVE.value)) or GeneratorStatus.ACTIVE.value,
                            notes=str(row.get("Notes", "")) or ""
                        )
                        self.generator_repo.save(generator)
                        loaded_count += 1
                    except Exception as row_error:
                        self.logger.error(f"Failed to process generator row | context={{'index': {idx}, 'error': '{row_error}'}}", exc_info=True)
                
                self.logger.info(f"Generator load complete | context={{'loaded': {loaded_count}, 'total': {len(gdf)}}}")
            except Exception as e:
                self.logger.error("Critical error loading generators", exc_info=True)
        else:
            self.logger.warning(f"Generator dataset not found | context={{'path': '{GENERATOR_DB_PATH}', 'cwd': '{os.getcwd()}'}}")

        # Load vendors
        self.logger.info(f"Attempting to load vendors | context={{'path': '{VENDOR_DB_PATH}'}}")
        if os.path.exists(VENDOR_DB_PATH):
            try:
                vdf = pd.read_excel(VENDOR_DB_PATH)
                self.logger.info(f"Read vendor file | context={{'shape': {vdf.shape}}}")
                
                vdf.to_csv(VENDOR_DB, index=False)
                
                loaded_count = 0
                for idx, row in vdf.iterrows():
                    try:
                        vendor = Vendor(
                            vendor_id=str(row["Vendor_ID"]),
                            vendor_name=str(row.get("Vendor_Name", "")) or "",
                            vendor_place=str(row.get("Vendor_Place", "")) or "",
                            phone=str(row.get("Phone", "")) or ""
                        )
                        self.vendor_repo.save(vendor)
                        loaded_count += 1
                    except Exception as row_error:
                        self.logger.error(f"Failed to process vendor row | context={{'index': {idx}, 'error': '{row_error}'}}", exc_info=True)
                
                self.logger.info(f"Vendor load complete | context={{'loaded': {loaded_count}, 'total': {len(vdf)}}}")
            except Exception as e:
                self.logger.error("Critical error loading vendors", exc_info=True)
        else:
            self.logger.warning(f"Vendor dataset not found | context={{'path': '{VENDOR_DB_PATH}'}}")


class ExportService:
    """Handles data export operations."""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def export_to_csv(self, out_dir: str = "exported_data") -> Tuple[str, str]:
        """Export all tables to CSV."""
        try:
            os.makedirs(out_dir, exist_ok=True)
            
            pd.read_sql_query("SELECT * FROM bookings", self.conn).to_csv(
                os.path.join(out_dir, BOOKINGS_PATH), index=False
            )
            pd.read_sql_query("SELECT * FROM booking_items", self.conn).to_csv(
                os.path.join(out_dir, BOOKING_ITEMS_PATH), index=False
            )
            pd.read_sql_query("SELECT * FROM generators", self.conn).to_csv(
                os.path.join(out_dir, GENERATOR_DB), index=False
            )
            pd.read_sql_query("SELECT * FROM vendors", self.conn).to_csv(
                os.path.join(out_dir, VENDOR_DB), index=False
            )
            
            self.logger.info(f"Data exported successfully | context={{'dir': '{out_dir}'}}")
            
            return (
                os.path.join(out_dir, BOOKINGS_PATH),
                os.path.join(out_dir, BOOKING_ITEMS_PATH)
            )
        except Exception:
            self.logger.error("Export failed", exc_info=True)
            raise


class CLI:
    """Command-line interface for the booking system."""
    
    def __init__(self, db_path: str = DB_PATH):
        self.db_manager = DatabaseManager(db_path)
        self.conn: Optional[sqlite3.Connection] = None
        self.booking_service: Optional[BookingService] = None
        self.export_service: Optional[ExportService] = None
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def initialize(self) -> None:
        """Initialize database and services."""
        self.conn = self.db_manager.connect()
        self.db_manager.init_schema()
        
        # Load sample data
        loader = DataLoader(self.conn)
        loader.load_from_excel()
        
        # Initialize services
        self.booking_service = BookingService(self.conn)
        self.export_service = ExportService(self.conn)
        
        self.logger.info("System initialized successfully")
        print(f"Generator Booking Ledger initialized. Database: {self.db_manager.db_path}")
    
    def print_table(self, table: str) -> None:
        """Print a database table."""
        try:
            df = pd.read_sql_query(f"SELECT * FROM {table}", self.conn)
            print(f"\n{table.upper()}:")
            print(df.to_string(index=False))
        except Exception as e:
            self.logger.error(f"Error displaying table | context={{'table': '{table}'}}", exc_info=True)
            print(f"Error displaying table '{table}': {e}")
    
    def run(self) -> None:
        """Run the main CLI loop."""
        try:
            self.initialize()
            
            while True:
                print("\n" + "=" * 50)
                print("Generator Booking Ledger - CLI")
                print("=" * 50)
                print("1. List generators")
                print("2. List vendors")
                print("3. List bookings and items")
                print("4. Create booking")
                print("5. Add generator to booking")
                print("6. Modify booking times")
                print("7. Cancel booking")
                print("8. Export CSVs")
                print("9. Archive all bookings (clear for new month)")  # NEW
                print("10. Add new vendor")  
                print("11. Exit")
                print("=" * 50)
                
                choice = input("Choose an option (1-11): ").strip()
                
                try:
                    if choice == '1':
                        self.print_table('generators')
                    elif choice == '2':
                        self.print_table('vendors')
                    elif choice == '3':
                        self.print_table('bookings')
                        self.print_table('booking_items')
                    elif choice == '4':
                        self.create_booking_interactive()
                    elif choice == '5':
                        self.add_generator_interactive()
                    elif choice == '6':
                        self.modify_times_interactive()
                    elif choice == '7':
                        self.cancel_booking_interactive()
                    elif choice == '8':
                        bpath, ipath = self.export_service.export_to_csv()
                        print(f'✓ Exported to:')
                        print(f'  - {bpath}')
                        print(f'  - {ipath}')
                    elif choice == '9':
                        print("\n⚠️  WARNING: This will archive ALL current bookings and clear the database!")
                        print("This is typically done at the end of each month to start fresh.")
                        
                        # Show current booking count
                        try:
                            bookings_df = pd.read_sql_query("SELECT COUNT(*) as count FROM bookings", self.conn)
                            items_df = pd.read_sql_query("SELECT COUNT(*) as count FROM booking_items", self.conn)
                            
                            booking_count = bookings_df['count'].iloc[0]
                            item_count = items_df['count'].iloc[0]
                            
                            print(f"Current database has {booking_count} bookings and {item_count} items.")
                            
                            if booking_count == 0 and item_count == 0:
                                print("No bookings to archive.")
                                continue
                        except Exception as e:
                            print(f"Error checking database: {e}")
                            continue
                        
                        confirm = input("\nType 'YES' to confirm archival and clear database: ").strip()
                        
                        if confirm != 'YES':
                            print("Archive cancelled.")
                            continue
                        
                        archive_dir = input("Archive directory (press Enter for 'archives'): ").strip()
                        if not archive_dir:
                            archive_dir = "archives"
                        
                        success, msg = archive_all_bookings(self.conn, archive_dir)
                        
                        if success:
                            print(f'\n{msg}')
                        else:
                            print(f'\n✗ Failed: {msg}')
                    elif choice == '10':
                        print("\n--- Add New Vendor ---")
                        
                        vendor_id = input('Vendor ID (e.g., V010): ').strip()
                        if not vendor_id:
                            print("✗ Vendor ID cannot be empty")
                            continue
                        
                        vendor_name = input('Vendor Name: ').strip()
                        if not vendor_name:
                            print("✗ Vendor name cannot be empty")
                            continue
                        
                        vendor_place = input('Vendor Place/Location (optional): ').strip()
                        phone = input('Phone Number (optional): ').strip()
                        
                        success, msg = create_vendor(
                            self.conn,
                            vendor_id=vendor_id,
                            vendor_name=vendor_name,
                            vendor_place=vendor_place,
                            phone=phone
                        )
                        
                        if success:
                            print(f'\n{msg}')
                        else:
                            print(f'\n✗ Failed: {msg}')
                    elif choice == '11':
                        self.logger.info("User requested exit")
                        print('Goodbye!')
                        break
                    else:
                        print('Invalid choice. Please enter 1-11.')
                        
                except Exception as e:
                    self.logger.error("CLI operation failed", exc_info=True)
                    print(f'Error: {e}')
                    
        finally:
            self.db_manager.close()
    
    def create_booking_interactive(self) -> None:
        """Interactive booking creation."""
        booking_id = input('Enter booking ID (e.g., BKG-0001): ').strip()
        if not booking_id:
            print("Booking ID cannot be empty")
            return
        
        vendor_id = input('Enter vendor ID (e.g., V001): ').strip()
        if not vendor_id:
            print("Vendor ID cannot be empty")
            return
        
        n_str = input('How many generators in this booking? ').strip()
        try:
            n = int(n_str)
            if n <= 0:
                print("Number must be positive")
                return
        except ValueError:
            print("Invalid number")
            return
        
        items = []
        for i in range(n):
            print(f"\n--- Item {i+1} ---")
            mode = input('Assign by (1) generator_id or (2) capacity_kva? [1/2]: ').strip()
            
            if mode == '1':
                gid = input('Generator ID (e.g., GEN-45-01): ').strip()
                start_dt = input("Start (YYYY-MM-DD HH:MM): ").strip()
                end_dt = input("End   (YYYY-MM-DD HH:MM): ").strip()
                items.append({
                    'generator_id': gid,
                    'start_dt': start_dt,
                    'end_dt': end_dt,
                    'remarks': ''
                })
            elif mode == '2':
                cap_str = input('Capacity kVA (e.g., 45): ').strip()
                try:
                    cap = int(cap_str)
                except ValueError:
                    print("Invalid capacity. Skipping item.")
                    continue
                start_dt = input("Start (YYYY-MM-DD HH:MM): ").strip()
                end_dt = input("End   (YYYY-MM-DD HH:MM): ").strip()
                items.append({
                    'capacity_kva': cap,
                    'start_dt': start_dt,
                    'end_dt': end_dt,
                    'remarks': ''
                })
            else:
                print("Invalid choice. Skipping item.")
        
        self.booking_service.create_booking(booking_id, vendor_id, items)
        print(f"✓ Created booking {booking_id}")
    
    def add_generator_interactive(self) -> None:
        """Interactive generator addition."""
        booking_id = input('Booking ID: ').strip()
        mode = input('Add by (1) generator_id or (2) capacity_kva? [1/2]: ').strip()
        
        if mode == '1':
            gid = input('Generator ID: ').strip()
            start_dt = input("Start (YYYY-MM-DD HH:MM): ").strip()
            end_dt = input("End   (YYYY-MM-DD HH:MM): ").strip()
            success, info = self.booking_service.add_generator(
                booking_id, generator_id=gid, start_dt=start_dt, end_dt=end_dt
            )
        elif mode == '2':
            cap_str = input('Capacity kVA: ').strip()
            try:
                cap = int(cap_str)
            except ValueError:
                print("Invalid capacity")
                return
            start_dt = input("Start (YYYY-MM-DD HH:MM): ").strip()
            end_dt = input("End   (YYYY-MM-DD HH:MM): ").strip()
            success, info = self.booking_service.add_generator(
                booking_id, capacity_kva=cap, start_dt=start_dt, end_dt=end_dt
            )
        else:
            print("Invalid choice")
            return
        
        if success:
            print(f'✓ Added generator {info}')
        else:
            print(f'✗ Failed: {info}')
    
    def modify_times_interactive(self) -> None:
        """Interactive time modification."""
        booking_id = input('Booking ID: ').strip()
        new_start = input("New Start (YYYY-MM-DD HH:MM): ").strip()
        new_end = input("New End   (YYYY-MM-DD HH:MM): ").strip()
        
        success, msg = self.booking_service.modify_times(booking_id, new_start, new_end)
        
        if success:
            print(f'✓ {msg}')
        else:
            print(f'✗ Failed: {msg}')
    
    def cancel_booking_interactive(self) -> None:
        """Interactive booking cancellation."""
        booking_id = input('Booking ID: ').strip()
        reason = input('Reason (optional): ').strip() or 'Cancelled via CLI'
        
        success, msg = self.booking_service.cancel_booking(booking_id, reason)
        
        if success:
            print(f'✓ {msg}')
        else:
            print(f'✗ Failed: {msg}')


def main() -> None:
    """Main entry point."""
    cli = CLI()
    cli.run()


if __name__ == "__main__":
    main()