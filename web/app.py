"""
FastAPI web application for Generator Booking Ledger.
"""

from fastapi import FastAPI, Request, HTTPException, Form, Depends, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exceptions import RequestValidationError
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import os
import json
import sqlite3
import time
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any, Tuple
import logging
import re
import hashlib
from pydantic import BaseModel, Field, field_validator
import jwt
try:
    import psutil
except ImportError:  # pragma: no cover - handled at runtime
    psutil = None

from core import (
    Generator,
    Vendor,
    RentalVendor,
    DatabaseManager,
    BookingService,
    DataLoader,
    ExportService,
    AvailabilityChecker,
    GeneratorRepository,
    VendorRepository,
    RentalVendorRepository,
    BookingRepository,
    BookingHistoryRepository,
    UserRepository,
    normalize_generator_inventory_type,
)
from core.repositories import SessionRepository, RevokedTokenRepository
from core.observability import (
    begin_request_observation,
    connect_sqlite,
    end_request_observation,
    get_request_db_metrics,
)
from core.utils import transaction, now_ts
from core.validation import ensure_booking
from core.services import (
    create_vendor,
    create_rental_vendor,
    archive_all_bookings,
    log_booking_history,
    encode_history_items,
    RetailerOutOfStockError,
)
from core.auth import (
    hash_password,
    verify_password,
    ensure_owner_user,
    validate_password_length,
    generate_session_id,
    generate_csrf_token,
    create_access_token,
    decode_access_token,
)
from core.permissions import (
    ALL_CAPABILITY_KEYS,
    EDITABLE_CAPABILITY_KEYS,
    PERMISSION_MATRIX_CAPABILITIES,
    CAPABILITY_BILLING_ACCESS,
    CAPABILITY_BOOKING_CREATE_UPDATE,
    CAPABILITY_BOOKING_DELETE,
    CAPABILITY_EXPORT_ACCESS,
    CAPABILITY_GENERATOR_MANAGEMENT,
    CAPABILITY_MONITOR_ACCESS,
    CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS,
    CAPABILITY_SETTINGS_USER_ADMIN,
    CAPABILITY_VENDOR_MANAGEMENT,
    resolve_configured_permissions,
    resolve_effective_permissions,
    role_default_permissions,
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
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_SECURE,
    SESSION_TTL_MINUTES,
    JWT_SECRET,
    JWT_ALGORITHM,
    JWT_EXPIRE_MINUTES,
    CSRF_HEADER_NAME,
    ENABLE_HSTS,
    OWNER_USERNAME,
    OWNER_PASSWORD,
    ROLE_ADMIN,
    ROLE_OPERATOR,
    APP_TITLE,
    APP_VERSION,
    STATUS_CONFIRMED,
    STATUS_PENDING,
    STATUS_CANCELLED,
    GEN_STATUS_ACTIVE,
    GEN_STATUS_INACTIVE,
    GEN_STATUS_MAINTENANCE,
    GEN_INVENTORY_RETAILER,
    GEN_INVENTORY_EMERGENCY,
    DATETIME_FORMAT,
)
setup_logging()

logger = logging.getLogger(__name__)

GENERATOR_INVENTORY_LABELS = {
    GEN_INVENTORY_RETAILER: "Retailer Genset",
    GEN_INVENTORY_EMERGENCY: "Emergency Genset",
}

# Pydantic models for request bodies
class BookingItem(BaseModel):
    generator_id: Optional[str] = Field(None, max_length=50)
    capacity_kva: Optional[int] = Field(None, gt=0)  # Must be > 0
    date: str = Field(..., max_length=50)
    remarks: str = Field(default="", max_length=500)

    @field_validator('generator_id')
    @classmethod
    def validate_generator_id(cls, v):
        if v is not None and len(v.strip()) == 0:
            raise ValueError('Generator ID cannot be empty string')
        return v

    @field_validator('date')
    @classmethod
    def validate_date(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Date cannot be empty')
        return v

    @field_validator('remarks')
    @classmethod
    def validate_remarks(cls, v):
        if '<' in v or '>' in v or 'script' in v.lower():
            raise ValueError('HTML/script tags not allowed in remarks')
        return v


class CreateBookingRequest(BaseModel):
    vendor_id: str = Field(..., min_length=1, max_length=50)
    items: List[BookingItem] = Field(..., min_items=1)

    @field_validator('vendor_id')
    @classmethod
    def validate_vendor_id(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Vendor ID cannot be empty')
        return v.strip()


class CreateVendorRequest(BaseModel):
    vendor_id: Optional[str] = Field(None, max_length=50)
    vendor_name: str = Field(..., min_length=1, max_length=200)
    vendor_place: str = Field(default="Civil Line", max_length=200)
    phone: str = Field(default="", max_length=20)

    @field_validator('vendor_name')
    @classmethod
    def validate_vendor_name(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Vendor name cannot be empty')
        if '<' in v or '>' in v or 'script' in v.lower():
            raise ValueError('HTML/script tags not allowed in vendor name')
        return v.strip()

    @field_validator('vendor_place')
    @classmethod
    def validate_vendor_place(cls, v):
        if v and ('<' in v or '>' in v or 'script' in v.lower()):
            raise ValueError('HTML/script tags not allowed in vendor place')
        return v

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v):
        if v and not re.match(r'^[\d\-\+\s\(\)]*$', v):
            raise ValueError('Phone number contains invalid characters')
        return v


class CreateRentalVendorRequest(BaseModel):
    rental_vendor_id: Optional[str] = Field(None, max_length=50)
    vendor_name: str = Field(..., min_length=1, max_length=200)
    vendor_place: str = Field(default="Civil Line", max_length=200)
    phone: str = Field(default="", max_length=20)

    @field_validator('rental_vendor_id')
    @classmethod
    def validate_rental_vendor_id(cls, v):
        if v is not None and len(v.strip()) == 0:
            raise ValueError('Rental Vendor ID cannot be empty string')
        return v

    @field_validator('vendor_name')
    @classmethod
    def validate_vendor_name(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Vendor name cannot be empty')
        if '<' in v or '>' in v or 'script' in v.lower():
            raise ValueError('HTML/script tags not allowed in vendor name')
        return v.strip()

    @field_validator('vendor_place')
    @classmethod
    def validate_vendor_place(cls, v):
        if v and ('<' in v or '>' in v or 'script' in v.lower()):
            raise ValueError('HTML/script tags not allowed in vendor place')
        return v

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v):
        if v and not re.match(r'^[\d\-\+\s\(\)]*$', v):
            raise ValueError('Phone number contains invalid characters')
        return v


class UpdateVendorRequest(BaseModel):
    vendor_name: str = Field(..., min_length=1, max_length=200)
    vendor_place: str = Field(default="Civil Line", max_length=200)
    phone: str = Field(default="", max_length=20)

    @field_validator('vendor_name')
    @classmethod
    def validate_vendor_name(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Vendor name cannot be empty')
        if '<' in v or '>' in v or 'script' in v.lower():
            raise ValueError('HTML/script tags not allowed in vendor name')
        return v.strip()

    @field_validator('vendor_place')
    @classmethod
    def validate_vendor_place(cls, v):
        if v and ('<' in v or '>' in v or 'script' in v.lower()):
            raise ValueError('HTML/script tags not allowed in vendor place')
        return v

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v):
        if v and not re.match(r'^[\d\-\+\s\(\)]*$', v):
            raise ValueError('Phone number contains invalid characters')
        return v


class CreateGeneratorRequest(BaseModel):
    capacity_kva: int = Field(..., gt=0)  # Must be > 0
    type: str = Field(..., min_length=1, max_length=100)
    identification: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=500)
    status: Optional[str] = Field(default=GEN_STATUS_ACTIVE, max_length=50)
    inventory_type: str = Field(default=GEN_INVENTORY_RETAILER, max_length=50)

    @field_validator('type')
    @classmethod
    def validate_type(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Generator type cannot be empty')
        if '<' in v or '>' in v or 'script' in v.lower():
            raise ValueError('HTML/script tags not allowed in type')
        return v.strip()

    @field_validator('identification')
    @classmethod
    def validate_identification(cls, v):
        if v and ('<' in v or '>' in v or 'script' in v.lower()):
            raise ValueError('HTML/script tags not allowed in identification')
        return v

    @field_validator('notes')
    @classmethod
    def validate_notes(cls, v):
        if v and ('<' in v or '>' in v or 'script' in v.lower()):
            raise ValueError('HTML/script tags not allowed in notes')
        return v

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        if v and v not in [GEN_STATUS_ACTIVE, GEN_STATUS_INACTIVE, GEN_STATUS_MAINTENANCE]:
            raise ValueError(f'Status must be one of: {GEN_STATUS_ACTIVE}, {GEN_STATUS_INACTIVE}, {GEN_STATUS_MAINTENANCE}')
        return v

    @field_validator('inventory_type')
    @classmethod
    def validate_inventory_type(cls, v):
        normalized = (v or "").strip().lower()
        if normalized not in {GEN_INVENTORY_RETAILER, GEN_INVENTORY_EMERGENCY}:
            raise ValueError(
                f'Inventory type must be one of: {GEN_INVENTORY_RETAILER}, {GEN_INVENTORY_EMERGENCY}'
            )
        return normalized


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=100)

    @field_validator('username')
    @classmethod
    def validate_username(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Username cannot be empty')
        if len(v) > 50:
            raise ValueError('Username too long')
        return v.strip()

    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Password cannot be empty')
        if len(v) > 72:
            raise ValueError('Password too long (bcrypt limit is 72 chars)')
        return v

# FastAPI app
app = FastAPI(title=APP_TITLE, version=APP_VERSION)

# Rate limiter configuration
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda request, exc: JSONResponse(
    status_code=429,
    content={"detail": "Too many requests. Please try again later."}
))

if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET must be set for production authentication")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET must be set for API authentication")

PUBLIC_PATHS = {
    "/login",
    "/api/login",
    "/health",
    "/api/info",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/openapi.json",
}
PUBLIC_PREFIXES = ("/static",)
CSRF_EXEMPT_PATHS = {
    "/login",
    "/api/login",
    "/health",
}
ALLOWED_ROLES = {ROLE_ADMIN, ROLE_OPERATOR}
MONITOR_CPU_HIGH_THRESHOLD = 80.0
MONITOR_CPU_CRITICAL_THRESHOLD = 90.0
MONITOR_MEMORY_HIGH_THRESHOLD = 80.0
MONITOR_MEMORY_CRITICAL_THRESHOLD = 90.0
MONITOR_TEMP_HIGH_THRESHOLD = 75.0
MONITOR_TEMP_CRITICAL_THRESHOLD = 85.0
MONITOR_TEMP_PREFERRED_SENSORS = ("coretemp", "cpu_thermal", "k10temp")

