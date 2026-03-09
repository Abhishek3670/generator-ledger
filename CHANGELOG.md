# Changelog

All notable changes to this project should be recorded in this file.

## Historical Note

Versioning was introduced after the project already had active development history.

The entries below for `1.0.0` through `2.1.0` are inferred from git commit groupings and feature milestones.
They should be treated as retrospective release notes, not as proof of exact historical deployment tags.

## [Unreleased]

- No unreleased changes documented after `2.1.0` yet.

## [2.1.0]

Status: current repository state / next deployment target  
Basis: inferred from commits `7823c8f` through `6f9bfe9`

### Added

- Emergency genset inventory support as a separate operational stock group.
- Emergency genset table on the generators page after the retailer genset table.
- Retailer out-of-stock fallback flow for create-booking with emergency suggestions.
- Emergency inventory metadata in booking and billing responses.
- Formalized project versioning and release history documentation.

### Changed

- Renamed the original generators table/section to `Retailer Genset`.
- Added responsive vertical scroll behavior to the generator inventory tables.
- Emergency-booked gensets now render in danger-red text across booking and billing views.
- Billing page now highlights emergency gensets in red.

### Fixed

- New generator creation validation now imports and recognizes maintenance status correctly.

## [2.0.0]

Status: inferred deployed `Pre-prod` baseline  
Basis: inferred from commits `744ad2e` through `ab14db4`

### Added

- Repository-layer refactor for web SQL access.
- Critical, high-priority, and medium-priority security hardening across the app.
- `python-dotenv` support for environment loading.
- Phase-2 UI and UX improvements for validation, tables, and forms.
- Per-user permission controls in settings.
- Session security handling for LAN and Docker access.
- Rental vendors directory support.

### Changed

- Refined bookings table interactions and create-booking vendor bookings panel behavior.
- Refined vendor UI and renamed rental vendor IDs for clearer management flows.

### Fixed

- Data integrity, auth, and request-handling issues addressed across the March hardening wave.
- Added the missing `Request` parameter for the login rate-limiter path.

## [1.3.0]

Status: inferred historical milestone  
Basis: inferred from commits `51455a5` through `fdc30fb`

### Added

- Live monitor tab with server metrics charts.
- GitLens-style history page redesign.
- Vendor hover actions with edit and delete overlays.
- Permission matrix with role-based access controls in admin settings.

### Changed

- Refined history timeline scrolling and detail presentation.

### Fixed

- Prevented removing the last booking item from a booking.
- Restricted billing access in line with the permissions model.

## [1.2.0]

Status: inferred historical milestone  
Basis: inferred from commits `bd8d4ba` through `58e918b`

### Added

- Grouped bookings page rows by booked date with booking detail overlay support.
- Advanced client-side booking filters with URL state.
- Billing preview with printable A4 output.
- Billing print layout improvements and vendor paid adjustments.
- Vendor search in billing UI.

### Changed

- Improved bookings page interaction flow and visibility rules.

### Fixed

- Reordered matched booking rows and hid empty vendor groups correctly.

## [1.1.0]

Status: inferred historical milestone  
Basis: inferred from commits `ec8ab72` through `c36064a`

### Added

- Hybrid session and JWT authentication.
- Vendor booking table on the create-booking page.
- Admin settings page and user delete flow.
- Grouped booking rows by date with better booking detail views.

### Changed

- Refined admin settings overlays and sorting behavior.

## [1.0.0]

Status: inferred initial release milestone  
Basis: inferred from commits `adf0168` through `233a4ac`

### Added

- Initial Generator Booking Ledger foundation.
- Duplicate vendor booking auto-merge.
- Create-booking UX improvements.
- Dashboard and navigation redesign.
- Booking calendar with day overlay.
- Booking detail and creation overlays.
- Booking history log and UI.
- Session auth with user roles and history audit.
- Generator management view and overlays.

### Changed

- Hardened core flows and archived the original monolith-style structure.
- Refined booking views, overlays, history details, and navigation actions.

### Fixed

- Bulk booking item validation.
- FastAPI SQLite connection lifecycle handling.
- Concurrency-safe ID generation.
