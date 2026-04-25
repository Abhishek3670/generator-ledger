import importlib
import sys

import pytest
from fastapi.testclient import TestClient

from core.auth import create_access_token, decode_access_token
from core.database import DatabaseManager


@pytest.fixture
def auth_client(test_database_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "60")
    monkeypatch.setenv("JWT_REFRESH_EXPIRE_MINUTES", "120")
    monkeypatch.setenv("OWNER_USERNAME", "owner")
    monkeypatch.setenv("OWNER_PASSWORD", "Qwerty@345")
    monkeypatch.setenv("LOAD_SEED_DATA", "false")
    monkeypatch.setenv("DEBUG", "true")

    import config as config_module

    importlib.reload(config_module)
    sys.modules.pop("web.app", None)
    sys.modules.pop("web", None)
    web_app_module = importlib.import_module("web.app")

    db = DatabaseManager(test_database_url)
    conn = db.connect()
    db.init_schema()

    try:
        with TestClient(web_app_module.app) as client:
            yield web_app_module, client, conn
    finally:
        db.close()


def _login(client: TestClient) -> dict:
    response = client.post(
        "/api/login",
        json={"username": "owner", "password": "Qwerty@345"},
    )
    assert response.status_code == 200
    return response.json()


def test_api_login_returns_refresh_token(auth_client):
    _web_app_module, client, _conn = auth_client

    payload = _login(client)

    assert payload["access_token"]
    assert payload["refresh_token"]
    assert payload["expires_in"] > 0
    assert payload["refresh_expires_in"] > payload["expires_in"]
    assert payload["token_type"] == "bearer"


def test_refresh_endpoint_rotates_refresh_token(auth_client):
    _web_app_module, client, _conn = auth_client

    login_payload = _login(client)
    response = client.post(
        "/auth/refresh",
        json={"refresh_token": login_payload["refresh_token"]},
    )

    assert response.status_code == 200
    refreshed = response.json()
    assert refreshed["access_token"] != login_payload["access_token"]
    assert refreshed["refresh_token"] != login_payload["refresh_token"]
    assert decode_access_token(
        refreshed["access_token"],
        "test-jwt-secret",
        "HS256",
    )["type"] == "access"


def test_refresh_token_cannot_access_protected_routes(auth_client):
    _web_app_module, client, _conn = auth_client

    login_payload = _login(client)
    response = client.get(
        "/api/generators",
        headers={"Authorization": f"Bearer {login_payload['refresh_token']}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid token"


def test_expired_access_token_is_rejected_before_db_connection(auth_client, monkeypatch):
    web_app_module, client, _conn = auth_client

    login_payload = _login(client)
    user = login_payload["user"]
    expired_token, _exp_ts, _jti = create_access_token(
        user_id=user["id"],
        username=user["username"],
        role=user["role"],
        secret="test-jwt-secret",
        algorithm="HS256",
        expires_minutes=-1,
    )

    def fail_db_connection():
        raise AssertionError("DB connection should not be opened for an expired bearer token")

    monkeypatch.setattr(web_app_module, "_new_db_connection", fail_db_connection)

    response = client.get(
        "/api/generators",
        headers={"Authorization": f"Bearer {expired_token}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Token expired"