HISTORY_EVENT_CATEGORY_SETS = {
    "added": {"booking_created", "booking_merged", "booking_item_added"},
    "updated": {"booking_items_updated", "booking_times_modified"},
    "cancelled": {"booking_cancelled"},
    "removed": {"booking_deleted"},
}
HISTORY_EVENT_ACTION_LABELS = {
    "booking_created": "Genset Added",
    "booking_merged": "Genset Added",
    "booking_item_added": "Genset Added",
    "booking_items_updated": "Genset Updated",
    "booking_times_modified": "Genset Updated",
    "booking_cancelled": "Genset Cancelled",
    "booking_deleted": "Genset Removed",
}
EMPTY_PERMISSION_MAP = {
    capability_key: False
    for capability_key in ALL_CAPABILITY_KEYS
}

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
    if is_api_request(request):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return templates.TemplateResponse(
        "error.html",
        template_context(request, error=exc.detail),
        status_code=exc.status_code
    )

# Helper function for secure error handling
def handle_error(
    error: Exception,
    status_code: int = 500,
    message: str = "An error occurred",
    log_details: bool = True
) -> Tuple[str, int]:
    """
    Handle errors securely by logging details server-side
    and returning generic messages to clients.

    Args:
        error: The exception to handle
        status_code: HTTP status code
        message: Generic message to return to client
        log_details: Whether to log exception details

    Returns:
        Tuple of (generic_message, status_code)
    """
    if log_details:
        logger.error(f"{message} (status={status_code}): {str(error)}", exc_info=True)
    return message, status_code

# Static files and templates
template_dir = os.path.join(os.path.dirname(__file__), "templates")
static_dir = os.path.join(os.path.dirname(__file__), "static")

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

templates = Jinja2Templates(directory=template_dir)


def _fetch_booking_items_with_capacity(
    conn: sqlite3.Connection,
    booking_id: str,
) -> List[Dict[str, Any]]:
    """Return booking items with optional generator capacity metadata."""
    booking_repo = BookingRepository(conn)
    return booking_repo.get_items_with_capacity(booking_id)


def _build_booking_date_rows(
    conn: sqlite3.Connection,
    booking_id: str,
) -> List[Dict[str, Any]]:
    """Group booking items by booked date and format date-row details."""
    items = _fetch_booking_items_with_capacity(conn, booking_id)
    grouped: Dict[str, List[Dict[str, Any]]] = {}

    for item in items:
        start_dt = item.get("start_dt", "")
        date_key = "N/A"
        if start_dt:
            candidate = start_dt.split()[0]
            if candidate:
                try:
                    datetime.strptime(candidate, "%Y-%m-%d")
                    date_key = candidate
                except ValueError:
                    date_key = "N/A"

        grouped.setdefault(date_key, []).append(item)

    date_keys = sorted(key for key in grouped if key != "N/A")
    if "N/A" in grouped:
        date_keys.append("N/A")

    rows: List[Dict[str, Any]] = []
    for date_key in date_keys:
        gensets = []
        status_values: List[str] = []
        for item in grouped[date_key]:
            generator_id = item.get("generator_id") or "Unknown"
            capacity_kva = item.get("capacity_kva")
            inventory_type = normalize_generator_inventory_type(item.get("inventory_type"))
            if capacity_kva is not None:
                label = f"{generator_id} ({capacity_kva} kVA)"
            else:
                label = generator_id

            item_status = (item.get("item_status") or "").strip()
            if item_status:
                status_values.append(item_status)

            gensets.append(
                {
                    "generator_id": generator_id,
                    "capacity_kva": capacity_kva,
                    "label": label,
                    "item_status": item_status,
                    "remarks": item.get("remarks", ""),
                    "start_dt": item.get("start_dt", ""),
                    "inventory_type": inventory_type,
                    "is_emergency": inventory_type == GEN_INVENTORY_EMERGENCY,
                }
            )

        distinct_statuses = sorted(set(status_values))
        if not distinct_statuses:
            status_label = "N/A"
            status_tone = "unknown"
        elif len(distinct_statuses) == 1:
            status_label = distinct_statuses[0]
            if status_label == STATUS_CONFIRMED:
                status_tone = "confirmed"
            elif status_label == STATUS_PENDING:
                status_tone = "pending"
            elif status_label == STATUS_CANCELLED:
                status_tone = "cancelled"
            else:
                status_tone = "mixed"
        else:
            status_label = " / ".join(distinct_statuses)
            status_tone = "mixed"

        rows.append(
            {
                "date": date_key,
                "gensets": gensets,
                "status_label": status_label,
                "status_tone": status_tone,
            }
        )

    if not rows:
        rows = [{
            "date": "N/A",
            "gensets": [],
            "status_label": "N/A",
            "status_tone": "unknown",
        }]

    return rows


def _build_booking_tree_block(conn: sqlite3.Connection, booking: Any) -> Dict[str, Any]:
    """Build the booking block shape required by the tree-style bookings table."""
    date_rows = _build_booking_date_rows(conn, booking.booking_id)
    return {
        "booking": booking,
        "rowspan": max(1, len(date_rows)),
        "date_rows": date_rows,
    }

def template_context(request: Request, **kwargs: Any) -> Dict[str, Any]:
    """Standard template context with user attached."""
    context = {
        "request": request,
        "user": getattr(request.state, "user", None),
        "csrf_token": getattr(request.state, "csrf_token", None),
        "permissions": getattr(request.state, "permissions", dict(EMPTY_PERMISSION_MAP)),
    }
    context.update(kwargs)
    return context


def is_api_request(request: Request) -> bool:
    """Determine whether this request expects JSON responses."""
    if request.url.path.startswith("/api"):
        return True
    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        return True
    if request.headers.get("x-requested-with", "").lower() == "xmlhttprequest":
        return True
    return False


def query_param(request: Request, key: str, default: Optional[str] = None) -> Optional[str]:
    """
    Safe query param getter for direct function calls in tests.
    """
    try:
        return request.query_params.get(key, default)
    except KeyError:
        return default


def _load_effective_permissions(conn: sqlite3.Connection, user: Any) -> Dict[str, bool]:
    if not user or getattr(user, "id", None) is None:
        return dict(EMPTY_PERMISSION_MAP)

    repo = UserRepository(conn)
    overrides = repo.list_permission_overrides(int(user.id))
    return resolve_effective_permissions(
        str(getattr(user, "role", "") or ""),
        bool(getattr(user, "is_active", False)),
        overrides,
    )


def get_current_permissions(request: Request) -> Dict[str, bool]:
    permissions = getattr(request.state, "permissions", None)
    if isinstance(permissions, dict):
        merged = dict(EMPTY_PERMISSION_MAP)
        for capability_key in ALL_CAPABILITY_KEYS:
            if capability_key in permissions:
                merged[capability_key] = bool(permissions[capability_key])
        return merged
    return dict(EMPTY_PERMISSION_MAP)


def unauthorized_response(request: Request, detail: str = "Unauthorized") -> JSONResponse | RedirectResponse:
    if is_api_request(request):
        return JSONResponse(status_code=401, content={"detail": detail})
    return RedirectResponse("/login", status_code=303)


def forbidden_response(request: Request, detail: str = "Forbidden") -> JSONResponse | HTMLResponse:
    if is_api_request(request):
        return JSONResponse(status_code=403, content={"detail": detail})
    return templates.TemplateResponse(
        "error.html",
        template_context(request, error=detail),
        status_code=403,
    )


