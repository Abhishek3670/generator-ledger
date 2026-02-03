# 🚀 QUICK START GUIDE

## What You Have

A completely refactored **Generator Booking Ledger** system with:
- ✅ Modern FastAPI web interface
- ✅ Original CLI preserved and working
- ✅ RESTful API with automatic documentation
- ✅ Professional, responsive UI design
- ✅ Zero changes to business logic
- ✅ Docker-ready for deployment

## Get Running in 3 Steps

### Step 1: Install Dependencies
```bash
cd generator_booking_web
pip install -r requirements.txt
```

### Step 2: (Optional) Add Sample Data
Place your Excel files in the `Data/` folder:
- `Generator_Dataset.xlsx`
- `Vendor_Dataset.xlsx`

### Step 3: Start the Application

#### Option A: Web Interface (Recommended)
```bash
python main.py
```
Then open: **http://localhost:8000**

#### Option B: Command Line
```bash
python main.py --cli
```

## What's Inside

```
generator_booking_web/
├── 📁 core/              ← Your business logic (untouched)
├── 📁 web/               ← NEW: FastAPI web app
│   ├── app.py           ← Main web application
│   ├── templates/       ← HTML pages
│   └── static/          ← CSS & JavaScript
├── 📁 cli/              ← Your original CLI
├── main.py              ← Entry point (routes web/CLI)
├── config.py            ← Configuration
└── requirements.txt     ← Dependencies
```

## Key Features

### Web Interface
- **Dashboard**: System overview with statistics
- **Generators**: View entire fleet
- **Vendors**: Manage vendor relationships
- **Bookings**: Create, view, modify bookings
- **Auto-assignment**: Smart generator allocation by capacity
- **Conflict detection**: Prevents double-booking

### API Endpoints
- Full RESTful API at `/api/*`
- Interactive docs at `/docs`
- Alternative docs at `/redoc`

### CLI (Preserved)
All original commands work:
- List generators, vendors, bookings
- Create/modify/cancel bookings
- Export to CSV
- Archive bookings
- Add vendors

## Common Commands

```bash
# Web on default port (8000)
python main.py

# Web on custom port
python main.py --web --port 8080

# CLI mode
python main.py --cli

# Direct CLI
python cli_main.py

# Docker
docker-compose up
```

## Important URLs

When web server is running:
- **Main App**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

## Configuration

Edit `config.py` or use environment variables:
```python
DB_PATH = "ledger.db"          # Database location
HOST = "127.0.0.1"             # Server host
PORT = 8000                     # Server port
DEBUG = True                    # Debug mode
```

## Deployment

### Quick Deploy with Docker
```bash
docker build -t generator-ledger .
docker run -p 8000:8000 generator-ledger
```

### Using Docker Compose
```bash
docker-compose up -d
```

## Need Help?

- 📖 Full docs: See `README.md`
- 🔧 Integration details: See `INTEGRATION_GUIDE.md`
- 🏗️ Architecture: See `web_integration_analysis.md`
- 📊 API: Visit `/docs` when app is running

## Verification Checklist

Test that everything works:
- [ ] Web starts: `python main.py`
- [ ] Dashboard loads in browser
- [ ] CLI works: `python main.py --cli`
- [ ] Can create booking in web
- [ ] Can create booking in CLI
- [ ] Both interfaces see the same data

## What Changed?

### Before
```
main.py (single 800+ line file)
```

### After  
```
Modular architecture:
- core/ (business logic)
- web/ (FastAPI app)
- cli/ (preserved CLI)
```

### What Stayed the Same
- ✅ All functionality
- ✅ Database schema
- ✅ Business logic
- ✅ Data formats
- ✅ CLI interface

## Next Steps

1. **Try it out**: Start the web app and explore
2. **Read docs**: Check README.md for full features
3. **Customize**: Edit config.py for your needs
4. **Deploy**: Use Docker for production
5. **Extend**: Add features using the clean architecture

## Support

- Logs: Check `application.log`
- Database: `ledger.db` (SQLite)
- Exports: `exported_data/` folder
- Archives: `archives/` folder

---

**🎉 You're all set! Start with `python main.py` and open http://localhost:8000**
