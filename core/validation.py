"""
Shared validation helpers for repository lookups.
"""

from typing import Optional

from .models import Generator, Vendor, Booking
from .repositories import GeneratorRepository, VendorRepository, BookingRepository


def ensure_vendor(
    vendor_repo: VendorRepository,
    vendor_id: str,
    message: Optional[str] = None
) -> Vendor:
    """Return vendor if found; raise ValueError otherwise."""
    vendor = vendor_repo.get_by_id(vendor_id)
    if not vendor:
        raise ValueError(message or f"Vendor '{vendor_id}' does not exist")
    return vendor


def ensure_generator(
    generator_repo: GeneratorRepository,
    generator_id: str,
    message: Optional[str] = None
) -> Generator:
    """Return generator if found; raise ValueError otherwise."""
    generator = generator_repo.get_by_id(generator_id)
    if not generator:
        raise ValueError(message or f"Generator '{generator_id}' not found")
    return generator


def ensure_booking(
    booking_repo: BookingRepository,
    booking_id: str,
    message: Optional[str] = None
) -> Booking:
    """Return booking if found; raise ValueError otherwise."""
    booking = booking_repo.get_by_id(booking_id)
    if not booking:
        raise ValueError(message or f"Booking '{booking_id}' not found")
    return booking
