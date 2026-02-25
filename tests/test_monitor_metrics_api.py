import asyncio
import importlib
import sys
from types import SimpleNamespace

import pytest

from core.database import DatabaseManager


@pytest.fixture
def app_module_and_conn(tmp_path, monkeypatch):
    db_path = tmp_path / "monitor_metrics_api.db"
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


def test_monitor_live_success_payload(app_module_and_conn, monkeypatch):
    web_app_module, conn = app_module_and_conn

    fake_psutil = SimpleNamespace(
        cpu_percent=lambda interval=None: 34.2,
        virtual_memory=lambda: SimpleNamespace(
            percent=61.5,
            used=7921.4 * 1024 * 1024,
            total=128808.2 * 1024 * 1024,
        ),
        sensors_temperatures=lambda fahrenheit=False: {
            "coretemp": [SimpleNamespace(current=58.0)]
        },
    )
    monkeypatch.setattr(web_app_module, "psutil", fake_psutil)

    payload = asyncio.run(web_app_module.api_monitor_live(conn=conn))

    assert payload["timestamp"].endswith("Z")
    assert payload["cpu"] == {
        "percent": 34.2,
        "status": "normal",
    }
    assert payload["memory"] == {
        "percent": 61.5,
        "used_mb": 7921.4,
        "total_mb": 128808.2,
        "status": "normal",
    }
    assert payload["temperature"] == {
        "available": True,
        "celsius": 58.0,
        "sensor": "coretemp",
        "status": "normal",
        "note": "",
    }


def test_monitor_live_temperature_unavailable_fallback(app_module_and_conn, monkeypatch):
    web_app_module, conn = app_module_and_conn

    fake_psutil = SimpleNamespace(
        cpu_percent=lambda interval=None: 18.3,
        virtual_memory=lambda: SimpleNamespace(
            percent=42.0,
            used=5400.0 * 1024 * 1024,
            total=128808.2 * 1024 * 1024,
        ),
        sensors_temperatures=lambda fahrenheit=False: {},
    )
    monkeypatch.setattr(web_app_module, "psutil", fake_psutil)

    payload = asyncio.run(web_app_module.api_monitor_live(conn=conn))
    temp = payload["temperature"]

    assert temp["available"] is False
    assert temp["celsius"] is None
    assert temp["sensor"] is None
    assert temp["status"] == "unknown"
    assert temp["note"] == "Temperature sensor not available on this host"


def test_monitor_threshold_classification_mapping(app_module_and_conn):
    web_app_module, _conn = app_module_and_conn

    classify = web_app_module._classify_resource_usage

    assert classify(79.9, 80.0, 90.0) == "normal"
    assert classify(80.0, 80.0, 90.0) == "high"
    assert classify(89.9, 80.0, 90.0) == "high"
    assert classify(90.0, 80.0, 90.0) == "critical"

    assert classify(74.9, 75.0, 85.0) == "normal"
    assert classify(75.0, 75.0, 85.0) == "high"
    assert classify(84.9, 75.0, 85.0) == "high"
    assert classify(85.0, 75.0, 85.0) == "critical"
