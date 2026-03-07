import asyncio
import importlib
import sys
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException
from starlette.middleware.base import _CachedRequest
from starlette.requests import Request

from core.auth import hash_password
from core.database import DatabaseManager
from core.permissions import (
    CAPABILITY_BILLING_ACCESS,
    CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS,
    CAPABILITY_SETTINGS_USER_ADMIN,
    EDITABLE_CAPABILITY_KEYS,
    role_default_permissions,
)
from core.repositories import UserRepository


TEST_PASSWORD = "Passw0rd!234"


@pytest.fixture
def app_module_and_conn(tmp_path, monkeypatch):
    db_path = tmp_path / "user_permission_overrides.db"
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
    web_app_module.initialize_app()
    try:
        yield web_app_module, conn
    finally:
        db.close()


def _create_user(conn, username: str, role: str) -> int:
    return UserRepository(conn).create_user(
        username,
        hash_password(TEST_PASSWORD),
        role,
        is_active=True,
    )


def _build_request(path: str, method: str = "GET", form_data=None) -> Request:
    body = b""
    headers = []
    if form_data is not None:
        body = urlencode(form_data, doseq=True).encode("utf-8")
        headers.append((b"content-type", b"application/x-www-form-urlencoded"))

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": headers,
    }

    body_sent = False

    async def receive():
        nonlocal body_sent
        if body_sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        body_sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(scope, receive)
    request.state.user = None
    request.state.permissions = {}
    request.state.csrf_token = None
    return request


def _build_cached_request(path: str, method: str = "GET", form_data=None) -> Request:
    body = b""
    headers = []
    if form_data is not None:
        body = urlencode(form_data, doseq=True).encode("utf-8")
        headers.append((b"content-type", b"application/x-www-form-urlencoded"))

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": headers,
    }

    body_sent = False

    async def receive():
        nonlocal body_sent
        if body_sent:
            return {"type": "http.disconnect"}
        body_sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    request = _CachedRequest(scope, receive)
    request.state.user = None
    request.state.permissions = {}
    request.state.csrf_token = None
    return request


def _effective_permissions(web_app_module, conn, user):
    return web_app_module._load_effective_permissions(conn, user)


def _prepare_request(web_app_module, conn, path: str, user, method: str = "GET", form_data=None) -> Request:
    request = _build_request(path, method=method, form_data=form_data)
    request.state.user = user
    request.state.permissions = _effective_permissions(web_app_module, conn, user)
    return request


def _permission_form_data(role: str, **updates: bool) -> dict[str, str]:
    desired_permissions = role_default_permissions(role)
    desired_permissions.update(updates)
    return {
        capability_key: "1"
        for capability_key in EDITABLE_CAPABILITY_KEYS
        if desired_permissions.get(capability_key, False)
    }


def _save_permissions(web_app_module, conn, admin_user, user_id: int, role: str, **updates: bool):
    request = _prepare_request(
        web_app_module,
        conn,
        f"/admin/settings/users/{user_id}/permissions",
        admin_user,
        method="POST",
        form_data=_permission_form_data(role, **updates),
    )
    response = asyncio.run(
        web_app_module.admin_update_user_permissions(
            request,
            user_id,
            conn=conn,
            _=admin_user,
        )
    )
    assert response.status_code == 303
    return response


async def _read_form_value(request: Request, key: str):
    form = await request.form()
    return form.get(key)


def test_admin_can_grant_and_revoke_billing_access_for_operator(app_module_and_conn):
    web_app_module, conn = app_module_and_conn
    repo = UserRepository(conn)
    operator_id = _create_user(conn, "billing_operator", "operator")
    admin_user = repo.get_by_username("owner")
    operator_user = repo.get_by_id(operator_id)

    denied_request = _prepare_request(web_app_module, conn, "/billing", operator_user)
    with pytest.raises(HTTPException) as exc_info:
        web_app_module.require_capability(CAPABILITY_BILLING_ACCESS)(denied_request)
    assert exc_info.value.status_code == 403

    _save_permissions(
        web_app_module,
        conn,
        admin_user,
        operator_id,
        "operator",
        billing_access=True,
    )

    assert repo.list_permission_overrides(operator_id) == {CAPABILITY_BILLING_ACCESS: True}

    allowed_request = _prepare_request(web_app_module, conn, "/billing", repo.get_by_id(operator_id))
    checked_user = web_app_module.require_capability(CAPABILITY_BILLING_ACCESS)(allowed_request)
    response = asyncio.run(web_app_module.billing_page(allowed_request, _=checked_user))
    assert response.status_code == 200

    _save_permissions(web_app_module, conn, admin_user, operator_id, "operator")

    assert repo.list_permission_overrides(operator_id) == {}
    denied_request = _prepare_request(web_app_module, conn, "/billing", repo.get_by_id(operator_id))
    with pytest.raises(HTTPException) as exc_info:
        web_app_module.require_capability(CAPABILITY_BILLING_ACCESS)(denied_request)
    assert exc_info.value.status_code == 403


