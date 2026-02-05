# Architecture Diagram - Bookings Display System

## User Interface Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                      BOOKINGS DISPLAY SYSTEM                     │
└─────────────────────────────────────────────────────────────────┘

                            User Browser
                                 │
                    ┌────────────┼────────────┐
                    │            │            │
                    ▼            ▼            ▼
            ┌──────────────┐ ┌──────────┐ ┌──────────┐
            │  GET /       │ │ GET /    │ │ DELETE / │
            │  bookings    │ │ booking/ │ │ api/... │
            │              │ │ {id}/    │ │          │
            │ Display list │ │ edit     │ │ Delete   │
            │ grouped by   │ │          │ │ booking  │
            │ vendor       │ │ Edit     │ │          │
            │              │ │ single   │ │          │
            │ + Search     │ │ booking  │ │          │
            │ + Filter     │ │ inline   │ │          │
            └──────────────┘ └──────────┘ └──────────┘
                    │            │            │
                    └────────────┼────────────┘
                                 │
                        ┌────────▼────────┐
                        │   FastAPI Web   │
                        │   Server        │
                        │   /bookings     │
                        │   /booking/{id} │
                        │   /booking/{id}/│
                        │     edit        │
                        │   /api/...      │
                        └────────┬────────┘
                                 │
                    ┌────────────┼────────────┐
                    │            │            │
                    ▼            ▼            ▼
            ┌──────────────┐ ┌──────────┐ ┌──────────┐
            │  Get All     │ │  Get All │ │  Get All │
            │  Bookings    │ │ Vendors  │ │ Booking  │
            │              │ │          │ │  Items   │
            │  Group by    │ │ Use to   │ │          │
            │  Vendor      │ │ enrich   │ │ Extract  │
            │              │ │ data     │ │  dates   │
            │  Extract     │ │          │ │          │
            │  dates       │ │          │ │          │
            └──────────────┘ └──────────┘ └──────────┘
                    │            │            │
                    └────────────┼────────────┘
                                 │
                        ┌────────▼────────┐
                        │   SQLite DB     │
                        │   ledger.db     │
                        │                 │
                        │  - bookings     │
                        │  - booking_     │
                        │    items        │
                        │  - vendors      │
                        │  - generators   │
                        └─────────────────┘
