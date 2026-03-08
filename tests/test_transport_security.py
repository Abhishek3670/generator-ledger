import asyncio
import importlib

from fastapi.responses import RedirectResponse, Response
from starlette.requests import Request

web_app_module = importlib.import_module("web.app")


def _build_request(scheme: str = "http", headers=None) -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": scheme,
        "path": "/login",
        "raw_path": b"/login",
        "query_string": b"",
        "headers": headers or [],
    }

    async def receive():
        return {"type": "http.disconnect"}

    return Request(scope, receive)


async def _call_next(_request: Request) -> Response:
    return Response("ok")


def test_session_cookie_secure_flag_follows_request_scheme(monkeypatch):
    monkeypatch.setattr(web_app_module, "SESSION_COOKIE_SECURE", "auto")

    http_response = RedirectResponse("/", status_code=303)
    web_app_module.set_session_cookie(
        http_response,
        "session-http",
        web_app_module.now_ts() + 60,
        _build_request("http"),
    )
    assert "Secure" not in http_response.headers["set-cookie"]

    https_response = RedirectResponse("/", status_code=303)
    web_app_module.set_session_cookie(
        https_response,
        "session-https",
        web_app_module.now_ts() + 60,
        _build_request("https"),
    )
    assert "Secure" in https_response.headers["set-cookie"]


def test_session_cookie_secure_flag_honors_forwarded_proto(monkeypatch):
    monkeypatch.setattr(web_app_module, "SESSION_COOKIE_SECURE", "auto")

    forwarded_https_request = _build_request(
        "http",
        headers=[(b"x-forwarded-proto", b"https")],
    )
    response = RedirectResponse("/", status_code=303)
    web_app_module.set_session_cookie(
        response,
        "session-forwarded",
        web_app_module.now_ts() + 60,
        forwarded_https_request,
    )

    assert "Secure" in response.headers["set-cookie"]


def test_hsts_header_only_added_for_https_in_auto_mode(monkeypatch):
    monkeypatch.setattr(web_app_module, "ENABLE_HSTS", "auto")

    http_response = asyncio.run(
        web_app_module.security_headers_middleware(_build_request("http"), _call_next)
    )
    assert "Strict-Transport-Security" not in http_response.headers

    https_response = asyncio.run(
        web_app_module.security_headers_middleware(_build_request("https"), _call_next)
    )
    assert https_response.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"


def test_transport_security_overrides_allow_forcing_secure_behavior(monkeypatch):
    monkeypatch.setattr(web_app_module, "SESSION_COOKIE_SECURE", "true")
    monkeypatch.setattr(web_app_module, "ENABLE_HSTS", "true")

    response = RedirectResponse("/", status_code=303)
    request = _build_request("http")

    web_app_module.set_session_cookie(
        response,
        "session-forced",
        web_app_module.now_ts() + 60,
        request,
    )
    assert "Secure" in response.headers["set-cookie"]

    secure_headers_response = asyncio.run(
        web_app_module.security_headers_middleware(request, _call_next)
    )
    assert secure_headers_response.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"
