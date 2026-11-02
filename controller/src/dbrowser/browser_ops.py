"""Drive a session's Chromium over CDP with Playwright. Each call connects, acts, disconnects.

Tabs are numbered in a stable order, and "the current tab" is the one an agent last opened
or selected. PlaywrightOps remembers both per session (in memory, bounded), keyed by CDP
target id, because Chromium can't be asked reliably: every call reconnects and Playwright
lists pages in attach order, which varies between connections; pages created over CDP open
in their own windows, so bringing one to the front doesn't change DevTools' /json/list
activation order; and document.visibilityState reads "visible" everywhere. /json/list
order is only the fallback, e.g. after a controller restart or when the remembered tab is
closed.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx
from playwright.async_api import TimeoutError as PlaywrightTimeout

log = logging.getLogger("dbrowser.browser_ops")

WaitState = Literal["visible", "hidden", "attached", "detached"]
HISTORY_SETTLE_MS = 10_000
MAX_REMEMBERED_SESSIONS = 1024


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


@dataclass
class _TabState:
    order: list[str] = field(default_factory=list)  # target ids in the order agents see them
    selected: str | None = None  # target id of the tab last opened or selected


def _stable_order(known: list[str], ids: list[str | None]) -> list[int]:
    """Indices into `ids`: known tabs in their remembered order, then new ones, then unidentified."""
    pos = {tid: i for i, tid in enumerate(known)}

    def key(i: int) -> tuple[int, int]:
        tid = ids[i]
        if tid in pos:
            return (0, pos[tid])
        return (1 if tid is not None else 2, i)

    return sorted(range(len(ids)), key=key)


def _pick_active(ids: list[str | None], selected: str | None, devtools_order: list[str]) -> int:
    """Index of the current tab: the remembered one, else Chromium's most recent, else the last."""
    if selected is not None and selected in ids:
        return ids.index(selected)
    rank = {tid: i for i, tid in enumerate(devtools_order)}
    ranked = [(rank[tid], i) for i, tid in enumerate(ids) if tid in rank]
    return min(ranked)[1] if ranked else len(ids) - 1


class PlaywrightOps:
    def __init__(self, timeout_ms: int = 30_000) -> None:
        self.timeout_ms = timeout_ms
        self._sessions: OrderedDict[str, _TabState] = OrderedDict()  # cdp_url -> tabs, LRU

    def _session(self, cdp_url: str) -> _TabState:
        state = self._sessions.setdefault(cdp_url, _TabState())
        self._sessions.move_to_end(cdp_url)
        while len(self._sessions) > MAX_REMEMBERED_SESSIONS:
            self._sessions.popitem(last=False)
        return state

    async def _tabs(self, ctx, cdp_url: str) -> tuple[list, list[str | None]]:
        """User tabs in stable order, with their target ids."""
        pages = _user_pages(ctx)
        ids = list(await asyncio.gather(*(_target_id(ctx, p) for p in pages)))
        state = self._session(cdp_url)
        idx = _stable_order(state.order, ids)
        pages, ids = [pages[i] for i in idx], [ids[i] for i in idx]
        state.order = [tid for tid in ids if tid is not None]
        return pages, ids

    async def _active_index(self, ids: list[str | None], cdp_url: str) -> int:
        if len(ids) <= 1:
            return 0
        selected = self._session(cdp_url).selected
        order: list[str] = []
        if selected not in ids:
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    targets = (await client.get(f"{cdp_url}/json/list")).json()
                order = [t["id"] for t in targets if t.get("type") == "page"]
            except (httpx.HTTPError, ValueError):
                log.warning("could not read %s/json/list; assuming the last tab is active", cdp_url)
        return _pick_active(ids, selected, order)

    async def _activate(self, page, target_id: str | None, cdp_url: str) -> None:
        await page.bring_to_front()  # for a human watching the viewer
        if target_id is not None:
            self._session(cdp_url).selected = target_id

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
            pages, ids = await self._tabs(ctx, cdp_url)
            page = pages[await self._active_index(ids, cdp_url)] if pages else await ctx.new_page()
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
            pages, ids = await self._tabs(ctx, cdp_url)
            return await self._tab_list(pages, await self._active_index(ids, cdp_url))

    async def new_tab(self, cdp_url: str, url: str) -> list[dict[str, Any]]:
        async with self._context(cdp_url) as ctx:
            await self._tabs(ctx, cdp_url)  # record the existing order before adding a tab
            page = await ctx.new_page()
            page.set_default_timeout(self.timeout_ms)
            await page.goto(url, wait_until="domcontentloaded")
            pages, ids = await self._tabs(ctx, cdp_url)  # the new tab sorts last
            active = pages.index(page)
            await self._activate(page, ids[active], cdp_url)
            return await self._tab_list(pages, active)

    async def select_tab(self, cdp_url: str, index: int) -> list[dict[str, Any]]:
        async with self._context(cdp_url) as ctx:
            pages, ids = await self._tabs(ctx, cdp_url)
            self._check_index(pages, index)
            await self._activate(pages[index], ids[index], cdp_url)
            return await self._tab_list(pages, index)

    async def close_tab(self, cdp_url: str, index: int) -> list[dict[str, Any]]:
        async with self._context(cdp_url) as ctx:
            pages, _ = await self._tabs(ctx, cdp_url)
            self._check_index(pages, index)
            if len(pages) == 1:
                # Closing the last tab exits Chromium, which destroys the whole session.
                raise BrowserOpsError("refusing to close the last tab; use browser_close to end the session")
            await pages[index].close()
            pages, ids = await self._tabs(ctx, cdp_url)
            active = await self._active_index(ids, cdp_url)
            await self._activate(pages[active], ids[active], cdp_url)
            return await self._tab_list(pages, active)

    @staticmethod
    def _check_index(pages: list, index: int) -> None:
        if not 0 <= index < len(pages):
            raise BrowserOpsError(f"no tab {index}; there are {len(pages)} (0-{len(pages) - 1})")
