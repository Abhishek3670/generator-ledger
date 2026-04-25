#!/bin/bash
# ==========================================================================
# run_tests.sh — Safe test runner for the Generator Ledger test suite
#
# SAFETY: Enforces database isolation per SAFETY.md.
# Refuses to run if TEST_DATABASE_URL is not set or points to production.
#
# Usage:
#   source .env.test && ./scripts/run_tests.sh
#   source .env.test && ./scripts/run_tests.sh tests/test_auth.py -v
#   source .env.test && ./scripts/run_tests.sh -k "test_login"
# ==========================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
TEST_CONTAINER="genset-test-db"

echo "============================================"
echo "  Generator Ledger — Test Runner"
echo "  Safety pre-flight check (SAFETY.md S5)"
echo "============================================"
echo ""

# ---- S5 Check 1: TEST_DATABASE_URL must be set ----
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
    echo "❌ FAILED: TEST_DATABASE_URL is not set."
    echo ""
    echo "   Fix: source .env.test && ./scripts/run_tests.sh"
    echo "   See: SAFETY.md rule S1"
    exit 1
fi
echo "✅ TEST_DATABASE_URL is set"

# ---- S5 Check 2: Must NOT contain production hosts ----
PRODUCTION_HOSTS=("192.168.29.71")
for host in "${PRODUCTION_HOSTS[@]}"; do
    if echo "$TEST_DATABASE_URL" | grep -q "$host"; then
        echo "❌ FATAL: TEST_DATABASE_URL contains production host: $host"
        echo ""
        echo "   This would DESTROY production data."
        echo "   Fix: Set TEST_DATABASE_URL to the test database."
        echo "   See: SAFETY.md rule S1"
        exit 1
    fi
done
echo "✅ No production hosts detected"

# ---- S5 Check 3: Database name must contain 'test' ----
DB_NAME=$(echo "$TEST_DATABASE_URL" | sed 's|.*/||')
if ! echo "$DB_NAME" | grep -qi "test"; then
    echo "❌ FAILED: Database name '$DB_NAME' does not contain 'test'."
    echo ""
    echo "   Fix: Use a database named like 'ledger_db_test'."
    echo "   See: SAFETY.md rule S1"
    exit 1
fi
echo "✅ Database name contains 'test': $DB_NAME"

# ---- S5 Check 4: Test container must be running ----
if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${TEST_CONTAINER}$"; then
    echo "⚠️  Test container '${TEST_CONTAINER}' is not running. Starting..."
    docker compose -f "$PROJECT_DIR/docker-compose.test.yml" up -d
    echo "   Waiting for database to be ready..."
    sleep 3

    # Wait for health check
    for i in $(seq 1 10); do
        if docker exec "$TEST_CONTAINER" pg_isready -U genset_test_user -d ledger_db_test > /dev/null 2>&1; then
            break
        fi
        echo "   Waiting... ($i/10)"
        sleep 2
    done
fi
echo "✅ Test container '${TEST_CONTAINER}' is running"

echo ""
echo "============================================"
echo "  All safety checks passed. Running tests."
echo "============================================"
echo ""

# ---- Activate virtualenv if present ----
cd "$PROJECT_DIR"
if [[ -f ".venv/bin/activate" ]]; then
    source .venv/bin/activate
fi

# ---- Run migrations on test DB ----
python -c "
import os
os.environ['DATABASE_URL'] = os.environ['TEST_DATABASE_URL']
from core.database import DatabaseManager
db = DatabaseManager(os.environ['TEST_DATABASE_URL'])
db.init_schema()
db.close()
print('  Schema initialized on test database.')
" 2>&1

echo ""

# ---- Run pytest ----
python -m pytest "$@"
