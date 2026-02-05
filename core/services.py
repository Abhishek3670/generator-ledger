"""
Business logic services for the Generator Booking Ledger system.
"""

import sqlite3
import pandas as pd
import os
import logging
from typing import Optional, List, Dict, Tuple, Any
from datetime import datetime

from .models import (
    Generator, Vendor, Booking, BookingItem,
    BookingStatus, GeneratorStatus
)
from .repositories import (
    GeneratorRepository, VendorRepository, BookingRepository
)
from .utils import DateTimeParser, DATETIME_FORMAT
from .database import DatabaseManager


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
                self.logger.debug(f"Conflict detected | context={{'generator_id': '{generator_id}', 'conflicting_booking': '{row[0]}'}}")
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
        vendor_id: str,
        items: List[Dict[str, Any]],
        booking_id: Optional[str] = None
    ) -> str:
        """Create a new booking with items. Returns the generated booking ID.
        
        This method validates ALL items before saving anything to the database,
        ensuring that failed bookings don't leave orphaned records.
        """
        # Generate booking ID if not provided
        if not booking_id:
            booking_id = self.booking_repo.generate_booking_id()
        
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
        
        # FIRST: Validate and prepare ALL items (without saving)
        prepared_items = []
        for idx, item_spec in enumerate(items):
            generator_id = item_spec.get("generator_id")
            remarks = item_spec.get("remarks", "")
            
            # Handle date field (convert to start_dt and end_dt for full day)
            if "date" in item_spec:
                date = item_spec.get("date")
                # Create full-day booking: 00:00 to 23:59
                start_dt = f"{date} 00:00"
                end_dt = f"{date} 23:59"
            else:
                start_dt = item_spec.get("start_dt")
                end_dt = item_spec.get("end_dt")
            
            if not start_dt or not end_dt:
                self.logger.error(f"Item validation failed | context={{'index': {idx}, 'reason': 'missing dates'}}")
                raise ValueError(f"Item {idx + 1}: date or start_dt/end_dt required")
            
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
                    
                    # Get total count of generators with this capacity
                    total_gens = len(self.generator_repo.find_by_capacity(int(capacity_kva), GeneratorStatus.ACTIVE.value))
                    
                    raise RuntimeError(
                        f"Item {idx + 1}: No available {capacity_kva} kVA generator "
                        f"for {start_dt} - {end_dt}. "
                        f"({total_gens} generator(s) exist but all are booked on this date. "
                        f"Please try a different date or select a different capacity.)"
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
            
            # Store validated item data
            prepared_items.append({
                "generator_id": generator_id,
                "start_dt": start_dt,
                "end_dt": end_dt,
                "remarks": remarks
            })
        
        # SECOND: All items validated - now save to database
        # Create booking
        booking = Booking(
            booking_id=booking_id,
            vendor_id=vendor_id,
            created_at=datetime.now().strftime(DATETIME_FORMAT),
            status=BookingStatus.CONFIRMED.value
        )
        self.booking_repo.save(booking)
        
        # Save all prepared items
        for item_data in prepared_items:
            booking_item = BookingItem(
                booking_id=booking_id,
                generator_id=item_data["generator_id"],
                start_dt=item_data["start_dt"],
                end_dt=item_data["end_dt"],
                item_status=BookingStatus.CONFIRMED.value,
                remarks=item_data["remarks"]
            )
            self.booking_repo.save_item(booking_item)
        
        self.logger.info(f"Booking created successfully | context={{'booking_id': '{booking_id}', 'items_saved': {len(prepared_items)}}}")
        return booking_id
    
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
                os.path.join(out_dir, "bookings.csv"), index=False
            )
            pd.read_sql_query("SELECT * FROM booking_items", self.conn).to_csv(
                os.path.join(out_dir, "booking_items.csv"), index=False
            )
            pd.read_sql_query("SELECT * FROM generators", self.conn).to_csv(
                os.path.join(out_dir, "Generator_Dataset.csv"), index=False
            )
            pd.read_sql_query("SELECT * FROM vendors", self.conn).to_csv(
                os.path.join(out_dir, "Vendor_Dataset.csv"), index=False
            )
            
            self.logger.info(f"Data exported successfully | context={{'dir': '{out_dir}'}}")
            
            return (
                os.path.join(out_dir, "bookings.csv"),
                os.path.join(out_dir, "booking_items.csv")
            )
        except Exception:
            self.logger.error("Export failed", exc_info=True)
            raise


class DataLoader:
    """Loads sample data from Excel files."""
    
    GENERATOR_DB_PATH = "Data/Generator_Dataset.xlsx"
    VENDOR_DB_PATH = "Data/Vendor_Dataset.xlsx"
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.generator_repo = GeneratorRepository(conn)
        self.vendor_repo = VendorRepository(conn)
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def load_from_excel(self) -> None:
        """Load sample data from Excel files."""
        # Load generators
        self.logger.info(f"Attempting to load generators | context={{'path': '{self.GENERATOR_DB_PATH}'}}")
        if os.path.exists(self.GENERATOR_DB_PATH):
            try:
                gdf = pd.read_excel(self.GENERATOR_DB_PATH)
                self.logger.info(f"Read generator file | context={{'shape': {gdf.shape}}}")
                
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
            self.logger.warning(f"Generator dataset not found | context={{'path': '{self.GENERATOR_DB_PATH}', 'cwd': '{os.getcwd()}'}}")

        # Load vendors
        self.logger.info(f"Attempting to load vendors | context={{'path': '{self.VENDOR_DB_PATH}'}}")
        if os.path.exists(self.VENDOR_DB_PATH):
            try:
                vdf = pd.read_excel(self.VENDOR_DB_PATH)
                self.logger.info(f"Read vendor file | context={{'shape': {vdf.shape}}}")
                
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
            self.logger.warning(f"Vendor dataset not found | context={{'path': '{self.VENDOR_DB_PATH}'}}")


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
