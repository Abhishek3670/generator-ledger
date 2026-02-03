"""
Data models for the Generator Booking Ledger system.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


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
