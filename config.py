"""
Configuration for Generator Booking Ledger application.
"""

import os
from logging.handlers import RotatingFileHandler
import logging
import sys

# Database Configuration
DB_PATH = os.getenv("DB_PATH", "ledger.db")

# Web Server Configuration
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
DEBUG = os.getenv("DEBUG", "True").lower() == "true"

# Application Configuration
APP_TITLE = "Generator Booking Ledger"
APP_VERSION = "2.0.0"

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
