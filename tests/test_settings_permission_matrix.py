import asyncio
import importlib
import json
import re
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
    assert all(isinstance(row["editable"], bool) for row in rows)
    settings_row = next(row for row in rows if row["key"] == "settings_user_admin")
    assert settings_row["editable"] is False
    vendor_row = next(row for row in rows if row["key"] == "vendor_management")
    assert "PATCH /api/vendors/{vendor_id}" in vendor_row["endpoint_refs"]
    assert "PATCH /api/rental-vendors/{rental_vendor_id}" in vendor_row["endpoint_refs"]
    generator_row = next(row for row in rows if row["key"] == "generator_management")
    assert "PATCH /api/generators/{generator_id}" in generator_row["endpoint_refs"]


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


def test_effective_permission_uses_override_payload_for_capability_rows(app_module_and_conn):
    web_app_module, _conn = app_module_and_conn

    row = {
        "key": "billing_access",
        "admin_allowed": True,
        "operator_allowed": False,
    }

    assert web_app_module._resolve_effective_permission(
        "operator",
        True,
        row,
        overrides={"billing_access": True},
    ) is True
    assert web_app_module._resolve_effective_permission(
        "admin",
        True,
        row,
        overrides={"billing_access": False},
    ) is False


def test_admin_settings_context_includes_permission_matrix_payload(app_module_and_conn):
    web_app_module, conn = app_module_and_conn
    user_repo = UserRepository(conn)

    admin_id = user_repo.create_user("admin_user", "hash", "admin", is_active=True)
    operator_id = user_repo.create_user("operator_user", "hash", "operator", is_active=True)
    user_repo.set_permission_override(operator_id, "billing_access", True)
    current_user = user_repo.get_by_id(admin_id)

    request = Request({"type": "http", "method": "GET", "path": "/admin/settings", "headers": []})
    request.state.user = current_user
    request.state.csrf_token = "csrf-token"

    response = asyncio.run(web_app_module.admin_settings_page(request, conn=conn, _=current_user))
    context = response.context

    assert "permission_matrix_rows" in context
    assert "permission_matrix_users" in context
    assert "permission_matrix_default_user_id" in context
    assert "permission_matrix_default_user" in context
    assert context["permission_matrix_default_user_id"] == admin_id
    assert context["permission_matrix_default_user"]["id"] == admin_id

    users = context["permission_matrix_users"]
    assert users and all(
        {"id", "username", "role", "is_active", "configured_permissions", "effective_permissions"} <= set(row.keys())
        for row in users
    )
    operator_row = next(row for row in users if row["id"] == operator_id)
    assert operator_row["configured_permissions"]["billing_access"] is True
    assert operator_row["effective_permissions"]["billing_access"] is True

    users_from_json = json.loads(context["permission_matrix_users_json"])
    assert users_from_json == users


def test_admin_settings_renders_merged_permission_matrix_form(app_module_and_conn):
    web_app_module, conn = app_module_and_conn
    user_repo = UserRepository(conn)

    admin_id = user_repo.create_user("admin_user", "hash", "admin", is_active=True)
    user_repo.create_user("operator_user", "hash", "operator", is_active=False)
    current_user = user_repo.get_by_id(admin_id)

    request = Request({"type": "http", "method": "GET", "path": "/admin/settings", "headers": []})
    request.state.user = current_user
    request.state.csrf_token = "csrf-token"

    response = asyncio.run(web_app_module.admin_settings_page(request, conn=conn, _=current_user))
    html = response.body.decode()

    assert 'id="permissionMatrixForm"' in html
    assert 'action="/admin/settings/users/0/permissions"' in html
    assert 'id="permissionEditorForm"' not in html
    assert '<option value="" selected>Select a user</option>' in html
    assert f'<option value="{admin_id}">' in html
    assert 'data-selected-user-column-header' in html
    assert 'data-permission-editor-checkbox' in html
    assert 'data-selected-user-toggle' in html
    assert 'data-selected-user-locked' in html
    assert 'name="billing_access"' in html
    assert 'data-initial-checked=' in html
    assert 'bg-amber-200' in html
    assert 'bg-slate-100' in html
    assert "Configured" not in html
    assert "Effective" not in html
    assert "Fixed to Admin" not in html
    assert 'data-effective-badge' not in html
    assert 'data-inactive-effective-note' not in html
    assert 'data-selected-user-cell' in html
    assert 'border border-slate-300 p-0 text-center align-middle' in html
    assert 'data-selected-user-toggle' in html
    assert 'min-h-[4.75rem] w-full items-center justify-center border text-sm font-bold' in html
    assert 'Select a user to view permissions.' in html
    assert re.search(r'<button[^>]*data-selected-user-toggle[^>]*\sdisabled(?:\s|>)', html)


def test_admin_settings_inactive_default_user_renders_denied_helper_text(app_module_and_conn):
    web_app_module, conn = app_module_and_conn
    user_repo = UserRepository(conn)

    inactive_admin_id = user_repo.create_user("inactive_admin", "hash", "admin", is_active=False)
    current_user = user_repo.get_by_id(inactive_admin_id)

    request = Request({"type": "http", "method": "GET", "path": "/admin/settings", "headers": []})
    request.state.user = current_user
    request.state.csrf_token = "csrf-token"

    response = asyncio.run(web_app_module.admin_settings_page(request, conn=conn, _=current_user))
    html = response.body.decode()

    assert response.context["permission_matrix_default_user"]["id"] == inactive_admin_id
    assert "Select a user to view permissions." in html
    assert re.search(r'<button[^>]*data-selected-user-toggle[^>]*\sdisabled(?:\s|>)', html)