def get_bearer_token(request: Request) -> Optional[str]:
    """Extract bearer token from Authorization header."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header:
        return None
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


async def validate_csrf(request: Request, expected_token: str) -> bool:
    """Validate CSRF token from header or form body."""
    header_token = (
        request.headers.get(CSRF_HEADER_NAME)
        or request.headers.get("x-csrf-token")
        or request.headers.get("x-csrftoken")
    )
    if header_token and header_token == expected_token:
        return True

    if request.method == "GET":
        query_token = request.query_params.get("csrf_token")
        return bool(query_token and query_token == expected_token)

    content_type = request.headers.get("content-type", "").lower()
    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        # Read once so the body is cached on the request. Starlette's cached
        # request wrapper will replay the cached body for downstream form
        # parsing, and its wrapped receive expects the next low-level message
        # to be a disconnect rather than another synthetic http.request.
        raw_body = await request.body()

        form_token: Optional[str] = None
        if "application/x-www-form-urlencoded" in content_type:
            from urllib.parse import parse_qs

            decoded = raw_body.decode("utf-8", errors="ignore")
            values = parse_qs(decoded, keep_blank_values=True)
            form_token = values.get("csrf_token", [None])[0]
        else:
            # Minimal multipart token extraction for hidden csrf_token form field.
            text = raw_body.decode("utf-8", errors="ignore")
            match = re.search(r'name="csrf_token"\r\n\r\n([^\r\n]+)', text)
            if match:
                form_token = match.group(1)

        return bool(form_token and form_token == expected_token)
    return False


def requires_csrf(request: Request) -> bool:
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        return True
    if request.method == "GET" and request.url.path == "/logout":
        return True
    return False


def authenticate_credentials(
    conn: sqlite3.Connection,
    username: Optional[str],
    password: Optional[str],
) -> Optional["User"]:
    if not username or not password:
        return None
    repo = UserRepository(conn)
    try:
        validate_password_length(password)
    except ValueError:
        return None
    user = repo.get_by_username(username.strip())
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def create_session(
    conn: sqlite3.Connection,
    user_id: int,
    request: Request,
) -> Tuple[str, str, int]:
    session_id = generate_session_id()
    csrf_token = generate_csrf_token()
    created_at = now_ts()
    expires_at = created_at + (SESSION_TTL_MINUTES * 60)
    repo = SessionRepository(conn)
    repo.create(
        session_id=session_id,
        user_id=user_id,
        csrf_token=csrf_token,
        created_at=created_at,
        expires_at=expires_at,
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
    )
    return session_id, csrf_token, expires_at


def _request_uses_https(request: Optional[Request]) -> bool:
    if request is None:
        return False

    scheme = str(request.scope.get("scheme", "")).lower()
    if scheme == "https":
        return True

    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    if forwarded_proto:
        return forwarded_proto.split(",")[0].strip().lower() == "https"
    return False


def _resolve_transport_security(setting: str, request: Optional[Request]) -> bool:
    if setting == "true":
        return True
    if setting == "false":
        return False
    return _request_uses_https(request)


def set_session_cookie(
    response: RedirectResponse,
    session_id: str,
    expires_at: int,
    request: Optional[Request] = None,
) -> None:
    max_age = max(0, expires_at - now_ts())
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        max_age=max_age,
        httponly=True,
        secure=_resolve_transport_security(SESSION_COOKIE_SECURE, request),
        samesite="strict",
        path="/",
    )


def clear_session_cookie(
    response: RedirectResponse | JSONResponse | HTMLResponse,
    request: Optional[Request] = None,
) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=_resolve_transport_security(SESSION_COOKIE_SECURE, request),
        samesite="strict",
    )


async def get_db(request: Request):
    """Dependency for getting a per-request database connection."""
    conn = getattr(request.state, "db", None)
    if conn:
        yield conn
        return

    conn = None
    try:
        conn = connect_sqlite(DB_PATH)
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
    except sqlite3.Error as e:
        logger.error(f"Database connection failed | context={{'db_path': '{DB_PATH}'}}", exc_info=True)
        raise HTTPException(status_code=500, detail="Database connection error")
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


def require_capability(capability_key: str):
    """Require the current user to have a specific effective capability."""
    def _checker(request: Request):
        user = get_current_user(request)
        permissions = get_current_permissions(request)
        if not permissions.get(capability_key, False):
            raise HTTPException(status_code=403, detail="Forbidden")
        return user
    return _checker


def require_login():
    """Require the current user to be logged in (any authenticated user)."""
    def _checker(request: Request):
        user = get_current_user(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return user
    return _checker


def get_actor(request: Request) -> str:
    """Return the username for audit logs."""
    user = getattr(request.state, "user", None)
    if user and getattr(user, "username", None):
        return user.username
    return "unknown"


def _new_db_connection() -> sqlite3.Connection:
    conn = connect_sqlite(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _initialize_auth_state(request: Request) -> None:
    request.state.user = None
    request.state.auth_type = None
    request.state.csrf_token = None
    request.state.session_id = None
    request.state.token_jti = None
    request.state.permissions = dict(EMPTY_PERMISSION_MAP)


def _apply_auth_state(request: Request, state: Dict[str, Any]) -> None:
    request.state.user = state.get("user")
    request.state.auth_type = state.get("auth_type")
    request.state.csrf_token = state.get("csrf_token")
    request.state.session_id = state.get("session_id")
    request.state.token_jti = state.get("token_jti")


def _delete_session_cookie(response: Any, request: Optional[Request] = None) -> None:
    """Delete session cookie from response, with safe handling for streaming responses."""
    secure = _resolve_transport_security(SESSION_COOKIE_SECURE, request)
    try:
        # Try to delete using the standard method for regular responses
        if hasattr(response, "delete_cookie"):
            response.delete_cookie(
                SESSION_COOKIE_NAME,
                path="/",
                samesite="strict",
                secure=secure,
                httponly=True,
            )
        # Fallback for streaming/special responses: manipulate headers directly
        elif hasattr(response, "headers"):
            secure_attr = "; Secure" if secure else ""
            response.headers.append(
                "Set-Cookie",
                f"{SESSION_COOKIE_NAME}=; Path=/; Max-Age=0; SameSite=strict{secure_attr}; HttpOnly"
            )
    except Exception as e:
        logger.warning(f"Failed to delete session cookie: {e}", exc_info=False)


def _authenticate_with_bearer_token(
    request: Request,
    conn: sqlite3.Connection
) -> Tuple[Optional[Dict[str, Any]], Optional[JSONResponse | RedirectResponse]]:
    auth_header = request.headers.get("authorization")
    if not auth_header:
        return None, None

    token = get_bearer_token(request)
    if not token:
        return None, unauthorized_response(request)

    try:
        payload = decode_access_token(token, JWT_SECRET, JWT_ALGORITHM, verify_exp=True)
    except jwt.ExpiredSignatureError:
        return None, unauthorized_response(request, detail="Token expired")
    except jwt.PyJWTError:
        return None, unauthorized_response(request, detail="Invalid token")

    jti = payload.get("jti")
    if not jti:
        return None, unauthorized_response(request, detail="Invalid token")

    revoked_repo = RevokedTokenRepository(conn)
    if revoked_repo.is_revoked(jti, now_ts()):
        return None, unauthorized_response(request, detail="Token revoked")

    user_id_raw = payload.get("sub")
    try:
        user_id = int(user_id_raw)
    except (TypeError, ValueError):
        return None, unauthorized_response(request, detail="Invalid token")

    user_repo = UserRepository(conn)
    user = user_repo.get_by_id(user_id)
    if not user or not user.is_active:
        return None, unauthorized_response(request, detail="Unauthorized")

    return {
        "user": user,
        "auth_type": "jwt",
        "token_jti": jti,
    }, None


def _authenticate_with_session_cookie(
    request: Request,
    conn: sqlite3.Connection
) -> Tuple[Dict[str, Any], bool]:
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        return {}, False

    clear_cookie = False
    session_repo = SessionRepository(conn)
    session = session_repo.get_by_id(session_id)
    if not session or session.expires_at <= now_ts():
        if session:
            session_repo.delete(session_id)
        clear_cookie = True
        return {}, clear_cookie

    user_repo = UserRepository(conn)
    user = user_repo.get_by_id(int(session.user_id))
    if not user or not user.is_active:
        session_repo.delete(session_id)
        clear_cookie = True
        return {}, clear_cookie

    session_repo.update_last_seen(session.session_id, now_ts())
    return {
        "user": user,
        "auth_type": "session",
        "csrf_token": session.csrf_token,
        "session_id": session.session_id,
    }, clear_cookie



@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)
    # Prevent clickjacking attacks
    response.headers["X-Frame-Options"] = "DENY"
    # Prevent MIME type sniffing
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Enable XSS protection
    response.headers["X-XSS-Protection"] = "1; mode=block"
    if _resolve_transport_security(ENABLE_HSTS, request):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # Content Security Policy - allow Tailwind CDN, Google Fonts, FullCalendar, and inline styles/scripts
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://fonts.googleapis.com https://cdn.jsdelivr.net; "
        "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net data:; "
        "img-src 'self' data: https:; "
        "connect-src 'self'"
    )
    return response


@app.middleware("http")
async def db_auth_middleware(request: Request, call_next):
    """Attach DB connection and enforce authentication for protected routes."""
    conn: Optional[sqlite3.Connection] = None
    response: Optional[JSONResponse | RedirectResponse | HTMLResponse] = None
    clear_cookie = False
    path = request.url.path
    request_started = time.perf_counter()
    observation_tokens = begin_request_observation(f"{request.method} {path}")
    try:
        conn = _new_db_connection()
        request.state.db = conn
        _initialize_auth_state(request)

        is_public = path in PUBLIC_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)

        jwt_auth_state, auth_error = _authenticate_with_bearer_token(request, conn)
        if auth_error:
            response = auth_error
            return response

        if jwt_auth_state:
            _apply_auth_state(request, jwt_auth_state)
        else:
            session_auth_state, clear_cookie = _authenticate_with_session_cookie(request, conn)
            _apply_auth_state(request, session_auth_state)

        if request.state.user:
            request.state.permissions = _load_effective_permissions(conn, request.state.user)

        if request.state.user and request.state.auth_type == "session":
            if requires_csrf(request) and path not in CSRF_EXEMPT_PATHS:
                if not await validate_csrf(request, request.state.csrf_token):
                    response = forbidden_response(request, detail="Invalid CSRF token")
                    return response

        if not request.state.user and not is_public:
            response = unauthorized_response(request)
            if clear_cookie:
                _delete_session_cookie(response, request)
            return response

        response = await call_next(request)
        if clear_cookie:
            _delete_session_cookie(response, request)
        return response
    finally:
        duration_ms = (time.perf_counter() - request_started) * 1000.0
        query_count, query_ms = get_request_db_metrics()
        logger.info(
            "Request completed | context=%s",
            {
                "method": request.method,
                "path": path,
                "status": getattr(response, "status_code", 500),
                "duration_ms": round(duration_ms, 2),
                "db_query_count": query_count,
                "db_query_ms": round(query_ms, 2),
            },
        )
        end_request_observation(observation_tokens)
        if conn:
            conn.close()


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

    # Cleanup expired sessions and revoked tokens on startup
    try:
        from core.repositories import SessionRepository, RevokedTokenRepository

        current_time = now_ts()

        session_repo = SessionRepository(conn)
        session_repo.delete_expired(current_time)
        logger.info("Startup cleanup: Expired sessions deleted")

        token_repo = RevokedTokenRepository(conn)
        token_repo.delete_expired(current_time)
        logger.info("Startup cleanup: Expired revoked tokens deleted")
    except Exception as e:
        logger.warning(f"Failed to cleanup expired sessions/tokens on startup: {e}", exc_info=False)

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


def _classify_resource_usage(value: float, high_threshold: float, critical_threshold: float) -> str:
    """Classify usage values into normal/high/critical."""
    if value >= critical_threshold:
        return "critical"
    if value >= high_threshold:
        return "high"
    return "normal"


def _build_temperature_unavailable(note: str) -> Dict[str, Any]:
    """Return a standardized payload when temperature is not available."""
    return {
        "available": False,
        "celsius": None,
        "sensor": None,
        "status": "unknown",
        "note": note,
    }


def _collect_temperature_metrics() -> Dict[str, Any]:
    """Collect server temperature from psutil sensors API."""
    if psutil is None:
        return _build_temperature_unavailable("Temperature monitor unavailable (psutil not installed)")

    if not hasattr(psutil, "sensors_temperatures"):
        return _build_temperature_unavailable("Temperature sensor API unavailable on this platform")

    try:
        sensor_map = psutil.sensors_temperatures(fahrenheit=False) or {}
    except (OSError, RuntimeError, AttributeError):
        logger.warning("Failed reading temperature sensors", exc_info=True)
        return _build_temperature_unavailable("Temperature sensor read failed")

    if not sensor_map:
        return _build_temperature_unavailable("Temperature sensor not available on this host")

    ordered_sensor_keys: List[str] = []
    for sensor_key in MONITOR_TEMP_PREFERRED_SENSORS:
        if sensor_key in sensor_map:
            ordered_sensor_keys.append(sensor_key)
    for sensor_key in sensor_map.keys():
        if sensor_key not in ordered_sensor_keys:
            ordered_sensor_keys.append(sensor_key)

    for sensor_key in ordered_sensor_keys:
        entries = sensor_map.get(sensor_key) or []
        for entry in entries:
            current = getattr(entry, "current", None)
            if current is None:
                continue
            try:
                temp_celsius = float(current)
            except (TypeError, ValueError):
                continue
            return {
                "available": True,
                "celsius": round(temp_celsius, 1),
                "sensor": sensor_key,
                "status": _classify_resource_usage(
                    temp_celsius,
                    MONITOR_TEMP_HIGH_THRESHOLD,
                    MONITOR_TEMP_CRITICAL_THRESHOLD,
                ),
                "note": "",
            }

    return _build_temperature_unavailable("Temperature sensor not available on this host")


def _collect_monitor_live_metrics() -> Dict[str, Any]:
    """Collect CPU, memory and temperature metrics for monitor view."""
    if psutil is None:
        raise RuntimeError("Monitor metrics backend unavailable (psutil not installed)")

    cpu_percent = float(psutil.cpu_percent(interval=None))
    memory = psutil.virtual_memory()
    memory_percent = float(memory.percent)
    used_mb = float(memory.used) / (1024 * 1024)
    total_mb = float(memory.total) / (1024 * 1024)
    temperature = _collect_temperature_metrics()

    return {
        "timestamp": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "cpu": {
            "percent": round(cpu_percent, 1),
            "status": _classify_resource_usage(
                cpu_percent,
                MONITOR_CPU_HIGH_THRESHOLD,
                MONITOR_CPU_CRITICAL_THRESHOLD,
            ),
        },
        "memory": {
            "percent": round(memory_percent, 1),
            "used_mb": round(used_mb, 1),
            "total_mb": round(total_mb, 1),
            "status": _classify_resource_usage(
                memory_percent,
                MONITOR_MEMORY_HIGH_THRESHOLD,
                MONITOR_MEMORY_CRITICAL_THRESHOLD,
            ),
        },
        "temperature": temperature,
    }


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page."""
    if getattr(request.state, "user", None):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", template_context(request))


