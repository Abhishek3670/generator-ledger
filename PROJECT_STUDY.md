# Generator Booking Ledger - Complete Project Study

## 📋 Project Overview

**Generator Booking Ledger** is a comprehensive database management system for tracking generator rentals to vendors. It provides both a modern web interface and a command-line interface for managing generators, vendors, bookings, and scheduling.

**Version**: 2.0.0  
**Date**: February 2026  
**Technology Stack**: Python, FastAPI, SQLite, Pandas, Uvicorn

---

## 🎯 Core Purpose

The system solves a critical business problem: Managing generator availability and preventing double-bookings. Key capabilities:

- **Generator Fleet Management**: Track 30+ generators of varying capacities (20-45 KVA)
- **Vendor Relationships**: Manage ~14 rental vendors
- **Booking System**: Create and track bookings with automatic conflict detection
- **Time-based Availability**: Check generator availability for specific date/time periods
- **Data Export**: Export bookings to CSV for records/analysis
- **Monthly Archiving**: Archive old bookings to clear data for new periods

---

## 📁 Project Structure

```
/home/aatish/app/genset/
├── 📄 Main Entry Points
│   ├── main.py                 # Entry point (routes to web/CLI)
│   ├── app.ipynb              # Jupyter notebook for analysis
│   └── app.py                 # (Alternative entry point)
│
├── 📁 core/                    # Business logic layer
│   ├── __init__.py
│   ├── database.py            # Database connection & schema
│   ├── models.py              # Data models (dataclasses)
│   ├── repositories.py        # Data access layer
│   ├── services.py            # Business logic (563 lines)
│   └── utils.py               # Utility functions (DateTime parsing)
│
├── 📁 cli/                     # Command-line interface
│   ├── __init__.py
│   └── cli.py                 # Interactive CLI (289 lines)
│
├── 📁 web/                     # Web interface (FastAPI)
│   ├── __init__.py
│   ├── app.py                 # FastAPI application (511 lines)
│   ├── 📁 templates/          # HTML templates (8 templates)
│   │   ├── base.html
│   │   ├── index.html
│   │   ├── generators.html
│   │   ├── vendors.html
│   │   ├── bookings.html
│   │   ├── create_booking.html
│   │   ├── booking_detail.html
│   │   └── error.html
│   └── 📁 static/             # Static assets
│       ├── 📁 css/
│       │   └── styles.css
│       └── 📁 js/
│           └── main.js
│
├── 📁 Data/                    # Input data
│   ├── Generator_Dataset.csv   # 31 generators
│   └── Vendor_Dataset.csv      # 29 vendors
│
├── 📁 exported_data/           # Output directory
│   ├── booking_items.csv
│   ├── bookings.csv
│   ├── Generator_Dataset.csv
│   └── Vendor_Dataset.csv
│
├── 📁 archives/                # Archived monthly data
│   ├── booking_items_*.csv
│   └── bookings_*.csv
│
├── 📄 Configuration
│   ├── config.py              # App configuration & logging
│   ├── requirements.txt        # Dependencies (10 packages)
│   ├── Dockerfile             # Docker image definition
│   └── docker-compose.yml     # Docker compose setup
│
├── 📄 Documentation
│   ├── README.md              # Project documentation
│   ├── quick_guide.md         # Quick start guide
│   └── COMMANDS.sh            # Shell commands reference
│
└── 📁 Other Files
    ├── ledger.db              # SQLite database
    ├── clean_up_database.py   # Utility script
    ├── cli_main.py            # Alternative CLI entry
    └── __pycache__/           # Python cache
```

---

## 🗄️ Data Models

### 1. **Generator** (Physical Equipment)
```python
@dataclass
class Generator:
    generator_id: str           # e.g., "GEN-20KVA-PL-HA-01"
    capacity_kva: int           # 20, 30, 45, etc.
    identification: str         # e.g., "Plain(सादा)", "Blue (नीला)"
    type: str                   # e.g., "HA", "HATA", "RB", "4R"
    status: str                 # "Active", "Inactive", "Maintenance"
    notes: str                  # Optional metadata
```

