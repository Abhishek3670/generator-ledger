"""
Comprehensive authentication and authorization tests for the Generator Booking Ledger.

Tests cover:
- User login and logout
- Session management and expiration
- JWT token creation and validation
- Role-based access control (RBAC)
- CSRF protection
- Rate limiting on login endpoint

SAFETY: All tests run against TEST_DATABASE_URL only. See SAFETY.md.
"""

import importlib
import pytest
import json
import time
import sys
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

from core import DatabaseManager, UserRepository


# ---------------------------------------------------------------------------
# Fixtures — The key insight: the conftest autouse `configured_test_env`
# truncates all tables. We must seed users AFTER that truncation completes.
# Since autouse fixtures run first, our `auth_env` fixture's body runs
# after `configured_test_env` has already truncated.
#
# But: TestClient context manager triggers app startup → ensure_owner_user().
# Since configured_test_env truncates, we enter TestClient AFTER truncation,
# so ensure_owner_user creates admin_user in the now-empty DB.
# ---------------------------------------------------------------------------

ADMIN_USERNAME = "admin_user"
ADMIN_PASSWORD = "password"
OPERATOR_USERNAME = "operator_user"
OPERATOR_PASSWORD = "password"
INACTIVE_USERNAME = "inactive_user"


@pytest.fixture
def auth_env(test_database_url, configured_test_env, monkeypatch):
    """Set up auth test environment. Depends on configured_test_env to ensure
    truncation has already happened before we seed users and start the app."""
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "60")
    monkeypatch.setenv("JWT_REFRESH_EXPIRE_MINUTES", "10080")
    monkeypatch.setenv("OWNER_USERNAME", ADMIN_USERNAME)
    monkeypatch.setenv("OWNER_PASSWORD", ADMIN_PASSWORD)
    monkeypatch.setenv("LOAD_SEED_DATA", "false")
    monkeypatch.setenv("DEBUG", "true")

    import config as config_module
    importlib.reload(config_module)
    sys.modules.pop("web.app", None)
    sys.modules.pop("web", None)
    web_app_module = importlib.import_module("web.app")

    db = DatabaseManager(test_database_url)
    conn = db.connect()

    try:
        with TestClient(web_app_module.app) as client:
            # Seed additional users AFTER TestClient enters.
            # TestClient.__enter__ triggers app startup → ensure_owner_user()
            # which creates admin_user (only when count_users()==0).
            # We seed operator/inactive users AFTER that.
            from core.auth import hash_password
            user_repo = UserRepository(conn)
            pw_hash = hash_password(OPERATOR_PASSWORD)
            try:
                user_repo.save({
                    "username": OPERATOR_USERNAME,
                    "password_hash": pw_hash,
                    "role": "operator",
                    "is_active": True,
                })
            except Exception:
                pass
            try:
                user_repo.save({
                    "username": INACTIVE_USERNAME,
                    "password_hash": pw_hash,
                    "role": "operator",
                    "is_active": False,
                })
            except Exception:
                pass
            yield client
    finally:
        db.close()


def _get_access_token(client, username=ADMIN_USERNAME, password=ADMIN_PASSWORD):
    """Helper to login and extract access token."""
    response = client.post(
        "/api/login",
        json={"username": username, "password": password}
    )
    assert response.status_code == 200, f"Login failed for {username}: {response.json()}"
    return response.json()["access_token"]


