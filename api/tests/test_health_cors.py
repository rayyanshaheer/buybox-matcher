"""Integration tests for the /health endpoint and CORS behavior (Req 10.7, 10.9, 10.10).

The FastAPI app (api/main.py) resolves the single CORS-allowed origin at import
time from ``ALLOWED_ORIGIN`` (falling back to the dev default). Because the
middleware is wired during app construction, these tests set ``ALLOWED_ORIGIN``
*before* importing the app and reload the module so the configured origin takes
effect. Assertions are made against the *resolved* allowed origin
(``main._resolve_allowed_origin()``) rather than a hard-coded value, so the
suite stays robust whether the value comes from the env or the dev fallback.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

#: An explicit, configured origin used to exercise the matching path (Req 10.9).
CONFIGURED_ORIGIN = "https://app.example.com"

#: An origin guaranteed not to match the configured one (Req 10.10).
NON_MATCHING_ORIGIN = "https://evil.example.com"


@pytest.fixture()
def app_module(monkeypatch):
    """Reload api.main with a known ``ALLOWED_ORIGIN`` so CORS is config-driven.

    Returns the freshly reloaded module so tests can read the resolved allowed
    origin directly.
    """
    monkeypatch.setenv("ALLOWED_ORIGIN", CONFIGURED_ORIGIN)
    import api.main as main

    importlib.reload(main)
    return main


@pytest.fixture()
def client(app_module):
    return TestClient(app_module.app)


# --------------------------------------------------------------------------- #
# GET /health (Req 10.7)
# --------------------------------------------------------------------------- #


def test_health_returns_200_status_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --------------------------------------------------------------------------- #
# CORS: matching Origin includes the header (Req 10.9)
# --------------------------------------------------------------------------- #


def test_cors_header_present_for_matching_origin(client, app_module):
    allowed = app_module._resolve_allowed_origin()
    assert allowed == CONFIGURED_ORIGIN  # the configured value drove the app

    response = client.get("/health", headers={"Origin": allowed})

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == allowed


def test_cors_preflight_allows_matching_origin(client, app_module):
    allowed = app_module._resolve_allowed_origin()

    response = client.options(
        "/health",
        headers={
            "Origin": allowed,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.headers.get("access-control-allow-origin") == allowed


# --------------------------------------------------------------------------- #
# CORS: non-matching Origin omits the header (Req 10.10)
# --------------------------------------------------------------------------- #


def test_cors_header_omitted_for_non_matching_origin(client, app_module):
    allowed = app_module._resolve_allowed_origin()
    assert NON_MATCHING_ORIGIN != allowed  # sanity: truly non-matching

    response = client.get("/health", headers={"Origin": NON_MATCHING_ORIGIN})

    # The request itself still succeeds; only the CORS header must be absent.
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_cors_preflight_omits_header_for_non_matching_origin(client):
    response = client.options(
        "/health",
        headers={
            "Origin": NON_MATCHING_ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert "access-control-allow-origin" not in response.headers