**Sample Data**: 31 generators from Generator_Dataset.csv
- **20 KVA**: 6 generators (Plain, Red, Blue types)
- **30 KVA**: 6 generators (Thin tyre, Blue, Plain types)
- **45 KVA**: 3+ generators

### 2. **Vendor** (Rental Customers)
```python
@dataclass
class Vendor:
    vendor_id: str              # e.g., "VEN001", "VEN002"
    vendor_name: str            # e.g., "Mallu", "Dabbu", "Sonu"
    vendor_place: str           # e.g., "Aligarh", "Hathras"
    phone: str                  # Contact number
```

**Sample Data**: 29 vendors from Vendor_Dataset.csv
- Mostly DJ/event organizers
- Located around Aligarh region
- Phone numbers available for most

### 3. **Booking** (Rental Agreement)
```python
@dataclass
class Booking:
    booking_id: str             # Unique identifier for the rental
    vendor_id: str              # Who is renting
    created_at: str             # When booking was created (YYYY-MM-DD HH:MM)
    status: str                 # "Confirmed", "Cancelled", "Pending"
```

### 4. **BookingItem** (Generator Assignment)
```python
@dataclass
class BookingItem:
    booking_id: str             # Link to booking
    generator_id: str           # Which generator
    start_dt: str               # Start time (YYYY-MM-DD HH:MM)
    end_dt: str                 # End time (YYYY-MM-DD HH:MM)
    item_status: str            # "Confirmed", "Cancelled", "Pending"
    remarks: str                # Notes about this assignment
    id: Optional[int]           # Database auto-increment ID
```

---

## 🗃️ Database Schema

**SQLite Database**: `ledger.db`

### Tables Structure

```sql
-- Generators table
CREATE TABLE generators (
    generator_id TEXT PRIMARY KEY,
    capacity_kva INTEGER NOT NULL,
    identification TEXT,
    type TEXT,
    status TEXT DEFAULT 'Active',
    notes TEXT
);
CREATE INDEX idx_generators_capacity ON generators(capacity_kva, status);

-- Vendors table
CREATE TABLE vendors (
    vendor_id TEXT PRIMARY KEY,
    vendor_name TEXT NOT NULL,
    vendor_place TEXT,
    phone TEXT
);

-- Bookings table
CREATE TABLE bookings (
    booking_id TEXT PRIMARY KEY,
    vendor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT DEFAULT 'Confirmed',
    FOREIGN KEY(vendor_id) REFERENCES vendors(vendor_id)
);

-- Booking Items table (many-to-many: bookings ↔ generators)
CREATE TABLE booking_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id TEXT NOT NULL,
    generator_id TEXT NOT NULL,
    start_dt TEXT NOT NULL,
    end_dt TEXT NOT NULL,
    item_status TEXT DEFAULT 'Confirmed',
    remarks TEXT,
    FOREIGN KEY(booking_id) REFERENCES bookings(booking_id),
    FOREIGN KEY(generator_id) REFERENCES generators(generator_id)
);
CREATE INDEX idx_booking_items_generator 
    ON booking_items(generator_id, item_status);
Create INDEX idx_booking_items_booking 
    ON booking_items(booking_id);
```

### Key Relationships

```
Generators (1) ──┐
                 ├─→ Booking Items (many)
Bookings   (1) ──┤
                 └─→ Connected via booking_id

Vendors (1) ─────→ Bookings (many)
```

---

## 🔧 Core Services Architecture

### 1. **DatabaseManager** (`core/database.py`)
- Handles SQLite connections
- Initializes schema on first run
- Context manager pattern for safe connection handling

### 2. **Repositories** (`core/repositories.py`)
Data access objects for each entity:

- **GeneratorRepository**: Get, save, find by capacity
- **VendorRepository**: Get, save, generate vendor IDs
- **BookingRepository**: CRUD operations on bookings
- **BookingItemRepository**: Manage booking items