def test_revoking_read_only_blocks_pages_and_read_api(app_module_and_conn):
    web_app_module, conn = app_module_and_conn
    repo = UserRepository(conn)
    operator_id = _create_user(conn, "readonly_operator", "operator")
    admin_user = repo.get_by_username("owner")
    operator_user = repo.get_by_id(operator_id)

    allowed_request = _prepare_request(web_app_module, conn, "/bookings", operator_user)
    checked_user = web_app_module.require_capability(CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS)(allowed_request)
    response = asyncio.run(web_app_module.bookings_page(allowed_request, conn=conn, _=checked_user))
    assert response.status_code == 200
    assert asyncio.run(web_app_module.api_bookings(conn=conn, _=checked_user)) == []

    _save_permissions(
        web_app_module,
        conn,
        admin_user,
        operator_id,
        "operator",
        read_only_operational_views=False,
    )

    assert repo.list_permission_overrides(operator_id)[CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS] is False

    denied_request = _prepare_request(web_app_module, conn, "/bookings", repo.get_by_id(operator_id))
    with pytest.raises(HTTPException) as exc_info:
        web_app_module.require_capability(CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS)(denied_request)
    assert exc_info.value.status_code == 403


def test_admin_settings_stays_role_based_when_other_access_is_revoked(app_module_and_conn):
    web_app_module, conn = app_module_and_conn
    repo = UserRepository(conn)
    admin_id = _create_user(conn, "restricted_admin", "admin")
    owner_user = repo.get_by_username("owner")

    _save_permissions(
        web_app_module,
        conn,
        owner_user,
        admin_id,
        "admin",
        read_only_operational_views=False,
        billing_access=False,
    )

    restricted_admin = repo.get_by_id(admin_id)
    request = _prepare_request(web_app_module, conn, "/admin/settings", restricted_admin)
    checked_user = web_app_module.require_role("admin")(request)
    response = asyncio.run(web_app_module.admin_settings_page(request, conn=conn, _=checked_user))
    assert response.status_code == 200
    assert request.state.permissions[CAPABILITY_SETTINGS_USER_ADMIN] is True

    with pytest.raises(HTTPException) as billing_exc:
        web_app_module.require_capability(CAPABILITY_BILLING_ACCESS)(request)
    assert billing_exc.value.status_code == 403

    with pytest.raises(HTTPException) as readonly_exc:
        web_app_module.require_capability(CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS)(request)
    assert readonly_exc.value.status_code == 403


def test_role_change_preserves_permission_overrides(app_module_and_conn):
    web_app_module, conn = app_module_and_conn
    repo = UserRepository(conn)
    user_id = _create_user(conn, "promoted_user", "operator")
    owner_user = repo.get_by_username("owner")

    _save_permissions(
        web_app_module,
        conn,
        owner_user,
        user_id,
        "operator",
        read_only_operational_views=False,
    )

    repo.update_role(user_id, "admin")
    promoted_user = repo.get_by_id(user_id)
    permissions = _effective_permissions(web_app_module, conn, promoted_user)

    assert permissions[CAPABILITY_SETTINGS_USER_ADMIN] is True
    assert permissions[CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS] is False

    request = _prepare_request(web_app_module, conn, "/admin/settings", promoted_user)
    assert web_app_module.require_role("admin")(request).role == "admin"

    with pytest.raises(HTTPException) as exc_info:
        web_app_module.require_capability(CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS)(request)
    assert exc_info.value.status_code == 403
    assert repo.list_permission_overrides(user_id)[CAPABILITY_READ_ONLY_OPERATIONAL_VIEWS] is False


def test_validate_csrf_replays_form_body_then_disconnects(app_module_and_conn):
    web_app_module, _conn = app_module_and_conn

    request = _build_cached_request(
        "/admin/settings/users/1/permissions",
        method="POST",
        form_data={
            "csrf_token": "csrf-token",
            CAPABILITY_BILLING_ACCESS: "1",
        },
    )

    assert asyncio.run(web_app_module.validate_csrf(request, "csrf-token")) is True

    assert asyncio.run(_read_form_value(request, CAPABILITY_BILLING_ACCESS)) == "1"

    first_wrapped_message = asyncio.run(request.wrapped_receive())
    assert first_wrapped_message["type"] == "http.request"
    assert first_wrapped_message["body"]

    second_wrapped_message = asyncio.run(request.wrapped_receive())
    assert second_wrapped_message["type"] == "http.disconnect"
