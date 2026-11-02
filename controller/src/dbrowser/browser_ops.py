"""Drive a session's Chromium over CDP with Playwright. Each call connects, acts, disconnects."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Protocol


class BrowserOps(Protocol):
    async def navigate(self, cdp_url: str, url: str) -> dict[str, Any]: ...
    async def snapshot(self, cdp_url: str, max_chars: int) -> dict[str, Any]: ...
    async def screenshot(self, cdp_url: str, full_page: bool) -> bytes: ...
    async def click(self, cdp_url: str, selector: str) -> dict[str, Any]: ...
    async def type_text(self, cdp_url: str, selector: str, text: str, submit: bool) -> dict[str, Any]: ...
    async def evaluate(self, cdp_url: str, expression: str) -> Any: ...


class PlaywrightOps:
    def __init__(self, timeout_ms: int = 30_000) -> None:
        self.timeout_ms = timeout_ms

    @asynccontextmanager
    async def _page(self, cdp_url: str):
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(cdp_url, timeout=self.timeout_ms)
            try:
                ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
                pages = [p for p in ctx.pages if not p.url.startswith("devtools://")]
                page = pages[-1] if pages else await ctx.new_page()
                page.set_default_timeout(self.timeout_ms)
                yield page
            finally:
                # For CDP connections this only disconnects; the session keeps running.
                await browser.close()

    @staticmethod
    async def _state(page) -> dict[str, Any]:
        return {"url": page.url, "title": await page.title()}

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