```

---

## Component Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     WEB INTERFACE LAYER                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌────────────────────┐  ┌───────────────────────┐              │
│  │  bookings.html     │  │  edit_booking.html    │              │
│  │                    │  │                       │              │
│  │ - Vendor groups    │  │ - Booking info        │              │
│  │ - Booked dates     │  │ - Inline edit fields  │              │
│  │ - Status badges    │  │ - Add generator form  │              │
│  │ - 3 action buttons │  │ - Save/cancel buttons │              │
│  │ - Search filter    │  │ - JavaScript handling │              │
│  └────────────────────┘  └───────────────────────┘              │
│           │                         │                            │
│           └─────────────┬───────────┘                            │
│                         │                                        │
└─────────────────────────┼────────────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────────────┐
│                    API/ROUTES LAYER                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  WEB ROUTES (HTML Response)                              │   │
│  │  - GET /bookings        → Grouped list view              │   │
│  │  - GET /booking/{id}/edit → Edit form                   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  API ENDPOINTS (JSON Response)                           │   │
│  │  - GET  /api/bookings/{id}     → Booking detail          │   │
│  │  - POST /api/bookings/{id}/items        → Add generator  │   │
│  │  - POST /api/bookings/{id}/items/...    → Bulk update    │   │
│  │  - DELETE /api/bookings/{id}   → Delete booking          │   │
│  └──────────────────────────────────────────────────────────┘   │
│           │                                                      │
└───────────┼──────────────────────────────────────────────────────┘
            │
┌───────────▼──────────────────────────────────────────────────────┐
│                  SERVICES LAYER                                  │
├────────────────────────────────────────────────────────────────┐
│                                                                   │
│  ┌──────────────────┐  ┌──────────────────┐                     │
│  │  BookingService  │  │  BookingRepository                     │
│  │  - create        │  │  - get_all()     │                     │
│  │  - add_generator │  │  - get_by_id()   │                     │
│  │  - cancel        │  │  - get_items()   │                     │
│  │  - delete        │  │  - save()        │                     │
│  └──────────────────┘  └──────────────────┘                     │
│                                                                   │
│  ┌──────────────────┐  ┌──────────────────┐                     │
│  │ VendorRepository │  │ GeneratorRep.    │                     │
│  │  - get_all()     │  │  - get_all()     │                     │
│  │  - get_by_id()   │  │  - get_by_id()   │                     │
│  │  - save()        │  │  - save()        │                     │
│  └──────────────────┘  └──────────────────┘                     │
│           │                    │                                │
└───────────┼────────────────────┼────────────────────────────────┘
            │                    │
┌───────────▼────────────────────▼────────────────────────────────┐
│                  DATABASE LAYER                                 │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────────┐  ┌──────────────────┐                     │
│  │  bookings table  │  │  booking_items   │                     │
│  │  - booking_id PK │  │  table           │                     │
│  │  - vendor_id FK  │  │  - id PK         │                     │
│  │  - created_at    │  │  - booking_id FK │                     │
│  │  - status        │  │  - generator_id  │                     │
│  │                  │  │  - start_dt      │                     │
│  │                  │  │  - end_dt        │                     │
│  │                  │  │  - item_status   │                     │
│  │                  │  │  - remarks       │                     │
│  └────────┬─────────┘  └────────┬─────────┘                     │
│           │                     │                               │
│           └──────────┬──────────┘                               │
│                      │ FK                                       │
│           ┌──────────▼──────────┐  ┌──────────────────┐        │
│           │ vendors table       │  │ generators table │        │
│           │ - vendor_id PK      │  │ - generator_id   │        │
│           │ - vendor_name       │  │ - capacity_kva   │        │
│           │ - vendor_place      │  │ - identification │        │
│           │ - phone             │  │ - type           │        │
│           │                     │  │ - status         │        │
│           └─────────────────────┘  │ - notes          │        │
│                                    └──────────────────┘        │
│                                                                   │
│                   SQLite Database: ledger.db                     │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Data Processing Pipeline

### For /bookings Page Display

```
START: User requests /bookings
   │
   ├─ Step 1: Get all bookings from DB
   │   └─ SELECT * FROM bookings
   │
   ├─ Step 2: For each booking, get vendor info
   │   └─ SELECT * FROM vendors WHERE vendor_id = ?
   │
   ├─ Step 3: For each booking, get items
   │   └─ SELECT * FROM booking_items WHERE booking_id = ?
   │
   ├─ Step 4: Extract booked dates from items
   │   └─ For each item: extract date from start_dt
   │       Sort and unique them
   │
   ├─ Step 5: Group bookings by vendor name
   │   └─ bookings_by_vendor[vendor_name] = [bookings]
   │
   ├─ Step 6: Sort vendors alphabetically
   │   └─ Sort dict keys: A-Z
   │
   └─ Step 7: Render template
       └─ Pass grouped data to bookings.html
           User sees organized vendor-grouped layout
```

---

## Event Flow for Modify Action

```
User clicks "Modify" button
   │
   ├─ Navigate to: /booking/{booking_id}/edit
   │
   ├─ Backend:
   │   ├─ Get booking details
   │   ├─ Get all booking items
   │   ├─ Load generators list
   │   └─ Render edit_booking.html
   │
   ├─ User modifies:
   │   ├─ Changes start_dt values
   │   ├─ Changes end_dt values
   │   ├─ Updates remarks
   │   ├─ Removes items (marks in array)
   │   └─ Adds new generators (fills form)
   │
   └─ User clicks "Save Changes"
       │
       ├─ Collect updates from all edit fields
       ├─ Collect removed item IDs
       │
       ├─ POST to /api/bookings/{id}/items/bulk-update
       │
       ├─ Backend:
       │   ├─ UPDATE booking_items SET ... (for each change)
       │   ├─ DELETE FROM booking_items WHERE id IN (...)
       │   └─ COMMIT transaction
       │
       └─ Redirect to /bookings
           User sees updated bookings list
