"""End-to-end tests against a running controller + real Docker + the built browser image.

Run:  docker compose --profile build build && docker compose up -d
      DBROWSER_API_TOKEN=... pytest -m integration controller/tests/integration
"""

from __future__ import annotations

import contextlib
import json
import os
import time

import httpx
import pytest

pytestmark = pytest.mark.integration

BASE = os.environ.get("DBROWSER_URL", "http://localhost:8080")
TOKEN = os.environ.get("DBROWSER_API_TOKEN", "")
H = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(scope="module")
def api():
    if not TOKEN:
        pytest.skip("DBROWSER_API_TOKEN not set")
    with httpx.Client(base_url=BASE, headers=H, timeout=60) as c:
        try:
            c.get("/healthz").raise_for_status()
        except httpx.HTTPError as e:
            pytest.skip(f"controller not reachable at {BASE}: {e}")
        yield c
        for s in c.get("/v1/sessions").json():
            c.delete(f"/v1/sessions/{s['id']}")


def wait_gone(api, sid: str, timeout: float = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if api.get(f"/v1/sessions/{sid}").status_code == 404:
            return
        time.sleep(0.5)
    pytest.fail(f"session {sid} still present after {timeout}s")


def test_session_lifecycle_and_privacy_defaults(api):
    from playwright.sync_api import sync_playwright

    s = api.post("/v1/sessions", json={"agent_id": "e2e"}).json()
    assert s["cdp_url"] and s["viewer_url"]
    viewer = httpx.get(s["viewer_url"].split("?")[0], timeout=10)
    assert viewer.status_code == 200 and "noVNC" in viewer.text

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(s["cdp_url"])
        page = browser.contexts[0].pages[0]
        page.wait_for_load_state()
        assert "duckduckgo.com" in page.url

        page.goto("chrome://policy")
        # chrome://policy renders inside shadow DOM; text locators pierce it.
        for name in ("DefaultSearchProviderSearchURL", "WebRtcIPHandling", "BlockThirdPartyCookies"):
            page.get_by_text(name, exact=True).first.wait_for(timeout=15_000)
        browser.close()

    assert api.delete(f"/v1/sessions/{s['id']}").status_code == 204
    wait_gone(api, s["id"])


def test_closing_the_browser_destroys_the_session(api):
    from playwright.sync_api import sync_playwright

    s = api.post("/v1/sessions", json={}).json()
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(s["cdp_url"])
        cdp = browser.new_browser_cdp_session()
        with contextlib.suppress(Exception):  # connection drops as Chromium exits
            cdp.send("Browser.close")
    wait_gone(api, s["id"])


def test_new_session_starts_clean(api):
    from playwright.sync_api import sync_playwright

    def open_page(pw, sid_holder):
        s = api.post("/v1/sessions", json={"agent_id": "clean", "reuse": False}).json()
        sid_holder.append(s["id"])
        browser = pw.chromium.connect_over_cdp(s["cdp_url"])
        page = browser.contexts[0].pages[0]
        page.goto("https://example.com/")
        return browser, page

    ids: list[str] = []
    with sync_playwright() as pw:
        b1, p1 = open_page(pw, ids)
        p1.evaluate("localStorage.setItem('marker', 'leak'); document.cookie = 'marker=leak; max-age=3600'")
        assert p1.evaluate("localStorage.getItem('marker')") == "leak"
        b1.close()

        b2, p2 = open_page(pw, ids)  # reuse=False destroys the first session
        assert p2.evaluate("localStorage.getItem('marker')") is None
        assert "marker" not in p2.evaluate("document.cookie")
        b2.close()
    assert ids[0] != ids[1]
    wait_gone(api, ids[0])


def _rpc(token: str, method: str, params: dict, rid: int) -> dict:
    r = httpx.post(
        f"{BASE}/mcp/",
        json={"jsonrpc": "2.0", "id": rid, "method": method, "params": params},
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        },
        timeout=90,
    )
    r.raise_for_status()
    if r.headers["content-type"].startswith("text/event-stream"):
        data = [ln[5:].strip() for ln in r.text.splitlines() if ln.startswith("data:")]
        return json.loads(data[-1])
    return r.json()


