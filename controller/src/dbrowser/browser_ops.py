"""Drive a session's Chromium over CDP with Playwright. Each call connects, acts, disconnects.

The controller keeps no per-session state, so "the current tab" is the one Chromium activated
most recently: DevTools' /json/list returns page targets newest-activation first. `select_tab`
brings a tab to the front (an activation), and so does a human clicking a tab in the noVNC
viewer, so later calls follow either. (document.visibilityState can't be used: Playwright
emulates focus on every page it attaches to, so all tabs report "visible".)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from typing import Any, Literal, Protocol

import httpx
from playwright.async_api import TimeoutError as PlaywrightTimeout

log = logging.getLogger("dbrowser.browser_ops")

WaitState = Literal["visible", "hidden", "attached", "detached"]
HISTORY_SETTLE_MS = 10_000
ACTIVATE_SETTLE_S = 5.0


class BrowserOpsError(Exception):
    """A browser action was refused or is not possible (bad tab index, last tab, ...)."""


class BrowserOps(Protocol):
    async def navigate(self, cdp_url: str, url: str) -> dict[str, Any]: ...
    async def snapshot(self, cdp_url: str, max_chars: int) -> dict[str, Any]: ...
    async def aria_snapshot(self, cdp_url: str, selector: str, max_chars: int) -> dict[str, Any]: ...
    async def screenshot(self, cdp_url: str, full_page: bool) -> bytes: ...
    async def click(self, cdp_url: str, selector: str) -> dict[str, Any]: ...
    async def type_text(self, cdp_url: str, selector: str, text: str, submit: bool) -> dict[str, Any]: ...
    async def evaluate(self, cdp_url: str, expression: str) -> Any: ...
    async def history(self, cdp_url: str, direction: Literal["back", "forward"]) -> dict[str, Any]: ...
    async def wait_for(
        self, cdp_url: str, selector: str | None, text: str | None, state: WaitState, timeout_ms: int
    ) -> dict[str, Any]: ...
    async def tabs(self, cdp_url: str) -> list[dict[str, Any]]: ...
    async def new_tab(self, cdp_url: str, url: str) -> list[dict[str, Any]]: ...
    async def select_tab(self, cdp_url: str, index: int) -> list[dict[str, Any]]: ...
    async def close_tab(self, cdp_url: str, index: int) -> list[dict[str, Any]]: ...


def _user_pages(ctx) -> list:
    return [p for p in ctx.pages if not p.url.startswith(("devtools://", "chrome-extension://"))]


async def _target_id(ctx, page) -> str | None:
    try:
        session = await ctx.new_cdp_session(page)
        try:
            return (await session.send("Target.getTargetInfo"))["targetInfo"]["targetId"]
        finally:
            await session.detach()
    except Exception:  # a closing page has no target; it can't be the active tab anyway
        return None


async def _active_index(ctx, pages: list, cdp_url: str) -> int:
    """Index of the most recently activated tab; the last tab if Chromium won't say."""
    if len(pages) <= 1:
        return 0
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            targets = (await client.get(f"{cdp_url}/json/list")).json()
    except (httpx.HTTPError, ValueError):
        log.warning("could not read %s/json/list; assuming the last tab is active", cdp_url)
        return len(pages) - 1
    rank = {t["id"]: i for i, t in enumerate(t for t in targets if t.get("type") == "page")}
    ids = await asyncio.gather(*(_target_id(ctx, p) for p in pages))
    ranked = [(rank[tid], i) for i, tid in enumerate(ids) if tid in rank]
    return min(ranked)[1] if ranked else len(pages) - 1


async def _activate(ctx, page, cdp_url: str) -> None:
    """Bring `page` to the front and wait until /json/list reports it as most recent.

    Chromium updates the activation order asynchronously, so without the wait the next
    (separately connected) call can still see the previously active tab first.
    """
    await page.bring_to_front()
    tid = await _target_id(ctx, page)
    if tid is None:
        return
    deadline = asyncio.get_running_loop().time() + ACTIVATE_SETTLE_S
    async with httpx.AsyncClient(timeout=5) as client:
        while True:
            try:
                targets = (await client.get(f"{cdp_url}/json/list")).json()
                first = next((t["id"] for t in targets if t.get("type") == "page"), None)
                if first == tid:
                    return
            except (httpx.HTTPError, ValueError):
                pass
            if asyncio.get_running_loop().time() >= deadline:
                log.warning("tab %s not reported active after %.1fs", tid, ACTIVATE_SETTLE_S)
                return
            await asyncio.sleep(0.1)


