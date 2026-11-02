"""Drive a disposable browser from your own agent code with Playwright (no MCP).

pip install httpx playwright
DBROWSER_API_TOKEN=... python examples/playwright_agent.py "privacy focused browsers"
"""

import os
import sys

import httpx
from playwright.sync_api import sync_playwright

BASE = os.environ.get("DBROWSER_URL", "http://localhost:8080")
HEADERS = {"Authorization": f"Bearer {os.environ['DBROWSER_API_TOKEN']}"}
query = " ".join(sys.argv[1:]) or "disposable browser"

with httpx.Client(base_url=BASE, headers=HEADERS, timeout=60) as api:
    session = api.post("/v1/sessions", json={"agent_id": "example-agent", "ttl_seconds": 600}).json()
    print("watch live:", session["viewer_url"])
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(session["cdp_url"])
            page = browser.contexts[0].pages[0]
            page.goto(f"https://duckduckgo.com/?q={query}")
            page.wait_for_selector("[data-testid='result-title-a']")
            for link in page.locator("[data-testid='result-title-a']").all()[:5]:
                print("-", link.inner_text())
            browser.close()  # disconnects; the session keeps running until deleted
    finally:
        api.delete(f"/v1/sessions/{session['id']}")  # everything is gone now
