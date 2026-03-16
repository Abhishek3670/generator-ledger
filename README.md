# Generator Booking Ledger

Generator Booking Ledger is a FastAPI + SQLite operations system for managing generator inventory, vendor relationships, bookings, billing visibility, and audit history in one place. It ships with a browser-based UI, a preserved CLI, authenticated APIs, and a data model tailored to day-to-day genset operations.

The project has grown beyond a simple booking tracker. In its current form it supports:

- generator inventory management across `Retailer`, `Permanent`, and `Emergency` groups
- retailer vendor management for normal bookings
- rental vendor management for marriage halls or properties where gensets are parked permanently
- booking creation, modification, cancellation, deletion, and conflict detection
- automatic generator allocation by capacity
- billing and calendar views for operational follow-up
- audit-style booking history and role-based administration
- browser sessions, JWT login for APIs, CSRF protection, and transport-security controls

Current version: `3.1.1`

## Business Model

This repo models three related operational concepts:

- `Vendors`: regular retailer-facing customers who book gensets for date/time ranges
- `Rental Vendors`: marriage halls or properties where a genset may stay parked permanently
- `Generators`: physical gensets tracked by capacity, identification, status, inventory type, and optional rental-vendor assignment

The `Permanent Genset` flow is important:

- a generator with `inventory_type = permanent` can be linked to a `rental_vendor_id`
- it appears on the Generator page in a dedicated `Permanent Genset` table
- it is excluded from normal booking stock and auto-assignment
- the table shows the assigned `Rental Vendor` instead of a booking-status badge

## What The System Does

- prevents overlapping generator bookings using time-based conflict checks
- manages bookings and booking items separately so one booking can hold multiple gensets
- keeps operational views for generators, vendors, bookings, billing, history, and settings
- records booking history for an audit-friendly timeline
- supports both human UI flows and JSON APIs
- can optionally seed initial data from Excel files in `Data/`
- exports operational data to `exported_data/`

## Architecture Overview

The project follows a fairly clean layered structure:

```text
genset/
├── .github/                 # Repository-level instructions and automation metadata
├── main.py                  # Main entry point: web or CLI
├── cli_main.py              # CLI-only entry point
├── config.py                # App settings, version, logging
├── core/                    # Models, repositories, services, auth, permissions
├── web/                     # FastAPI app, Jinja templates, static assets
├── cli/                     # Interactive command-line interface
├── tests/                   # API, service, auth, permissions, UI behavior tests
├── README.md                # Project guide and onboarding
├── CHANGELOG.md             # Release history
├── VERSIONING.md            # Versioning rules and release status
└── docker-compose.yml       # Container deployment
```

### Core Layers

- `core/database.py`: SQLite schema creation, additive migrations, and bootstrap-safe initialization
- `core/models.py`: dataclasses and enums for generators, vendors, bookings, users, sessions, and history
- `core/repositories.py`: SQL persistence and query logic
- `core/services.py`: booking rules, availability checks, exports, and seed loading
- `core/auth.py`: password hashing, token/session helpers, owner bootstrap
- `core/permissions.py`: capability matrix for admin/operator access
- `web/app.py`: routes, APIs, request auth, template rendering, and startup lifecycle

## Data Flow

At a high level, requests move through the system like this:

1. The app starts, initializes the SQLite schema, ensures the owner user exists, and optionally loads seed data.
2. Browser requests authenticate with a signed session cookie; API clients can use JWT-based login.
3. `web/app.py` resolves auth and permissions, opens a per-request DB connection, and dispatches routes.
4. Repositories load and persist data.
5. Services apply business rules such as availability checks, conflict prevention, export logic, and booking restrictions.
6. Jinja templates render HTML pages, while `/api/*` routes return JSON.

Booking stock behavior is intentionally selective:

- `retailer` and `emergency` generators are bookable inventory
- `permanent` generators are visible operational assets, but not part of bookable supply

## Database Model

The main SQLite database is `ledger.db`. Core tables include:

- `generators`
- `vendors`
- `rental_vendors`
- `bookings`
- `booking_items`
- `booking_history`
- `users`
- `user_permission_overrides`
- `sessions`
- `revoked_tokens`

Notable schema behavior:

- additive migrations keep older databases compatible
- generator inventory is indexed by `inventory_type`
- permanent generators can store `rental_vendor_id`
- booking history is stored separately for timeline and audit views

## User-Facing Features

### Web App

- dashboard and operational overview
- generator inventory page with Retailer, Permanent, and Emergency sections
- vendor page with retailer and rental-vendor management
- booking list, detail, creation, editing, cancellation, and deletion flows
- billing view for booking-line reporting
- history page with GitLens-style event presentation
- admin settings for users, roles, and permission overrides

### API

Representative routes and APIs:

