"""MCP over real streamable HTTP (JSON-RPC through the ASGI app), with fake Docker + browser."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from dbrowser.api import create_app

from .conftest import ADMIN, AGENT_A, AGENT_B, FakeOps

EXPECTED_TOOLS = {
    "browser_open",
    "browser_list",
    "browser_close",
    "browser_navigate",
    "browser_snapshot",
    "browser_screenshot",
    "browser_click",
    "browser_type",
    "browser_evaluate",
}


@pytest.fixture
def ops():
    return FakeOps()


@pytest.fixture
def client(settings, runtime, ops):
    with TestClient(create_app(settings, runtime=runtime, ops=ops, probe=lambda url: True)) as c:
        yield c


class Rpc:
    def __init__(self, client: TestClient, token: str) -> None:
        self.client, self.token, self.n = client, token, 0
        self.call(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "0"},
            },
        )

    def call(self, method: str, params: dict | None = None) -> dict:
        self.n += 1
        r = self.client.post(
            "/mcp/",
            json={"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}},
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-06-18",
            },
        )
        assert r.status_code == 200, r.text
        if r.headers["content-type"].startswith("text/event-stream"):
            data = [ln[5:].strip() for ln in r.text.splitlines() if ln.startswith("data:")]
            msg = json.loads(data[-1])
        else:
            msg = r.json()
        assert "error" not in msg, msg
        return msg["result"]

    def tool(self, name: str, args: dict | None = None) -> dict:
        return self.call("tools/call", {"name": name, "arguments": args or {}})


def payload(result: dict):
    if result.get("structuredContent") is not None:
        sc = result["structuredContent"]
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    return json.loads(result["content"][0]["text"])


def test_mcp_requires_token(client):
    r = client.post("/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401


def test_lists_all_tools(client):
    tools = {t["name"] for t in Rpc(client, ADMIN).call("tools/list")["tools"]}
    assert EXPECTED_TOOLS <= tools


def test_navigate_autocreates_and_searches(client, ops, runtime):
    rpc = Rpc(client, ADMIN)
    res = rpc.tool("browser_navigate", {"url": "privacy browsers"})
    assert not res.get("isError"), res
    out = payload(res)
    assert out["url"] == "https://duckduckgo.com/?q=privacy+browsers"
    assert len(runtime.list()) == 1 and runtime.list()[0].labels["dbrowser.agent"] == "default"
    assert ops.calls[0][1].startswith("http://172.30.0.")


def test_screenshot_returns_image(client):
    rpc = Rpc(client, ADMIN)
    res = rpc.tool("browser_screenshot")
    assert res["content"][0]["type"] == "image" and res["content"][0]["mimeType"] == "image/png"


def test_each_agent_token_gets_its_own_browser(client, runtime):
    a, b = Rpc(client, AGENT_A), Rpc(client, AGENT_B)
    sa = payload(a.tool("browser_open"))
    sb = payload(b.tool("browser_open"))
    assert sa["id"] != sb["id"]
    assert sa["agent_id"] == "agent-a" and sb["agent_id"] == "agent-b"

    # Agents only see their own sessions and cannot act on another's.
    assert [s["id"] for s in payload(a.tool("browser_list"))] == [sa["id"]]
    denied = a.tool("browser_navigate", {"url": "https://example.com", "session_id": sb["id"]})
    assert denied.get("isError")
    spoof = a.tool("browser_open", {"agent_id": "agent-b"})
    assert spoof.get("isError")


def test_agent_header_cannot_be_spoofed_by_client(client, runtime):
    r = client.post(
        "/mcp/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "browser_open", "arguments": {}},
        },
        headers={
            "Authorization": f"Bearer {AGENT_A}",
            "X-Dbrowser-Agent": "agent-b",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        },
    )
    assert r.status_code == 200, r.text
    # Middleware replaced the client-supplied header with the token's identity.
    assert [c.labels["dbrowser.agent"] for c in runtime.list()] == ["agent-a"]


def test_close_destroys_session(client, runtime):
    rpc = Rpc(client, AGENT_A)
    s = payload(rpc.tool("browser_open"))
    out = payload(rpc.tool("browser_close"))
    assert out == {"closed": True, "session_id": s["id"]}
    assert runtime.list() == []
    assert payload(rpc.tool("browser_close"))["closed"] is False


def test_fresh_gives_new_identity(client, runtime):
    rpc = Rpc(client, AGENT_A)
    first = payload(rpc.tool("browser_open"))
    second = payload(rpc.tool("browser_open", {"fresh": True}))
    assert first["id"] != second["id"] and len(runtime.list()) == 1
