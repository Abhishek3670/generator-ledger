"""
Repository layer for data access.
"""

import sqlite3
import logging
from typing import Optional, List, Dict, Any

from config import STATUS_CONFIRMED

from .models import (
    Generator,
    Vendor,
    Booking,
    BookingItem,
    BookingHistory,
    GeneratorStatus,
    User,
    UserSession,
)


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

    def count_by_capacity(self, capacity_kva: int) -> int:
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM generators WHERE capacity_kva = ?", (capacity_kva,))
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0


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

    def delete(self, vendor_id: str, commit: bool = True) -> None:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM vendors WHERE vendor_id = ?", (vendor_id,))
        if commit:
            self.conn.commit()

    def find_duplicate_name(
        self,
        vendor_name: str,
        exclude_vendor_id: Optional[str] = None
    ) -> Optional[str]:
        cur = self.conn.cursor()
        if exclude_vendor_id:
            cur.execute(
                """
                SELECT vendor_id
                FROM vendors
                WHERE LOWER(vendor_name) = LOWER(?)
                  AND vendor_id <> ?
                """,
                (vendor_name, exclude_vendor_id),
            )
        else:
            cur.execute(
                """
                SELECT vendor_id
                FROM vendors
                WHERE LOWER(vendor_name) = LOWER(?)
                """,
                (vendor_name,),
            )
        row = cur.fetchone()
        return row[0] if row else None
    
    def generate_vendor_id(self) -> str:
        """Generate the next vendor ID in sequence (VEN001, VEN002, etc.)."""
        cur = self.conn.cursor()
        started_tx = False
        if not self.conn.in_transaction:
            self.conn.execute("BEGIN IMMEDIATE")
            started_tx = True

        try:
            cur.execute(
                "INSERT OR IGNORE INTO vendor_id_seq (id, next_val) VALUES (1, 1)"
            )
            cur.execute("SELECT next_val FROM vendor_id_seq WHERE id = 1")
            row = cur.fetchone()
            seq_val = row[0] if row else 1

            cur.execute(
                "SELECT MAX(CAST(SUBSTR(vendor_id, 4) AS INTEGER)) "
                "FROM vendors WHERE vendor_id GLOB 'VEN[0-9]*'"
            )
            max_row = cur.fetchone()
            max_existing = max_row[0] if max_row and max_row[0] else 0

            next_num = max(seq_val, max_existing + 1)
            cur.execute(
                "UPDATE vendor_id_seq SET next_val = ? WHERE id = 1",
                (next_num + 1,)
            )

            if started_tx:
                self.conn.commit()

            return f"VEN{next_num:03d}"
        except Exception:
            if started_tx:
                self.conn.rollback()
            raise


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

    def get_item_by_id(self, item_id: int) -> Optional[BookingItem]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM booking_items WHERE id = ?", (item_id,))
        row = cur.fetchone()
        if not row:
            return None
        return BookingItem(
            id=row[0],
            booking_id=row[1],
            generator_id=row[2],
            start_dt=row[3],
            end_dt=row[4],
            item_status=row[5],
            remarks=row[6] or "",
        )

    def get_item_ids_for_booking(self, booking_id: str) -> List[int]:
        cur = self.conn.cursor()
        cur.execute("SELECT id FROM booking_items WHERE booking_id = ?", (booking_id,))
        return [int(row[0]) for row in cur.fetchall()]

    def get_items_with_capacity(self, booking_id: str) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT bi.generator_id,
                   bi.start_dt,
                   bi.item_status,
                   bi.remarks,
                   g.capacity_kva
            FROM booking_items bi
            LEFT JOIN generators g ON g.generator_id = bi.generator_id
            WHERE bi.booking_id = ?
            ORDER BY bi.start_dt ASC, bi.id ASC
            """,
            (booking_id,),
        )
        return [
            {
                "generator_id": row[0] or "",
                "start_dt": row[1] or "",
                "item_status": row[2] or "",
                "remarks": row[3] or "",
                "capacity_kva": row[4],
            }
            for row in cur.fetchall()
        ]

    def update_item(
        self,
        item_id: int,
        start_dt: str,
        end_dt: str,
        remarks: str,
        commit: bool = True
    ) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE booking_items SET start_dt = ?, end_dt = ?, remarks = ? WHERE id = ?",
            (start_dt, end_dt, remarks, item_id)
        )
        if commit:
            self.conn.commit()

    def delete_item(self, item_id: int, commit: bool = True) -> None:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM booking_items WHERE id = ?", (item_id,))
        if commit:
            self.conn.commit()

    def delete_with_items(self, booking_id: str, commit: bool = True) -> int:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM booking_items WHERE booking_id = ?", (booking_id,))
        deleted_items = max(int(cur.rowcount), 0)
        cur.execute("DELETE FROM bookings WHERE booking_id = ?", (booking_id,))
        if commit:
            self.conn.commit()
        return deleted_items

    def count_by_vendor(self, vendor_id: str) -> int:
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM bookings WHERE vendor_id = ?", (vendor_id,))
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def get_booked_generator_ids_for_date(
        self,
        selected_date: str,
        confirmed_status: str = STATUS_CONFIRMED
    ) -> List[str]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT bi.generator_id
            FROM booking_items bi
            JOIN bookings b ON bi.booking_id = b.booking_id
            WHERE date(bi.start_dt) = ?
              AND bi.item_status = ?
              AND b.status = ?
            """,
            (selected_date, confirmed_status, confirmed_status),
        )
        return [row[0] for row in cur.fetchall()]

    def list_generator_bookings(
        self,
        generator_id: str,
        date_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        if date_filter:
            cur.execute(
                """
                SELECT b.booking_id,
                       b.vendor_id,
                       v.vendor_name,
                       b.status,
                       bi.start_dt,
                       bi.end_dt,
                       bi.item_status,
                       bi.remarks
                FROM booking_items bi
                JOIN bookings b ON bi.booking_id = b.booking_id
                LEFT JOIN vendors v ON b.vendor_id = v.vendor_id
                WHERE bi.generator_id = ?
                  AND date(bi.start_dt) = ?
                ORDER BY bi.start_dt DESC
                """,
                (generator_id, date_filter),
            )
        else:
            cur.execute(
                """
                SELECT b.booking_id,
                       b.vendor_id,
                       v.vendor_name,
                       b.status,
                       bi.start_dt,
                       bi.end_dt,
                       bi.item_status,
                       bi.remarks
                FROM booking_items bi
                JOIN bookings b ON bi.booking_id = b.booking_id
                LEFT JOIN vendors v ON b.vendor_id = v.vendor_id
                WHERE bi.generator_id = ?
                ORDER BY bi.start_dt DESC
                """,
                (generator_id,),
            )

        return [
            {
                "booking_id": row[0],
                "vendor_id": row[1],
                "vendor_name": row[2] or row[1] or "-",
                "booking_status": row[3],
                "start_dt": row[4],
                "end_dt": row[5],
                "item_status": row[6],
                "remarks": row[7] or "",
            }
            for row in cur.fetchall()
        ]

    def list_vendor_booking_rows(self, vendor_id: str) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT b.booking_id,
                   b.status,
                   b.created_at,
                   bi.id,
                   bi.generator_id,
                   g.capacity_kva,
                   bi.start_dt,
                   bi.end_dt,
                   bi.item_status,
                   bi.remarks
            FROM bookings b
            LEFT JOIN booking_items bi ON bi.booking_id = b.booking_id
            LEFT JOIN generators g ON g.generator_id = bi.generator_id
            WHERE b.vendor_id = ?
            ORDER BY b.created_at DESC, b.booking_id DESC, bi.start_dt ASC, bi.id ASC
            """,
            (vendor_id,),
        )
        return [
            {
                "booking_id": row[0],
                "booking_status": row[1],
                "created_at": row[2] or "",
                "item_id": row[3],
                "generator_id": row[4],
                "capacity_kva": row[5],
                "start_dt": row[6],
                "end_dt": row[7],
                "item_status": row[8],
                "remarks": row[9] or "",
            }
            for row in cur.fetchall()
        ]

    def list_billing_line_rows(
        self,
        from_date: str,
        to_date: str,
        confirmed_status: str = STATUS_CONFIRMED
    ) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT v.vendor_id,
                   v.vendor_name,
                   b.booking_id,
                   date(bi.start_dt) AS booked_date,
                   bi.generator_id,
                   g.capacity_kva
            FROM booking_items bi
            JOIN bookings b ON b.booking_id = bi.booking_id
            JOIN vendors v ON v.vendor_id = b.vendor_id
            LEFT JOIN generators g ON g.generator_id = bi.generator_id
            WHERE date(bi.start_dt) >= ?
              AND date(bi.start_dt) <= ?
              AND bi.item_status = ?
              AND b.status = ?
            ORDER BY v.vendor_name ASC,
                     v.vendor_id ASC,
                     date(bi.start_dt) ASC,
                     bi.generator_id ASC,
                     b.booking_id ASC,
                     bi.id ASC
            """,
            (from_date, to_date, confirmed_status, confirmed_status),
        )
        return [
            {
                "vendor_id": row[0],
                "vendor_name": row[1],
                "booking_id": row[2],
                "booked_date": row[3],
                "generator_id": row[4],
                "capacity_kva": row[5],
            }
            for row in cur.fetchall()
        ]

    def list_calendar_event_counts(
        self,
        confirmed_status: str = STATUS_CONFIRMED
    ) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT date(bi.start_dt) as booking_date, COUNT(*) as item_count
            FROM booking_items bi
            JOIN bookings b ON bi.booking_id = b.booking_id
            WHERE bi.item_status = ? AND b.status = ?
            GROUP BY booking_date
            ORDER BY booking_date ASC
            """,
            (confirmed_status, confirmed_status),
        )
        return [
            {"booking_date": row[0], "item_count": row[1]}
            for row in cur.fetchall()
        ]

    def list_calendar_day_rows(
        self,
        selected_date: str,
        confirmed_status: str = STATUS_CONFIRMED
    ) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT v.vendor_id, v.vendor_name, b.booking_id, bi.generator_id,
                   g.capacity_kva, bi.start_dt, bi.end_dt, bi.remarks
            FROM booking_items bi
            JOIN bookings b ON bi.booking_id = b.booking_id
            JOIN vendors v ON b.vendor_id = v.vendor_id
            LEFT JOIN generators g ON bi.generator_id = g.generator_id
            WHERE date(bi.start_dt) = ?
              AND bi.item_status = ?
              AND b.status = ?
            ORDER BY v.vendor_name, b.booking_id
            """,
            (selected_date, confirmed_status, confirmed_status),
        )
        return [
            {
                "vendor_id": row[0],
                "vendor_name": row[1],
                "booking_id": row[2],
                "generator_id": row[3],
                "capacity_kva": row[4],
                "start_dt": row[5],
                "end_dt": row[6],
                "remarks": row[7] or "",
            }
            for row in cur.fetchall()
        ]

    def get_confirmed_generator_periods(
        self,
        generator_id: str,
        exclude_booking_id: Optional[str] = None,
        confirmed_status: str = STATUS_CONFIRMED
    ) -> List[Dict[str, str]]:
        cur = self.conn.cursor()
        if exclude_booking_id:
            cur.execute(
                """
                SELECT bi.booking_id, bi.start_dt, bi.end_dt
                FROM booking_items bi
                JOIN bookings b ON bi.booking_id = b.booking_id
                WHERE bi.generator_id = ?
                  AND bi.booking_id != ?
                  AND bi.item_status = ?
                  AND b.status = ?
                """,
                (generator_id, exclude_booking_id, confirmed_status, confirmed_status),
            )
        else:
            cur.execute(
                """
                SELECT bi.booking_id, bi.start_dt, bi.end_dt
                FROM booking_items bi
                JOIN bookings b ON bi.booking_id = b.booking_id
                WHERE bi.generator_id = ?
                  AND bi.item_status = ?
                  AND b.status = ?
                """,
                (generator_id, confirmed_status, confirmed_status),
            )

        return [
            {
                "booking_id": row[0],
                "start_dt": row[1],
                "end_dt": row[2],
            }
            for row in cur.fetchall()
        ]
    
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
        today = datetime.now().strftime("%Y%m%d")

        started_tx = False
        if not self.conn.in_transaction:
            self.conn.execute("BEGIN IMMEDIATE")
            started_tx = True

        try:
            cur.execute(
                "INSERT OR IGNORE INTO booking_id_seq (booking_date, next_val) VALUES (?, 1)",
                (today,)
            )
            cur.execute(
                "SELECT next_val FROM booking_id_seq WHERE booking_date = ?",
                (today,)
            )
            row = cur.fetchone()
            seq_val = row[0] if row else 1

            cur.execute(
                "SELECT MAX(CAST(SUBSTR(booking_id, 14) AS INTEGER)) "
                "FROM bookings WHERE booking_id LIKE ?",
                (f"BKG-{today}-%",)
            )
            max_row = cur.fetchone()
            max_existing = max_row[0] if max_row and max_row[0] else 0

            next_num = max(seq_val, max_existing + 1)
            cur.execute(
                "UPDATE booking_id_seq SET next_val = ? WHERE booking_date = ?",
                (next_num + 1, today)
            )

            if started_tx:
                self.conn.commit()

            return f"BKG-{today}-{next_num:05d}"
        except Exception:
            if started_tx:
                self.conn.rollback()
            raise


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
                (event_time, event_type, booking_id, vendor_id, user, summary, details)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.event_time,
                    event.event_type,
                    event.booking_id,
                    event.vendor_id,
                    event.user or "",
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
                """SELECT id, event_time, event_type, booking_id, vendor_id, user, summary, details
                   FROM booking_history
                   ORDER BY id DESC, event_time DESC
                   LIMIT ?""",
                (limit,)
            )
        else:
            cur.execute(
                """SELECT id, event_time, event_type, booking_id, vendor_id, user, summary, details
                   FROM booking_history
                   ORDER BY id DESC, event_time DESC"""
            )

        events = []
        for row in cur.fetchall():
            events.append(BookingHistory(
                id=row[0],
                event_time=row[1],
                event_type=row[2],
                booking_id=row[3],
                vendor_id=row[4],
                user=row[5] or "",
                summary=row[6] or "",
                details=row[7] or ""
            ))
        return events


