# Copilot Instructions - Generator Booking Ledger

## Overview
This is a **Generator Booking Ledger** system - a FastAPI web application that manages generator bookings for vendors. It provides both a web UI and CLI interface for managing generators, vendors, and bookings with time-slot availability checking.

---

## Architecture & Data Flow

### Layered Architecture (Repository Pattern)
```
web/app.py (FastAPI routes & Jinja2 templates)
    ↓
core/services.py (BookingService, AvailabilityChecker, etc.)
    ↓
core/repositories.py (GeneratorRepository, BookingRepository, etc.)
    ↓
core/database.py (SQLite connection & schema)
```

**Key principle**: Business logic lives in `services.py`, data access in `repositories.py`. Routes in `web/app.py` are thin wrappers that call services.

### Core Domain Models
- **Generator**: Has `generator_id`, `capacity_kva`, status (ACTIVE/INACTIVE/MAINTENANCE)
- **Vendor**: Has `vendor_id`, `vendor_name`, contact info
- **Booking**: Parent record with `booking_id`, `vendor_id`, created_at, status (CONFIRMED/CANCELLED/PENDING)
- **BookingItem**: Child records under Booking, each represents a generator assignment with `start_dt`/`end_dt` in format `"YYYY-MM-DD HH:MM"`

**Schema location**: [core/database.py](core/database.py#L48) - tables: `generators`, `vendors`, `bookings`, `booking_items`, `booking_history`, `users`, `user_sessions`

---

## Critical Patterns & Conventions

### 1. **DateTime Handling**
- Format everywhere: `"YYYY-MM-DD HH:MM"` (defined in [config.py](config.py#L39))
- Use `DateTimeParser` class (not raw strptime) for flexibility with day-month input
- Example: `DateTimeParser.parse("15-02")` → `"2026-02-15 08:00"` (with current year)
- **Always validate periods**: `DateTimeParser.validate_period(start_dt, end_dt)` before saving

### 2. **Availability Checking**
Location: [core/services.py](core/services.py#L65)
- `AvailabilityChecker.is_available(generator_id, start_dt, end_dt, exclude_booking_id=None)`
- Returns `(is_available: bool, conflicting_booking: Optional[Dict])`
- **Important**: Pass `exclude_booking_id` when editing bookings to allow time-slot reuse by same booking
- Logic: Two periods overlap if `start1 < end2 AND end1 > start2`

### 3. **Transaction & Error Handling**
```python
from core.utils import transaction
from core.services import log_booking_history

with transaction(conn):
    repo.save(booking)
    log_booking_history(conn, "booking_created", booking_id=booking.booking_id, ...)
```
- All DB writes must be in transactions (see [web/app.py](web/app.py#L1) for patterns)
- History logging is non-blocking (catches exceptions internally)

### 4. **Repository Pattern Data Access**
```python
gen_repo = GeneratorRepository(conn)
generator = gen_repo.get_by_id("GEN-1")
vendors = vendor_repo.list_all()
booking_items = booking_repo.get_items(booking_id)
```
- Repositories always take `conn` in `__init__`
- All queries return typed objects (not raw rows)
- Location: [core/repositories.py](core/repositories.py#L1)

### 5. **Service Layer Business Logic**
Location: [core/services.py](core/services.py#L1)
- `BookingService.create_booking(vendor_id, items_list)` - single call returns merged booking ID
- Merges multiple items into one booking if same vendor+date
- Auto-assigns generators based on availability and capacity
- `BookingService.cancel_booking()` - marks booking as CANCELLED (soft delete)

### 6. **Database Connections (Request-scoped)**
- **Web**: Uses `connect_sqlite()` middleware (see [core/observability.py](core/observability.py)) to create per-request connections
- **CLI**: Single connection for entire session (see [cli/cli.py](cli/cli.py#L27))
- Never share connections across requests or threads
- SQLite with `check_same_thread=False` compatibility for multi-threaded use

### 7. **Logging & Observability**
```python
from config import setup_logging
logger = logging.getLogger(__name__)
logger.info(f"Event | context={{'key': '{value}'}}")
logger.warning(..., exc_info=True)
```
- All logs use structured context dicts for easier parsing
- Exceptions logged with `exc_info=True`
- Setup: [config.py](config.py#L58) - writes to `application.log` + stdout

---

## Key Files & Their Purpose

| File | Purpose |
|------|---------|
| [web/app.py](web/app.py) | FastAPI routes (~2900 lines) - render HTML, handle forms, JSON APIs |
| [core/services.py](core/services.py) | Business logic: BookingService, AvailabilityChecker (~724 lines) |
| [core/repositories.py](core/repositories.py) | Data access layer (~983 lines) - all CRUD operations |
| [core/database.py](core/database.py) | Schema initialization & connection management |
| [core/models.py](core/models.py) | Dataclasses: Generator, Vendor, Booking, BookingItem |
| [core/auth.py](core/auth.py) | Password hashing, JWT token creation, user bootstrap |
| [core/utils.py](core/utils.py) | DateTimeParser, transaction context manager |
| [core/validation.py](core/validation.py) | ensure_booking(), ensure_generator(), ensure_vendor() helpers |
| [cli/cli.py](cli/cli.py) | CLI mode - print tables, load data, export CSV |

---

## Development Workflows

### Running the App
```bash
# Activate venv first
source .venv/bin/activate

# Web interface (default, http://localhost:8000)
python main.py

# CLI mode
python main.py --cli

# Custom port
python main.py --port 9000
```

### Running Tests
```bash
pytest tests/ -v
# Specific test:
pytest tests/test_booking_service.py::test_create_booking_auto_assign -v
```
- Tests use in-memory SQLite (`:memory:`)
- Fixtures: `conn`, `seed_minimal()` in [tests/test_booking_service.py](tests/test_booking_service.py#L7)

### Testing Pattern
```python
@pytest.fixture
def conn():
    db = DatabaseManager(":memory:")
    conn = db.connect()
    db.init_schema()
    yield conn
    db.close()
```

### Building & Deployment
- **Python**: 3.12+ (see [pyproject.toml](pyproject.toml#L7))
- **Dependencies**: FastAPI, Uvicorn, pandas, passlib, PyJWT (see [pyproject.toml](pyproject.toml#L10))
- **Docker**: `Dockerfile` provided, multi-stage build
- **Database**: SQLite (ledger.db), configured via `DB_PATH` env var

### Key Environment Variables
```
DB_PATH=ledger.db
LOAD_SEED_DATA=false
DEBUG=true
HOST=127.0.0.1
PORT=8000
SESSION_SECRET=... (must set for security)
OWNER_USERNAME=admin
OWNER_PASSWORD=password
```

---

## Project-Specific Edge Cases

1. **Cancelled Bookings**: Cannot modify or add items to cancelled bookings - check `booking.status == STATUS_CANCELLED` before allowing edits
2. **Time Slot Conflicts**: When editing a booking, exclude its own ID: `is_available(..., exclude_booking_id=booking_id)`
3. **Soft Deletes**: Bookings are cancelled, never deleted - Status field controls visibility
4. **Vendor Merging**: Multiple bookings for same vendor on same date merge into one booking ID
5. **Admin User Bootstrap**: First admin created via env vars (OWNER_USERNAME/PASSWORD) or skipped if user count > 0
6. **Empty Generator Query**: Before creating booking, verify generators exist and have required capacity

---

## Common Additions/Modifications

- **Add new API endpoint**: Add route to [web/app.py](web/app.py), call service layer, return HTML or JSON
- **Add new repository method**: Add to [core/repositories.py](core/repositories.py), follow existing cursor pattern
- **Add new service method**: Call repository in [core/services.py](core/services.py), log history events, handle exceptions
- **Add new table**: Update schema in [core/database.py](core/database.py#L48), create Repository class, update models
- **Add new field to model**: Update dataclass in [core/models.py](core/models.py), update schema, update repository queries

---

## Codebase Quality Standards

- **Code style**: PEP 8 (line length ~88 chars) with type hints throughout
- **Docstrings**: Google-style format (Args, Returns, Raises) for all functions
- **Error messages**: Clear and actionable (e.g., "Vendor 'X' does not exist" not "Operation failed")
- **Testing**: Unit tests in [tests/](tests/) using pytest; test fixtures for DB setup
- **No globals**: Database connections and services always passed, never stored globally
