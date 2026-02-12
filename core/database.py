"""
Database connection and schema management.
"""

import sqlite3
import logging
from typing import Optional

from config import STATUS_CONFIRMED, GEN_STATUS_ACTIVE, OWNER_USERNAME


class DatabaseManager:
    """Manages database connections and schema initialization."""
    
    def __init__(self, db_path: str = "ledger.db"):
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
            self.conn.execute("PRAGMA foreign_keys = ON")
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
            cur.executescript(f"""
            CREATE TABLE IF NOT EXISTS generators (
                generator_id TEXT PRIMARY KEY,
                capacity_kva INTEGER NOT NULL,
                identification TEXT,
                type TEXT,
                status TEXT DEFAULT '{GEN_STATUS_ACTIVE}',
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
                status TEXT DEFAULT '{STATUS_CONFIRMED}',
                FOREIGN KEY(vendor_id) REFERENCES vendors(vendor_id)
            );

            CREATE TABLE IF NOT EXISTS booking_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_id TEXT NOT NULL,
                generator_id TEXT NOT NULL,
                start_dt TEXT NOT NULL,
                end_dt TEXT NOT NULL,
                item_status TEXT DEFAULT '{STATUS_CONFIRMED}',
                remarks TEXT,
                FOREIGN KEY(booking_id) REFERENCES bookings(booking_id),
                FOREIGN KEY(generator_id) REFERENCES generators(generator_id)
            );

            CREATE TABLE IF NOT EXISTS booking_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_time TEXT NOT NULL,
                event_type TEXT NOT NULL,
                booking_id TEXT,
                vendor_id TEXT,
                summary TEXT,
                details TEXT
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_login TEXT
            );

            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                csrf_token TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                last_seen INTEGER,
                ip_address TEXT,
                user_agent TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS revoked_tokens (
                jti TEXT PRIMARY KEY,
                expires_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS booking_id_seq (
                booking_date TEXT PRIMARY KEY,
                next_val INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS vendor_id_seq (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                next_val INTEGER NOT NULL
            );

            INSERT OR IGNORE INTO vendor_id_seq (id, next_val) VALUES (1, 1);

            CREATE INDEX IF NOT EXISTS idx_booking_items_generator 
                ON booking_items(generator_id, item_status);

            CREATE INDEX IF NOT EXISTS idx_booking_items_booking 
                ON booking_items(booking_id);

            CREATE INDEX IF NOT EXISTS idx_booking_history_time
                ON booking_history(event_time);

            CREATE INDEX IF NOT EXISTS idx_booking_history_booking
                ON booking_history(booking_id);

            CREATE INDEX IF NOT EXISTS idx_booking_history_vendor
                ON booking_history(vendor_id);

            CREATE INDEX IF NOT EXISTS idx_sessions_user_id
                ON sessions(user_id);

            CREATE INDEX IF NOT EXISTS idx_sessions_expires_at
                ON sessions(expires_at);

            CREATE INDEX IF NOT EXISTS idx_revoked_tokens_expires_at
                ON revoked_tokens(expires_at);
            """)
            # Ensure booking_history has user column for audit trail
            cur.execute("PRAGMA table_info(booking_history)")
            existing_cols = {row[1] for row in cur.fetchall()}
            if "user" not in existing_cols:
                cur.execute("ALTER TABLE booking_history ADD COLUMN user TEXT")

            # Backfill legacy history rows with owner when user is missing
            owner_label = OWNER_USERNAME or "owner"
            cur.execute(
                "UPDATE booking_history SET user = ? WHERE user IS NULL OR user = ''",
                (owner_label,)
            )

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