class UserRepository:
    """Repository for user account data access."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.logger = logging.getLogger(self.__class__.__name__)

    def get_by_id(self, user_id: int) -> Optional[User]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, username, password_hash, role, is_active, created_at, last_login "
            "FROM users WHERE id = ?",
            (user_id,)
        )
        row = cur.fetchone()
        if not row:
            return None
        return User(
            id=row[0],
            username=row[1],
            password_hash=row[2],
            role=row[3],
            is_active=bool(row[4]),
            created_at=row[5],
            last_login=row[6]
        )

    def get_by_username(self, username: str) -> Optional[User]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, username, password_hash, role, is_active, created_at, last_login "
            "FROM users WHERE username = ?",
            (username,)
        )
        row = cur.fetchone()
        if not row:
            return None
        return User(
            id=row[0],
            username=row[1],
            password_hash=row[2],
            role=row[3],
            is_active=bool(row[4]),
            created_at=row[5],
            last_login=row[6]
        )

    def list_all(self) -> List[User]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, username, password_hash, role, is_active, created_at, last_login "
            "FROM users ORDER BY created_at DESC, id DESC"
        )
        users = []
        for row in cur.fetchall():
            users.append(User(
                id=row[0],
                username=row[1],
                password_hash=row[2],
                role=row[3],
                is_active=bool(row[4]),
                created_at=row[5],
                last_login=row[6]
            ))
        return users

    def count_users(self) -> int:
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        return int(cur.fetchone()[0])

    def count_active_admins(self, role_admin: str) -> int:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM users WHERE role = ? AND is_active = 1",
            (role_admin,)
        )
        return int(cur.fetchone()[0])

    def create_user(self, username: str, password_hash: str, role: str, is_active: bool = True) -> int:
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO users (username, password_hash, role, is_active, created_at)
               VALUES (?, ?, ?, ?, datetime('now'))""",
            (username, password_hash, role, 1 if is_active else 0)
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_permission_overrides(self, user_id: int) -> Dict[str, bool]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT capability_key, is_allowed
            FROM user_permission_overrides
            WHERE user_id = ?
            ORDER BY capability_key
            """,
            (user_id,),
        )
        return {
            str(row[0]): bool(row[1])
            for row in cur.fetchall()
        }

    def list_permission_overrides_by_user(self) -> Dict[int, Dict[str, bool]]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT user_id, capability_key, is_allowed
            FROM user_permission_overrides
            ORDER BY user_id, capability_key
            """
        )
        grouped: Dict[int, Dict[str, bool]] = {}
        for row in cur.fetchall():
            user_id = int(row[0])
            grouped.setdefault(user_id, {})[str(row[1])] = bool(row[2])
        return grouped

    def set_permission_override(
        self,
        user_id: int,
        capability_key: str,
        is_allowed: bool,
        commit: bool = True,
    ) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO user_permission_overrides (user_id, capability_key, is_allowed)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, capability_key)
            DO UPDATE SET is_allowed = excluded.is_allowed
            """,
            (user_id, capability_key, 1 if is_allowed else 0),
        )
        if commit:
            self.conn.commit()

    def delete_permission_override(
        self,
        user_id: int,
        capability_key: str,
        commit: bool = True,
    ) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            DELETE FROM user_permission_overrides
            WHERE user_id = ? AND capability_key = ?
            """,
            (user_id, capability_key),
        )
        if commit:
            self.conn.commit()

    def clear_permission_overrides(self, user_id: int, commit: bool = True) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "DELETE FROM user_permission_overrides WHERE user_id = ?",
            (user_id,),
        )
        if commit:
            self.conn.commit()

    def update_role(self, user_id: int, role: str) -> None:
        cur = self.conn.cursor()
        cur.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
        self.conn.commit()

    def update_active(self, user_id: int, is_active: bool) -> None:
        cur = self.conn.cursor()
        cur.execute("UPDATE users SET is_active = ? WHERE id = ?", (1 if is_active else 0, user_id))
        self.conn.commit()

    def update_password(self, user_id: int, password_hash: str) -> None:
        cur = self.conn.cursor()
        cur.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
        self.conn.commit()

    def update_last_login(self, user_id: int) -> None:
        cur = self.conn.cursor()
        cur.execute("UPDATE users SET last_login = datetime('now') WHERE id = ?", (user_id,))
        self.conn.commit()

    def delete_user(self, user_id: int) -> None:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
        self.conn.commit()


