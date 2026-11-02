from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dbrowser.api import create_app

from .conftest import ADMIN, AGENT_A, FakeOps

H = {"Authorization": f"Bearer {ADMIN}"}


@pytest.fixture
def client(settings, runtime):
    app = create_app(settings, runtime=runtime, ops=FakeOps(), probe=lambda url: True)
    with TestClient(app) as c:
        yield c


def test_public_endpoints(client):
    assert client.get("/healthz").json()["status"] == "ok"
    r = client.get("/")
    assert r.status_code == 200 and "Disposable Browser" in r.text


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": ADMIN}])
def test_requires_token(client, headers):
    assert client.get("/v1/sessions", headers=headers).status_code == 401


def test_agent_token_cannot_use_rest(client):
    r = client.get("/v1/sessions", headers={"Authorization": f"Bearer {AGENT_A}"})
    assert r.status_code == 403


def test_session_crud(client):
    r = client.post("/v1/sessions", json={"agent_id": "grok-1"}, headers=H)
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert [s["id"] for s in client.get("/v1/sessions", headers=H).json()] == [sid]
    assert client.get(f"/v1/sessions/{sid}", headers=H).json()["agent_id"] == "grok-1"
    assert client.delete(f"/v1/sessions/{sid}", headers=H).status_code == 204
    assert client.get(f"/v1/sessions/{sid}", headers=H).status_code == 404
    assert client.delete(f"/v1/sessions/{sid}", headers=H).status_code == 404


def test_errors_map_to_status(client):
    assert client.post("/v1/sessions", json={"network": "wireguard"}, headers=H).status_code == 422
    assert (
        client.post(
            "/v1/sessions", json={"network": "wireguard", "wireguard_profile": "nope"}, headers=H
        ).status_code
        == 400
    )
    for _ in range(3):
        assert client.post("/v1/sessions", json={}, headers=H).status_code == 201
    assert client.post("/v1/sessions", json={}, headers=H).status_code == 429