### 3. **Services** (`core/services.py` - 563 lines)

#### **AvailabilityChecker**
```python
is_available(generator_id, start_dt, end_dt) → (bool, conflict_info)
find_available(capacity_kva, start_dt, end_dt, needed) → [generators]
```
- Detects time-based conflicts
- Finds alternative generators
- Logs all conflicts

#### **BookingService**
```python
create_booking(vendor_id, items) → booking_id
add_generator(booking_id, generator_id, start_dt, end_dt)
modify_times(booking_id, generator_id, start_dt, end_dt)
cancel_booking(booking_id) → (bool, message)
get_booking(booking_id) → Booking object
```
- Manages booking lifecycle
- Validates inputs
- Handles conflict detection

#### **DataLoader**
```python
load_from_excel() → loads Generator_Dataset.xlsx, Vendor_Dataset.xlsx
```
- Populates initial database from CSV/Excel files
- Safe re-loading (INSERT OR REPLACE)

#### **ExportService**
```python
export_to_csv() → (bookings_path, items_path)
```
- Exports current bookings to CSV
- Creates timestamped archives

### 4. **Utilities** (`core/utils.py`)

#### **DateTimeParser**
- **parse()**: Handles multiple date formats
- **parse_day_month_to_full()**: Converts "DD-MM" → "YYYY-MM-DD HH:MM"
- **validate_period()**: Ensures start < end
- **periods_overlap()**: Time conflict detection

**Formats Supported**:
- `YYYY-MM-DD HH:MM` (standard)
- `DD-MM HH:MM` (day-month, assumes current year)
- `DD/MM HH:MM` (with slash separator)

---

## 🖥️ Web Interface (FastAPI)

**Main File**: `web/app.py` (511 lines)

### Key Features

1. **Routing Structure**:
   - `/` - Dashboard (index)
   - `/generators` - Generator listing/management
   - `/vendors` - Vendor listing/management
   - `/bookings` - Booking listing
   - `/bookings/<id>` - Booking details
   - `/api/*` - RESTful API endpoints
   - `/health` - Health check endpoint
   - `/docs` - Swagger UI documentation
   - `/redoc` - ReDoc API documentation

2. **Templates** (8 HTML files in `web/templates/`):
   - **base.html**: Navigation and layout
   - **index.html**: Dashboard with statistics
   - **generators.html**: Generator fleet view
   - **vendors.html**: Vendor management
   - **bookings.html**: Booking list
   - **create_booking.html**: New booking form
   - **booking_detail.html**: Booking details & modifications
   - **error.html**: Error display

3. **Static Assets** (`web/static/`):
   - **css/styles.css**: Professional responsive design
   - **js/main.js**: Client-side interactions

4. **API Endpoints** (Pydantic models):
   ```python
   BookingItem(generator_id, capacity_kva, date, remarks)
   CreateBookingRequest(vendor_id, items)
   CreateVendorRequest(vendor_id, vendor_name, vendor_place, phone)
   ```

### Workflow
1. User accesses dashboard
2. Select vendor and desired capacity/dates
3. System auto-suggests available generators
4. Create booking with selected generators
5. View/modify/cancel bookings anytime

---

## 💻 CLI Interface

**File**: `cli/cli.py` (289 lines)

### Interactive Menu
```
1. List generators
2. List vendors
3. List bookings and items
4. Create booking
5. Add generator to booking
6. Modify booking times
7. Cancel booking
8. Export CSVs
9. Archive all bookings (clear for new month)
10. Add new vendor
11. Exit
```

### Key Functions
- `create_booking_interactive()`: Get vendor, items, dates from user
- `add_generator_interactive()`: Add generator to existing booking
- `modify_times_interactive()`: Change booking dates
- `cancel_booking_interactive()`: Cancel and remove booking
- `export_service.export_to_csv()`: Export current data

---

## 🚀 Entry Points