class SessionRepository:
    """Repository for server-side session storage."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.logger = logging.getLogger(self.__class__.__name__)

    def create(
        self,
        session_id: str,
        user_id: int,
        csrf_token: str,
        created_at: int,
        expires_at: int,
        ip_address: str = "",
        user_agent: str = "",
    ) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO sessions
               (session_id, user_id, csrf_token, created_at, expires_at, last_seen, ip_address, user_agent)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, user_id, csrf_token, created_at, expires_at, created_at, ip_address, user_agent),
        )
        self.conn.commit()

    def get_by_id(self, session_id: str) -> Optional[UserSession]:
        cur = self.conn.cursor()
        cur.execute(
            """SELECT session_id, user_id, csrf_token, created_at, expires_at, last_seen, ip_address, user_agent
               FROM sessions WHERE session_id = ?""",
            (session_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return UserSession(
            session_id=row[0],
            user_id=row[1],
            csrf_token=row[2],
            created_at=row[3],
            expires_at=row[4],
            last_seen=row[5],
            ip_address=row[6] or "",
            user_agent=row[7] or "",
        )

    def update_last_seen(self, session_id: str, last_seen: int) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE sessions SET last_seen = ? WHERE session_id = ?",
            (last_seen, session_id),
        )
        self.conn.commit()

    def delete(self, session_id: str) -> None:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        self.conn.commit()

    def delete_by_user_id(self, user_id: int) -> None:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        self.conn.commit()

    def delete_expired(self, now_ts: int) -> None:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM sessions WHERE expires_at <= ?", (now_ts,))
        self.conn.commit()


class RevokedTokenRepository:
    """Repository for revoked JWT tracking."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.logger = logging.getLogger(self.__class__.__name__)

    def revoke(self, jti: str, expires_at: int) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO revoked_tokens (jti, expires_at) VALUES (?, ?)",
            (jti, expires_at),
        )
        self.conn.commit()

    def is_revoked(self, jti: str, now_ts: int) -> bool:
        cur = self.conn.cursor()
        cur.execute("SELECT expires_at FROM revoked_tokens WHERE jti = ?", (jti,))
        row = cur.fetchone()
        if not row:
            return False
        expires_at = int(row[0])
        if expires_at <= now_ts:
            cur.execute("DELETE FROM revoked_tokens WHERE jti = ?", (jti,))
            self.conn.commit()
            return False
        return True

    def delete_expired(self, now_ts: int) -> None:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM revoked_tokens WHERE expires_at <= ?", (now_ts,))
        self.conn.commit()
