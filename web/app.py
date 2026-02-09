"""
FastAPI web application for Generator Booking Ledger.
"""

from fastapi import FastAPI, Request, HTTPException, Form, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exceptions import RequestValidationError
import os
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any
import logging
import re
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from core import (
    DatabaseManager,
    BookingService,
    DataLoader,
    ExportService,
    AvailabilityChecker,
    GeneratorRepository,
    VendorRepository,
    BookingRepository,
    BookingHistoryRepository,
    UserRepository,
)
from core.utils import transaction
from core.validation import ensure_booking
from core.services import create_vendor, archive_all_bookings, log_booking_history, encode_history_items
from core.auth import (
    hash_password,
    verify_password,
    ensure_owner_user,
    validate_password_length,
)

# Initialize logging
from config import (
    setup_logging,
    DB_PATH,
    HOST,
    PORT,
    DEBUG,
    LOAD_SEED_DATA,
    SESSION_SECRET,
    OWNER_USERNAME,
    OWNER_PASSWORD,
    ROLE_ADMIN,
    ROLE_OPERATOR,
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

if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET must be set for production authentication")

PUBLIC_PATHS = {
    "/login",
    "/health",
    "/api/info",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/openapi.json",
}
PUBLIC_PREFIXES = ("/static",)
ALLOWED_ROLES = {ROLE_ADMIN, ROLE_OPERATOR}

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


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Return JSON for API errors and HTML for page errors."""
    if request.url.path.startswith("/api"):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return templates.TemplateResponse(
        "error.html",
        template_context(request, error=exc.detail),
        status_code=exc.status_code
    )

# Static files and templates
template_dir = os.path.join(os.path.dirname(__file__), "templates")
static_dir = os.path.join(os.path.dirname(__file__), "static")

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

templates = Jinja2Templates(directory=template_dir)

def template_context(request: Request, **kwargs: Any) -> Dict[str, Any]:
    """Standard template context with user attached."""
    context = {"request": request, "user": getattr(request.state, "user", None)}
    context.update(kwargs)
    return context


async def get_db(request: Request):
    """Dependency for getting a per-request database connection."""
    conn = getattr(request.state, "db", None)
    if conn:
        yield conn
        return

    conn = None
    try:
        conn = sqlite3.connect(
            DB_PATH,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        )
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
    except sqlite3.Error as e:
        logger.error(f"Database connection failed | context={{'db_path': '{DB_PATH}'}}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()


def get_current_user(request: Request):
    """Return current user from request state."""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


def require_role(*roles: str):
    """Require the current user to have one of the specified roles."""
    def _checker(request: Request):
        user = get_current_user(request)
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Forbidden")
        return user
    return _checker


def get_actor(request: Request) -> str:
    """Return the username for audit logs."""
    user = getattr(request.state, "user", None)
    if user and getattr(user, "username", None):
        return user.username
    return "unknown"


@app.middleware("http")
async def db_auth_middleware(request: Request, call_next):
    """Attach DB connection and enforce authentication for protected routes."""
    conn: Optional[sqlite3.Connection] = None
    try:
        conn = sqlite3.connect(
            DB_PATH,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        )
        conn.execute("PRAGMA foreign_keys = ON")
        request.state.db = conn

        path = request.url.path
        if path in PUBLIC_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
            return await call_next(request)

        user_id = request.session.get("user_id")
        if not user_id:
            if path.startswith("/api"):
                return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
            return RedirectResponse("/login", status_code=303)

        repo = UserRepository(conn)
        user = repo.get_by_id(int(user_id))
        if not user or not user.is_active:
            request.session.clear()
            if path.startswith("/api"):
                return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
            return RedirectResponse("/login", status_code=303)

        request.state.user = user
        return await call_next(request)
    finally:
        if conn:
            conn.close()


app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    https_only=not DEBUG,
    same_site="lax",
)


def initialize_app():
    """Initialize database and services."""
    db_manager = DatabaseManager(DB_PATH)
    conn = db_manager.connect()
    db_manager.init_schema()

    ensure_owner_user(conn, OWNER_USERNAME, OWNER_PASSWORD, strict=True)
    
    # Load sample data
    if LOAD_SEED_DATA:
        loader = DataLoader(conn)
        loader.load_from_excel()
    else:
        logger.info("Seed data load skipped (LOAD_SEED_DATA=false)")

    db_manager.close()
    logger.info("FastAPI application initialized successfully")


def shutdown_app():
    """Shutdown and cleanup."""
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


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page."""
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", template_context(request))


@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    conn: sqlite3.Connection = Depends(get_db)
):
    """Authenticate user and create session."""
    repo = UserRepository(conn)
    try:
        validate_password_length(password)
    except ValueError:
        return templates.TemplateResponse(
            "login.html",
            template_context(request, error="Invalid username or password"),
            status_code=401
        )
    user = repo.get_by_username(username.strip())
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "login.html",
            template_context(request, error="Invalid username or password"),
            status_code=401
        )

    request.session["user_id"] = user.id
    repo.update_last_login(user.id)
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    """Clear user session."""
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


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
        capacities = sorted(set(g.capacity_kva for g in generators))
        vendors = vendor_repo.get_all()
        
        # Count confirmed bookings and generators
        confirmed_bookings = len([b for b in bookings if b.status == STATUS_CONFIRMED])
        active_generators = len([g for g in generators if g.status == GEN_STATUS_ACTIVE])
        total_vendors = len(vendors)
        
        return templates.TemplateResponse("index.html", template_context(
            request,
            total_bookings=len(bookings),
            confirmed_bookings=confirmed_bookings,
            total_generators=len(generators),
            active_generators=active_generators,
            total_vendors=total_vendors,
        ))
    except Exception as e:
        logger.error(f"Error loading dashboard: {e}", exc_info=True)
        return templates.TemplateResponse("error.html", template_context(request, error=str(e)))


