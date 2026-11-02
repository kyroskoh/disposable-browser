from __future__ import annotations

import itertools
from typing import Any

import pytest

from dbrowser.browser_ops import BrowserOpsError
from dbrowser.config import Settings
from dbrowser.runtime import CDP_PORT, VIEWER_PORT, ContainerInfo, ContainerSpec
from dbrowser.sessions import SessionManager

ADMIN = "admin-token-for-tests-0123456789"
AGENT_A = "agent-a-token-0123456789"
AGENT_B = "agent-b-token-0123456789"


class FakeRuntime:
    """In-memory stand-in for Docker. `exit_on_start` simulates Chromium dying at boot."""

    def __init__(self) -> None:
        self.containers: dict[str, ContainerInfo] = {}
        self.specs: dict[str, ContainerSpec] = {}
        self.logs_by_name: dict[str, str] = {}
        self.removed: list[str] = []
        self.exit_on_start = False
        self._ports = itertools.count(40000)
        self._ips = itertools.count(2)

    def run(self, spec: ContainerSpec) -> ContainerInfo:
        info = ContainerInfo(
            id=f"cid-{spec.name}",
            name=spec.name,
            labels=dict(spec.labels),
            status="running",
            ip=f"172.30.0.{next(self._ips)}",
            host_ports={VIEWER_PORT: next(self._ports), CDP_PORT: next(self._ports)},
        )
        self.specs[spec.name] = spec
        if not self.exit_on_start:
            self.containers[spec.name] = info
        return info

    def list(self) -> list[ContainerInfo]:
        return list(self.containers.values())

    def get(self, name: str) -> ContainerInfo | None:
        return self.containers.get(name)

    def remove(self, name: str) -> None:
        self.containers.pop(name, None)
        self.removed.append(name)

    def logs(self, name: str) -> str:
        return self.logs_by_name.get(name, "")


class FakeOps:
    """Records calls; keeps a tiny tab model so tab tools can be exercised."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.tab_urls = ["https://duckduckgo.com/"]
        self.active = 0

    def _tabs(self):
        return [
            {"index": i, "url": u, "title": u, "active": i == self.active}
            for i, u in enumerate(self.tab_urls)
        ]

    async def navigate(self, cdp_url, url):
        self.calls.append(("navigate", cdp_url, url))
        return {"url": url, "title": "DuckDuckGo"}

    async def snapshot(self, cdp_url, max_chars):
        self.calls.append(("snapshot", cdp_url, max_chars))
        return {
            "url": "https://duckduckgo.com/",
            "title": "DuckDuckGo",
            "text": "hello",
            "truncated": False,
            "links": [],
        }

    async def screenshot(self, cdp_url, full_page):
        self.calls.append(("screenshot", cdp_url, full_page))
        return b"\x89PNG\r\n\x1a\nfake"

    async def click(self, cdp_url, selector):
        self.calls.append(("click", cdp_url, selector))
        return {"url": "https://duckduckgo.com/", "title": "clicked"}

    async def type_text(self, cdp_url, selector, text, submit):
        self.calls.append(("type", cdp_url, (selector, text, submit)))
        return {"url": "https://duckduckgo.com/", "title": "typed"}

    async def evaluate(self, cdp_url, expression):
        self.calls.append(("evaluate", cdp_url, expression))
        return 42

    async def aria_snapshot(self, cdp_url, selector, max_chars):
        self.calls.append(("aria", cdp_url, (selector, max_chars)))
        return {
            "url": "https://duckduckgo.com/",
            "title": "DuckDuckGo",
            "aria": '- button "Search"',
            "truncated": False,
        }

    async def history(self, cdp_url, direction):
        self.calls.append(("history", cdp_url, direction))
        return {"url": "https://duckduckgo.com/", "title": direction, "moved": direction == "back"}

    async def wait_for(self, cdp_url, selector, text, state, timeout_ms):
        self.calls.append(("wait_for", cdp_url, (selector, text, state, timeout_ms)))
        return {"url": "https://duckduckgo.com/", "title": "waited"}

    async def tabs(self, cdp_url):
        self.calls.append(("tabs", cdp_url, None))
        return self._tabs()

    async def new_tab(self, cdp_url, url):
        self.calls.append(("new_tab", cdp_url, url))
        self.tab_urls.append(url)
        self.active = len(self.tab_urls) - 1
        return self._tabs()

    async def select_tab(self, cdp_url, index):
        self.calls.append(("select_tab", cdp_url, index))
        if not 0 <= index < len(self.tab_urls):
            raise BrowserOpsError(f"no tab {index}")
        self.active = index
        return self._tabs()

    async def close_tab(self, cdp_url, index):
        self.calls.append(("close_tab", cdp_url, index))
        if len(self.tab_urls) == 1:
            raise BrowserOpsError("refusing to close the last tab")
        self.tab_urls.pop(index)
        self.active = min(self.active, len(self.tab_urls) - 1)
        return self._tabs()


class Clock:
    def __init__(self, t: float = 1_800_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        api_token=ADMIN,
        agent_tokens=f"agent-a:{AGENT_A},agent-b:{AGENT_B}",
        wireguard_profiles_dir=tmp_path,
        max_sessions=3,
        ready_timeout_seconds=2,
    )


@pytest.fixture
def runtime() -> FakeRuntime:
    return FakeRuntime()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def manager(runtime, settings, clock) -> SessionManager:
    def sleep(s: float) -> None:
        clock.advance(s)

    return SessionManager(runtime, settings, clock=clock, probe=lambda url: True, sleep=sleep)