def test_mcp_drives_a_real_browser(api):
    init = {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "e2e", "version": "0"},
    }
    assert "result" in _rpc(TOKEN, "initialize", init, 1)
    nav = _rpc(
        TOKEN, "tools/call", {"name": "browser_navigate", "arguments": {"url": "https://example.com/"}}, 2
    )
    assert not nav["result"].get("isError"), nav
    assert "Example Domain" in json.dumps(nav["result"])
    shot = _rpc(TOKEN, "tools/call", {"name": "browser_screenshot", "arguments": {}}, 3)
    assert shot["result"]["content"][0]["type"] == "image"
    closed = _rpc(TOKEN, "tools/call", {"name": "browser_close", "arguments": {}}, 4)
    assert '"closed": true' in json.dumps(closed["result"]).replace("True", "true")


def test_cloudflare_quick_tunnel(api):
    s = api.post("/v1/sessions", json={"expose": "cloudflare"}).json()
    try:
        deadline = time.time() + 60
        url = None
        while time.time() < deadline and not url:
            url = api.get(f"/v1/sessions/{s['id']}").json().get("public_url")
            time.sleep(2)
        if not url:
            pytest.skip("quick tunnel URL not published within 60s (Cloudflare rate limit / network)")
        assert url.startswith("https://") and url.endswith("/vnc.html")
    finally:
        api.delete(f"/v1/sessions/{s['id']}")


def _tool(name: str, args: dict, rid: int) -> dict:
    res = _rpc(TOKEN, "tools/call", {"name": name, "arguments": args}, rid)
    assert "result" in res and not res["result"].get("isError"), res
    result = res["result"]
    sc = result.get("structuredContent")
    if sc is not None:
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    return json.loads(result["content"][0]["text"])


def test_mcp_tabs_history_wait_and_accessibility(api):
    init = {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "e2e", "version": "0"},
    }
    assert "result" in _rpc(TOKEN, "initialize", init, 1)
    try:
        _tool("browser_navigate", {"url": "https://example.com/"}, 2)
        _tool("browser_navigate", {"url": "https://example.org/"}, 3)
        back = _tool("browser_back", {}, 4)
        assert back["moved"] and "example.com" in back["url"], back

        aria = _tool("browser_accessibility_snapshot", {}, 5)
        # Assert on ARIA structure, not page copy: example.com's markup changes over time.
        assert "- paragraph" in aria["aria"] and "- link " in aria["aria"], aria
        assert "example.com" in _tool("browser_wait_for", {"text": "Learn more"}, 6)["url"]
        attached = {"selector": "a[href]", "state": "attached"}
        assert "example.com" in _tool("browser_wait_for", attached, 61)["url"]

        tabs = _tool("browser_tabs", {"action": "new", "url": "https://example.net/"}, 7)["tabs"]
        assert len(tabs) == 2 and tabs[1]["active"] and "example.net" in tabs[1]["url"]
        # Stateless "current tab": the next call acts on the tab Chromium shows.
        assert "example.net" in _tool("browser_snapshot", {}, 8)["url"]

        tabs = _tool("browser_tabs", {"action": "select", "index": 0}, 9)["tabs"]
        assert tabs[0]["active"] and "example.com" in _tool("browser_snapshot", {}, 10)["url"]
        assert len(_tool("browser_tabs", {"action": "close", "index": 1}, 11)["tabs"]) == 1
    finally:
        _rpc(TOKEN, "tools/call", {"name": "browser_close", "arguments": {}}, 12)


def test_adblock_extension_loaded_and_optional(api):
    def extension_targets(cdp_url: str) -> list[dict]:
        return [
            t
            for t in httpx.get(f"{cdp_url}/json/list", timeout=5).json()
            if "chrome-extension://" in t["url"]
        ]

    on = api.post("/v1/sessions", json={}).json()
    off = api.post("/v1/sessions", json={"adblock": False}).json()
    try:
        assert on["adblock"] is True and off["adblock"] is False
        deadline, found = time.time() + 20, []
        while time.time() < deadline and not found:
            found = extension_targets(on["cdp_url"])
            time.sleep(1)
        assert found, "uBlock Origin Lite service worker never started"
        assert extension_targets(off["cdp_url"]) == []
    finally:
        api.delete(f"/v1/sessions/{on['id']}")
        api.delete(f"/v1/sessions/{off['id']}")


def test_idle_timeout_destroys_unused_session(api):
    s = api.post("/v1/sessions", json={"idle_timeout_seconds": 30}).json()
    assert s["idle_timeout_seconds"] == 30
    time.sleep(20)
    assert api.get(f"/v1/sessions/{s['id']}").status_code == 200  # not before the timeout
    wait_gone(api, s["id"], timeout=60)
