"""
FastAPI web application for Generator Booking Ledger.
"""

from fastapi import FastAPI, Request, HTTPException, Form, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exceptions import RequestValidationError
import os
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any
import logging
from pydantic import BaseModel

from core import (
    DatabaseManager,
    BookingService,
    DataLoader,
    ExportService,
    GeneratorRepository,
    VendorRepository,
    BookingRepository,
)
from core.utils import transaction
from core.validation import ensure_booking
from core.services import create_vendor, archive_all_bookings

# Initialize logging
from config import (
    setup_logging,
    DB_PATH,
    HOST,
    PORT,
    DEBUG,
    APP_TITLE,
    APP_VERSION,
    STATUS_CONFIRMED,
    GEN_STATUS_ACTIVE,
)
setup_logging()

logger = logging.getLogger(__name__)

# Pydantic models for request bodies
class BookingItem(BaseModel):
    generator_id: Optional[str] = None
    capacity_kva: Optional[int] = None
    date: str
    remarks: str = ""

class CreateBookingRequest(BaseModel):
    vendor_id: str
    items: List[BookingItem]

class CreateVendorRequest(BaseModel):
    vendor_id: Optional[str] = None
    vendor_name: str
    vendor_place: str = "Civil Line"
    phone: str = ""

# FastAPI app
app = FastAPI(title=APP_TITLE, version=APP_VERSION)

# Exception handler for validation errors
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle Pydantic validation errors with proper JSON response."""
    errors = []
    for error in exc.errors():
        errors.append(f"{'.'.join(str(x) for x in error['loc'][1:])}: {error['msg']}")
    error_message = "; ".join(errors) if errors else "Validation error"
    logger.warning(f"Validation error: {error_message}")
    return JSONResponse(
        status_code=400,
        content={"detail": error_message}
    )

# Static files and templates
template_dir = os.path.join(os.path.dirname(__file__), "templates")
static_dir = os.path.join(os.path.dirname(__file__), "static")

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

templates = Jinja2Templates(directory=template_dir)

# Global database manager
db_manager: Optional[DatabaseManager] = None


def get_db():
    """Dependency for getting database connection."""
    if db_manager is None or db_manager.conn is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    return db_manager.conn


def initialize_app():
    """Initialize database and services."""
    global db_manager
    db_manager = DatabaseManager(DB_PATH)
    conn = db_manager.connect()
    db_manager.init_schema()
    
    # Load sample data
    loader = DataLoader(conn)
    loader.load_from_excel()
    
    logger.info("FastAPI application initialized successfully")


def shutdown_app():
    """Shutdown and cleanup."""
    global db_manager
    if db_manager:
        db_manager.close()
    logger.info("FastAPI application shutdown")


def _summarize_booking_items(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize booking items for logging without full payloads."""
    dates = []
    generator_ids = []
    capacities = []
    for item in items:
        date_val = item.get("date") or item.get("start_dt")
        if date_val:
            dates.append(date_val)
        if item.get("generator_id"):
            generator_ids.append(item.get("generator_id"))
        if item.get("capacity_kva") is not None:
            capacities.append(item.get("capacity_kva"))

    sample_limit = 3
    return {
        "item_count": len(items),
        "date_samples": dates[:sample_limit],
        "generator_samples": generator_ids[:sample_limit],
        "capacity_samples": capacities[:sample_limit],
        "truncated": len(items) > sample_limit,
    }


@app.on_event("startup")
async def startup():
    initialize_app()


@app.on_event("shutdown")
async def shutdown():
    shutdown_app()


# ============================================================================
# HEALTH CHECKS & INFO
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "app": APP_TITLE,
        "version": APP_VERSION
    }


@app.get("/api/info")
async def app_info():
    """Get application information."""
    return {
        "title": APP_TITLE,
        "version": APP_VERSION,
        "database": DB_PATH,
    }


# ============================================================================
# WEB PAGES
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """Main dashboard page."""
    try:
        booking_repo = BookingRepository(conn)
        gen_repo = GeneratorRepository(conn)
        vendor_repo = VendorRepository(conn)
        
        bookings = booking_repo.get_all()
        generators = gen_repo.get_all()
        vendors = vendor_repo.get_all()
        
        # Count confirmed bookings and generators
        confirmed_bookings = len([b for b in bookings if b.status == STATUS_CONFIRMED])
        active_generators = len([g for g in generators if g.status == GEN_STATUS_ACTIVE])
        total_vendors = len(vendors)
        
        return templates.TemplateResponse("index.html", {
            "request": request,
            "total_bookings": len(bookings),
            "confirmed_bookings": confirmed_bookings,
            "total_generators": len(generators),
            "active_generators": active_generators,
            "total_vendors": total_vendors,
        })
    except Exception as e:
        logger.error(f"Error loading dashboard: {e}", exc_info=True)
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": str(e)
        })


