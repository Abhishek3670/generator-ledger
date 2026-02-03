# 🚀 Generator Booking Ledger v2.0

A modern, modular **Generator Booking Management System** with both web and CLI interfaces.

## ✨ Features

- 📊 **Web Dashboard** - Beautiful, responsive UI for managing bookings
- 💻 **Command-Line Interface** - Powerful CLI for advanced operations
- ⚡ **RESTful API** - Full REST API with automatic documentation
- 🔒 **Business Logic** - Availability checking and conflict detection
- 📈 **Scalable Architecture** - Clean separation of concerns
- 🐳 **Docker Support** - Easy deployment with Docker & Docker Compose
- 📱 **Responsive Design** - Works on desktop and mobile

## 📁 Project Structure

```
generator_booking_ledger/
├── core/                      # Business logic (unchanged)
│   ├── models.py             # Data models
│   ├── database.py           # Database management
│   ├── repositories.py       # Data access layer
│   ├── services.py           # Business services
│   └── utils.py              # Utilities
│
├── web/                       # FastAPI web application
│   ├── app.py                # FastAPI app
│   ├── templates/            # HTML templates
│   └── static/               # CSS & JavaScript
│
├── cli/                       # Command-line interface
│   └── cli.py                # CLI implementation
│
├── main.py                    # Entry point (web/CLI router)
├── cli_main.py                # Direct CLI entry point
├── config.py                  # Configuration
├── requirements.txt           # Python dependencies
├── Dockerfile                 # Docker image
├── docker-compose.yml         # Docker Compose
└── README.md                  # This file
```

## 🎯 Quick Start

### Prerequisites
- Python 3.9+
- pip or conda
- (Optional) Docker & Docker Compose

### Installation

1. **Clone/Download the project**
   ```bash
   cd generator_booking_ledger
   ```

2. **Create virtual environment** (recommended)
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Add sample data** (optional)
   - Place `Generator_Dataset.xlsx` in `Data/` folder
   - Place `Vendor_Dataset.xlsx` in `Data/` folder

### Running the Application

#### Option 1: Web Interface (Recommended)
```bash
python main.py
```
Then open: **http://localhost:8000**

#### Option 2: Command-Line Mode
```bash
python main.py --cli
```

#### Option 3: Direct CLI
```bash
python cli_main.py
```

#### Option 4: Docker
```bash
# Build and run
docker-compose up

# Or build manually
docker build -t generator-ledger .
docker run -p 8000:8000 generator-ledger
```

## 🌐 Web Interface

### Available Pages
- **Dashboard** (`/`) - Overview and quick stats
- **Generators** (`/generators`) - View fleet inventory
- **Vendors** (`/vendors`) - Manage vendor relationships
- **Bookings** (`/bookings`) - View all bookings
- **Create Booking** (`/create-booking`) - Create new reservation
- **Booking Details** (`/booking/{id}`) - View booking details

### API Documentation
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health

## 💻 CLI Interface

Interactive menu with options:
1. List generators
2. List vendors
3. List bookings and items
4. Create booking
5. Add generator to booking
6. Modify booking times
7. Cancel booking
8. Export CSVs
9. Archive all bookings
10. Add new vendor
11. Exit

## 🔧 Configuration

Edit `config.py` or use environment variables:

```python
DB_PATH = "ledger.db"           # Database location
HOST = "127.0.0.1"              # Web server host
PORT = 8000                     # Web server port
DEBUG = True                    # Debug mode
```

Environment variables:
```bash
export DB_PATH="/path/to/db"
export HOST="0.0.0.0"
export PORT=8080
export DEBUG="False"
```

## 📚 API Endpoints

### Generators
- `GET /api/generators` - List all generators
- `GET /api/generators/{id}` - Get generator details

### Vendors
- `GET /api/vendors` - List all vendors
- `GET /api/vendors/{id}` - Get vendor details

### Bookings
- `GET /api/bookings` - List all bookings
- `POST /api/bookings` - Create new booking
- `GET /api/bookings/{id}` - Get booking details
- `POST /api/bookings/{id}/cancel` - Cancel booking

### Utilities
- `GET /api/export` - Export data to CSV
- `GET /api/info` - Application info
- `GET /health` - Health check

## 📊 Database Schema

### tables
- **generators** - Fleet inventory
- **vendors** - Partner information
- **bookings** - Booking records
- **booking_items** - Individual generator assignments

## 🏗️ Architecture

### Three-Layer Design

```
┌─────────────────────────────────────┐
│      Web Layer (FastAPI)            │
│  - HTTP Routing                     │
│  - HTML Templates                   │
│  - Static Assets                    │
└─────────────────────────────────────┘
           ↓
┌─────────────────────────────────────┐
│      Service Layer                  │
│  - BookingService                   │
│  - AvailabilityChecker              │
│  - ExportService                    │
│  - DataLoader                       │
└─────────────────────────────────────┘
           ↓
┌─────────────────────────────────────┐
│      Data Layer (SQLite)            │
│  - Repositories                     │
│  - Database Manager                 │
│  - Models                           │
└─────────────────────────────────────┘
```

### CLI
Directly uses Service Layer for operations.

## 🔐 Error Handling

- Comprehensive validation for all inputs
- Conflict detection for double-booking
- Transaction support for data integrity
- Detailed logging to `application.log`

## 📝 Logging

Logs are written to:
- **Console** - Real-time feedback
- **File** - `application.log` (rotating, 5MB max, 3 backups)

Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL

## 🚀 Deployment

### Local Development
```bash
python main.py
```

### Production with Docker
```bash
docker-compose up -d
```

### Cloud Deployment
Works with:
- ✅ AWS (Elastic Beanstalk, ECS, Lambda)
- ✅ Azure (App Service, Container Instances)
- ✅ Google Cloud (Cloud Run, App Engine)
- ✅ Heroku, Railway, Render, Fly.io

## 🧪 Testing

Run tests with pytest:
```bash
pytest
```

## 📦 Backup & Export

### Automated
- CSV exports available in `exported_data/` folder
- Archive bookings monthly in `archives/` folder

### Manual
Use CLI option 8 or API endpoint `/api/export` to download CSV files.

## 🔄 Updates & Maintenance

### Updating Dependencies
```bash
pip install --upgrade -r requirements.txt
```

### Database Backups
1. SQLite database: `ledger.db`
2. Exported CSVs: `exported_data/` folder
3. Archived bookings: `archives/` folder

## ❓ FAQ

**Q: How do I back up my data?**
A: Use CLI option 8 to export CSVs, or copy `ledger.db`.

**Q: Can I use PostgreSQL instead of SQLite?**
A: Yes, modify `core/database.py` to use a different database driver.

**Q: How do I add custom fields?**
A: Modify the models in `core/models.py` and update database schema.

**Q: Is there authentication?**
A: Not yet. Add FastAPI-Users for auth support.

**Q: Can I access from other computers?**
A: Yes, set `HOST="0.0.0.0"` in config and access from remote IP.

## 📞 Support

For issues, check:
1. `application.log` file
2. API documentation at `/docs`
3. Error messages in web interface

## 📄 License

See LICENSE file.

## 🙏 Credits

Built with:
- **FastAPI** - Modern web framework
- **SQLite** - Lightweight database
- **Pandas** - Data processing
- **Jinja2** - Template engine

---

**Version**: 2.0.0  
**Last Updated**: February 2026  
**Status**: Production Ready ✅