@app.get("/generators", response_class=HTMLResponse)
async def generators_page(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """Generators list page."""
    try:
        gen_repo = GeneratorRepository(conn)
        generators = gen_repo.get_all()
        return templates.TemplateResponse("generators.html", template_context(
            request,
            generators=generators
        ))
    except Exception as e:
        logger.error(f"Error loading generators page: {e}", exc_info=True)
        return templates.TemplateResponse("error.html", template_context(request, error=str(e)))


@app.get("/vendors", response_class=HTMLResponse)
async def vendors_page(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """Vendors list page."""
    try:
        vendor_repo = VendorRepository(conn)
        vendors = vendor_repo.get_all()
        return templates.TemplateResponse("vendors.html", template_context(
            request,
            vendors=vendors
        ))
    except Exception as e:
        logger.error(f"Error loading vendors page: {e}", exc_info=True)
        return templates.TemplateResponse("error.html", template_context(request, error=str(e)))


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
        
        return templates.TemplateResponse("bookings.html", template_context(
            request,
            bookings_by_vendor=sorted_vendors
        ))
    except Exception as e:
        logger.error(f"Error loading bookings page: {e}", exc_info=True)
        return templates.TemplateResponse("error.html", template_context(request, error=str(e)))


@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """Booking history page."""
    try:
        history_repo = BookingHistoryRepository(conn)
        vendor_repo = VendorRepository(conn)
        booking_repo = BookingRepository(conn)
        gen_repo = GeneratorRepository(conn)
        events = history_repo.get_all(limit=500)
        generator_cache: Dict[str, Optional[int]] = {}

        def get_capacity(generator_id: str) -> Optional[int]:
            if generator_id in generator_cache:
                return generator_cache[generator_id]
            gen = gen_repo.get_by_id(generator_id)
            capacity = gen.capacity_kva if gen else None
            generator_cache[generator_id] = capacity
            return capacity

        def extract_generators(details: str) -> List[str]:
            if not details:
                return []
            match = re.search(r"generators=([^ ]+)", details)
            if match:
                raw = match.group(1)
                return [part.strip() for part in raw.split(",") if part.strip()]
            match = re.search(r"generator_id=([^ ]+)", details)
            if match:
                return [match.group(1).strip()]
            return []

        def extract_items(details: str) -> List[Dict[str, str]]:
            if not details:
                return []
            if "items=" in details:
                items_part = details.split("items=", 1)[1].split(" ", 1)[0]
                entries = []
                for token in items_part.split(";"):
                    token = token.strip()
                    if not token:
                        continue
                    if "|" in token:
                        generator_id, date_part = token.split("|", 1)
                    else:
                        generator_id, date_part = token, ""
                    entries.append({
                        "generator_id": generator_id.strip(),
                        "date": date_part.strip()
                    })
                return entries
            fallback = extract_generators(details)
            return [{"generator_id": gen_id, "date": ""} for gen_id in fallback]

        event_action_labels = {
            "booking_created": "Genset Added",
            "booking_merged": "Genset Added",
            "booking_item_added": "Genset Added",
            "booking_items_updated": "Genset Updated",
            "booking_times_modified": "Genset Updated",
            "booking_cancelled": "Genset Cancelled",
            "booking_deleted": "Genset Removed",
        }

        history_rows = []
        for event in events:
            vendor_name = "-"
            vendor_id = event.vendor_id
            if vendor_id:
                vendor = vendor_repo.get_by_id(vendor_id)
                vendor_name = vendor.vendor_name if vendor else vendor_id
            elif event.booking_id:
                booking = booking_repo.get_by_id(event.booking_id)
                if booking:
                    vendor = vendor_repo.get_by_id(booking.vendor_id)
                    vendor_name = vendor.vendor_name if vendor else booking.vendor_id

            items = extract_items(event.details)
            if not items and event.booking_id:
                booking_items = booking_repo.get_items(event.booking_id)
                items = [{
                    "generator_id": item.generator_id,
                    "date": item.start_dt.split()[0] if item.start_dt else ""
                } for item in booking_items]

            generator_ids = [item["generator_id"] for item in items if item.get("generator_id")]
            generator_summary = "\n".join(sorted(set(generator_ids))) if generator_ids else "-"

            formatted_entries = []
            for item in items:
                generator_id = item.get("generator_id")
                if not generator_id:
                    continue
                capacity = get_capacity(generator_id)
                capacity_label = f" ({capacity}kVA)" if capacity else ""
                date_label = item.get("date") or "-"
                formatted_entries.append(f"{generator_id}{capacity_label} [{date_label}]")

            genset_count = len(formatted_entries)
            generator_list_display = "\n".join(formatted_entries) if formatted_entries else "-"
            action_label = event_action_labels.get(event.event_type, "Genset Updated")
            details_display = (
                f"{action_label} = {genset_count}\n"
                f"Generator(s) = {generator_list_display}\n"
                f"Vendor = {vendor_name}"
            )
            history_rows.append({
                "event_time": event.event_time,
                "event_type": event.event_type,
                "user": event.user or "-",
                "vendor_name": vendor_name,
                "generators": generator_summary,
                "summary": event.summary or "",
                "details_display": details_display
            })

        return templates.TemplateResponse("history.html", template_context(
            request,
            events=history_rows
        ))
    except Exception as e:
        logger.error(f"Error loading history page: {e}", exc_info=True)
        return templates.TemplateResponse("error.html", template_context(request, error=str(e)))


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
        
        return templates.TemplateResponse("create_booking.html", template_context(
            request,
            vendors=vendors,
            generators=generators,
            capacities=capacities
        ))
    except Exception as e:
        logger.error(f"Error loading create booking page: {e}", exc_info=True)
        return templates.TemplateResponse("error.html", template_context(request, error=str(e)))


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
            return templates.TemplateResponse("error.html", template_context(request, error=str(e)))
        
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
        
        return templates.TemplateResponse("booking_detail.html", template_context(
            request,
            booking=booking,
            vendor=vendor,
            items=items_with_gen
        ))
    except Exception as e:
        logger.error(f"Error loading booking detail: {e}", exc_info=True)
        return templates.TemplateResponse("error.html", template_context(request, error=str(e)))


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
            return templates.TemplateResponse("error.html", template_context(request, error=str(e)))
        
        vendor = vendor_repo.get_by_id(booking.vendor_id)
        items = booking_repo.get_items(booking_id)
        generators = gen_repo.get_all()
        capacities = sorted(set(g.capacity_kva for g in generators))
        
        # Enrich items with generator info
        items_with_gen = []
        for item in items:
            gen = gen_repo.get_by_id(item.generator_id)
            items_with_gen.append({
                "item": item,
                "generator_name": f"{gen.generator_id} ({gen.capacity_kva} kVA)" if gen else "Unknown"
            })
        
        return templates.TemplateResponse("edit_booking.html", template_context(
            request,
            booking=booking,
            vendor=vendor,
            items=items_with_gen,
            generators=generators,
            capacities=capacities
        ))
    except Exception as e:
        logger.error(f"Error loading edit booking page: {e}", exc_info=True)
        return templates.TemplateResponse("error.html", template_context(request, error=str(e)))


# ============================================================================
# ADMIN - USER MANAGEMENT
# ============================================================================

@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
    _: Any = Depends(require_role(ROLE_ADMIN))
):
    """Admin user management page."""
    repo = UserRepository(conn)
    users = repo.list_all()
    message = request.query_params.get("message")
    error = request.query_params.get("error")
    return templates.TemplateResponse(
        "users.html",
        template_context(request, users=users, message=message, error=error)
    )


@app.post("/admin/users/create")
async def admin_create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    conn: sqlite3.Connection = Depends(get_db),
    _: Any = Depends(require_role(ROLE_ADMIN))
):
    """Create a new user account."""
    from urllib.parse import quote

    username = username.strip()
    role = role.strip().lower()
    if not username or not password:
        return RedirectResponse(
            f"/admin/users?error={quote('Username and password are required')}",
            status_code=303
        )
    try:
        validate_password_length(password)
    except ValueError as e:
        return RedirectResponse(
            f"/admin/users?error={quote(str(e))}",
            status_code=303
        )
    if role not in ALLOWED_ROLES:
        return RedirectResponse(
            f"/admin/users?error={quote('Invalid role')}",
            status_code=303
        )

    repo = UserRepository(conn)
    if repo.get_by_username(username):
        return RedirectResponse(
            f"/admin/users?error={quote('Username already exists')}",
            status_code=303
        )

    password_hash = hash_password(password)
    repo.create_user(username, password_hash, role=role, is_active=True)
    return RedirectResponse(
        f"/admin/users?message={quote('User created successfully')}",
        status_code=303
    )


