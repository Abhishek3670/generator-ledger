"""
FastAPI web application for Generator Booking Ledger.
"""

from fastapi import FastAPI, Request, HTTPException, Form, Depends, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exceptions import RequestValidationError
import os
import sqlite3
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any, Tuple
import logging
import re
import hashlib
from pydantic import BaseModel
import jwt
try:
    import psutil
except ImportError:  # pragma: no cover - handled at runtime
    psutil = None

from core import (
    Generator,
    Vendor,
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
from core.repositories import SessionRepository, RevokedTokenRepository
from core.utils import transaction
from core.validation import ensure_booking
from core.services import create_vendor, archive_all_bookings, log_booking_history, encode_history_items
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
    SESSION_TTL_MINUTES,
    JWT_SECRET,
    JWT_ALGORITHM,
    JWT_EXPIRE_MINUTES,
    CSRF_HEADER_NAME,
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
    DATETIME_FORMAT,
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


class UpdateVendorRequest(BaseModel):
    vendor_name: str
    vendor_place: str = "Civil Line"
    phone: str = ""


class CreateGeneratorRequest(BaseModel):
    capacity_kva: int
    type: str
    identification: str = ""
    notes: str = ""
    status: Optional[str] = GEN_STATUS_ACTIVE


class LoginRequest(BaseModel):
    username: str
    password: str

# FastAPI app
app = FastAPI(title=APP_TITLE, version=APP_VERSION)

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
    cur = conn.cursor()
    cur.execute(
        """
        SELECT bi.generator_id,
               bi.start_dt,
               bi.item_status,
               bi.remarks,
               g.capacity_kva
        FROM booking_items bi
        LEFT JOIN generators g ON g.generator_id = bi.generator_id
        WHERE bi.booking_id = ?
        ORDER BY bi.start_dt ASC, bi.id ASC
        """,
        (booking_id,),
    )

    items: List[Dict[str, Any]] = []
    for row in cur.fetchall():
        items.append(
            {
                "generator_id": row[0] or "",
                "start_dt": row[1] or "",
                "item_status": row[2] or "",
                "remarks": row[3] or "",
                "capacity_kva": row[4],
            }
        )
    return items


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
    }
    context.update(kwargs)
    return context


def now_ts() -> int:
    """Return current UTC timestamp in seconds."""
    return int(datetime.utcnow().timestamp())


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
        # Read once, then restore the body stream so downstream Form(...) parsing still works.
        raw_body = await request.body()

        body_sent = False

        async def receive() -> Dict[str, Any]:
            nonlocal body_sent
            if body_sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            body_sent = True
            return {"type": "http.request", "body": raw_body, "more_body": False}

        request._receive = receive

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


