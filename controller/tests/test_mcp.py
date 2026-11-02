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
    "browser_back",
    "browser_forward",
    "browser_tabs",
    "browser_wait_for",
    "browser_accessibility_snapshot",
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


def test_back_and_forward(client, ops):
    rpc = Rpc(client, AGENT_A)
    assert payload(rpc.tool("browser_back"))["moved"] is True
    assert payload(rpc.tool("browser_forward"))["moved"] is False
    assert [c[2] for c in ops.calls if c[0] == "history"] == ["back", "forward"]


def test_tabs_lifecycle(client, ops):
    rpc = Rpc(client, AGENT_A)
    assert len(payload(rpc.tool("browser_tabs"))["tabs"]) == 1

    tabs = payload(rpc.tool("browser_tabs", {"action": "new", "url": "privacy news"}))["tabs"]
    assert tabs[1]["url"] == "https://duckduckgo.com/?q=privacy+news" and tabs[1]["active"]

    tabs = payload(rpc.tool("browser_tabs", {"action": "select", "index": 0}))["tabs"]
    assert tabs[0]["active"] and not tabs[1]["active"]

    assert len(payload(rpc.tool("browser_tabs", {"action": "close", "index": 1}))["tabs"]) == 1
    # Closing the last tab would end the session; the tool refuses.
    assert rpc.tool("browser_tabs", {"action": "close", "index": 0}).get("isError")
    # select/close need an index; a bad index is an error, not a crash.
    assert rpc.tool("browser_tabs", {"action": "select"}).get("isError")
    assert rpc.tool("browser_tabs", {"action": "select", "index": 9}).get("isError")


def test_wait_for(client, ops):
    rpc = Rpc(client, AGENT_A)
    out = payload(rpc.tool("browser_wait_for", {"text": "Results", "timeout_ms": 999_999}))
    assert out["title"] == "waited"
    assert ops.calls[-1][2] == (None, "Results", "visible", 60_000)  # timeout clamped
    assert rpc.tool("browser_wait_for", {"selector": "#a", "text": "b"}).get("isError")
    assert rpc.tool("browser_wait_for", {"selector": "#a", "state": "bogus"}).get("isError")


def test_accessibility_snapshot(client, ops):
    rpc = Rpc(client, AGENT_A)
    out = payload(rpc.tool("browser_accessibility_snapshot", {"max_chars": 1}))
    assert 'button "Search"' in out["aria"]
    assert ops.calls[-1][2] == ("body", 500)  # max_chars clamped to the floor


def test_open_passes_idle_and_adblock(client, runtime):
    rpc = Rpc(client, AGENT_A)
    s = payload(rpc.tool("browser_open", {"idle_timeout_seconds": 90, "adblock": False}))
    assert s["idle_timeout_seconds"] == 90 and s["adblock"] is False
    env = runtime.specs[f"dbrowser-{s['id']}"].env
    assert env["IDLE_TIMEOUT"] == "90" and env["ADBLOCK"] == "0"


def test_agent_quota_enforced_over_mcp(settings, runtime, ops):
    settings.agent_quotas = '{"agent-a": {"expose": ["none"], "max_ttl_seconds": 120}}'
    with TestClient(create_app(settings, runtime=runtime, ops=ops, probe=lambda url: True)) as c:
        a, b = Rpc(c, AGENT_A), Rpc(c, AGENT_B)
        denied = a.tool("browser_open", {"expose": "cloudflare"})
        assert denied.get("isError") and "expose=cloudflare" in json.dumps(denied)
        s = payload(a.tool("browser_open", {"ttl_seconds": 3600}))
        assert s["expose"] == "none"
        assert payload(b.tool("browser_open", {"expose": "cloudflare"}))["expose"] == "cloudflare"


def test_malformed_quota_fails_at_startup(settings, runtime, ops):
    settings.agent_quotas = "{nope"
    with pytest.raises(ValueError, match="AGENT_QUOTAS"):
        create_app(settings, runtime=runtime, ops=ops, probe=lambda url: True)


def test_tool_schemas_survive_error_wrapper(client):
    tools = {t["name"]: t for t in Rpc(client, ADMIN).call("tools/list")["tools"]}
    props = tools["browser_tabs"]["inputSchema"]["properties"]
    assert {"action", "index", "url", "session_id"} <= set(props) and "ctx" not in props
    assert tools["browser_tabs"]["description"].startswith("List, open, switch or close tabs")


def test_expected_errors_reach_the_agent(client):
    rpc = Rpc(client, AGENT_A)
    spoof = rpc.tool("browser_open", {"agent_id": "agent-b"})
    assert spoof.get("isError") and "does not match the authenticated agent" in json.dumps(spoof)
    last = rpc.tool("browser_tabs", {"action": "close", "index": 0})
    assert "last tab" in json.dumps(last)