@app.post("/login")
@limiter.limit("5/minute")
async def login(
    request: Request,
    username: Optional[str] = Form(None),
    password: Optional[str] = Form(None),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Authenticate user and create session or issue JWT."""
    is_json = "application/json" in request.headers.get("content-type", "").lower()
    if is_json:
        try:
            payload = await request.json()
        except (ValueError, RuntimeError):  # JSONDecodeError inherits from ValueError
            logger.warning("Failed to parse JSON payload in login request", exc_info=False)
            payload = {}
        username = payload.get("username")
        password = payload.get("password")

    user = authenticate_credentials(conn, username, password)
    if not user:
        if is_api_request(request) or is_json:
            return JSONResponse(status_code=401, content={"detail": "Invalid username or password"})
        return templates.TemplateResponse(
            "login.html",
            template_context(request, error="Invalid username or password"),
            status_code=401,
        )

    repo = UserRepository(conn)
    repo.update_last_login(user.id)

    if is_api_request(request) or is_json:
        token, exp_ts, _jti = create_access_token(
            user_id=user.id,
            username=user.username,
            role=user.role,
            secret=JWT_SECRET,
            algorithm=JWT_ALGORITHM,
            expires_minutes=JWT_EXPIRE_MINUTES,
        )
        return JSONResponse(
            status_code=200,
            content={
                "access_token": token,
                "token_type": "bearer",
                "expires_in": max(0, exp_ts - now_ts()),
                "user": {"id": user.id, "username": user.username, "role": user.role},
            },
        )

    session_id, _csrf_token, expires_at = create_session(conn, user.id, request)
    response = RedirectResponse("/", status_code=303)
    set_session_cookie(response, session_id, expires_at, request)
    return response


@app.post("/api/login")
@limiter.limit("5/minute")
async def api_login(
    request: Request,
    payload: LoginRequest,
    conn: sqlite3.Connection = Depends(get_db)
):
    """API login: issue JWT token."""
    user = authenticate_credentials(conn, payload.username, payload.password)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Invalid username or password"})

    repo = UserRepository(conn)
    repo.update_last_login(user.id)

    token, exp_ts, _jti = create_access_token(
        user_id=user.id,
        username=user.username,
        role=user.role,
        secret=JWT_SECRET,
        algorithm=JWT_ALGORITHM,
        expires_minutes=JWT_EXPIRE_MINUTES,
    )
    return JSONResponse(
        status_code=200,
        content={
            "access_token": token,
            "token_type": "bearer",
            "expires_in": max(0, exp_ts - now_ts()),
            "user": {"id": user.id, "username": user.username, "role": user.role},
        },
    )


@app.get("/logout")
async def logout(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """Clear user session (browser)."""
    if request.state.auth_type == "session" and request.state.session_id:
        SessionRepository(conn).delete(request.state.session_id)
    response = RedirectResponse("/login", status_code=303)
    clear_session_cookie(response, request)
    return response


@app.post("/api/logout")
async def api_logout(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """API logout: revoke JWT or clear session."""
    if request.state.auth_type == "jwt":
        token = get_bearer_token(request)
        if token:
            try:
                payload = decode_access_token(
                    token,
                    JWT_SECRET,
                    JWT_ALGORITHM,
                    verify_exp=False,
                )
                jti = payload.get("jti")
                exp = payload.get("exp")
                if jti and exp and int(exp) > now_ts():
                    RevokedTokenRepository(conn).revoke(jti, int(exp))
            except jwt.PyJWTError:
                pass

    if request.state.auth_type == "session" and request.state.session_id:
        SessionRepository(conn).delete(request.state.session_id)

    response = JSONResponse(status_code=200, content={"detail": "Logged out"})
    if request.state.auth_type == "session":
        clear_session_cookie(response, request)
    return response


# ============================================================================
# WEB PAGES
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
    _: Any = Depends(require_capability(CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS)),
):
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
async def generators_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
    _: Any = Depends(require_capability(CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS)),
):
    """Generators list page."""
    try:
        gen_repo = GeneratorRepository(conn)
        generators = gen_repo.get_all()
        retailer_generators = [
            gen for gen in generators if gen.inventory_type == GEN_INVENTORY_RETAILER
        ]
        emergency_generators = [
            gen for gen in generators if gen.inventory_type == GEN_INVENTORY_EMERGENCY
        ]
        capacities = sorted(set(g.capacity_kva for g in generators))

        selected_date = request.query_params.get("date")
        if selected_date:
            selected_date = selected_date.strip()
        if not selected_date or selected_date.lower() == "all":
            selected_date = None

        if selected_date:
            try:
                datetime.strptime(selected_date, "%Y-%m-%d")
            except ValueError:
                return templates.TemplateResponse(
                    "error.html",
                    template_context(
                        request,
                        error="Invalid date format. Please use YYYY-MM-DD."
                    )
                )

        booking_status = {}
        if selected_date:
            booking_repo = BookingRepository(conn)
            booked_ids = set(booking_repo.get_booked_generator_ids_for_date(selected_date))
            booking_status = {
                gen.generator_id: ("Booked" if gen.generator_id in booked_ids else "Free")
                for gen in generators
            }

        return templates.TemplateResponse("generators.html", template_context(
            request,
            generators=generators,
            retailer_generators=retailer_generators,
            emergency_generators=emergency_generators,
            booking_status=booking_status,
            selected_date=selected_date or "",
            capacities=capacities,
            inventory_labels=GENERATOR_INVENTORY_LABELS,
        ))
    except Exception as e:
        logger.error(f"Error loading generators page: {e}", exc_info=True)
        return templates.TemplateResponse("error.html", template_context(request, error=str(e)))


@app.get("/vendors", response_class=HTMLResponse)
async def vendors_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
    _: Any = Depends(require_capability(CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS)),
):
    """Vendors list page."""
    try:
        vendor_repo = VendorRepository(conn)
        rental_vendor_repo = RentalVendorRepository(conn)
        vendors = vendor_repo.get_all()
        rental_vendors = rental_vendor_repo.get_all()
        return templates.TemplateResponse("vendors.html", template_context(
            request,
            vendors=vendors,
            rental_vendors=rental_vendors,
        ))
    except Exception as e:
        logger.error(f"Error loading vendors page: {e}", exc_info=True)
        return templates.TemplateResponse("error.html", template_context(request, error=str(e)))


@app.get("/bookings", response_class=HTMLResponse)
async def bookings_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
    _: Any = Depends(require_capability(CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS)),
):
    """Bookings list page."""
    try:
        booking_repo = BookingRepository(conn)
        vendor_repo = VendorRepository(conn)
        
        bookings = booking_repo.get_all()
        
        # Group bookings by vendor with booking blocks and date-level rows.
        bookings_by_vendor = {}
        for booking in bookings:
            vendor = vendor_repo.get_by_id(booking.vendor_id)
            vendor_name = vendor.vendor_name if vendor else "Unknown"
            
            if vendor_name not in bookings_by_vendor:
                bookings_by_vendor[vendor_name] = {
                    "vendor_id": booking.vendor_id,
                    "bookings": []
                }

            bookings_by_vendor[vendor_name]["bookings"].append(
                _build_booking_tree_block(conn, booking)
            )
        
        # Sort vendors alphabetically
        sorted_vendors = sorted(bookings_by_vendor.items())
        
        return templates.TemplateResponse("bookings.html", template_context(
            request,
            bookings_by_vendor=sorted_vendors
        ))
    except Exception as e:
        logger.error(f"Error loading bookings page: {e}", exc_info=True)
        return templates.TemplateResponse("error.html", template_context(request, error=str(e)))


@app.get("/billing", response_class=HTMLResponse)
async def billing_page(
    request: Request,
    _: Any = Depends(require_capability(CAPABILITY_BILLING_ACCESS)),
):
    """Billing preview page."""
    try:
        return templates.TemplateResponse("billing.html", template_context(request))
    except Exception as e:
        logger.error(f"Error loading billing page: {e}", exc_info=True)
        return templates.TemplateResponse("error.html", template_context(request, error=str(e)))


def _history_event_category(event_type: str) -> str:
    """Map history event type to GitLens-style category."""
    for category, types in HISTORY_EVENT_CATEGORY_SETS.items():
        if event_type in types:
            return category
    return "other"


def _history_action_label(event_type: str) -> str:
    """Human-readable action label for history event type."""
    if event_type in HISTORY_EVENT_ACTION_LABELS:
        return HISTORY_EVENT_ACTION_LABELS[event_type]
    return event_type.replace("_", " ").title() if event_type else "Event"


def _history_short_hash(
    event_id: Optional[int],
    event_time: str,
    event_type: str,
    booking_id: Optional[str]
) -> str:
    """Generate a stable 7-char pseudo hash for history entries."""
    if isinstance(event_id, int):
        return f"{event_id:07x}"[-7:]

    seed = f"{event_time}|{event_type}|{booking_id or ''}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:7]


def _history_parse_time(event_time_raw: str) -> Tuple[Optional[datetime], str]:
    """Parse history event time and return datetime + ISO-like value."""
    if not event_time_raw:
        return None, ""

    candidate = event_time_raw.strip()
    parse_formats = (
        DATETIME_FORMAT,
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    )
    for fmt in parse_formats:
        try:
            dt = datetime.strptime(candidate, fmt)
            return dt, dt.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue

    try:
        normalized = candidate.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt, dt.strftime("%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None, ""


def _history_extract_generators(details: str) -> List[str]:
    """Extract generator ids from free-form history details."""
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


def _history_extract_items(details: str) -> List[Dict[str, str]]:
    """Extract generator/date tuples from history details."""
    if not details:
        return []
    if "items=" in details:
        items_part = details.split("items=", 1)[1].split(" ", 1)[0]
        entries: List[Dict[str, str]] = []
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
                "date": date_part.strip(),
            })
        return entries
    fallback = _history_extract_generators(details)
    return [{"generator_id": gen_id, "date": ""} for gen_id in fallback]


def _history_date_label(event_dt: Optional[datetime]) -> Tuple[str, str]:
    """Return stable date key + display label for grouping."""
    if not event_dt:
        return "unknown", "Unknown Date"

    event_date = event_dt.date()
    today = date.today()
    if event_date == today:
        label = "Today"
    elif event_date == today - timedelta(days=1):
        label = "Yesterday"
    else:
        label = event_dt.strftime("%d %b %Y")

    return event_date.isoformat(), label


def _history_group_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group history entries by date section while preserving order."""
    groups: List[Dict[str, Any]] = []
    group_map: Dict[str, Dict[str, Any]] = {}

    for raw_entry in entries:
        event_dt = raw_entry.get("_event_dt")
        date_key, date_label = _history_date_label(event_dt)

        if date_key not in group_map:
            group = {
                "date_key": date_key,
                "date_label": date_label,
                "entries": [],
            }
            group_map[date_key] = group
            groups.append(group)

        entry = dict(raw_entry)
        entry.pop("_event_dt", None)
        group_map[date_key]["entries"].append(entry)

    return groups


def _history_build_filter_chips(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build filter chip metadata with category counts."""
    categories = [
        ("all", "All"),
        ("added", "Added"),
        ("updated", "Updated"),
        ("cancelled", "Cancelled"),
        ("removed", "Removed"),
        ("other", "Other"),
    ]

    counts = {key: 0 for key, _label in categories}
    counts["all"] = len(entries)
    for entry in entries:
        category = entry.get("event_category", "other")
        if category in counts:
            counts[category] += 1

    chips = []
    for key, label in categories:
        chips.append({
            "key": key,
            "label": label,
            "count": counts.get(key, 0),
        })
    return chips


def _build_permission_matrix_rows() -> List[Dict[str, Any]]:
    """Return normalized permission matrix rows for the settings template."""
    rows: List[Dict[str, Any]] = []
    for row in PERMISSION_MATRIX_CAPABILITIES:
        rows.append({
            "key": row["key"],
            "label": row["label"],
            "description": row["description"],
            "endpoint_refs": list(row["endpoint_refs"]),
            "admin_allowed": bool(row["admin_allowed"]),
            "operator_allowed": bool(row["operator_allowed"]),
            "editable": bool(row.get("editable", True)),
        })
    return rows


def _resolve_effective_permission(
    role: str,
    is_active: bool,
    row: Dict[str, Any],
    overrides: Optional[Dict[str, bool]] = None,
) -> bool:
    """Resolve effective access from role + active state for a matrix row."""
    capability_key = str(row.get("key") or "").strip()
    if capability_key:
        permissions = resolve_effective_permissions(role, is_active, overrides or {})
        return bool(permissions.get(capability_key, False))

    if not is_active:
        return False

    normalized_role = (role or "").strip().lower()
    if normalized_role == ROLE_ADMIN:
        return bool(row.get("admin_allowed"))
    if normalized_role == ROLE_OPERATOR:
        return bool(row.get("operator_allowed"))
    return False


def _build_permission_matrix_users(
    users: List[Any],
    overrides_by_user: Optional[Dict[int, Dict[str, bool]]] = None,
) -> List[Dict[str, Any]]:
    """Normalize settings users for client-side effective-permission rendering."""
    rows: List[Dict[str, Any]] = []
    overrides_by_user = overrides_by_user or {}
    for user in users:
        user_id = getattr(user, "id", None)
        if user_id is None:
            continue
        normalized_role = str(getattr(user, "role", "") or "").strip().lower()
        is_active = bool(getattr(user, "is_active", False))
        user_overrides = overrides_by_user.get(int(user_id), {})
        configured_permissions = resolve_configured_permissions(
            normalized_role,
            user_overrides,
        )
        effective_permissions = resolve_effective_permissions(
            normalized_role,
            is_active,
            user_overrides,
        )
        rows.append({
            "id": int(user_id),
            "username": str(getattr(user, "username", "") or ""),
            "role": normalized_role,
            "is_active": is_active,
            "configured_permissions": configured_permissions,
            "effective_permissions": effective_permissions,
        })
    return rows


@app.get("/history", response_class=HTMLResponse)
async def history_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
    _: Any = Depends(require_capability(CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS)),
):
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

        history_entries: List[Dict[str, Any]] = []
        for event in events:
            vendor_name = "-"
            vendor_id = event.vendor_id or ""
            if vendor_id:
                vendor = vendor_repo.get_by_id(vendor_id)
                vendor_name = vendor.vendor_name if vendor else vendor_id
            elif event.booking_id:
                booking = booking_repo.get_by_id(event.booking_id)
                if booking:
                    vendor = vendor_repo.get_by_id(booking.vendor_id)
                    vendor_name = vendor.vendor_name if vendor else booking.vendor_id
                    vendor_id = booking.vendor_id or ""

            details_raw = event.details or ""
            items = _history_extract_items(details_raw)
            if not items and event.booking_id:
                booking_items = booking_repo.get_items(event.booking_id)
                items = [{
                    "generator_id": item.generator_id,
                    "date": item.start_dt.split()[0] if item.start_dt else ""
                } for item in booking_items]

            items_structured = []
            for item in items:
                generator_id = item.get("generator_id")
                if not generator_id:
                    continue
                capacity = get_capacity(generator_id)
                capacity_label = f" ({capacity} kVA)" if capacity else ""
                date_label = item.get("date") or "-"
                items_structured.append({
                    "generator_id": generator_id,
                    "capacity_kva": capacity,
                    "date": date_label,
                    "label": f"{generator_id}{capacity_label}",
                })

            event_type = event.event_type or ""
            event_action_label = _history_action_label(event_type)
            event_category = _history_event_category(event_type)
            event_time_raw = event.event_time or ""
            event_dt, event_time_iso = _history_parse_time(event_time_raw)
            short_hash = _history_short_hash(
                event.id,
                event_time_raw,
                event_type,
                event.booking_id,
            )
            summary = (event.summary or "").strip() or event_action_label
            booking_id = event.booking_id or ""
            generators_summary = ", ".join(
                sorted({item["generator_id"] for item in items_structured})
            ) if items_structured else "-"
            search_blob = " ".join(filter(None, [
                summary,
                event_action_label,
                event_type,
                vendor_name,
                vendor_id,
                booking_id,
                event.user or "",
                details_raw,
                generators_summary,
            ])).lower()

            history_entries.append({
                "event_id": event.id,
                "short_hash": short_hash,
                "event_type": event_type,
                "event_category": event_category,
                "event_action_label": event_action_label,
                "event_time_raw": event_time_raw,
                "event_time_iso": event_time_iso,
                "user": event.user or "-",
                "vendor_name": vendor_name,
                "vendor_id": vendor_id,
                "booking_id": booking_id,
                "summary": summary,
                "details_raw": details_raw,
                "generators_summary": generators_summary,
                "items_structured": items_structured,
                "search_blob": search_blob,
                "_event_dt": event_dt,
            })

        history_groups = _history_group_entries(history_entries)
        history_filter_chips = _history_build_filter_chips(history_entries)

        return templates.TemplateResponse("history.html", template_context(
            request,
            history_groups=history_groups,
            history_filter_chips=history_filter_chips,
            history_total_count=len(history_entries),
        ))
    except Exception as e:
        logger.error(f"Error loading history page: {e}", exc_info=True)
        return templates.TemplateResponse("error.html", template_context(request, error=str(e)))


@app.get("/create-booking", response_class=HTMLResponse)
async def create_booking_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
    _: Any = Depends(require_capability(CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS)),
):
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
async def booking_detail_page(
    request: Request,
    booking_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: Any = Depends(require_capability(CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS)),
):
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
                "generator_name": f"{gen.generator_id} ({gen.capacity_kva} kVA)" if gen else "Unknown",
                "inventory_type": normalize_generator_inventory_type(gen.inventory_type if gen else None),
                "is_emergency": bool(gen and normalize_generator_inventory_type(gen.inventory_type) == GEN_INVENTORY_EMERGENCY),
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
async def edit_booking_page(
    request: Request,
    booking_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: Any = Depends(require_capability(CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS)),
):
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
                "generator_name": f"{gen.generator_id} ({gen.capacity_kva} kVA)" if gen else "Unknown",
                "inventory_type": normalize_generator_inventory_type(gen.inventory_type if gen else None),
                "is_emergency": bool(gen and normalize_generator_inventory_type(gen.inventory_type) == GEN_INVENTORY_EMERGENCY),
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
# ADMIN - SETTINGS
# ============================================================================

@app.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
    _: Any = Depends(require_role(ROLE_ADMIN))
):
    """Admin settings page."""
    repo = UserRepository(conn)
    users = repo.list_all()
    overrides_by_user = repo.list_permission_overrides_by_user()
    permission_matrix_rows = _build_permission_matrix_rows()
    permission_matrix_users = _build_permission_matrix_users(users, overrides_by_user)
    current_user = getattr(request.state, "user", None)

    default_user_id: Optional[int] = None
    current_user_id = getattr(current_user, "id", None)
    if current_user_id is not None:
        for user in permission_matrix_users:
            if user["id"] == int(current_user_id):
                default_user_id = int(current_user_id)
                break
    if default_user_id is None and permission_matrix_users:
        default_user_id = permission_matrix_users[0]["id"]
    default_user = None
    if default_user_id is not None:
        for user in permission_matrix_users:
            if user["id"] == int(default_user_id):
                default_user = user
                break
    # Use json.dumps() without manual escaping; let Jinja2 template handle proper escaping
    permission_matrix_users_json = json.dumps(permission_matrix_users)

    message = query_param(request, "message")
    error = query_param(request, "error")
    return templates.TemplateResponse(
        "settings.html",
        template_context(
            request,
            users=users,
            message=message,
            error=error,
            permission_matrix_rows=permission_matrix_rows,
            permission_matrix_users=permission_matrix_users,
            permission_matrix_users_json=permission_matrix_users_json,
            permission_matrix_default_user_id=default_user_id,
            permission_matrix_default_user=default_user,
        )
    )


@app.post("/admin/settings/users/create")
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
            f"/admin/settings?error={quote('Username and password are required')}",
            status_code=303
        )
    try:
        validate_password_length(password)
    except ValueError as e:
        return RedirectResponse(
            f"/admin/settings?error={quote(str(e))}",
            status_code=303
        )
    if role not in ALLOWED_ROLES:
        return RedirectResponse(
            f"/admin/settings?error={quote('Invalid role')}",
            status_code=303
        )

    repo = UserRepository(conn)
    if repo.get_by_username(username):
        return RedirectResponse(
            f"/admin/settings?error={quote('Username already exists')}",
            status_code=303
        )

    password_hash = hash_password(password)
    repo.create_user(username, password_hash, role=role, is_active=True)
    return RedirectResponse(
        f"/admin/settings?message={quote('User created successfully')}",
        status_code=303
    )


@app.post("/admin/settings/users/{user_id}/update")
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
            f"/admin/settings?error={quote('Invalid role')}",
            status_code=303
        )

    repo = UserRepository(conn)
    user = repo.get_by_id(user_id)
    if not user:
        return RedirectResponse(
            f"/admin/settings?error={quote('User not found')}",
            status_code=303
        )

    active_flag = is_active == "on"

    # Prevent locking out the last active admin
    if user.role == ROLE_ADMIN and (role != ROLE_ADMIN or not active_flag):
        active_admins = repo.count_active_admins(ROLE_ADMIN)
        if active_admins <= 1:
            return RedirectResponse(
                f"/admin/settings?error={quote('Cannot remove or deactivate the last admin')}",
                status_code=303
            )

    # Prevent self-demotion or deactivation
    if user.id == current_user.id and (role != ROLE_ADMIN or not active_flag):
        return RedirectResponse(
            f"/admin/settings?error={quote('You cannot remove or deactivate your own admin access')}",
            status_code=303
        )

    repo.update_role(user_id, role)
    repo.update_active(user_id, active_flag)

    return RedirectResponse(
        f"/admin/settings?message={quote('User updated successfully')}",
        status_code=303
    )


@app.post("/admin/settings/users/{user_id}/password")
@app.post("/admin/users/{user_id}/password")
async def admin_reset_password(
    request: Request,
    user_id: int,
    new_password: str = Form(...),
    confirm_new_password: Optional[str] = Form(default=None),
    conn: sqlite3.Connection = Depends(get_db),
    _: Any = Depends(require_role(ROLE_ADMIN))
):
    """Reset a user's password."""
    from urllib.parse import quote

    if not new_password:
        return RedirectResponse(
            f"/admin/settings?error={quote('Password cannot be empty')}",
            status_code=303
        )
    if confirm_new_password is not None and confirm_new_password != new_password:
        return RedirectResponse(
            f"/admin/settings?error={quote('Passwords do not match')}",
            status_code=303
        )
    try:
        validate_password_length(new_password)
    except ValueError as e:
        return RedirectResponse(
            f"/admin/settings?error={quote(str(e))}",
            status_code=303
        )

    repo = UserRepository(conn)
    user = repo.get_by_id(user_id)
    if not user:
        return RedirectResponse(
            f"/admin/settings?error={quote('User not found')}",
            status_code=303
        )

    repo.update_password(user_id, hash_password(new_password))
    return RedirectResponse(
        f"/admin/settings?message={quote('Password updated successfully')}",
        status_code=303
    )


@app.post("/admin/settings/users/{user_id}/permissions")
@app.post("/admin/users/{user_id}/permissions")
async def admin_update_user_permissions(
    request: Request,
    user_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _: Any = Depends(require_role(ROLE_ADMIN))
):
    """Persist per-user capability overrides for editable capabilities."""
    from urllib.parse import quote

    repo = UserRepository(conn)
    user = repo.get_by_id(user_id)
    if not user:
        return RedirectResponse(
            f"/admin/settings?error={quote('User not found')}",
            status_code=303,
        )

    form = await request.form()
    role_defaults = role_default_permissions(user.role)

    with transaction(conn):
        for capability_key in EDITABLE_CAPABILITY_KEYS:
            desired_allowed = form.get(capability_key) == "1"
            if desired_allowed == bool(role_defaults.get(capability_key, False)):
                repo.delete_permission_override(
                    user_id,
                    capability_key,
                    commit=False,
                )
            else:
                repo.set_permission_override(
                    user_id,
                    capability_key,
                    desired_allowed,
                    commit=False,
                )

    return RedirectResponse(
        f"/admin/settings?message={quote('Permissions updated successfully')}",
        status_code=303,
    )


@app.post("/admin/settings/users/{user_id}/delete")
@app.post("/admin/users/{user_id}/delete")
async def admin_delete_user(
    request: Request,
    user_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    current_user: Any = Depends(require_role(ROLE_ADMIN))
):
    """Delete a user account."""
    from urllib.parse import quote

    repo = UserRepository(conn)
    user = repo.get_by_id(user_id)
    if not user:
        return RedirectResponse(
            f"/admin/settings?error={quote('User not found')}",
            status_code=303
        )

    # Prevent removing the last active admin account
    if user.role == ROLE_ADMIN and user.is_active:
        active_admins = repo.count_active_admins(ROLE_ADMIN)
        if active_admins <= 1:
            return RedirectResponse(
                f"/admin/settings?error={quote('Cannot delete the last admin')}",
                status_code=303
            )

    # Prevent self-deletion from the admin panel
    if user.id == current_user.id:
        return RedirectResponse(
            f"/admin/settings?error={quote('You cannot delete your own account')}",
            status_code=303
        )

    SessionRepository(conn).delete_by_user_id(user_id)
    repo.delete_user(user_id)
    return RedirectResponse(
        f"/admin/settings?error={quote('User deleted successfully')}",
        status_code=303
    )

# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.get("/api/monitor/live")
async def api_monitor_live(
    _: Any = Depends(require_capability(CAPABILITY_MONITOR_ACCESS)),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Return live server monitor metrics for monitor tab."""
    try:
        # Keep DB dependency to stay aligned with authenticated API dependency patterns.
        _ = conn
        return _collect_monitor_live_metrics()
    except RuntimeError as e:
        logger.error(f"Monitor metrics unavailable: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Monitor metrics unavailable")
    except Exception as e:
        logger.error(f"Error collecting monitor metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while collecting metrics")

@app.get("/api/generators")
async def api_generators(
    _: Any = Depends(require_capability(CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS)),
    conn: sqlite3.Connection = Depends(get_db)
):
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
                "notes": g.notes,
                "inventory_type": g.inventory_type,
                "inventory_label": GENERATOR_INVENTORY_LABELS.get(
                    g.inventory_type,
                    GENERATOR_INVENTORY_LABELS[GEN_INVENTORY_RETAILER],
                ),
            }
            for g in generators
        ]
    except Exception as e:
        logger.error(f"Error fetching generators: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while fetching generators")


@app.get("/api/generators/{generator_id}/bookings")
async def api_generator_bookings(
    generator_id: str,
    date: Optional[str] = None,
    _: Any = Depends(require_capability(CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS)),
    conn: sqlite3.Connection = Depends(get_db)
):
    """Get bookings for a generator (optionally filtered by date)."""
    try:
        gen_repo = GeneratorRepository(conn)
        if not gen_repo.get_by_id(generator_id):
            raise HTTPException(status_code=404, detail="Generator not found")

        if date:
            try:
                datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date format (YYYY-MM-DD)")

        booking_repo = BookingRepository(conn)
        bookings = booking_repo.list_generator_bookings(generator_id, date_filter=date)

        return {
            "generator_id": generator_id,
            "count": len(bookings),
            "bookings": bookings
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching generator bookings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while fetching bookings")


@app.post("/api/generators")
async def api_create_generator(
    request_data: CreateGeneratorRequest,
    _: Any = Depends(require_capability(CAPABILITY_GENERATOR_MANAGEMENT)),
    conn: sqlite3.Connection = Depends(get_db)
):
    """Create a new generator with auto-generated ID."""
    try:
        try:
            capacity_kva = int(request_data.capacity_kva)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Capacity (kVA) must be a number")

        if capacity_kva <= 0:
            raise HTTPException(status_code=400, detail="Capacity (kVA) must be greater than zero")

        type_raw = (request_data.type or "").strip()
        if not type_raw:
            raise HTTPException(status_code=400, detail="Type is required")

        identification_raw = (request_data.identification or "").strip()
        notes_raw = (request_data.notes or "").strip()
        status_raw = (request_data.status or GEN_STATUS_ACTIVE).strip()
        inventory_type_raw = normalize_generator_inventory_type(request_data.inventory_type)
        if status_raw not in {GEN_STATUS_ACTIVE, GEN_STATUS_INACTIVE}:
            raise HTTPException(status_code=400, detail="Operational Status must be Active or Inactive")
        if inventory_type_raw not in {GEN_INVENTORY_RETAILER, GEN_INVENTORY_EMERGENCY}:
            raise HTTPException(
                status_code=400,
                detail="Inventory type must be retailer or emergency",
            )

        def normalize_token(value: str) -> str:
            return re.sub(r"[^A-Za-z0-9]+", "", value.upper())

        type_token = normalize_token(type_raw)
        if not type_token:
            raise HTTPException(
                status_code=400,
                detail="Type must include at least one alphanumeric character"
            )

        ident_token = normalize_token(identification_raw) if identification_raw else ""
        parts = ["GEN", f"{capacity_kva}KVA"]
        if ident_token:
            parts.append(ident_token)
        parts.append(type_token)

        gen_repo = GeneratorRepository(conn)
        base_count = gen_repo.count_by_capacity(capacity_kva)

        counter = base_count
        generator_id = ""
        while True:
            counter += 1
            suffix = f"{counter:02d}"
            candidate = "-".join(parts + [suffix])
            if not gen_repo.get_by_id(candidate):
                generator_id = candidate
                break

        generator = Generator(
            generator_id=generator_id,
            capacity_kva=capacity_kva,
            identification=identification_raw,
            type=type_raw,
            status=status_raw,
            notes=notes_raw,
            inventory_type=inventory_type_raw,
        )
        gen_repo.save(generator)
        logger.info(f"Generator created | context={{'generator_id': '{generator_id}'}}")
        return {
            "success": True,
            "generator_id": generator_id,
            "inventory_type": inventory_type_raw,
            "message": f"Generator {generator_id} created successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating generator: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while creating the generator")


def _serialize_vendor_directory_entry(
    vendor: Vendor | RentalVendor,
    *,
    id_key: str = "id",
    id_attr: str = "vendor_id",
) -> Dict[str, str]:
    return {
        id_key: str(getattr(vendor, id_attr)),
        "name": vendor.vendor_name,
        "place": vendor.vendor_place,
        "phone": vendor.phone,
    }


def _normalize_vendor_directory_fields(
    request_data: CreateVendorRequest | CreateRentalVendorRequest | UpdateVendorRequest,
    *,
    name_label: str = "Vendor Name",
) -> Tuple[str, str, str]:
    vendor_name = request_data.vendor_name.strip() if request_data.vendor_name else ""
    vendor_place = (
        request_data.vendor_place.strip() if request_data.vendor_place else ""
    ).strip() or "Civil Line"
    phone = request_data.phone.strip() if request_data.phone else ""

    if not vendor_name:
        raise HTTPException(status_code=400, detail=f"{name_label} is required")

    return vendor_name, vendor_place, phone


@app.get("/api/vendors")
async def api_vendors(
    _: Any = Depends(require_capability(CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS)),
    conn: sqlite3.Connection = Depends(get_db)
):
    """Get all retailer vendors."""
    try:
        vendor_repo = VendorRepository(conn)
        vendors = vendor_repo.get_all()
        return [_serialize_vendor_directory_entry(v) for v in vendors]
    except Exception as e:
        logger.error(f"Error fetching vendors: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while fetching vendors")


@app.get("/api/rental-vendors")
async def api_rental_vendors(
    _: Any = Depends(require_capability(CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS)),
    conn: sqlite3.Connection = Depends(get_db)
):
    """Get all rental vendors."""
    try:
        rental_vendor_repo = RentalVendorRepository(conn)
        rental_vendors = rental_vendor_repo.get_all()
        return [
            _serialize_vendor_directory_entry(
                v,
                id_key="rental_vendor_id",
                id_attr="rental_vendor_id",
            )
            for v in rental_vendors
        ]
    except Exception as e:
        logger.error(f"Error fetching rental vendors: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while fetching rental vendors")


@app.get("/api/vendors/{vendor_id}/bookings")
async def api_vendor_bookings(
    vendor_id: str,
    _: Any = Depends(require_capability(CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS)),
    conn: sqlite3.Connection = Depends(get_db)
):
    """Get all bookings (all statuses) for a specific vendor."""
    try:
        vendor_repo = VendorRepository(conn)
        booking_repo = BookingRepository(conn)
        vendor = vendor_repo.get_by_id(vendor_id)
        if not vendor:
            logger.warning(f"Vendor bookings lookup failed | context={{'vendor_id': '{vendor_id}', 'reason': 'not found'}}")
            raise HTTPException(status_code=404, detail="Vendor not found")

        rows = booking_repo.list_vendor_booking_rows(vendor_id)

        status_counts: Dict[str, int] = {
            STATUS_CONFIRMED: 0,
            STATUS_PENDING: 0,
            STATUS_CANCELLED: 0,
        }
        booking_map: Dict[str, Dict[str, Any]] = {}

        for row in rows:
            booking_id = row["booking_id"]
            booking_status = row["booking_status"] or STATUS_PENDING
            created_at = row["created_at"] or ""
            item_id = row["item_id"]
            generator_id = row["generator_id"]
            capacity_kva = row["capacity_kva"]
            start_dt = row["start_dt"]
            end_dt = row["end_dt"]
            item_status = row["item_status"]
            remarks = row["remarks"] or ""

            if booking_id not in booking_map:
                booking_map[booking_id] = {
                    "booking_id": booking_id,
                    "status": booking_status,
                    "created_at": created_at,
                    "item_count": 0,
                    "booked_dates": set(),
                    "items": [],
                }
                status_counts[booking_status] = status_counts.get(booking_status, 0) + 1

            if item_id is None:
                continue

            date_part = start_dt.split()[0] if start_dt else ""
            if date_part:
                booking_map[booking_id]["booked_dates"].add(date_part)

            booking_map[booking_id]["items"].append(
                {
                    "id": item_id,
                    "generator_id": generator_id,
                    "capacity_kva": capacity_kva,
                    "inventory_type": normalize_generator_inventory_type(row.get("inventory_type")),
                    "is_emergency": normalize_generator_inventory_type(row.get("inventory_type")) == GEN_INVENTORY_EMERGENCY,
                    "start_dt": start_dt,
                    "end_dt": end_dt,
                    "item_status": item_status,
                    "remarks": remarks,
                }
            )

        bookings = []
        for booking in booking_map.values():
            booking["booked_dates"] = sorted(booking["booked_dates"])
            booking["item_count"] = len(booking["items"])
            bookings.append(booking)

        logger.info(
            f"Vendor bookings fetched | context={{'vendor_id': '{vendor_id}', 'count': {len(bookings)}}}"
        )
        return {
            "vendor_id": vendor.vendor_id,
            "vendor_name": vendor.vendor_name,
            "total_bookings": len(bookings),
            "status_counts": status_counts,
            "bookings": bookings,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching vendor bookings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while fetching vendor bookings")


@app.get("/api/bookings")
async def api_bookings(
    _: Any = Depends(require_capability(CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS)),
    conn: sqlite3.Connection = Depends(get_db)
):
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
        raise HTTPException(status_code=500, detail="An error occurred while fetching bookings")


@app.get("/api/billing/lines")
async def api_billing_lines(
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
    _: Any = Depends(require_capability(CAPABILITY_BILLING_ACCESS)),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Get billable booking lines by date range (confirmed records only)."""
    try:
        try:
            from_parsed = datetime.strptime(from_date, "%Y-%m-%d")
            to_parsed = datetime.strptime(to_date, "%Y-%m-%d")
        except ValueError:
            logger.warning(
                "Billing lines validation failed | context="
                f"{{'from': '{from_date}', 'to': '{to_date}', 'reason': 'invalid date format'}}"
            )
            raise HTTPException(status_code=400, detail="Invalid date format (YYYY-MM-DD)")

        if from_parsed > to_parsed:
            logger.warning(
                "Billing lines validation failed | context="
                f"{{'from': '{from_date}', 'to': '{to_date}', 'reason': 'invalid range'}}"
            )
            raise HTTPException(status_code=400, detail='"from" cannot be later than "to"')

        booking_repo = BookingRepository(conn)
        rows = booking_repo.list_billing_line_rows(from_date, to_date)

        capacities: set[int] = set()

        for row in rows:
            capacity_kva = row["capacity_kva"]
            if isinstance(capacity_kva, int):
                capacities.add(capacity_kva)

        logger.info(
            "Billing lines fetched | context="
            f"{{'from': '{from_date}', 'to': '{to_date}', 'count': {len(rows)}}}"
        )
        return {
            "from": from_date,
            "to": to_date,
            "rows": rows,
            "capacities": sorted(capacities),
            "count": len(rows),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching billing lines: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while fetching billing lines")


@app.get("/api/calendar/events")
async def api_calendar_events(
    _: Any = Depends(require_capability(CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS)),
    conn: sqlite3.Connection = Depends(get_db)
):
    """Calendar events aggregated by date (confirmed bookings only)."""
    try:
        booking_repo = BookingRepository(conn)
        rows = booking_repo.list_calendar_event_counts()
        events = []
        for row in rows:
            booking_date = row["booking_date"]
            item_count = row["item_count"]
            events.append({
                "title": f"{item_count} booking(s)",
                "start": booking_date,
                "allDay": True,
                "extendedProps": {"date": booking_date},
            })
        return events
    except Exception as e:
        logger.error(f"Error fetching calendar events: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while fetching calendar events")


@app.get("/api/calendar/day")
async def api_calendar_day(
    date: str,
    _: Any = Depends(require_capability(CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS)),
    conn: sqlite3.Connection = Depends(get_db)
):
    """Get vendor bookings for a given date (confirmed only)."""
    try:
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format (YYYY-MM-DD)")

        booking_repo = BookingRepository(conn)
        rows = booking_repo.list_calendar_day_rows(date)

        vendors: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            vendor_id = row["vendor_id"]
            vendor_name = row["vendor_name"]
            booking_id = row["booking_id"]
            generator_id = row["generator_id"]
            capacity_kva = row["capacity_kva"]
            start_dt = row["start_dt"]
            end_dt = row["end_dt"]
            remarks = row["remarks"]
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
        raise HTTPException(status_code=500, detail="An error occurred while fetching calendar day details")


@app.post("/api/vendors")
async def api_create_vendor(
    request_data: CreateVendorRequest,
    _: Any = Depends(require_capability(CAPABILITY_VENDOR_MANAGEMENT)),
    conn: sqlite3.Connection = Depends(get_db)
):
    """Create a new retailer vendor with auto-generated ID."""
    try:
        vendor_name, vendor_place, phone = _normalize_vendor_directory_fields(request_data)

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


@app.patch("/api/vendors/{vendor_id}")
async def api_update_vendor(
    vendor_id: str,
    request_data: UpdateVendorRequest,
    _: Any = Depends(require_capability(CAPABILITY_VENDOR_MANAGEMENT)),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Update retailer vendor profile details."""
    try:
        vendor_repo = VendorRepository(conn)
        existing_vendor = vendor_repo.get_by_id(vendor_id)
        if not existing_vendor:
            logger.warning(
                f"Vendor update failed | context={{'vendor_id': '{vendor_id}', 'reason': 'not found'}}"
            )
            raise HTTPException(status_code=404, detail="Vendor not found")

        vendor_name, vendor_place, phone = _normalize_vendor_directory_fields(request_data)

        duplicate_vendor_id = vendor_repo.find_duplicate_name(
            vendor_name,
            exclude_directory_id=vendor_id,
        )
        if duplicate_vendor_id:
            logger.warning(
                "Vendor update failed | context="
                f"{{'vendor_id': '{vendor_id}', 'reason': 'duplicate name', 'duplicate_vendor_id': '{duplicate_vendor_id}'}}"
            )
            raise HTTPException(
                status_code=400,
                detail=f"Vendor name '{vendor_name}' already exists with ID '{duplicate_vendor_id}'",
            )

        vendor_repo.save(
            Vendor(
                vendor_id=vendor_id,
                vendor_name=vendor_name,
                vendor_place=vendor_place,
                phone=phone,
            )
        )
        logger.info(f"Vendor updated successfully | context={{'vendor_id': '{vendor_id}'}}")
        return {
            "success": True,
            "message": f"Vendor {vendor_id} updated successfully",
            "vendor": {
                "id": vendor_id,
                "name": vendor_name,
                "place": vendor_place,
                "phone": phone,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating vendor: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while updating the vendor")


@app.post("/api/rental-vendors")
async def api_create_rental_vendor(
    request_data: CreateRentalVendorRequest,
    _: Any = Depends(require_capability(CAPABILITY_VENDOR_MANAGEMENT)),
    conn: sqlite3.Connection = Depends(get_db)
):
    """Create a new rental vendor with auto-generated ID."""
    try:
        vendor_name, vendor_place, phone = _normalize_vendor_directory_fields(
            request_data,
            name_label="Property Name",
        )

        rental_vendor_id = request_data.rental_vendor_id
        if not rental_vendor_id or not rental_vendor_id.strip():
            rental_vendor_repo = RentalVendorRepository(conn)
            rental_vendor_id = rental_vendor_repo.generate_vendor_id()
        else:
            rental_vendor_id = rental_vendor_id.strip()

        logger.info(
            "API rental vendor creation request | context=%s",
            {"rental_vendor_id": rental_vendor_id, "vendor_name": vendor_name},
        )

        success, message = create_rental_vendor(
            conn,
            rental_vendor_id,
            vendor_name,
            vendor_place,
            phone,
        )

        if success:
            logger.info(
                f"Rental vendor created successfully | context={{'rental_vendor_id': '{rental_vendor_id}'}}"
            )
            return {
                "success": True,
                "message": message,
                "rental_vendor_id": rental_vendor_id,
            }

        logger.warning(
            f"Rental vendor creation failed | context={{'rental_vendor_id': '{rental_vendor_id}', 'reason': '{message}'}}"
        )
        raise HTTPException(status_code=400, detail=message)
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error creating rental vendor: {error_msg}", exc_info=True)
        raise HTTPException(status_code=500, detail=error_msg)


@app.patch("/api/rental-vendors/{rental_vendor_id}")
async def api_update_rental_vendor(
    rental_vendor_id: str,
    request_data: UpdateVendorRequest,
    _: Any = Depends(require_capability(CAPABILITY_VENDOR_MANAGEMENT)),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Update rental vendor profile details."""
    try:
        rental_vendor_repo = RentalVendorRepository(conn)
        existing_vendor = rental_vendor_repo.get_by_id(rental_vendor_id)
        if not existing_vendor:
            logger.warning(
                f"Rental vendor update failed | context={{'rental_vendor_id': '{rental_vendor_id}', 'reason': 'not found'}}"
            )
            raise HTTPException(status_code=404, detail="Rental vendor not found")

        vendor_name, vendor_place, phone = _normalize_vendor_directory_fields(
            request_data,
            name_label="Property Name",
        )

        duplicate_vendor_id = rental_vendor_repo.find_duplicate_name(
            vendor_name,
            exclude_directory_id=rental_vendor_id,
        )
        if duplicate_vendor_id:
            logger.warning(
                "Rental vendor update failed | context="
                f"{{'rental_vendor_id': '{rental_vendor_id}', 'reason': 'duplicate name', 'duplicate_rental_vendor_id': '{duplicate_vendor_id}'}}"
            )
            raise HTTPException(
                status_code=400,
                detail=f"Rental vendor name '{vendor_name}' already exists with ID '{duplicate_vendor_id}'",
            )

        rental_vendor_repo.save(
            RentalVendor(
                rental_vendor_id=rental_vendor_id,
                vendor_name=vendor_name,
                vendor_place=vendor_place,
                phone=phone,
            )
        )
        logger.info(
            f"Rental vendor updated successfully | context={{'rental_vendor_id': '{rental_vendor_id}'}}"
        )
        return {
            "success": True,
            "message": f"Rental vendor {rental_vendor_id} updated successfully",
            "vendor": {
                "rental_vendor_id": rental_vendor_id,
                "name": vendor_name,
                "place": vendor_place,
                "phone": phone,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating rental vendor: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while updating the rental vendor")


@app.delete("/api/vendors/{vendor_id}")
async def api_delete_vendor(
    vendor_id: str,
    _: Any = Depends(require_capability(CAPABILITY_VENDOR_MANAGEMENT)),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Delete a vendor when it is not referenced by any booking."""
    try:
        vendor_repo = VendorRepository(conn)
        booking_repo = BookingRepository(conn)
        vendor = vendor_repo.get_by_id(vendor_id)
        if not vendor:
            logger.warning(
                f"Vendor delete failed | context={{'vendor_id': '{vendor_id}', 'reason': 'not found'}}"
            )
            raise HTTPException(status_code=404, detail="Vendor not found")

        booking_count = booking_repo.count_by_vendor(vendor_id)

        if booking_count > 0:
            logger.warning(
                "Vendor delete blocked | context="
                f"{{'vendor_id': '{vendor_id}', 'reason': 'bookings exist', 'booking_count': {booking_count}}}"
            )
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cannot delete vendor '{vendor_id}' because {booking_count} booking(s) reference it."
                ),
            )

        vendor_repo.delete(vendor_id)
        logger.info(f"Vendor deleted successfully | context={{'vendor_id': '{vendor_id}'}}")
        return {"success": True, "message": f"Vendor {vendor_id} deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting vendor: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while deleting the vendor")


@app.delete("/api/rental-vendors/{rental_vendor_id}")
async def api_delete_rental_vendor(
    rental_vendor_id: str,
    _: Any = Depends(require_capability(CAPABILITY_VENDOR_MANAGEMENT)),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Delete a rental vendor."""
    try:
        rental_vendor_repo = RentalVendorRepository(conn)
        vendor = rental_vendor_repo.get_by_id(rental_vendor_id)
        if not vendor:
            logger.warning(
                f"Rental vendor delete failed | context={{'rental_vendor_id': '{rental_vendor_id}', 'reason': 'not found'}}"
            )
            raise HTTPException(status_code=404, detail="Rental vendor not found")

        rental_vendor_repo.delete(rental_vendor_id)
        logger.info(
            f"Rental vendor deleted successfully | context={{'rental_vendor_id': '{rental_vendor_id}'}}"
        )
        return {
            "success": True,
            "message": f"Rental vendor {rental_vendor_id} deleted successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting rental vendor: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while deleting the rental vendor")


@app.post("/api/bookings")
async def api_create_booking(
    request: Request,
    request_data: CreateBookingRequest,
    _: Any = Depends(require_capability(CAPABILITY_BOOKING_CREATE_UPDATE)),
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
    except RetailerOutOfStockError as e:
        logger.info(
            "Retailer stock unavailable for booking request | context="
            f"{{'vendor_id': '{request_data.vendor_id}', 'affected_dates': {len(e.affected_dates)}}}"
        )
        return JSONResponse(status_code=409, content=e.payload)
    except ValueError as e:
        logger.warning(f"Validation error creating booking: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        logger.warning(f"Booking creation blocked: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating booking: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while creating the booking")


@app.get("/api/bookings/{booking_id}")
async def api_booking_detail(
    booking_id: str,
    _: Any = Depends(require_capability(CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS)),
    conn: sqlite3.Connection = Depends(get_db)
):
    """Get booking detail."""
    try:
        booking_repo = BookingRepository(conn)
        try:
            booking = ensure_booking(booking_repo, booking_id, message="Booking not found")
        except ValueError as e:
            raise HTTPException(status_code=404, detail="Booking not found")
        
        items = booking_repo.get_items_with_capacity(booking_id)
        
        return {
            "booking": {
                "id": booking.booking_id,
                "vendor_id": booking.vendor_id,
                "created_at": booking.created_at,
                "status": booking.status
            },
            "items": [
                {
                    "id": item["id"],
                    "generator_id": item["generator_id"],
                    "capacity_kva": item["capacity_kva"],
                    "inventory_type": normalize_generator_inventory_type(item.get("inventory_type")),
                    "is_emergency": normalize_generator_inventory_type(item.get("inventory_type")) == GEN_INVENTORY_EMERGENCY,
                    "start_dt": item["start_dt"],
                    "end_dt": item["end_dt"],
                    "status": item["item_status"],
                    "remarks": item["remarks"],
                }
                for item in items
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching booking detail: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while fetching booking details")


@app.post("/api/bookings/{booking_id}/cancel")
async def api_cancel_booking(
    request: Request,
    booking_id: str,
    reason: str = Form(default="Cancelled via web"),
    _: Any = Depends(require_capability(CAPABILITY_BOOKING_CREATE_UPDATE)),
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
        raise HTTPException(status_code=500, detail="An error occurred while cancelling the booking")


@app.delete("/api/bookings/{booking_id}")
async def api_delete_booking(
    request: Request,
    booking_id: str,
    _: Any = Depends(require_capability(CAPABILITY_BOOKING_DELETE)),
    conn: sqlite3.Connection = Depends(get_db)
):
    """Delete a booking completely."""
    try:
        booking_repo = BookingRepository(conn)
        try:
            booking = ensure_booking(booking_repo, booking_id, message="Booking not found")
        except ValueError as e:
            raise HTTPException(status_code=404, detail="Booking not found")

        items = booking_repo.get_items(booking_id)
        booking_repo.delete_with_items(booking_id)

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
        raise HTTPException(status_code=500, detail="An error occurred while deleting the booking")


@app.post("/api/bookings/{booking_id}/items")
async def api_add_booking_item(
    request: Request,
    booking_id: str,
    generator_id: Optional[str] = Form(default=None),
    capacity_kva: Optional[int] = Form(default=None),
    start_dt: str = Form(...),
    end_dt: str = Form(...),
    remarks: str = Form(default=""),
    _: Any = Depends(require_capability(CAPABILITY_BOOKING_CREATE_UPDATE)),
    conn: sqlite3.Connection = Depends(get_db)
):
    """Add a new generator to an existing booking."""
    try:
        booking_repo = BookingRepository(conn)
        try:
            ensure_booking(booking_repo, booking_id, message="Booking not found")
        except ValueError as e:
            raise HTTPException(status_code=404, detail="Booking not found")
        
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
        raise HTTPException(status_code=400, detail="Invalid item data provided")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding item to booking: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while adding the item")


@app.post("/api/bookings/{booking_id}/items/bulk-update")
async def api_bulk_update_items(
    request: Request,
    booking_id: str,
    request_data: Dict[str, Any],
    _: Any = Depends(require_capability(CAPABILITY_BOOKING_CREATE_UPDATE)),
    conn: sqlite3.Connection = Depends(get_db)
):
    """Update multiple booking items and remove items."""
    try:
        booking_repo = BookingRepository(conn)
        try:
            booking = ensure_booking(booking_repo, booking_id, message="Booking not found")
        except ValueError as e:
            raise HTTPException(status_code=404, detail="Booking not found")

        updates_raw = request_data.get("updates", [])
        removes_raw = request_data.get("removes", [])
        updates = updates_raw if isinstance(updates_raw, list) else []
        removes = removes_raw if isinstance(removes_raw, list) else []

        existing_item_ids = {str(item_id) for item_id in booking_repo.get_item_ids_for_booking(booking_id)}
        remove_item_ids = {str(item_id) for item_id in removes}
        remaining_item_ids = existing_item_ids - remove_item_ids

        if existing_item_ids and not remaining_item_ids:
            logger.warning(
                "Booking items update blocked | context="
                f"{{'booking_id': '{booking_id}', 'reason': 'attempt to remove all items'}}"
            )
            raise HTTPException(
                status_code=400,
                detail="Cannot remove all booking items. Use Delete Booking to remove this booking.",
            )

        availability = AvailabilityChecker(conn)
        history_items: List[Dict[str, str]] = []
        prepared_updates: List[Dict[str, Any]] = []
        prepared_removes: List[int] = []
        if updates or removes:
            for update in updates:
                item_id_raw = update.get("id")
                start_dt = update.get("start_dt")
                end_dt = update.get("end_dt")
                remarks = update.get("remarks", "")

                if item_id_raw is None:
                    raise HTTPException(status_code=400, detail="Update item missing id")
                if not start_dt or not end_dt:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Update item {item_id_raw}: start_dt and end_dt are required"
                    )

                try:
                    item_id = int(item_id_raw)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400, detail=f"Update item {item_id_raw}: invalid id")

                existing_item = booking_repo.get_item_by_id(item_id)
                if not existing_item or existing_item.booking_id != booking_id:
                    raise HTTPException(status_code=404, detail=f"Booking item {item_id} not found")

                generator_id = existing_item.generator_id
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

                prepared_updates.append({
                    "id": item_id,
                    "start_dt": start_dt,
                    "end_dt": end_dt,
                    "remarks": remarks,
                })
                history_items.append({
                    "generator_id": generator_id,
                    "start_dt": start_dt
                })

            for item_id_raw in removes:
                try:
                    item_id = int(item_id_raw)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400, detail=f"Remove item {item_id_raw}: invalid id")

                existing_item = booking_repo.get_item_by_id(item_id)
                if not existing_item or existing_item.booking_id != booking_id:
                    raise HTTPException(status_code=404, detail=f"Booking item {item_id} not found")

                prepared_removes.append(item_id)
                history_items.append({
                    "generator_id": existing_item.generator_id,
                    "start_dt": existing_item.start_dt
                })

        with transaction(conn):
            for update in prepared_updates:
                booking_repo.update_item(
                    update["id"],
                    update["start_dt"],
                    update["end_dt"],
                    update["remarks"],
                    commit=False,
                )
            for item_id in prepared_removes:
                booking_repo.delete_item(item_id, commit=False)

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
        logger.info(
            f"Booking items updated | context={{'booking_id': '{booking_id}', 'updates': {len(prepared_updates)}, 'removes': {len(prepared_removes)}}}"
        )
        return {"success": True, "message": "Items updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating items: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while updating items")


@app.get("/api/export")
async def api_export(
    conn: sqlite3.Connection = Depends(get_db),
    _: Any = Depends(require_capability(CAPABILITY_EXPORT_ACCESS))
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
        raise HTTPException(status_code=500, detail="An error occurred while exporting data")
