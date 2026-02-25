import asyncio
import importlib
import json
import sys

import pytest
from starlette.requests import Request

from core.database import DatabaseManager
from core.repositories import UserRepository


@pytest.fixture
def app_module_and_conn(tmp_path, monkeypatch):
    db_path = tmp_path / "settings_permission_matrix.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("OWNER_USERNAME", "owner")
    monkeypatch.setenv("OWNER_PASSWORD", "Qwerty@345")
    monkeypatch.setenv("LOAD_SEED_DATA", "false")
    monkeypatch.setenv("DEBUG", "true")

    import config as config_module

    importlib.reload(config_module)
    sys.modules.pop("web.app", None)
    sys.modules.pop("web", None)
    web_app_module = importlib.import_module("web.app")

    db = DatabaseManager(str(db_path))
    conn = db.connect()
    db.init_schema()
    try:
        yield web_app_module, conn
    finally:
        db.close()


def test_permission_matrix_rows_include_capabilities_and_endpoints(app_module_and_conn):
    web_app_module, _conn = app_module_and_conn

    rows = web_app_module._build_permission_matrix_rows()
    keys = [row["key"] for row in rows]

    assert keys == [
        "settings_user_admin",
        "monitor_access",
        "vendor_management",
        "generator_management",
        "booking_create_update",
        "booking_delete",
        "billing_access",
        "export_access",
        "read_only_operational_views",
    ]

    assert all(isinstance(row["endpoint_refs"], list) and row["endpoint_refs"] for row in rows)
    vendor_row = next(row for row in rows if row["key"] == "vendor_management")
    assert "PATCH /api/vendors/{vendor_id}" in vendor_row["endpoint_refs"]


def test_effective_permission_active_admin_follows_admin_column(app_module_and_conn):
    web_app_module, _conn = app_module_and_conn

    row = {"admin_allowed": True, "operator_allowed": False}
    assert web_app_module._resolve_effective_permission("admin", True, row) is True

    row = {"admin_allowed": False, "operator_allowed": True}
    assert web_app_module._resolve_effective_permission("admin", True, row) is False


def test_effective_permission_active_operator_follows_operator_column(app_module_and_conn):
    web_app_module, _conn = app_module_and_conn

    row = {"admin_allowed": True, "operator_allowed": True}
    assert web_app_module._resolve_effective_permission("operator", True, row) is True

    row = {"admin_allowed": True, "operator_allowed": False}
    assert web_app_module._resolve_effective_permission("operator", True, row) is False


def test_effective_permission_inactive_user_denied(app_module_and_conn):
    web_app_module, _conn = app_module_and_conn

    rows = web_app_module._build_permission_matrix_rows()
    for row in rows:
        assert web_app_module._resolve_effective_permission("admin", False, row) is False
        assert web_app_module._resolve_effective_permission("operator", False, row) is False


def test_effective_permission_unknown_role_denied(app_module_and_conn):
    web_app_module, _conn = app_module_and_conn

    row = {"admin_allowed": True, "operator_allowed": True}
    assert web_app_module._resolve_effective_permission("viewer", True, row) is False
    assert web_app_module._resolve_effective_permission("", True, row) is False


def test_admin_settings_context_includes_permission_matrix_payload(app_module_and_conn):
    web_app_module, conn = app_module_and_conn
    user_repo = UserRepository(conn)

    admin_id = user_repo.create_user("admin_user", "hash", "admin", is_active=True)
    user_repo.create_user("operator_user", "hash", "operator", is_active=True)
    current_user = user_repo.get_by_id(admin_id)

    request = Request({"type": "http", "method": "GET", "path": "/admin/settings", "headers": []})
    request.state.user = current_user
    request.state.csrf_token = "csrf-token"

    response = asyncio.run(web_app_module.admin_settings_page(request, conn=conn, _=current_user))
    context = response.context

    assert "permission_matrix_rows" in context
    assert "permission_matrix_users" in context
    assert "permission_matrix_default_user_id" in context
    assert context["permission_matrix_default_user_id"] == admin_id

    users = context["permission_matrix_users"]
    assert users and all({"id", "username", "role", "is_active"} <= set(row.keys()) for row in users)

    users_from_json = json.loads(context["permission_matrix_users_json"])
    assert users_from_json == users