```

---

## Event Flow for Delete Action

```
User clicks "Delete" button
   │
   ├─ JavaScript shows confirmation dialog
   │   └─ "Delete booking for {vendor}? ID: {booking_id}"
   │
   ├─ User confirms
   │   │
   │   └─ DELETE /api/bookings/{booking_id}
   │
   ├─ Backend:
   │   ├─ Verify booking exists
   │   ├─ Get all booking items
   │   ├─ DELETE FROM booking_items WHERE booking_id = ?
   │   ├─ DELETE FROM bookings WHERE booking_id = ?
   │   └─ COMMIT
   │
   └─ Frontend:
       ├─ Show success message
       └─ Reload page
           User sees updated bookings list without deleted booking
```

---

## Technology Stack

```
┌──────────────────────┐
│   Frontend Layer     │
├──────────────────────┤
│ HTML/CSS/JavaScript  │
│ Jinja2 Templates     │
│ Responsive Design    │
│ Form Handling        │
│ Filter & Search      │
└──────────────────────┘
         │
         │ HTTP/AJAX
         ▼
┌──────────────────────┐
│  FastAPI Backend     │
├──────────────────────┤
│ Route Handlers       │
│ Request Validation   │
│ Business Logic       │
│ Error Handling       │
└──────────────────────┘
         │
         │ SQL
         ▼
┌──────────────────────┐
│   SQLite Database    │
├──────────────────────┤
│ ledger.db            │
│ 4 Tables             │
│ Indexes              │
│ FK Constraints       │
└──────────────────────┘
```

---

## Request/Response Examples

### GET /bookings
```
REQUEST:
  GET /bookings HTTP/1.1
  Host: localhost:8000

RESPONSE:
  HTTP/1.1 200 OK
  Content-Type: text/html

  [HTML with grouped bookings]
  
Structure:
  - Vendor: Dabbu
    - Booking 1: dates, status, actions
    - Booking 2: dates, status, actions
  - Vendor: Mallu
    - Booking 1: dates, status, actions
    - Booking 2: dates, status, actions
```

### POST /api/bookings/{id}/items/bulk-update
```
REQUEST:
  POST /api/bookings/BOOK-001/items/bulk-update HTTP/1.1
  Content-Type: application/json
  
  {
    "updates": [
      {
        "id": 123,
        "start_dt": "2026-02-10 08:00",
        "end_dt": "2026-02-11 16:00",
        "remarks": "Updated"
      }
    ],
    "removes": [456, 789]
  }

RESPONSE:
  HTTP/1.1 200 OK
  Content-Type: application/json
  
  {
    "success": true,
    "message": "Items updated successfully"
  }
```

### DELETE /api/bookings/{id}
```
REQUEST:
  DELETE /api/bookings/BOOK-001 HTTP/1.1
  Host: localhost:8000

RESPONSE:
  HTTP/1.1 200 OK
  Content-Type: application/json
  
  {
    "success": true,
    "message": "Booking BOOK-001 deleted successfully"
  }
```

---

## State Management

### Client-Side State (JavaScript)
```javascript
itemsToUpdate = {};  // Track modified fields
itemsToRemove = [];  // Track removed items
filterValue = "";    // Current search filter
```

### Server-Side State
```python
# Session: bookings data in context
# Database: persistent bookings/items
# Transactions: atomic updates
```

---

This architecture ensures:
- ✅ Clean separation of concerns
- ✅ Scalable design
- ✅ Proper error handling
- ✅ Data integrity
- ✅ Performance optimization