### 1. **Web Interface** (Default)
```bash
python main.py
# or
python main.py --web --port 8000
```
- Starts FastAPI on http://localhost:8000
- Modern web UI for all operations
- Full REST API available at /docs

### 2. **CLI Interface**
```bash
python main.py --cli
# or
python cli_main.py
```
- Interactive command-line menu
- Original preserved functionality
- Useful for automated scripts

### 3. **Jupyter Notebook**
```bash
jupyter notebook app.ipynb
```
- Data analysis and exploration
- Ad-hoc reporting

---

## 🐳 Docker Deployment

### Dockerfile
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8000
HEALTHCHECK ...
CMD ["python", "main.py", "--web", "--host", "0.0.0.0"]
```

### Docker Compose
```yaml
services:
  web:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./Data:/app/Data
      - ./ledger.db:/app/ledger.db
      - ./exported_data:/app/exported_data
    environment:
      - DB_PATH=/app/ledger.db
      - DEBUG=False
```

**Usage**:
```bash
docker compose up --build
```

---

## 📦 Dependencies

```
pandas>=1.5.3          # Data processing
openpyxl>=3.1.0       # Excel read/write
xlrd>=2.0.1           # Excel reading
fastapi==0.109.0      # Web framework
uvicorn[standard]==0.27.0  # ASGI server
jinja2==3.1.3         # Template engine
python-multipart==0.0.6   # Form parsing
pytest>=7.0.0         # Testing (optional)
pytest-asyncio>=0.21.0    # Async tests (optional)
```

---

## 🐛 Critical Bugs Fixed (From Refactoring)

1. **Duplicate Function Definition**: `parse_dt_or_daymonth()` defined twice
2. **Missing Function**: `modify_booking_times()` called non-existent `parse_dt()`
3. **Undefined Variables**: CLI code executed on import instead of in `main()`
4. **Missing Return Values**: `cancel_booking()` didn't return status
5. **SQL Injection Risk**: Table names in f-strings (mitigated with validation)

---

## 📊 Business Logic Highlights

### Conflict Detection
```python
# Prevents double-booking
def is_available(generator_id, start_dt, end_dt):
    # Checks all confirmed bookings
    # Detects overlapping time periods
    # Returns conflict details if found
```

### Time Validation
```python
# Ensures logical bookings
start < end  # Start must be before end
format: YYYY-MM-DD HH:MM
```

### Generator Assignment
```python
# Auto-suggest available generators
def find_available(capacity_kva, start_dt, end_dt, needed):
    # Find N active generators of specified capacity
    # Check all are available for entire period
    # Return list of suitable generators
```

### Monthly Archiving
```python
# Clear database for new month
def archive_all_bookings():
    # Export all current data to timestamped CSVs
    # Clear booking tables
    # Preserve generator/vendor master data
```

---

## 🔒 Security & Robustness

### Input Validation
- ✅ Vendor existence checks
- ✅ Generator existence verification
- ✅ Datetime format validation
- ✅ Period logic validation (start < end)
- ✅ Positive integer validation
- ✅ Empty string handling
- ✅ Duplicate booking ID prevention

### Error Handling
- ✅ Comprehensive try-catch blocks
- ✅ Specific error messages
- ✅ Graceful degradation
- ✅ Resource cleanup (finally blocks)
- ✅ Type conversion validation

### Logging
- ✅ All operations logged
- ✅ File + Console handlers
- ✅ Rotating file handler (5MB limit)
- ✅ Structured logging with context

---

## 📈 Data Flow Overview

```
┌─────────────────────────────────────────────────────────┐
│                    User Interaction                      │
├─────────────────────────────────────────────────────────┤
│  Web UI (FastAPI)          │    CLI (Interactive Menu)   │
└────────────────────────────┬────────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │   Services      │
                    │ - Booking       │
                    │ - Availability  │
                    │ - Export        │
                    │ - DataLoader    │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ Repositories    │
                    │ - Generator     │
                    │ - Vendor        │
                    │ - Booking       │
                    │ - BookingItem   │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  SQLite DB      │
                    │  (ledger.db)    │
                    └─────────────────┘