class PlaywrightOps:
    def __init__(self, timeout_ms: int = 30_000) -> None:
        self.timeout_ms = timeout_ms

    @asynccontextmanager
    async def _context(self, cdp_url: str):
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(cdp_url, timeout=self.timeout_ms)
            try:
                yield browser.contexts[0] if browser.contexts else await browser.new_context()
            finally:
                # For CDP connections this only disconnects; the session keeps running.
                await browser.close()

    @asynccontextmanager
    async def _page(self, cdp_url: str):
        async with self._context(cdp_url) as ctx:
            pages = _user_pages(ctx)
            page = pages[await _active_index(ctx, pages, cdp_url)] if pages else await ctx.new_page()
            page.set_default_timeout(self.timeout_ms)
            yield page

    @staticmethod
    async def _state(page) -> dict[str, Any]:
        return {"url": page.url, "title": await page.title()}

    @staticmethod
    async def _tab_list(pages: list, active: int) -> list[dict[str, Any]]:
        titles = await asyncio.gather(*(p.title() for p in pages))
        return [
            {"index": i, "url": p.url, "title": t, "active": i == active}
            for i, (p, t) in enumerate(zip(pages, titles, strict=True))
        ]

    async def navigate(self, cdp_url: str, url: str) -> dict[str, Any]:
        async with self._page(cdp_url) as page:
            await page.goto(url, wait_until="domcontentloaded")
            return await self._state(page)

    async def snapshot(self, cdp_url: str, max_chars: int) -> dict[str, Any]:
        async with self._page(cdp_url) as page:
            text = await page.evaluate("() => document.body ? document.body.innerText : ''")
            links = await page.evaluate(
                "() => Array.from(document.links).slice(0, 100)"
                ".map(a => ({text: a.innerText.trim().slice(0, 120), href: a.href}))"
            )
            return {
                **await self._state(page),
                "text": text[:max_chars],
                "truncated": len(text) > max_chars,
                "links": links,
            }

    async def aria_snapshot(self, cdp_url: str, selector: str, max_chars: int) -> dict[str, Any]:
        async with self._page(cdp_url) as page:
            tree = await page.locator(selector).first.aria_snapshot()
            return {**await self._state(page), "aria": tree[:max_chars], "truncated": len(tree) > max_chars}

    async def screenshot(self, cdp_url: str, full_page: bool) -> bytes:
        async with self._page(cdp_url) as page:
            return await page.screenshot(full_page=full_page, type="png")

    async def click(self, cdp_url: str, selector: str) -> dict[str, Any]:
        async with self._page(cdp_url) as page:
            await page.click(selector)
            await page.wait_for_load_state("domcontentloaded")
            return await self._state(page)

    async def type_text(self, cdp_url: str, selector: str, text: str, submit: bool) -> dict[str, Any]:
        async with self._page(cdp_url) as page:
            await page.fill(selector, text)
            if submit:
                await page.press(selector, "Enter")
                await page.wait_for_load_state("domcontentloaded")
            return await self._state(page)

    async def evaluate(self, cdp_url: str, expression: str) -> Any:
        async with self._page(cdp_url) as page:
            return await page.evaluate(expression)

    async def history(self, cdp_url: str, direction: Literal["back", "forward"]) -> dict[str, Any]:
        async with self._page(cdp_url) as page:
            go = page.go_back if direction == "back" else page.go_forward
            before = page.url
            # The image disables the back-forward cache, because a restored page fires no
            # lifecycle events and Playwright's load-state tracking stalls over CDP. As a
            # safety net (e.g. a custom image with it enabled), wait for the commit and give
            # the load state a bounded wait. The response is None for "no history" and for
            # cache restores alike, so judge movement by the URL.
            await go(wait_until="commit")
            with contextlib.suppress(PlaywrightTimeout):
                await page.wait_for_load_state("domcontentloaded", timeout=HISTORY_SETTLE_MS)
            return {**await self._state(page), "moved": page.url != before}

    async def wait_for(
        self, cdp_url: str, selector: str | None, text: str | None, state: WaitState, timeout_ms: int
    ) -> dict[str, Any]:
        async with self._page(cdp_url) as page:
            if selector:
                await page.locator(selector).first.wait_for(state=state, timeout=timeout_ms)
            elif text:
                await page.get_by_text(text).first.wait_for(state=state, timeout=timeout_ms)
            else:
                await page.wait_for_load_state("load", timeout=timeout_ms)
            return await self._state(page)

    async def tabs(self, cdp_url: str) -> list[dict[str, Any]]:
        async with self._context(cdp_url) as ctx:
            pages = _user_pages(ctx)
            return await self._tab_list(pages, await _active_index(ctx, pages, cdp_url))

    async def new_tab(self, cdp_url: str, url: str) -> list[dict[str, Any]]:
        async with self._context(cdp_url) as ctx:
            page = await ctx.new_page()
            page.set_default_timeout(self.timeout_ms)
            await page.goto(url, wait_until="domcontentloaded")
            await _activate(ctx, page, cdp_url)
            pages = _user_pages(ctx)
            return await self._tab_list(pages, pages.index(page))

    async def select_tab(self, cdp_url: str, index: int) -> list[dict[str, Any]]:
        async with self._context(cdp_url) as ctx:
            pages = _user_pages(ctx)
            self._check_index(pages, index)
            await _activate(ctx, pages[index], cdp_url)
            return await self._tab_list(pages, index)

    async def close_tab(self, cdp_url: str, index: int) -> list[dict[str, Any]]:
        async with self._context(cdp_url) as ctx:
            pages = _user_pages(ctx)
            self._check_index(pages, index)
            if len(pages) == 1:
                # Closing the last tab exits Chromium, which destroys the whole session.
                raise BrowserOpsError("refusing to close the last tab; use browser_close to end the session")
            await pages[index].close()
            pages = _user_pages(ctx)
            active = await _active_index(ctx, pages, cdp_url)
            await _activate(ctx, pages[active], cdp_url)
            return await self._tab_list(pages, active)

    @staticmethod
    def _check_index(pages: list, index: int) -> None:
        if not 0 <= index < len(pages):
            raise BrowserOpsError(f"no tab {index}; there are {len(pages)} (0-{len(pages) - 1})")
