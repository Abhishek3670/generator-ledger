#!/bin/bash
# ==========================================================================
# sync_test_db.sh — Sync production schema + sanitized data to test database
#
# SAFETY: This script reads FROM production but writes ONLY to the test DB.
# It sanitizes passwords and phone numbers before restoring.
# See SAFETY.md for rules.
#
# Usage:
#   ./scripts/sync_test_db.sh
#
# Prerequisites:
#   - Test DB container running: docker compose -f docker-compose.test.yml up -d
#   - psql and pg_dump available (or run via docker exec)
# ==========================================================================
set -euo pipefail

# ---- Configuration ----
PROD_HOST="192.168.29.71"
PROD_PORT="7865"
PROD_DB="ledger_db"
PROD_USER="genset_user"
PROD_CONTAINER="postgres-db"

TEST_HOST="localhost"
TEST_PORT="7899"
TEST_DB="ledger_db_test"
TEST_USER="genset_test_user"
TEST_PASSWORD="test_only_password"
TEST_CONTAINER="genset-test-db"

WORK_DIR="/tmp/genset_sync_$$"

# ---- Safety checks ----
echo "============================================"
echo "  Production Replica Sync — SAFETY CHECK"
echo "============================================"

# Check test container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${TEST_CONTAINER}$"; then
    echo "ERROR: Test database container '${TEST_CONTAINER}' is not running."
    echo "  Start it with: docker compose -f docker-compose.test.yml up -d"
    exit 1
fi

echo "✅ Test container '${TEST_CONTAINER}' is running"

# Check production container is reachable
if ! docker ps --format '{{.Names}}' | grep -q "^${PROD_CONTAINER}$"; then
    echo "ERROR: Production container '${PROD_CONTAINER}' is not running or not accessible."
    echo "  This script must be run on the same machine as the production database,"
    echo "  or the production container must be accessible via Docker."
    exit 1
fi

echo "✅ Production container '${PROD_CONTAINER}' is accessible"
echo ""

# ---- Create work directory ----
mkdir -p "$WORK_DIR"
trap "rm -rf $WORK_DIR" EXIT

echo "Step 1/5: Dumping production schema..."
docker exec "$PROD_CONTAINER" pg_dump \
    -U "$PROD_USER" \
    -d "$PROD_DB" \
    --schema-only \
    --no-owner \
    --no-privileges \
    > "$WORK_DIR/schema.sql"
echo "  → Schema dumped ($(wc -l < "$WORK_DIR/schema.sql") lines)"

echo "Step 2/5: Dumping production data (excluding sessions/tokens)..."
docker exec "$PROD_CONTAINER" pg_dump \
    -U "$PROD_USER" \
    -d "$PROD_DB" \
    --data-only \
    --no-owner \
    --no-privileges \
    --exclude-table=sessions \
    --exclude-table=revoked_tokens \
    --exclude-table=alembic_version \
    > "$WORK_DIR/data.sql"
echo "  → Data dumped ($(wc -l < "$WORK_DIR/data.sql") lines)"

echo "Step 3/5: Sanitizing sensitive data..."

# Sanitize user passwords — replace with bcrypt hash of 'TestPass@123'
# bcrypt hash for TestPass@123: $2b$12$LJ3m4ys3Lk8YORAOxCBKruYppDnQ1C0nHMdLBG8eLpKJVFmNuD8QW
SAFE_HASH='$2b$12$LJ3m4ys3Lk8YORAOxCBKruYppDnQ1C0nHMdLBG8eLpKJVFmNuD8QW'

# Create sanitization SQL that runs after data restore
cat > "$WORK_DIR/sanitize.sql" << 'SANITIZE_EOF'
-- Sanitize passwords (all users get TestPass@123)
UPDATE users SET password_hash = '$2b$12$LJ3m4ys3Lk8YORAOxCBKruYppDnQ1C0nHMdLBG8eLpKJVFmNuD8QW';

-- Sanitize phone numbers
UPDATE vendors SET phone = '0000000000' WHERE phone IS NOT NULL AND phone != '';
UPDATE rental_vendors SET phone = '0000000000' WHERE phone IS NOT NULL AND phone != '';

-- Clear any stale session/token data that might have leaked in
TRUNCATE TABLE sessions, revoked_tokens;
SANITIZE_EOF

echo "  → Sanitization script created"

echo "Step 4/5: Restoring to test database..."

# Drop and recreate test database
docker exec "$TEST_CONTAINER" psql \
    -U "$TEST_USER" \
    -d postgres \
    -c "DROP DATABASE IF EXISTS ${TEST_DB};" \
    -c "CREATE DATABASE ${TEST_DB} OWNER ${TEST_USER};"

# Restore schema
docker exec -i "$TEST_CONTAINER" psql \
    -U "$TEST_USER" \
    -d "$TEST_DB" \
    < "$WORK_DIR/schema.sql" \
    2>&1 | grep -c "ERROR" | xargs -I{} echo "  → Schema restored ({} errors)"

# Restore data
docker exec -i "$TEST_CONTAINER" psql \
    -U "$TEST_USER" \
    -d "$TEST_DB" \
    < "$WORK_DIR/data.sql" \
    2>&1 | grep -c "ERROR" | xargs -I{} echo "  → Data restored ({} errors)"

echo "Step 5/5: Applying sanitization..."
docker exec -i "$TEST_CONTAINER" psql \
    -U "$TEST_USER" \
    -d "$TEST_DB" \
    < "$WORK_DIR/sanitize.sql" \
    > /dev/null 2>&1

echo ""
echo "============================================"
echo "  Sync complete!"
echo "============================================"
echo ""
echo "Test database: postgresql://${TEST_USER}:***@${TEST_HOST}:${TEST_PORT}/${TEST_DB}"
echo ""

# Quick verification
echo "Table row counts:"
docker exec "$TEST_CONTAINER" psql \
    -U "$TEST_USER" \
    -d "$TEST_DB" \
    -c "SELECT 'vendors' as tbl, count(*) FROM vendors UNION ALL \
        SELECT 'generators', count(*) FROM generators UNION ALL \
        SELECT 'bookings', count(*) FROM bookings UNION ALL \
        SELECT 'users', count(*) FROM users UNION ALL \
        SELECT 'rental_vendors', count(*) FROM rental_vendors;"

echo ""
echo "All passwords have been reset to: TestPass@123"
echo "All phone numbers have been sanitized to: 0000000000"
echo "Sessions and revoked tokens have been cleared."