@app.post("/admin/users/{user_id}/update")
async def admin_update_user(
    request: Request,
    user_id: int,
    role: str = Form(...),
    is_active: Optional[str] = Form(default=None),
    conn: sqlite3.Connection = Depends(get_db),
    current_user: Any = Depends(require_role(ROLE_ADMIN))
):
    """Update a user's role or active status."""
    from urllib.parse import quote

    role = role.strip().lower()
    if role not in ALLOWED_ROLES:
        return RedirectResponse(
            f"/admin/users?error={quote('Invalid role')}",
            status_code=303
        )

    repo = UserRepository(conn)
    user = repo.get_by_id(user_id)
    if not user:
        return RedirectResponse(
            f"/admin/users?error={quote('User not found')}",
            status_code=303
        )

    active_flag = is_active == "on"

    # Prevent locking out the last active admin
    if user.role == ROLE_ADMIN and (role != ROLE_ADMIN or not active_flag):
        active_admins = repo.count_active_admins(ROLE_ADMIN)
        if active_admins <= 1:
            return RedirectResponse(
                f"/admin/users?error={quote('Cannot remove or deactivate the last admin')}",
                status_code=303
            )

    # Prevent self-demotion or deactivation
    if user.id == current_user.id and (role != ROLE_ADMIN or not active_flag):
        return RedirectResponse(
            f"/admin/users?error={quote('You cannot remove or deactivate your own admin access')}",
            status_code=303
        )

    repo.update_role(user_id, role)
    repo.update_active(user_id, active_flag)

    return RedirectResponse(
        f"/admin/users?message={quote('User updated successfully')}",
        status_code=303
    )