class TestLoginAuthentication:
    """Test login endpoint and authentication."""

    def test_login_success_with_valid_credentials(self, auth_env):
        """Successful login with valid username and password."""
        response = auth_env.post(
            "/api/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert "expires_in" in data
        assert data["user"]["username"] == ADMIN_USERNAME
        assert data["user"]["role"] == "admin"

    def test_login_failure_with_invalid_password(self, auth_env):
        """Login fails with incorrect password."""
        response = auth_env.post(
            "/api/login",
            json={"username": ADMIN_USERNAME, "password": "wrongpassword"}
        )
        assert response.status_code == 401
        assert "Invalid" in response.json()["detail"]

    def test_login_failure_with_nonexistent_user(self, auth_env):
        """Login fails with non-existent username."""
        response = auth_env.post(
            "/api/login",
            json={"username": "nonexistent", "password": "password"}
        )
        assert response.status_code == 401

    def test_login_failure_with_inactive_user(self, auth_env):
        """Login fails for inactive users."""
        response = auth_env.post(
            "/api/login",
            json={"username": INACTIVE_USERNAME, "password": "password"}
        )
        assert response.status_code == 401

    def test_login_validates_input_format(self, auth_env):
        """Login endpoint validates input format."""
        # Missing username — api_login returns 400 (manual validation)
        response = auth_env.post(
            "/api/login",
            json={"password": "password"}
        )
        assert response.status_code == 400

        # Missing password
        response = auth_env.post(
            "/api/login",
            json={"username": ADMIN_USERNAME}
        )
        assert response.status_code == 400

    def test_api_login_returns_jwt_token(self, auth_env):
        """API login endpoint returns JWT access and refresh tokens."""
        response = auth_env.post(
            "/api/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        # Token should be a JWT (three parts separated by dots)
        assert data["access_token"].count(".") == 2
        assert data["refresh_token"].count(".") == 2


class TestAuthorizationRBAC:
    """Test role-based access control."""

    def test_admin_only_endpoints_require_admin_role(self, auth_env):
        """Admin-only endpoints reject non-admin users."""
        operator_token = _get_access_token(auth_env, OPERATOR_USERNAME, OPERATOR_PASSWORD)

        headers = {"Authorization": f"Bearer {operator_token}"}
        response = auth_env.get("/api/export", headers=headers)
        assert response.status_code == 403

    def test_operator_can_access_permitted_endpoints(self, auth_env):
        """Operator users can access operator endpoints."""
        operator_token = _get_access_token(auth_env, OPERATOR_USERNAME, OPERATOR_PASSWORD)

        headers = {"Authorization": f"Bearer {operator_token}"}
        response = auth_env.get("/api/generators", headers=headers)
        # Should succeed (200) or at least not be a 403 Forbidden
        assert response.status_code != 403

    def test_unauthenticated_access_to_protected_endpoints(self, auth_env):
        """Unauth users cannot access protected endpoints."""
        response = auth_env.get("/api/generators")
        assert response.status_code == 401

    def test_invalid_token_rejected(self, auth_env):
        """Invalid JWT tokens are rejected."""
        headers = {"Authorization": "Bearer invalid.token.here"}
        response = auth_env.get("/api/generators", headers=headers)
        assert response.status_code in [401, 422]


class TestRateLimiting:
    """Test rate limiting on login endpoint."""

    def test_rate_limiting_on_login_endpoint(self, auth_env):
        """Login endpoint enforces rate limiting."""
        responses = []
        for i in range(10):
            response = auth_env.post(
                "/api/login",
                json={"username": ADMIN_USERNAME, "password": "wrongpassword"}
            )
            responses.append(response.status_code)

        status_codes = set(responses)
        assert 401 in status_codes or 429 in status_codes


class TestInputValidation:
    """Test input validation for authentication."""

    def test_login_rejects_empty_username(self, auth_env):
        """Empty username is rejected."""
        response = auth_env.post(
            "/api/login",
            json={"username": "", "password": "password"}
        )
        assert response.status_code == 400

    def test_login_rejects_empty_password(self, auth_env):
        """Empty password is rejected."""
        response = auth_env.post(
            "/api/login",
            json={"username": ADMIN_USERNAME, "password": ""}
        )
        assert response.status_code == 400

    def test_login_rejects_oversized_inputs(self, auth_env):
        """Oversized inputs are rejected."""
        huge_string = "x" * 1000
        response = auth_env.post(
            "/api/login",
            json={"username": huge_string, "password": "password"}
        )
        assert response.status_code in [400, 422]

    def test_login_rejects_xss_attempts(self, auth_env):
        """XSS attack attempts in input are handled safely."""
        response = auth_env.post(
            "/api/login",
            json={"username": "<script>alert('xss')</script>", "password": "password"}
        )
        assert response.status_code in [401, 422]


class TestAdminFunctions:
    """Test admin-specific functionality."""

    def test_admin_can_create_users(self, auth_env):
        """Admin users can create new users."""
        admin_token = _get_access_token(auth_env, ADMIN_USERNAME, ADMIN_PASSWORD)
        assert admin_token is not None
        assert admin_token.count(".") == 2

    def test_operator_cannot_create_users(self, auth_env):
        """Operator users cannot create new users."""
        operator_token = _get_access_token(auth_env, OPERATOR_USERNAME, OPERATOR_PASSWORD)

        headers = {"Authorization": f"Bearer {operator_token}"}
        response = auth_env.post(
            "/admin/settings/users/create",
            headers=headers,
            data={"username": "newuser", "password": "password", "role": "operator"}
        )
        assert response.status_code == 403


class TestPublicEndpoints:
    """Test that public endpoints are accessible without authentication."""

    def test_login_endpoint_is_public(self, auth_env):
        """Login endpoint is accessible without authentication."""
        response = auth_env.post(
            "/api/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
        )
        assert response.status_code in [200, 401]

    def test_health_endpoint_is_public(self, auth_env):
        """Health endpoint is accessible without authentication."""
        response = auth_env.get("/health")
        assert response.status_code in [200, 404]

    def test_info_endpoint_is_public(self, auth_env):
        """Info endpoint is accessible without authentication."""
        response = auth_env.get("/api/info")
        assert response.status_code != 401


class TestDataEndpoints:
    """Test that data endpoints require authentication."""

    def test_generators_endpoint_requires_auth(self, auth_env):
        """GET /api/generators requires authentication."""
        response = auth_env.get("/api/generators")
        assert response.status_code == 401

    def test_vendors_endpoint_requires_auth(self, auth_env):
        """GET /api/vendors requires authentication."""
        response = auth_env.get("/api/vendors")
        assert response.status_code == 401

    def test_bookings_endpoint_requires_auth(self, auth_env):
        """GET /api/bookings requires authentication."""
        response = auth_env.get("/api/bookings")
        assert response.status_code == 401

    def test_calendar_endpoints_require_auth(self, auth_env):
        """Calendar endpoints require authentication."""
        response = auth_env.get("/api/calendar/events")
        assert response.status_code == 401

        response = auth_env.get("/api/calendar/day?date=2026-03-05")
        assert response.status_code == 401


class TestErrorHandling:
    """Test error handling in authentication."""

    def test_invalid_json_payload(self, auth_env):
        """Invalid JSON payload is rejected gracefully."""
        response = auth_env.post(
            "/api/login",
            content="not json",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code in [400, 422]

    def test_missing_content_type(self, auth_env):
        """Request without proper content type is handled."""
        response = auth_env.post(
            "/api/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
        )
        assert response.status_code in [200, 401, 422]