@app.get("/generators", response_class=HTMLResponse)
async def generators_page(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """Generators list page."""
    try:
        gen_repo = GeneratorRepository(conn)
        generators = gen_repo.get_all()
        return templates.TemplateResponse("generators.html", {
            "request": request,
            "generators": generators
        })
    except Exception as e:
        logger.error(f"Error loading generators page: {e}", exc_info=True)
        return templates.TemplateResponse("error.html", {"request": request, "error": str(e)})


@app.get("/vendors", response_class=HTMLResponse)
async def vendors_page(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """Vendors list page."""
    try:
        vendor_repo = VendorRepository(conn)
        vendors = vendor_repo.get_all()
        return templates.TemplateResponse("vendors.html", {
            "request": request,
            "vendors": vendors
        })
    except Exception as e:
        logger.error(f"Error loading vendors page: {e}", exc_info=True)
        return templates.TemplateResponse("error.html", {"request": request, "error": str(e)})


@app.get("/bookings", response_class=HTMLResponse)
async def bookings_page(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """Bookings list page."""
    try:
        booking_repo = BookingRepository(conn)
        vendor_repo = VendorRepository(conn)
        
        bookings = booking_repo.get_all()
        
        # Group bookings by vendor with booked dates
        bookings_by_vendor = {}
        for booking in bookings:
            vendor = vendor_repo.get_by_id(booking.vendor_id)
            vendor_name = vendor.vendor_name if vendor else "Unknown"
            
            if vendor_name not in bookings_by_vendor:
                bookings_by_vendor[vendor_name] = {
                    "vendor_id": booking.vendor_id,
                    "bookings": []
                }
            
            items = booking_repo.get_items(booking.booking_id)
            
            # Extract unique dates from items
            booked_dates = set()
            for item in items:
                # Extract date from start_dt (YYYY-MM-DD HH:MM format)
                date_part = item.start_dt.split()[0]
                booked_dates.add(date_part)
            
            booked_dates_str = ", ".join(sorted(booked_dates)) if booked_dates else "N/A"
            
            bookings_by_vendor[vendor_name]["bookings"].append({
                "booking": booking,
                "items": items,
                "item_count": len(items),
                "booked_dates": booked_dates_str
            })
        
        # Sort vendors alphabetically
        sorted_vendors = sorted(bookings_by_vendor.items())
        
        return templates.TemplateResponse("bookings.html", {
            "request": request,
            "bookings_by_vendor": sorted_vendors
        })
    except Exception as e:
        logger.error(f"Error loading bookings page: {e}", exc_info=True)
        return templates.TemplateResponse("error.html", {"request": request, "error": str(e)})


@app.get("/create-booking", response_class=HTMLResponse)
async def create_booking_page(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """Create booking page."""
    try:
        vendor_repo = VendorRepository(conn)
        gen_repo = GeneratorRepository(conn)
        
        vendors = vendor_repo.get_all()
        generators = gen_repo.get_all()
        
        # Get unique capacities
        capacities = sorted(set(g.capacity_kva for g in generators))
        
        return templates.TemplateResponse("create_booking.html", {
            "request": request,
            "vendors": vendors,
            "generators": generators,
            "capacities": capacities
        })
    except Exception as e:
        logger.error(f"Error loading create booking page: {e}", exc_info=True)
        return templates.TemplateResponse("error.html", {"request": request, "error": str(e)})


@app.get("/booking/{booking_id}", response_class=HTMLResponse)
async def booking_detail_page(request: Request, booking_id: str, conn: sqlite3.Connection = Depends(get_db)):
    """Booking detail page."""
    try:
        booking_repo = BookingRepository(conn)
        vendor_repo = VendorRepository(conn)
        gen_repo = GeneratorRepository(conn)
        
        try:
            booking = ensure_booking(
                booking_repo,
                booking_id,
                message=f"Booking '{booking_id}' not found"
            )
        except ValueError as e:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "error": str(e)
            })
        
        vendor = vendor_repo.get_by_id(booking.vendor_id)
        items = booking_repo.get_items(booking_id)
        
        # Enrich items with generator info
        items_with_gen = []
        for item in items:
            gen = gen_repo.get_by_id(item.generator_id)
            items_with_gen.append({
                "item": item,
                "generator_name": f"{gen.generator_id} ({gen.capacity_kva} kVA)" if gen else "Unknown"
            })
        
        return templates.TemplateResponse("booking_detail.html", {
            "request": request,
            "booking": booking,
            "vendor": vendor,
            "items": items_with_gen
        })
    except Exception as e:
        logger.error(f"Error loading booking detail: {e}", exc_info=True)
        return templates.TemplateResponse("error.html", {"request": request, "error": str(e)})


@app.get("/booking/{booking_id}/edit", response_class=HTMLResponse)
async def edit_booking_page(request: Request, booking_id: str, conn: sqlite3.Connection = Depends(get_db)):
    """Edit booking page."""
    try:
        booking_repo = BookingRepository(conn)
        vendor_repo = VendorRepository(conn)
        gen_repo = GeneratorRepository(conn)
        
        try:
            booking = ensure_booking(
                booking_repo,
                booking_id,
                message=f"Booking '{booking_id}' not found"
            )
        except ValueError as e:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "error": str(e)
            })
        
        vendor = vendor_repo.get_by_id(booking.vendor_id)
        items = booking_repo.get_items(booking_id)
        generators = gen_repo.get_all()
        
        # Enrich items with generator info
        items_with_gen = []
        for item in items:
            gen = gen_repo.get_by_id(item.generator_id)
            items_with_gen.append({
                "item": item,
                "generator_name": f"{gen.generator_id} ({gen.capacity_kva} kVA)" if gen else "Unknown"
            })
        
        return templates.TemplateResponse("edit_booking.html", {
            "request": request,
            "booking": booking,
            "vendor": vendor,
            "items": items_with_gen,
            "generators": generators
        })
    except Exception as e:
        logger.error(f"Error loading edit booking page: {e}", exc_info=True)
        return templates.TemplateResponse("error.html", {"request": request, "error": str(e)})


# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.get("/api/generators")
async def api_generators(conn: sqlite3.Connection = Depends(get_db)):
    """Get all generators."""
    try:
        gen_repo = GeneratorRepository(conn)
        generators = gen_repo.get_all()
        return [
            {
                "id": g.generator_id,
                "capacity": g.capacity_kva,
                "identification": g.identification,
                "type": g.type,
                "status": g.status,
                "notes": g.notes
            }
            for g in generators
        ]
    except Exception as e:
        logger.error(f"Error fetching generators: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/vendors")
async def api_vendors(conn: sqlite3.Connection = Depends(get_db)):
    """Get all vendors."""
    try:
        vendor_repo = VendorRepository(conn)
        vendors = vendor_repo.get_all()
        return [
            {
                "id": v.vendor_id,
                "name": v.vendor_name,
                "place": v.vendor_place,
                "phone": v.phone
            }
            for v in vendors
        ]
    except Exception as e:
        logger.error(f"Error fetching vendors: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/bookings")
async def api_bookings(conn: sqlite3.Connection = Depends(get_db)):
    """Get all bookings."""
    try:
        booking_repo = BookingRepository(conn)
        bookings = booking_repo.get_all()
        return [
            {
                "id": b.booking_id,
                "vendor_id": b.vendor_id,
                "created_at": b.created_at,
                "status": b.status
            }
            for b in bookings
        ]
    except Exception as e:
        logger.error(f"Error fetching bookings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/calendar/events")