@app.post("/admin/users/{user_id}/password")
async def admin_reset_password(
    request: Request,
    user_id: int,
    new_password: str = Form(...),
    conn: sqlite3.Connection = Depends(get_db),
    _: Any = Depends(require_role(ROLE_ADMIN))
):
    """Reset a user's password."""
    from urllib.parse import quote

    if not new_password:
        return RedirectResponse(
            f"/admin/users?error={quote('Password cannot be empty')}",
            status_code=303
        )
    try:
        validate_password_length(new_password)
    except ValueError as e:
        return RedirectResponse(
            f"/admin/users?error={quote(str(e))}",
            status_code=303
        )

    repo = UserRepository(conn)
    user = repo.get_by_id(user_id)
    if not user:
        return RedirectResponse(
            f"/admin/users?error={quote('User not found')}",
            status_code=303
        )

    repo.update_password(user_id, hash_password(new_password))
    return RedirectResponse(
        f"/admin/users?message={quote('Password updated successfully')}",
        status_code=303
    )

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
            (date, STATUS_CONFIRMED, STATUS_CONFIRMED),
        )

        vendors: Dict[str, Dict[str, Any]] = {}
        for row in cur.fetchall():
            vendor_id, vendor_name, booking_id, generator_id, capacity_kva, start_dt, end_dt, remarks = row
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
                "capacity_kva": capacity_kva,
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
    _: Any = Depends(require_role(ROLE_ADMIN)),
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
    request: Request,
    request_data: CreateBookingRequest,
    _: Any = Depends(require_role(ROLE_ADMIN, ROLE_OPERATOR)),
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
        booking_id = service.create_booking(vendor_id, items, actor=get_actor(request))
        
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
    request: Request,
    booking_id: str,
    reason: str = Form(default="Cancelled via web"),
    _: Any = Depends(require_role(ROLE_ADMIN, ROLE_OPERATOR)),
    conn: sqlite3.Connection = Depends(get_db)
):
    """Cancel a booking."""
    try:
        service = BookingService(conn)
        success, msg = service.cancel_booking(booking_id, reason, actor=get_actor(request))
        
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
    request: Request,
    booking_id: str,
    _: Any = Depends(require_role(ROLE_ADMIN)),
    conn: sqlite3.Connection = Depends(get_db)
):
    """Delete a booking completely."""
    try:
        booking_repo = BookingRepository(conn)
        try:
            booking = ensure_booking(booking_repo, booking_id, message="Booking not found")
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
        
        log_booking_history(
            conn,
            event_type="booking_deleted",
            booking_id=booking_id,
            vendor_id=booking.vendor_id,
            user=get_actor(request),
            summary="Booking deleted",
            details=encode_history_items(
                [{"generator_id": item.generator_id, "start_dt": item.start_dt} for item in items]
            )
        )
        logger.info(f"Booking deleted | context={{'booking_id': '{booking_id}'}}")
        return {"success": True, "message": f"Booking {booking_id} deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting booking: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/bookings/{booking_id}/items")
