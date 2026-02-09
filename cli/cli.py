"""
Command-line interface for the Generator Booking Ledger.
"""

import sqlite3
import pandas as pd
import logging
from typing import Optional

from core import (
    DatabaseManager,
    BookingService,
    DataLoader,
    ExportService,
)
from core.services import archive_all_bookings, create_vendor
from config import LOAD_SEED_DATA, OWNER_USERNAME, OWNER_PASSWORD
from core.auth import ensure_owner_user


class CLI:
    """Command-line interface for the booking system."""
    
    def __init__(self, db_path: str = "ledger.db"):
        self.db_manager = DatabaseManager(db_path)
        self.conn: Optional[sqlite3.Connection] = None
        self.booking_service: Optional[BookingService] = None
        self.export_service: Optional[ExportService] = None
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def initialize(self) -> None:
        """Initialize database and services."""
        self.conn = self.db_manager.connect()
        self.db_manager.init_schema()

        # Ensure at least one admin user exists (non-strict in CLI)
        ensure_owner_user(self.conn, OWNER_USERNAME, OWNER_PASSWORD, strict=False)
        
        # Load sample data
        if LOAD_SEED_DATA:
            loader = DataLoader(self.conn)
            loader.load_from_excel()
        else:
            self.logger.info("Seed data load skipped (LOAD_SEED_DATA=false)")
        
        # Initialize services
        self.booking_service = BookingService(self.conn)
        self.export_service = ExportService(self.conn)
        self.actor = "cli"
        
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
                print("9. Archive all bookings (clear for new month)")
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
        
        self.booking_service.create_booking(vendor_id, items, actor=self.actor)
        print(f"✓ Created booking")
    
    def add_generator_interactive(self) -> None:
        """Interactive generator addition."""
        booking_id = input('Booking ID: ').strip()
        mode = input('Add by (1) generator_id or (2) capacity_kva? [1/2]: ').strip()
        
        if mode == '1':
            gid = input('Generator ID: ').strip()
            start_dt = input("Start (YYYY-MM-DD HH:MM): ").strip()
            end_dt = input("End   (YYYY-MM-DD HH:MM): ").strip()
            success, info = self.booking_service.add_generator(
                booking_id,
                generator_id=gid,
                start_dt=start_dt,
                end_dt=end_dt,
                actor=self.actor
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
                booking_id,
                capacity_kva=cap,
                start_dt=start_dt,
                end_dt=end_dt,
                actor=self.actor
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
        
        success, msg = self.booking_service.modify_times(
            booking_id,
            new_start,
            new_end,
            actor=self.actor
        )
        
        if success:
            print(f'✓ {msg}')
        else:
            print(f'✗ Failed: {msg}')
    
    def cancel_booking_interactive(self) -> None:
        """Interactive booking cancellation."""
        booking_id = input('Booking ID: ').strip()
        reason = input('Reason (optional): ').strip() or 'Cancelled via CLI'
        
        success, msg = self.booking_service.cancel_booking(
            booking_id,
            reason,
            actor=self.actor
        )
        
        if success:
            print(f'✓ {msg}')
        else:
            print(f'✗ Failed: {msg}')