async def api_calendar_events(conn: sqlite3.Connection = Depends(get_db)):
    """Calendar events aggregated by date (confirmed bookings only)."""
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT date(bi.start_dt) as booking_date, COUNT(*) as item_count
            FROM booking_items bi
            JOIN bookings b ON bi.booking_id = b.booking_id
            WHERE bi.item_status = ? AND b.status = ?
            GROUP BY booking_date
            ORDER BY booking_date ASC
            """,
            (STATUS_CONFIRMED, STATUS_CONFIRMED),
        )
        events = []
        for row in cur.fetchall():
            booking_date = row[0]
            item_count = row[1]
            events.append({
                "title": f"{item_count} booking(s)",
                "start": booking_date,
                "allDay": True,
                "extendedProps": {"date": booking_date},
            })
        return events
    except Exception as e:
        logger.error(f"Error fetching calendar events: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/calendar/day")
async def api_calendar_day(date: str, conn: sqlite3.Connection = Depends(get_db)):
    """Get vendor bookings for a given date (confirmed only)."""
    try:
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format (YYYY-MM-DD)")

        cur = conn.cursor()
        cur.execute(
            """
            SELECT v.vendor_id, v.vendor_name, b.booking_id, bi.generator_id,
                   bi.start_dt, bi.end_dt, bi.remarks
            FROM booking_items bi
            JOIN bookings b ON bi.booking_id = b.booking_id
            JOIN vendors v ON b.vendor_id = v.vendor_id
            WHERE date(bi.start_dt) = ?
              AND bi.item_status = ?
              AND b.status = ?
            ORDER BY v.vendor_name, b.booking_id
            """,
            (date, STATUS_CONFIRMED, STATUS_CONFIRMED),
        )

        vendors: Dict[str, Dict[str, Any]] = {}
        for row in cur.fetchall():
            vendor_id, vendor_name, booking_id, generator_id, start_dt, end_dt, remarks = row
            if vendor_id not in vendors:
                vendors[vendor_id] = {
                    "vendor_id": vendor_id,
                    "vendor_name": vendor_name,
                    "bookings": {},
                }
            booking_group = vendors[vendor_id]["bookings"].setdefault(
                booking_id,
                {"booking_id": booking_id, "items": []},
            )
            booking_group["items"].append({
                "generator_id": generator_id,
                "start_dt": start_dt,
                "end_dt": end_dt,
                "remarks": remarks or "",
            })

        vendor_list = []
        for vendor in vendors.values():
            vendor["bookings"] = list(vendor["bookings"].values())
            vendor_list.append(vendor)

        return {
            "date": date,
            "vendors": vendor_list,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching calendar day detail: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/vendors")
async def api_create_vendor(
    request_data: CreateVendorRequest,
    conn: sqlite3.Connection = Depends(get_db)
):
    """Create a new vendor with auto-generated ID."""
    try:
        vendor_name = request_data.vendor_name.strip() if request_data.vendor_name else ""
        vendor_place = (request_data.vendor_place.strip() if request_data.vendor_place else "").strip() or "Civil Line"
        phone = request_data.phone.strip() if request_data.phone else ""
        
        if not vendor_name:
            raise HTTPException(status_code=400, detail="Vendor Name is required")
        
        # Auto-generate vendor ID if not provided
        vendor_id = request_data.vendor_id
        if not vendor_id or not vendor_id.strip():
            vendor_repo = VendorRepository(conn)
            vendor_id = vendor_repo.generate_vendor_id()
        else:
            vendor_id = vendor_id.strip()
        
        logger.info(f"API vendor creation request | context={{'vendor_id': '{vendor_id}', 'vendor_name': '{vendor_name}'}}")
        
        success, message = create_vendor(conn, vendor_id, vendor_name, vendor_place, phone)
        
        if success:
            logger.info(f"Vendor created successfully | context={{'vendor_id': '{vendor_id}'}}")
            return {"success": True, "message": message, "vendor_id": vendor_id}
        else:
            logger.warning(f"Vendor creation failed | context={{'vendor_id': '{vendor_id}', 'reason': '{message}'}}")
            raise HTTPException(status_code=400, detail=message)
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error creating vendor: {error_msg}", exc_info=True)
        raise HTTPException(status_code=500, detail=error_msg)


@app.post("/api/bookings")
async def api_create_booking(
    request_data: CreateBookingRequest,
    conn: sqlite3.Connection = Depends(get_db)
):
    """Create a new booking with auto-generated ID and items.
    
    If vendor already has a booking with overlapping dates,
    automatically merges the new items into the existing booking.
    """
    try:
        vendor_id = request_data.vendor_id
        items = [item.dict() for item in request_data.items]
        
        item_summary = _summarize_booking_items(items)
        item_summary["vendor_id"] = vendor_id
        logger.info(f"API booking request | context={item_summary}")
        
        if not vendor_id:
            raise HTTPException(status_code=400, detail="vendor_id is required")
        
        if not items:
            raise HTTPException(status_code=400, detail="At least one date must be selected")
        
        service = BookingService(conn)
        # Create booking with auto-generated ID and items
        # If vendor already has overlapping dates, will merge into existing booking
        booking_id = service.create_booking(vendor_id, items)
        
        # Check if this was a merge or new creation
        booking_repo = BookingRepository(conn)
        booking = booking_repo.get_by_id(booking_id)
        item_count = len(booking_repo.get_items(booking_id))
        
        # If item_count > requested items, it was merged
        is_merged = item_count > len(items)
        message = f"Merged into existing booking" if is_merged else f"New booking created"
        
        return {
            "success": True,
            "booking_id": booking_id,
            "message": message,
            "is_merged": is_merged,
            "total_items": item_count
        }
    except ValueError as e:
        logger.warning(f"Validation error creating booking: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating booking: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/bookings/{booking_id}")
async def api_booking_detail(booking_id: str, conn: sqlite3.Connection = Depends(get_db)):
    """Get booking detail."""
    try:
        booking_repo = BookingRepository(conn)
        try:
            booking = ensure_booking(booking_repo, booking_id, message="Booking not found")
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        
        items = booking_repo.get_items(booking_id)
        
        return {
            "booking": {
                "id": booking.booking_id,
                "vendor_id": booking.vendor_id,
                "created_at": booking.created_at,
                "status": booking.status
            },
            "items": [
                {
                    "id": item.id,
                    "generator_id": item.generator_id,
                    "start_dt": item.start_dt,
                    "end_dt": item.end_dt,
                    "status": item.item_status,
                    "remarks": item.remarks
                }
                for item in items
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching booking detail: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/bookings/{booking_id}/cancel")
async def api_cancel_booking(
    booking_id: str,
    reason: str = Form(default="Cancelled via web"),
    conn: sqlite3.Connection = Depends(get_db)
):
    """Cancel a booking."""
    try:
        service = BookingService(conn)
        success, msg = service.cancel_booking(booking_id, reason)
        
        if not success:
            raise HTTPException(status_code=400, detail=msg)
        
        return {"success": True, "message": msg}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling booking: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/bookings/{booking_id}")
async def api_delete_booking(
    booking_id: str,
    conn: sqlite3.Connection = Depends(get_db)
):
    """Delete a booking completely."""
    try:
        booking_repo = BookingRepository(conn)
        try:
            ensure_booking(booking_repo, booking_id, message="Booking not found")
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        
        # Delete all booking items first
        items = booking_repo.get_items(booking_id)
        cur = conn.cursor()
        
        with transaction(conn):
            for item in items:
                cur.execute("DELETE FROM booking_items WHERE id = ?", (item.id,))
            
            # Delete the booking
            cur.execute("DELETE FROM bookings WHERE booking_id = ?", (booking_id,))
        
        logger.info(f"Booking deleted | context={{'booking_id': '{booking_id}'}}")
        return {"success": True, "message": f"Booking {booking_id} deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting booking: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/bookings/{booking_id}/items")
async def api_add_booking_item(
    booking_id: str,
    generator_id: str = Form(...),
    start_dt: str = Form(...),
    end_dt: str = Form(...),
    remarks: str = Form(default=""),
    conn: sqlite3.Connection = Depends(get_db)
):
    """Add a new generator to an existing booking."""
    try:
        booking_repo = BookingRepository(conn)
        try:
            ensure_booking(booking_repo, booking_id, message="Booking not found")
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        
        service = BookingService(conn)
        # Add generator to booking
        success, message = service.add_generator(booking_id, generator_id, start_dt, end_dt, remarks)
        
        if not success:
            raise HTTPException(status_code=400, detail=message)
        
        return {"success": True, "message": message}
    except ValueError as e:
        logger.warning(f"Validation error adding item: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding item to booking: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/bookings/{booking_id}/items/bulk-update")
async def api_bulk_update_items(
    booking_id: str,
    request_data: Dict[str, Any],
    conn: sqlite3.Connection = Depends(get_db)
):
    """Update multiple booking items and remove items."""
    try:
        booking_repo = BookingRepository(conn)
        try:
            ensure_booking(booking_repo, booking_id, message="Booking not found")
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        
        cur = conn.cursor()
        
        # Update items
        updates = request_data.get("updates", [])
        removes = request_data.get("removes", [])
        
        with transaction(conn):
            for update in updates:
                cur.execute(
                    "UPDATE booking_items SET start_dt = ?, end_dt = ?, remarks = ? WHERE id = ?",
                    (update["start_dt"], update["end_dt"], update["remarks"], update["id"])
                )
            
            # Remove items
            for item_id in removes:
                cur.execute("DELETE FROM booking_items WHERE id = ?", (item_id,))
        
        logger.info(f"Booking items updated | context={{'booking_id': '{booking_id}', 'updates': {len(updates)}, 'removes': {len(removes)}}}")
        return {"success": True, "message": "Items updated successfully"}
    except Exception as e:
        logger.error(f"Error updating items: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/export")
async def api_export(conn: sqlite3.Connection = Depends(get_db)):
    """Export data to CSV."""
    try:
        export_service = ExportService(conn)
        bpath, ipath = export_service.export_to_csv()
        return {
            "success": True,
            "bookings": bpath,
            "items": ipath
        }
    except Exception as e:
        logger.error(f"Error exporting data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