async def api_add_booking_item(
    request: Request,
    booking_id: str,
    generator_id: Optional[str] = Form(default=None),
    capacity_kva: Optional[int] = Form(default=None),
    start_dt: str = Form(...),
    end_dt: str = Form(...),
    remarks: str = Form(default=""),
    _: Any = Depends(require_role(ROLE_ADMIN, ROLE_OPERATOR)),
    conn: sqlite3.Connection = Depends(get_db)
):
    """Add a new generator to an existing booking."""
    try:
        booking_repo = BookingRepository(conn)
        try:
            ensure_booking(booking_repo, booking_id, message="Booking not found")
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        
        generator_id = generator_id.strip() if generator_id else None
        if not generator_id and capacity_kva is None:
            raise HTTPException(status_code=400, detail="Provide generator_id or capacity_kva")

        service = BookingService(conn)
        # Add generator to booking
        success, message = service.add_generator(
            booking_id,
            generator_id=generator_id,
            capacity_kva=capacity_kva,
            start_dt=start_dt,
            end_dt=end_dt,
            remarks=remarks,
            actor=get_actor(request)
        )
        
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
    request: Request,
    booking_id: str,
    request_data: Dict[str, Any],
    _: Any = Depends(require_role(ROLE_ADMIN, ROLE_OPERATOR)),
    conn: sqlite3.Connection = Depends(get_db)
):
    """Update multiple booking items and remove items."""
    try:
        booking_repo = BookingRepository(conn)
        try:
            booking = ensure_booking(booking_repo, booking_id, message="Booking not found")
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        
        cur = conn.cursor()
        
        updates = request_data.get("updates", [])
        removes = request_data.get("removes", [])

        availability = AvailabilityChecker(conn)
        history_items: List[Dict[str, str]] = []
        if updates or removes:
            for update in updates:
                item_id = update.get("id")
                start_dt = update.get("start_dt")
                end_dt = update.get("end_dt")

                if not item_id:
                    raise HTTPException(status_code=400, detail="Update item missing id")
                if not start_dt or not end_dt:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Update item {item_id}: start_dt and end_dt are required"
                    )

                cur.execute(
                    "SELECT generator_id FROM booking_items WHERE id = ?",
                    (item_id,)
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail=f"Booking item {item_id} not found")

                generator_id = row[0]
                try:
                    is_available, conflict = availability.is_available(
                        generator_id,
                        start_dt,
                        end_dt,
                        exclude_booking_id=booking_id
                    )
                except ValueError as e:
                    raise HTTPException(status_code=400, detail=f"Update item {item_id}: {e}")

                if not is_available:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Update item {item_id}: Generator {generator_id} not available. Conflict: {conflict}"
                    )

                history_items.append({
                    "generator_id": generator_id,
                    "start_dt": start_dt
                })

            for item_id in removes:
                try:
                    cur.execute(
                        "SELECT generator_id, start_dt FROM booking_items WHERE id = ?",
                        (item_id,)
                    )
                    row = cur.fetchone()
                    if row:
                        history_items.append({
                            "generator_id": row[0],
                            "start_dt": row[1]
                        })
                except Exception:
                    logger.warning(
                        f"Unable to load booking item for history | context={{'id': {item_id}}}",
                        exc_info=True
                    )
        
        with transaction(conn):
            for update in updates:
                cur.execute(
                    "UPDATE booking_items SET start_dt = ?, end_dt = ?, remarks = ? WHERE id = ?",
                    (update["start_dt"], update["end_dt"], update["remarks"], update["id"])
                )
            
            # Remove items
            for item_id in removes:
                cur.execute("DELETE FROM booking_items WHERE id = ?", (item_id,))
        
        if updates or removes:
            log_booking_history(
                conn,
                event_type="booking_items_updated",
                booking_id=booking_id,
                vendor_id=booking.vendor_id,
                user=get_actor(request),
                summary="Booking items updated",
                details=encode_history_items(history_items)
            )
        logger.info(f"Booking items updated | context={{'booking_id': '{booking_id}', 'updates': {len(updates)}, 'removes': {len(removes)}}}")
        return {"success": True, "message": "Items updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating items: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/export")
async def api_export(
    conn: sqlite3.Connection = Depends(get_db),
    _: Any = Depends(require_role(ROLE_ADMIN))
):
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