def set_session_cookie(response: RedirectResponse, session_id: str, expires_at: int) -> None:
    max_age = max(0, expires_at - now_ts())
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        max_age=max_age,
        httponly=True,
        secure=not DEBUG,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: RedirectResponse | JSONResponse | HTMLResponse) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=not DEBUG,
        samesite="lax",
    )


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
    clear_cookie = False
    try:
        conn = sqlite3.connect(
            DB_PATH,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        )
        conn.execute("PRAGMA foreign_keys = ON")
        request.state.db = conn
        request.state.user = None
        request.state.auth_type = None
        request.state.csrf_token = None
        request.state.session_id = None

        path = request.url.path
        is_public = path in PUBLIC_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)

        auth_header = request.headers.get("authorization")
        if auth_header:
            token = get_bearer_token(request)
            if not token:
                return unauthorized_response(request)
            try:
                payload = decode_access_token(token, JWT_SECRET, JWT_ALGORITHM, verify_exp=True)
            except jwt.ExpiredSignatureError:
                return unauthorized_response(request, detail="Token expired")
            except jwt.PyJWTError:
                return unauthorized_response(request, detail="Invalid token")

            jti = payload.get("jti")
            if not jti:
                return unauthorized_response(request, detail="Invalid token")

            revoked_repo = RevokedTokenRepository(conn)
            if revoked_repo.is_revoked(jti, now_ts()):
                return unauthorized_response(request, detail="Token revoked")

            user_id_raw = payload.get("sub")
            try:
                user_id = int(user_id_raw)
            except (TypeError, ValueError):
                return unauthorized_response(request, detail="Invalid token")

            user_repo = UserRepository(conn)
            user = user_repo.get_by_id(user_id)
            if not user or not user.is_active:
                return unauthorized_response(request, detail="Unauthorized")

            request.state.user = user
            request.state.auth_type = "jwt"
            request.state.token_jti = jti
        else:
            session_id = request.cookies.get(SESSION_COOKIE_NAME)
            if session_id:
                session_repo = SessionRepository(conn)
                session = session_repo.get_by_id(session_id)
                if not session or session.expires_at <= now_ts():
                    if session:
                        session_repo.delete(session_id)
                    clear_cookie = True
                else:
                    user_repo = UserRepository(conn)
                    user = user_repo.get_by_id(int(session.user_id))
                    if not user or not user.is_active:
                        session_repo.delete(session_id)
                        clear_cookie = True
                    else:
                        request.state.user = user
                        request.state.auth_type = "session"
                        request.state.csrf_token = session.csrf_token
                        request.state.session_id = session.session_id
                        session_repo.update_last_seen(session.session_id, now_ts())

        if request.state.user and request.state.auth_type == "session":
            if requires_csrf(request) and path not in CSRF_EXEMPT_PATHS:
                if not await validate_csrf(request, request.state.csrf_token):
                    return forbidden_response(request, detail="Invalid CSRF token")

        if not request.state.user and not is_public:
            response = unauthorized_response(request)
            if clear_cookie and hasattr(response, "delete_cookie"):
                response.delete_cookie(
                    SESSION_COOKIE_NAME,
                    path="/",
                    samesite="lax",
                    secure=not DEBUG,
                    httponly=True,
                )
            return response

        response = await call_next(request)
        if clear_cookie and hasattr(response, "delete_cookie"):
            response.delete_cookie(
                SESSION_COOKIE_NAME,
                path="/",
                samesite="lax",
                secure=not DEBUG,
                httponly=True,
            )
        return response
    finally:
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
    except Exception:
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
        except Exception:
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
    set_session_cookie(response, session_id, expires_at)
    return response


