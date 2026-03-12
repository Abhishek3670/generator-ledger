"""
Configuration for Generator Booking Ledger application.
"""

import os
from logging.handlers import RotatingFileHandler
import logging
import sys


def _normalize_toggle_setting(value: str, default: str = "auto") -> str:
    normalized = (value or default).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return "true"
    if normalized in {"0", "false", "no", "off"}:
        return "false"
    return "auto"

# Load environment variables from .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed (ok for Docker)

# Database Configuration
DB_PATH = os.getenv("DB_PATH", "ledger.db")
LOAD_SEED_DATA = os.getenv("LOAD_SEED_DATA", "false").lower() == "true"
DB_SLOW_QUERY_MS = float(os.getenv("DB_SLOW_QUERY_MS", "80"))

# Auth / Session Configuration
SESSION_SECRET = os.getenv("SESSION_SECRET", "").strip()
OWNER_USERNAME = os.getenv("OWNER_USERNAME", "").strip()
OWNER_PASSWORD = os.getenv("OWNER_PASSWORD", "").strip()
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "gbl_session").strip()
SESSION_TTL_MINUTES = int(os.getenv("SESSION_TTL_MINUTES", "480"))
SESSION_COOKIE_SECURE = _normalize_toggle_setting(
    os.getenv("SESSION_COOKIE_SECURE", "auto"),
    default="auto",
)
JWT_SECRET = (os.getenv("JWT_SECRET", "").strip() or SESSION_SECRET)
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256").strip()
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "15"))
CSRF_HEADER_NAME = os.getenv("CSRF_HEADER_NAME", "X-CSRF-Token").strip()
ENABLE_HSTS = _normalize_toggle_setting(
    os.getenv("ENABLE_HSTS", "auto"),
    default="auto",
)

# Role Configuration
ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"

# Web Server Configuration
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# Application Configuration
APP_TITLE = "Generator Booking Ledger"
APP_VERSION = "2.2.0"

# Date/Time Configuration
DATETIME_FORMAT = "%Y-%m-%d %H:%M"
DEFAULT_TIME = "08:00"

# Status Constants
STATUS_CONFIRMED = "Confirmed"
STATUS_CANCELLED = "Cancelled"
STATUS_PENDING = "Pending"

GEN_STATUS_ACTIVE = "Active"
GEN_STATUS_INACTIVE = "Inactive"
GEN_STATUS_MAINTENANCE = "Maintenance"

GEN_INVENTORY_RETAILER = "retailer"
GEN_INVENTORY_EMERGENCY = "emergency"


def setup_logging():
    """Configures the application-wide logger to write to file and console."""
    
    # Define the log format
    log_formatter = logging.Formatter("[%(levelname)s] %(name)s.%(funcName)s - %(message)s")
    
    # --- Handler 1: File Handler ---
    file_handler = RotatingFileHandler(
        "application.log", 
        mode='a',
        maxBytes=5*1024*1024,  # 5MB
        backupCount=3,
        encoding='utf-8'
    )
    file_handler.setFormatter(log_formatter)
    
    # --- Handler 2: Console Handler ---
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
