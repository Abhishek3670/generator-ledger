# Migration Guide: From CLI to Web + CLI v2.0

## What Changed?

Your Generator Booking Ledger application has been modernized with a new modular architecture while preserving all original functionality.

### Before (Old Structure)
```
app.py (1,290+ lines)
├── All business logic
├── All database code  
└── CLI interface
```

### After (New Structure)
```
core/              (Business logic - untouched)
web/               (New: Modern web interface)
cli/               (Preserved: All CLI functionality)
main.py            (Smart router)
```

## What Stayed the Same?

✅ **Database**: Same SQLite schema (`ledger.db`)  
✅ **Data Models**: Same classes and structure  
✅ **Business Logic**: Identical algorithms and services  
✅ **CLI Commands**: All 11 options work exactly the same  
✅ **Export/Archive**: Same functionality  

## What's New?

✨ **Web Dashboard**: Beautiful UI at `http://localhost:8000`  
✨ **REST API**: Full API at `/api/*` endpoints  
✨ **Auto-documentation**: Swagger UI at `/docs`  
✨ **Responsive Design**: Works on mobile and desktop  
✨ **Modular Code**: Clean, maintainable architecture  

## Migration Steps

### Step 1: Update Python (Optional but Recommended)
Ensure Python 3.9+:
```bash
python3 --version
```

### Step 2: Update Dependencies
```bash
pip install -r requirements.txt
```

### Step 3: Update Your Startup Command

| Scenario | Old | New |
|----------|-----|-----|
| Web interface | N/A | `python main.py` |
| CLI mode | `python app.py` | `python main.py --cli` |
| Direct CLI | N/A | `python cli_main.py` |

### Step 4: Update Any Scripts

If you have automation scripts that called `app.py`:

**Old**:
```bash
python app.py
```

**New**:
```bash
# For CLI:
python cli_main.py

# For web API:
python main.py  # then curl http://localhost:8000/api/...
```

## File Structure Reference

### For CLI Users
Your workflow is **unchanged**:
```bash
python cli_main.py
# or
python main.py --cli
```
All 11 menu options work identically.

### For Programmatic Access
Import from modular packages:

**Old**:
```python
from app import BookingService, CLI
```

**New**:
```python
from core import BookingService
from cli import CLI
```

### For Web Integration
Access via REST API:

```bash
# List generators
curl http://localhost:8000/api/generators

# List bookings
curl http://localhost:8000/api/bookings

# Create booking (example)
curl -X POST http://localhost:8000/api/bookings \
  -F "booking_id=BKG-001" \
  -F "vendor_id=V001"
```

## Database Compatibility

✅ **No migration needed!** The new `core/` code uses the same SQLite schema.

If you have an existing `ledger.db`:
1. Copy it to the new project folder
2. Run `python main.py`
3. It will use your existing database

## Environment Variables

You can now configure via environment variables:

```bash
export DB_PATH="/path/to/ledger.db"
export HOST="0.0.0.0"
export PORT=8080
export DEBUG="False"
```

## API Endpoints (New Feature)

Full REST API available at `/api/`:

```
GET  /api/generators        # List all
GET  /api/vendors           # List all
GET  /api/bookings          # List all
POST /api/bookings          # Create new
GET  /api/bookings/{id}     # Get detail
POST /api/bookings/{id}/cancel

GET  /api/export            # Export to CSV
GET  /api/info              # App info
GET  /health                # Health check
```

Documentation: `http://localhost:8000/docs`

## Troubleshooting Migration

### Issue: "ModuleNotFoundError: No module named 'core'"
**Solution**: Make sure you're running from the project directory:
```bash
cd /path/to/generator_booking_ledger
python main.py
```

### Issue: "Database locked"
**Solution**: Old instance still running. Check for other processes:
```bash
pkill -f "python.*main.py"
```

### Issue: "No generators loaded"
**Solution**: Ensure Excel files are in `Data/` folder:
- `Data/Generator_Dataset.xlsx`
- `Data/Vendor_Dataset.xlsx`

### Issue: Web page won't load
**Solution**: Check if server started correctly:
```bash
curl http://localhost:8000/health
```

## Rollback to Old Version

If needed, the old `app.py` is still present. You can run it:
```bash
# Not recommended, but possible
python3 app.py
```

However, we recommend using the new structure which is more maintainable.

## Performance & Improvements

| Aspect | Old | New |
|--------|-----|-----|
| Code organization | Single file | Modular packages |
| Startup time | Fast | Faster |
| Web support | No | Yes ✅ |
| API support | No | Yes ✅ |
| Testing | Hard | Easy ✅ |
| Deployment | Local only | Docker ready ✅ |
| Maintenance | Difficult | Easy ✅ |

## Next Steps

1. **Try the web interface**:
   ```bash
   python main.py
   open http://localhost:8000
   ```

2. **Explore API docs**:
   ```
   http://localhost:8000/docs
   ```

3. **Read full docs**:
   - See `INTEGRATION_GUIDE.md` for complete features
   - See `README.md` for troubleshooting

4. **Deploy with Docker** (optional):
   ```bash
   docker-compose up
   ```

## Support

For issues:
1. Check `application.log` for errors
2. Review `/docs` endpoint for API usage
3. See `INTEGRATION_GUIDE.md` for FAQ

---

**Version**: 2.0.0  
**All data and functionality preserved** ✅  
**Backward compatible** ✅  
**Ready for production** ✅
