"""
Repository layer for data access.
"""

import sqlite3
import logging
from typing import Optional, List

from .models import Generator, Vendor, Booking, BookingItem, BookingHistory, GeneratorStatus


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
    
    def generate_vendor_id(self) -> str:
        """Generate the next vendor ID in sequence (VEN001, VEN002, etc.)."""
        cur = self.conn.cursor()
        
        # Get all vendor IDs and extract the numeric part
        cur.execute("SELECT vendor_id FROM vendors ORDER BY vendor_id")
        existing_ids = [row[0] for row in cur.fetchall()]
        
        # Extract numbers from vendor IDs like "VEN001", "VEN008", etc.
        max_num = 0
        for vid in existing_ids:
            if vid.startswith('VEN'):
                try:
                    num = int(vid[3:])
                    max_num = max(max_num, num)
                except ValueError:
                    pass
        
        # Generate next vendor ID
        next_num = max_num + 1
        vendor_id = f"VEN{next_num:03d}"
        return vendor_id


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
    
    def save(self, booking: Booking, commit: bool = True) -> None:
        try:
            cur = self.conn.cursor()
            cur.execute(
                """INSERT OR REPLACE INTO bookings
                (booking_id, vendor_id, created_at, status)
                VALUES (?, ?, ?, ?)""",
                (booking.booking_id, booking.vendor_id, booking.created_at, booking.status)
            )
            if commit:
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
    
    def save_item(self, item: BookingItem, commit: bool = True) -> None:
        try:
            cur = self.conn.cursor()
            cur.execute(
                """INSERT INTO booking_items
                (booking_id, generator_id, start_dt, end_dt, item_status, remarks)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (item.booking_id, item.generator_id, item.start_dt, item.end_dt, item.item_status, item.remarks)
            )
            if commit:
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
    
    def generate_booking_id(self) -> str:
        """Generate the next booking ID in sequence."""
        from datetime import datetime
        cur = self.conn.cursor()
        
        # Get count of bookings for today
        today = datetime.now().strftime("%Y%m%d")
        cur.execute(
            "SELECT COUNT(*) FROM bookings WHERE booking_id LIKE ?",
            (f"BKG-{today}-%",)
        )
        count = cur.fetchone()[0] + 1
        
        # Generate ID as BKG-YYYYMMDD-00001
        booking_id = f"BKG-{today}-{count:05d}"
        return booking_id


class BookingHistoryRepository:
    """Repository for booking history events."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.logger = logging.getLogger(self.__class__.__name__)

    def save(self, event: BookingHistory, commit: bool = True) -> None:
        try:
            cur = self.conn.cursor()
            cur.execute(
                """INSERT INTO booking_history
                (event_time, event_type, booking_id, vendor_id, summary, details)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    event.event_time,
                    event.event_type,
                    event.booking_id,
                    event.vendor_id,
                    event.summary,
                    event.details,
                )
            )
            if commit:
                self.conn.commit()
        except sqlite3.Error:
            self.logger.error(
                "Failed to save booking history event",
                exc_info=True
            )
            raise

    def get_all(self, limit: int = 200) -> List[BookingHistory]:
        cur = self.conn.cursor()
        if limit:
            cur.execute(
                "SELECT * FROM booking_history ORDER BY event_time DESC, id DESC LIMIT ?",
                (limit,)
            )
        else:
            cur.execute("SELECT * FROM booking_history ORDER BY event_time DESC, id DESC")

        events = []
        for row in cur.fetchall():
            events.append(BookingHistory(
                id=row[0],
                event_time=row[1],
                event_type=row[2],
                booking_id=row[3],
                vendor_id=row[4],
                summary=row[5] or "",
                details=row[6] or ""
            ))
        return events