```

---

## 🎓 Sample Workflow

### Creating a Booking
1. **Web Interface**: User selects vendor "Mallu" (VEN001)
2. **Input**: Needs 2×20KVA generators for Feb 8-9, 2026
3. **System**:
   - Validates vendor exists ✓
   - Creates Booking record
   - Finds available 20KVA generators
   - Creates BookingItem for each assignment
   - Checks no time conflicts ✓
4. **Output**: Booking ID (e.g., "BOOK-20260208-001")

### Monthly Archiving
1. **Before**: Database has Feb data
2. **Command**: `Export & Archive`
3. **System**:
   - Exports bookings.csv & booking_items.csv
   - Timestamps: `bookings_2026_02_2026_02_03_184443.csv`
   - Clears booking tables
   - Preserves generator/vendor master data
4. **After**: Ready for March bookings

---

## 🔄 Recent Refactoring Summary

The project underwent comprehensive refactoring addressing:

- **Critical Bugs**: 5 blocking issues fixed
- **Code Quality**: PEP 8 compliance, proper docstrings
- **Robustness**: Input validation, error handling
- **Performance**: Database indexing on frequently-queried fields
- **Maintainability**: Organized modules, clear separation of concerns

All business logic preserved; zero functional changes.

---

## 📝 Configuration

### Environment Variables (`config.py`)
- `DB_PATH`: Database file path (default: "ledger.db")
- `HOST`: Web server host (default: "127.0.0.1")
- `PORT`: Web server port (default: 8000)
- `DEBUG`: Debug mode (default: "True")

### Logging
- **Format**: `[LEVEL] module.function - message`
- **File**: `application.log` (rotating, 5MB max)
- **Console**: stdout
- **Handlers**: RotatingFileHandler + StreamHandler

---

## 🔗 Key Files at a Glance

| File | Purpose | Size |
|------|---------|------|
| main.py | Entry point router | 50 lines |
| core/database.py | DB connection & schema | 90 lines |
| core/models.py | Data models | 50 lines |
| core/repositories.py | Data access | 257 lines |
| core/services.py | Business logic | 563 lines |
| core/utils.py | Datetime parsing | 80 lines |
| cli/cli.py | Interactive CLI | 289 lines |
| web/app.py | FastAPI application | 511 lines |
| config.py | Configuration | 50 lines |

---

## 🎯 Usage Examples

### Start Web Server
```bash
python main.py
# Opens dashboard at http://localhost:8000
```

### Start CLI
```bash
python main.py --cli
# Interactive menu appears
```

### Docker Deployment
```bash
docker compose up --build
# Container runs on port 8000
```

### Export Data
```bash
# Via Web: Click "Export" button
# Via CLI: Select option 8
# Output: /exported_data/bookings.csv, booking_items.csv
```

### Archive Monthly Data
```bash
# Via Web: Click "Archive" button
# Via CLI: Select option 9
# Creates: /archives/bookings_YYYY_MM_YYYY_MM_DD_HHMMSS.csv
```

---

## 📅 Current State (February 2026)

- **Database**: Active with historical bookings
- **Generators**: 31 units ready for rental
- **Vendors**: 29 rental partners
- **System**: Running in production
- **Last Access**: 2026-02-05

---

## 🚀 Next Steps & Potential Enhancements

1. **Multi-user Management**: Add user authentication/roles
2. **Reporting Dashboard**: Advanced analytics & KPIs
3. **Payment Integration**: Invoice generation and tracking
4. **Mobile App**: Native mobile clients
5. **API Rate Limiting**: Protect against abuse
6. **Database Backup**: Automated backup strategy
7. **Notification System**: Email/SMS for bookings
8. **Capacity Planning**: Predictive analytics

---

*This study document provides a comprehensive overview of the Generator Booking Ledger system as of February 2026.*
