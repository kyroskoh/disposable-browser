"""MCP server: lets any MCP client (Hermes agents, Claude, Cursor, ...) own a disposable browser.

Agent identity: when a client authenticates with a per-agent token, BearerAuth sets the
`X-Dbrowser-Agent` header from that token (overwriting anything the client sent), and the agent
can only see and touch its own session. Admin-token clients may pass `agent_id` freely.
"""

from __future__ import annotations

from typing import Any

import anyio
from mcp.server.mcpserver import Context, Image, MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from . import __version__
from .browser_ops import BrowserOps
from .models import ExposeMode, NetworkMode, Session, SessionCreate
from .sessions import SessionError, SessionManager

AGENT_HEADER = "x-dbrowser-agent"

INSTRUCTIONS = """\
Disposable, privacy-first Chromium (DuckDuckGo default search). Each agent gets its own
isolated browser; closing it destroys all cookies, history and cache. Typical flow:
browser_navigate(url) -> browser_snapshot() -> browser_click/type -> browser_close().
session_id is optional everywhere: omit it to use (or auto-create) your own session."""


def _header_agent(ctx: Context | None) -> str | None:
    try:
        headers = ctx.headers if ctx else None
    except (ValueError, AttributeError, LookupError):  # outside a request / stdio
        return None
    value = headers.get(AGENT_HEADER) if headers else None
    return value.strip() if value else None


def _public(s: Session) -> dict[str, Any]:
    return s.model_dump(mode="json")


def http_app(mcp: MCPServer) -> Starlette:
    """Streamable-HTTP app to mount at /mcp. Bearer auth replaces Host-header rebinding checks."""
    return mcp.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )


def build_mcp(manager: SessionManager, ops: BrowserOps) -> MCPServer:
    mcp = MCPServer("disposable-browser", instructions=INSTRUCTIONS, version=__version__)

    def agent_of(ctx: Context | None, agent_id: str | None) -> str:
        header = _header_agent(ctx)
        if header and agent_id and agent_id != header:
            raise SessionError(f"agent_id '{agent_id}' does not match the authenticated agent '{header}'")
        return agent_id or header or "default"

    async def resolve(ctx: Context | None, session_id: str | None) -> str:
        """Session to act on: explicit id (ownership-checked) or the caller's own, created on demand."""
        header = _header_agent(ctx)
        if session_id:
            s = await anyio.to_thread.run_sync(manager.get, session_id)
            if header and s.agent_id != header:
                raise SessionError(f"session {session_id} belongs to another agent")
            return s.id
        agent = agent_of(ctx, None)
        s = await anyio.to_thread.run_sync(manager.find_by_agent, agent)
        if s is None:
            s = await anyio.to_thread.run_sync(manager.create, SessionCreate(agent_id=agent))
        return s.id

    async def cdp(session_id: str) -> str:
        return await anyio.to_thread.run_sync(manager.cdp_endpoint, session_id)

    @mcp.tool()
    async def browser_open(
        agent_id: str | None = None,
        network: NetworkMode = NetworkMode.direct,
        wireguard_profile: str | None = None,
        tailscale_exit_node: str | None = None,
        expose: ExposeMode = ExposeMode.none,
        ttl_seconds: int | None = None,
        start_url: str = "https://duckduckgo.com/",
        fresh: bool = False,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Open (or return) this agent's disposable browser.

        network: direct | wireguard (needs wireguard_profile) | tailscale (optional exit node).
        expose: none | cloudflare | tailscale - share a live view URL with a human.
        fresh=true destroys any existing session first for a brand-new identity.
        """
        req = SessionCreate(
            agent_id=agent_of(ctx, agent_id),
            network=network,
            wireguard_profile=wireguard_profile,
            tailscale_exit_node=tailscale_exit_node,
            expose=expose,
            ttl_seconds=ttl_seconds,
            start_url=start_url,
            reuse=not fresh,
        )
        return _public(await anyio.to_thread.run_sync(manager.create, req))

    @mcp.tool()
    async def browser_list(ctx: Context | None = None) -> list[dict[str, Any]]:
        """List live sessions (only your own when called with an agent header)."""
        header = _header_agent(ctx)
        sessions = await anyio.to_thread.run_sync(manager.list)
        return [_public(s) for s in sessions if not header or s.agent_id == header]

    @mcp.tool()
    async def browser_close(session_id: str | None = None, ctx: Context | None = None) -> dict[str, Any]:
        """Close the browser and permanently delete the session (cookies, history, cache)."""
        sid = await resolve(ctx, session_id) if session_id else None
        if sid is None:
            s = await anyio.to_thread.run_sync(manager.find_by_agent, agent_of(ctx, None))
            if s is None:
                return {"closed": False, "reason": "no open session"}
            sid = s.id
        await anyio.to_thread.run_sync(manager.destroy, sid)
        return {"closed": True, "session_id": sid}

    @mcp.tool()
    async def browser_navigate(url: str, session_id: str | None = None, ctx: Context | None = None) -> dict:
        """Navigate to a URL (or a search: plain words go to DuckDuckGo). Returns url + title."""
        if not url.startswith(("http://", "https://")):
            from urllib.parse import quote_plus

            url = f"https://duckduckgo.com/?q={quote_plus(url)}"
        sid = await resolve(ctx, session_id)
        return {"session_id": sid, **await ops.navigate(await cdp(sid), url)}

    @mcp.tool()
    async def browser_snapshot(
        session_id: str | None = None, max_chars: int = 20_000, ctx: Context | None = None
    ) -> dict[str, Any]:
        """Readable text of the current page plus up to 100 links."""
        sid = await resolve(ctx, session_id)
        return {"session_id": sid, **await ops.snapshot(await cdp(sid), max(500, min(max_chars, 200_000)))}

    @mcp.tool()
    async def browser_screenshot(
        session_id: str | None = None, full_page: bool = False, ctx: Context | None = None
    ) -> Image:
        """PNG screenshot of the current page."""
        sid = await resolve(ctx, session_id)
        return Image(data=await ops.screenshot(await cdp(sid), full_page), format="png")

    @mcp.tool()
    async def browser_click(selector: str, session_id: str | None = None, ctx: Context | None = None) -> dict:
        """Click an element by CSS / Playwright selector (e.g. 'text=Sign in')."""
        sid = await resolve(ctx, session_id)
        return {"session_id": sid, **await ops.click(await cdp(sid), selector)}

    @mcp.tool()
    async def browser_type(
        selector: str,
        text: str,
        submit: bool = False,
        session_id: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Fill an input; submit=true presses Enter afterwards."""
        sid = await resolve(ctx, session_id)
        return {"session_id": sid, **await ops.type_text(await cdp(sid), selector, text, submit)}

    @mcp.tool()
    async def browser_evaluate(
        expression: str, session_id: str | None = None, ctx: Context | None = None
    ) -> Any:
        """Evaluate a JavaScript expression in the page and return its JSON result."""
        sid = await resolve(ctx, session_id)
        return await ops.evaluate(await cdp(sid), expression)

    return mcp