- `GET /login`
- `POST /login`
- `GET /health`
- `GET /api/info`
- `POST /api/login`
- `GET /api/generators`
- `POST /api/generators`
- `PATCH /api/generators/{generator_id}`
- `GET /api/vendors`
- `GET /api/rental-vendors`
- `POST /api/bookings`
- `GET /api/bookings/{booking_id}`
- `POST /api/bookings/{booking_id}/cancel`
- `DELETE /api/bookings/{booking_id}`
- `GET /api/billing/lines`
- `GET /api/calendar/events`
- `GET /api/monitor/live`
- `GET /api/export`

Interactive API docs are available at `/docs` when the app is running.

### CLI

The original CLI is still available for terminal-based workflows:

- list generators, vendors, and bookings
- create and manage bookings
- export operational data
- run without the browser UI

## Security Model

The current app includes several practical security controls:

- owner-user bootstrap from environment variables
- browser session authentication
- JWT login for API clients
- CSRF validation for session-authenticated state-changing requests
- role-based permissions for `admin` and `operator` users
- per-user permission overrides
- optional HSTS and secure-cookie behavior controlled by environment

## Getting Started

### Requirements

- Python `3.12+`
- SQLite
- `pip`

### 1. Create a Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

Copy the example file:

```bash
cp .env.example .env
```

Edit `.env` and set these values before first run:

- `SESSION_SECRET`
- `JWT_SECRET`
- `OWNER_USERNAME`
- `OWNER_PASSWORD`

Recommended: replace the example secrets with secure random values.

### 4. Optional Seed Data

If you want the app to import initial Excel data on startup:

- create `Data/` if it does not already exist
- place `Generator_Dataset.xlsx` in `Data/`
- place `Vendor_Dataset.xlsx` in `Data/`
- set `LOAD_SEED_DATA=true` in `.env`

Generator seed rows can also include `Inventory_Type` and `Rental_Vendor_ID`. If you use `Rental_Vendor_ID`, make sure the referenced rental vendor already exists in the database.

### 5. Start The Application

Run the web app:

```bash
python main.py --web
```

Or simply:

```bash
python main.py
```

Default local URLs:

- Login: `http://127.0.0.1:8000/login`
- App: `http://127.0.0.1:8000`
- API docs: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

### 6. First Login

Use the `OWNER_USERNAME` and `OWNER_PASSWORD` values from `.env` to sign in at:

```text
http://127.0.0.1:8000/login
```

That bootstrap owner account is the first admin user for the system. After login, you can manage additional users and permission overrides from `Admin Settings`.

Run the CLI instead:

```bash
python main.py --cli
```

Or:

```bash
python cli_main.py
```

## Docker

The repo includes a single-container Docker deployment with bind mounts for operational data.

### Start With Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

By default:

- the container listens on `8000`
- host port defaults to `8001` through `DOCKER_HOST_PORT`
- the database is mounted from `./ledger.db`
- `Data/`, `exported_data/`, and `archives/` are mounted into the container

The compose file expects `APP_IMAGE_TAG` in `.env`, which is currently `v3.1.1`.

Open the app at `http://127.0.0.1:8001/login` when running with the default compose port mapping.

## Common Commands

```bash
# Web
python main.py

# CLI
python main.py --cli

# Custom port
python main.py --web --port 8080

# Tests
pytest

# Health check
curl http://127.0.0.1:8000/health

# App metadata
curl http://127.0.0.1:8000/api/info
```

## Testing

The test suite covers a broad slice of the current behavior, including:

- authentication and transport security
- booking service rules
- generator inventory features, including Permanent Gensets
- billing-line APIs
- vendor and rental-vendor management
- user permissions and settings matrix
- booking bulk updates and page behavior
- history and monitor endpoints

Run all tests:

```bash
pytest
```

## Operational Files And Folders

- `ledger.db`: main SQLite database
- `logs/application.log`: rotating runtime log file
- `exported_data/`: generated CSV exports
- `archives/`: archived historical exports
- `Backup/`: manual backup area

## Configuration Notes

Key environment variables from `.env.example`:

- `DB_PATH`
- `LOAD_SEED_DATA`
- `SESSION_SECRET`
- `JWT_SECRET`
- `OWNER_USERNAME`
- `OWNER_PASSWORD`
- `HOST`
- `PORT`
- `DEBUG`
- `SESSION_TTL_MINUTES`
- `SESSION_COOKIE_SECURE`
- `ENABLE_HSTS`
- `JWT_EXPIRE_MINUTES`

Versioning and release tracking live in:

- `CHANGELOG.md`
- `VERSIONING.md`

## Development Notes

- the browser UI uses Jinja templates in `web/templates/`
- static assets live in `web/static/`
- the app logs to `logs/application.log`
- startup fails safely if owner credentials are missing
- the schema is designed to migrate older databases forward without destructive resets
- release/version governance is documented in `CHANGELOG.md` and `VERSIONING.md`

## Why This Repo Is Useful

This project works well as both an internal operations tool and a solid example of a pragmatic Python web app:

- SQLite-backed but structured with clear layers
- simple enough to run locally
- serious enough to include auth, permissions, auditing, and deployment support
- tailored to real operational problems like conflict-free bookings and permanently assigned stock
