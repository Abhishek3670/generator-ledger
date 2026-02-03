#!/bin/bash
# Quick Reference Commands for Generator Booking Ledger v2.0

# ============================================================================
# INSTALLATION
# ============================================================================

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt


# ============================================================================
# RUNNING THE APPLICATION
# ============================================================================

# START WEB INTERFACE (Recommended)
python main.py
# Then visit: http://localhost:8000

# START CLI MODE
python main.py --cli
# or directly:
python cli_main.py

# CUSTOM WEB PORT
python main.py --web --port 8080

# CUSTOM HOST (for remote access)
python main.py --web --host 0.0.0.0


# ============================================================================
# DOCKER COMMANDS
# ============================================================================

# Build Docker image
docker build -t generator-ledger .

# Run Docker container
docker run -p 8000:8000 generator-ledger

# Using Docker Compose (easiest)
docker-compose up
docker-compose up -d         # Background
docker-compose down          # Stop and remove
docker-compose logs -f       # View logs
docker-compose restart       # Restart


# ============================================================================
# API ENDPOINTS
# ============================================================================

# List generators
curl http://localhost:8000/api/generators

# List vendors
curl http://localhost:8000/api/vendors

# List bookings
curl http://localhost:8000/api/bookings

# Export data
curl http://localhost:8000/api/export -O exported.json

# Health check
curl http://localhost:8000/health

# API documentation
open http://localhost:8000/docs


# ============================================================================
# DEVELOPMENT & TESTING
# ============================================================================

# Check Python syntax
python3 -m py_compile core/*.py web/app.py cli/cli.py

# Run tests (when added)
pytest

# Check code style
python3 -m flake8 core/ cli/ web/

# Run CLI directly
python3 cli_main.py


# ============================================================================
# DATABASE OPERATIONS
# ============================================================================

# Backup database
cp ledger.db ledger.db.backup

# Export all data
curl http://localhost:8000/api/export > data_export.json

# Reset database (creates new)
rm ledger.db
python main.py  # Will create fresh database


# ============================================================================
# TROUBLESHOOTING
# ============================================================================

# Check if server is running
curl http://localhost:8000/health

# View application logs
tail -f application.log

# Kill processes on port 8000
lsof -ti:8000 | xargs kill -9    # Linux/Mac
netstat -ano | findstr :8000     # Windows

# Check Python version
python3 --version

# Check installed packages
pip list

# Reinstall dependencies
pip install --upgrade -r requirements.txt


# ============================================================================
# PROJECT DOCUMENTATION
# ============================================================================

# Read main documentation
cat README.md

# Read integration guide
cat INTEGRATION_GUIDE.md

# Read migration guide
cat MIGRATION_GUIDE.md

# Read quick guide
cat quick_guide.md

# View architecture analysis
cat Web_integration.md


# ============================================================================
# FILE STRUCTURE
# ============================================================================

# List project structure
ls -la
ls -la core/
ls -la cli/
ls -la web/
ls -la web/templates/
ls -la web/static/

# Find all Python files
find . -name "*.py" | grep -v ".venv"

# Count lines of code
wc -l core/*.py cli/cli.py web/app.py

# ============================================================================
# USEFUL SHORTCUTS
# ============================================================================

# Open in browser
open http://localhost:8000              # Mac
start http://localhost:8000             # Windows
xdg-open http://localhost:8000          # Linux

# Quick setup (all in one)
python3 -m venv .venv && \
source .venv/bin/activate && \
pip install -r requirements.txt && \
python main.py

# Run with custom config
export DB_PATH="./my_database.db"
export HOST="0.0.0.0"
export PORT=9000
python main.py