@app.post("/api/login")
async def api_login(payload: LoginRequest, conn: sqlite3.Connection = Depends(get_db)):
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
    clear_session_cookie(response)
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
        clear_session_cookie(response)
    return response


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
            cur = conn.cursor()
            cur.execute(
                """
                SELECT DISTINCT bi.generator_id
                FROM booking_items bi
                JOIN bookings b ON bi.booking_id = b.booking_id
                WHERE date(bi.start_dt) = ?
                  AND bi.item_status = ?
                  AND b.status = ?
                """,
                (selected_date, STATUS_CONFIRMED, STATUS_CONFIRMED)
            )
            booked_ids = {row[0] for row in cur.fetchall()}
            booking_status = {
                gen.generator_id: ("Booked" if gen.generator_id in booked_ids else "Free")
                for gen in generators
            }

        return templates.TemplateResponse("generators.html", template_context(
            request,
            generators=generators,
            booking_status=booking_status,
            selected_date=selected_date or "",
            capacities=capacities
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
    _: Any = Depends(require_role(ROLE_ADMIN, ROLE_OPERATOR)),
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
            view_link = f"/booking/{booking_id}" if booking_id else None

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
                "view_link": view_link,
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
    message = request.query_params.get("message")
    error = request.query_params.get("error")
    return templates.TemplateResponse(
        "settings.html",
        template_context(request, users=users, message=message, error=error)
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
    _: Any = Depends(require_role(ROLE_ADMIN)),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Return live server monitor metrics for monitor tab."""
    try:
        # Keep DB dependency to stay aligned with authenticated API dependency patterns.
        _ = conn
        return _collect_monitor_live_metrics()
    except RuntimeError as e:
        logger.error(f"Monitor metrics unavailable: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Error collecting monitor metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

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


@app.get("/api/generators/{generator_id}/bookings")
async def api_generator_bookings(
    generator_id: str,
    date: Optional[str] = None,
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

        cur = conn.cursor()
        if date:
            cur.execute(
                """
                SELECT b.booking_id,
                       b.vendor_id,
                       v.vendor_name,
                       b.status,
                       bi.start_dt,
                       bi.end_dt,
                       bi.item_status,
                       bi.remarks
                FROM booking_items bi
                JOIN bookings b ON bi.booking_id = b.booking_id
                LEFT JOIN vendors v ON b.vendor_id = v.vendor_id
                WHERE bi.generator_id = ?
                  AND date(bi.start_dt) = ?
                ORDER BY bi.start_dt DESC
                """,
                (generator_id, date)
            )
        else:
            cur.execute(
                """
                SELECT b.booking_id,
                       b.vendor_id,
                       v.vendor_name,
                       b.status,
                       bi.start_dt,
                       bi.end_dt,
                       bi.item_status,
                       bi.remarks
                FROM booking_items bi
                JOIN bookings b ON bi.booking_id = b.booking_id
                LEFT JOIN vendors v ON b.vendor_id = v.vendor_id
                WHERE bi.generator_id = ?
                ORDER BY bi.start_dt DESC
                """,
                (generator_id,)
            )

        bookings = []
        for row in cur.fetchall():
            bookings.append({
                "booking_id": row[0],
                "vendor_id": row[1],
                "vendor_name": row[2] or row[1] or "-",
                "booking_status": row[3],
                "start_dt": row[4],
                "end_dt": row[5],
                "item_status": row[6],
                "remarks": row[7] or ""
            })

        return {
            "generator_id": generator_id,
            "count": len(bookings),
            "bookings": bookings
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching generator bookings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/generators")
async def api_create_generator(
    request_data: CreateGeneratorRequest,
    _: Any = Depends(require_role(ROLE_ADMIN)),
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
        if status_raw not in {GEN_STATUS_ACTIVE, GEN_STATUS_INACTIVE}:
            raise HTTPException(status_code=400, detail="Operational Status must be Active or Inactive")

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
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM generators WHERE capacity_kva = ?", (capacity_kva,))
        base_count = int(cur.fetchone()[0] or 0)

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
            notes=notes_raw
        )
        gen_repo.save(generator)
        logger.info(f"Generator created | context={{'generator_id': '{generator_id}'}}")
        return {
            "success": True,
            "generator_id": generator_id,
            "message": f"Generator {generator_id} created successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating generator: {e}", exc_info=True)
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


@app.get("/api/vendors/{vendor_id}/bookings")
async def api_vendor_bookings(vendor_id: str, conn: sqlite3.Connection = Depends(get_db)):
    """Get all bookings (all statuses) for a specific vendor."""
    try:
        vendor_repo = VendorRepository(conn)
        vendor = vendor_repo.get_by_id(vendor_id)
        if not vendor:
            logger.warning(f"Vendor bookings lookup failed | context={{'vendor_id': '{vendor_id}', 'reason': 'not found'}}")
            raise HTTPException(status_code=404, detail="Vendor not found")

        cur = conn.cursor()
        cur.execute(
            """
            SELECT b.booking_id,
                   b.status,
                   b.created_at,
                   bi.id,
                   bi.generator_id,
                   g.capacity_kva,
                   bi.start_dt,
                   bi.end_dt,
                   bi.item_status,
                   bi.remarks
            FROM bookings b
            LEFT JOIN booking_items bi ON bi.booking_id = b.booking_id
            LEFT JOIN generators g ON g.generator_id = bi.generator_id
            WHERE b.vendor_id = ?
            ORDER BY b.created_at DESC, b.booking_id DESC, bi.start_dt ASC, bi.id ASC
            """,
            (vendor_id,),
        )

        status_counts: Dict[str, int] = {
            STATUS_CONFIRMED: 0,
            STATUS_PENDING: 0,
            STATUS_CANCELLED: 0,
        }
        booking_map: Dict[str, Dict[str, Any]] = {}

        for row in cur.fetchall():
            booking_id = row[0]
            booking_status = row[1] or STATUS_PENDING
            created_at = row[2] or ""
            item_id = row[3]
            generator_id = row[4]
            capacity_kva = row[5]
            start_dt = row[6]
            end_dt = row[7]
            item_status = row[8]
            remarks = row[9] or ""

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


@app.get("/api/billing/lines")
async def api_billing_lines(
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
    _: Any = Depends(require_role(ROLE_ADMIN, ROLE_OPERATOR)),
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

        cur = conn.cursor()
        cur.execute(
            """
            SELECT v.vendor_id,
                   v.vendor_name,
                   b.booking_id,
                   date(bi.start_dt) AS booked_date,
                   bi.generator_id,
                   g.capacity_kva
            FROM booking_items bi
            JOIN bookings b ON b.booking_id = bi.booking_id
            JOIN vendors v ON v.vendor_id = b.vendor_id
            LEFT JOIN generators g ON g.generator_id = bi.generator_id
            WHERE date(bi.start_dt) >= ?
              AND date(bi.start_dt) <= ?
              AND bi.item_status = ?
              AND b.status = ?
            ORDER BY v.vendor_name ASC,
                     v.vendor_id ASC,
                     date(bi.start_dt) ASC,
                     bi.generator_id ASC,
                     b.booking_id ASC,
                     bi.id ASC
            """,
            (from_date, to_date, STATUS_CONFIRMED, STATUS_CONFIRMED),
        )

        rows: List[Dict[str, Any]] = []
        capacities: set[int] = set()

        for row in cur.fetchall():
            capacity_kva = row[5]
            if isinstance(capacity_kva, int):
                capacities.add(capacity_kva)

            rows.append(
                {
                    "vendor_id": row[0],
                    "vendor_name": row[1],
                    "booking_id": row[2],
                    "booked_date": row[3],
                    "generator_id": row[4],
                    "capacity_kva": capacity_kva,
                }
            )

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


@app.patch("/api/vendors/{vendor_id}")
async def api_update_vendor(
    vendor_id: str,
    request_data: UpdateVendorRequest,
    _: Any = Depends(require_role(ROLE_ADMIN)),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Update vendor profile details."""
    try:
        vendor_repo = VendorRepository(conn)
        existing_vendor = vendor_repo.get_by_id(vendor_id)
        if not existing_vendor:
            logger.warning(
                f"Vendor update failed | context={{'vendor_id': '{vendor_id}', 'reason': 'not found'}}"
            )
            raise HTTPException(status_code=404, detail="Vendor not found")

        vendor_name = request_data.vendor_name.strip() if request_data.vendor_name else ""
        vendor_place = (
            request_data.vendor_place.strip() if request_data.vendor_place else ""
        ).strip() or "Civil Line"
        phone = request_data.phone.strip() if request_data.phone else ""

        if not vendor_name:
            raise HTTPException(status_code=400, detail="Vendor Name is required")

        cur = conn.cursor()
        cur.execute(
            """
            SELECT vendor_id
            FROM vendors
            WHERE LOWER(vendor_name) = LOWER(?)
              AND vendor_id <> ?
            """,
            (vendor_name, vendor_id),
        )
        duplicate = cur.fetchone()
        if duplicate:
            logger.warning(
                "Vendor update failed | context="
                f"{{'vendor_id': '{vendor_id}', 'reason': 'duplicate name', 'duplicate_vendor_id': '{duplicate[0]}'}}"
            )
            raise HTTPException(
                status_code=400,
                detail=f"Vendor name '{vendor_name}' already exists with ID '{duplicate[0]}'",
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
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/vendors/{vendor_id}")
async def api_delete_vendor(
    vendor_id: str,
    _: Any = Depends(require_role(ROLE_ADMIN)),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Delete a vendor when it is not referenced by any booking."""
    try:
        vendor_repo = VendorRepository(conn)
        vendor = vendor_repo.get_by_id(vendor_id)
        if not vendor:
            logger.warning(
                f"Vendor delete failed | context={{'vendor_id': '{vendor_id}', 'reason': 'not found'}}"
            )
            raise HTTPException(status_code=404, detail="Vendor not found")

        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM bookings WHERE vendor_id = ?", (vendor_id,))
        row = cur.fetchone()
        booking_count = int(row[0]) if row and row[0] is not None else 0

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

        cur.execute("DELETE FROM vendors WHERE vendor_id = ?", (vendor_id,))
        conn.commit()
        logger.info(f"Vendor deleted successfully | context={{'vendor_id': '{vendor_id}'}}")
        return {"success": True, "message": f"Vendor {vendor_id} deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting vendor: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


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
