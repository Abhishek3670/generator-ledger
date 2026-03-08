"""
Data models for the Generator Booking Ledger system.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from config import (
    STATUS_CONFIRMED,
    STATUS_CANCELLED,
    STATUS_PENDING,
    GEN_STATUS_ACTIVE,
    GEN_STATUS_INACTIVE,
    GEN_STATUS_MAINTENANCE,
)


class BookingStatus(Enum):
    """Booking status enumeration."""
    CONFIRMED = STATUS_CONFIRMED
    CANCELLED = STATUS_CANCELLED
    PENDING = STATUS_PENDING


class GeneratorStatus(Enum):
    """Generator status enumeration."""
    ACTIVE = GEN_STATUS_ACTIVE
    INACTIVE = GEN_STATUS_INACTIVE
    MAINTENANCE = GEN_STATUS_MAINTENANCE


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
class RentalVendor:
    """Rental vendor data model."""
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


@dataclass
class BookingHistory:
    """Booking history event data model."""
    event_time: str
    event_type: str
    booking_id: Optional[str] = None
    vendor_id: Optional[str] = None
    user: str = ""
    summary: str = ""
    details: str = ""
    id: Optional[int] = None


@dataclass
class User:
    """User account data model."""
    username: str
    password_hash: str
    role: str
    is_active: bool = True
    created_at: str = ""
    last_login: Optional[str] = None
    id: Optional[int] = None


@dataclass
class UserSession:
    """Server-side session data model."""
    session_id: str
    user_id: int
    csrf_token: str
    created_at: int
    expires_at: int
    last_seen: Optional[int] = None
    ip_address: str = ""
    user_agent: str = ""
