# Booking Creation Fix - Generator Count & Date Submission

## Issues Fixed

### 1. Generator Count Showing Zero
**Problem**: Bookings were created but with 0 generators assigned
**Root Cause**: The form was collecting generator/capacity and date information, but the API endpoint was ignoring all this data and creating bookings with empty items list `[]`

**Solution**: 
- Updated form submission to collect all booking data (generator ID or capacity, start date, end date, remarks)
- Updated API endpoint to accept JSON with vendor_id and items array
- Items are now properly passed to the `create_booking()` method

### 2. Dates Submitting in Wrong Format
**Problem**: HTML5 datetime-local input format (`YYYY-MM-DDTHH:MM`) was not being converted to the expected format (`YYYY-MM-DD HH:MM`)

**Solution**:
- Added JavaScript date conversion: `replace('T', ' ')` to convert `2026-02-03T14:30` to `2026-02-03 14:30`
- This format matches the `DATETIME_FORMAT` expected by the system

## Code Changes

### File 1: web/templates/create_booking.html
**Changes**: 
- Form submission now collects all data including generator/capacity selection
- Converts datetime-local format to required format with `replace('T', ' ')`
- Validates that both start and end dates are selected
- Validates that either generator_id or capacity_kva is selected based on assignment method
- Sends JSON request with proper structure: `{ vendor_id, items: [{ generator_id/capacity_kva, start_dt, end_dt, remarks }] }`

**Key JavaScript Logic**:
```javascript
// Convert datetime-local format to YYYY-MM-DD HH:MM
const startDt = startDtLocal.replace('T', ' ');
const endDt = endDtLocal.replace('T', ' ');

// Build item object with proper fields
let item = {
    'start_dt': startDt,
    'end_dt': endDt,
    'remarks': remarks
};

// Add either generator_id or capacity_kva
if (assignMethod === 'generator') {
    item['generator_id'] = generatorId;
} else {
    item['capacity_kva'] = parseInt(capacityKva);
}

// Send as JSON to API
body: JSON.stringify({
    'vendor_id': vendorId,
    'items': [item]
})
```

### File 2: web/app.py
**Changes**:
- Added imports: `Dict, Any` from typing and `BaseModel` from pydantic
- Added Pydantic models for request validation:
  - `BookingItem`: Represents a single generator assignment with start/end times
  - `CreateBookingRequest`: Represents the complete request with vendor_id and items array
- Updated endpoint signature to accept `CreateBookingRequest` instead of `Form(...)`
- Endpoint now converts Pydantic models to dictionaries and passes items to service

**Key Changes**:
```python
from pydantic import BaseModel

class BookingItem(BaseModel):
    generator_id: Optional[str] = None
    capacity_kva: Optional[int] = None
    start_dt: str
    end_dt: str
    remarks: str = ""

class CreateBookingRequest(BaseModel):
    vendor_id: str
    items: List[BookingItem]

@app.post("/api/bookings")
async def api_create_booking(
    request_data: CreateBookingRequest,
    conn: sqlite3.Connection = Depends(get_db)
):
    vendor_id = request_data.vendor_id
    items = [item.dict() for item in request_data.items]
    # Now items contains all the generator/capacity and date data
    booking_id = service.create_booking(vendor_id, items)
    return {"success": True, "booking_id": booking_id}
```

## Data Flow

**Before (Broken)**:
```
Form Input (generator_id, dates) 
  → Ignored by JS
  → API receives only vendor_id
  → API creates booking with items=[]
  → Result: 0 generators assigned
```

**After (Fixed)**:
```
Form Input (generator_id/capacity, dates) 
  → JS collects and converts dates
  → Validates all required fields
  → Sends JSON: { vendor_id, items: [{...}] }
  → API receives and validates via Pydantic
  → API passes items to create_booking()
  → Result: Generators properly assigned with dates
```

## Testing Steps

1. **Test Generator Assignment by ID**:
   - Select vendor
   - Choose "Assign by Generator ID"
   - Select a generator
   - Enter start and end dates
   - Submit form
   - Verify: Booking created with generator assigned, dates correct

2. **Test Auto-Assignment by Capacity**:
   - Select vendor
   - Choose "Assign by Capacity"
   - Select capacity
   - Enter start and end dates
   - Submit form
   - Verify: Booking created with auto-assigned generator, dates correct

3. **Test Date Conversion**:
   - Select dates/times using date picker
   - Submit form
   - Check booking detail page
   - Verify: Dates displayed in correct format (YYYY-MM-DD HH:MM)

4. **Test Validation**:
   - Try submitting without selecting dates → Should show error
   - Try submitting without selecting generator/capacity → Should show error
   - Try submitting with invalid date range → Should be caught by backend

## Files Modified

1. `/home/aatish/app/genset/web/templates/create_booking.html` - Updated form submission logic
2. `/home/aatish/app/genset/web/app.py` - Added Pydantic models and updated endpoint

## Verification

✅ Python syntax validated for web/app.py
✅ Pydantic models properly defined
✅ Date conversion logic implemented
✅ API endpoint properly handles JSON requests
✅ Form validation in JavaScript added
