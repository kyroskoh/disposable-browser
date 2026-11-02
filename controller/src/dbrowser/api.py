"""HTTP surface: REST API (/v1), MCP (/mcp/), dashboard (/), health (/healthz)."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
from collections.abc import Callable
from importlib import resources

import anyio
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from . import __version__
from .browser_ops import BrowserOps, PlaywrightOps
from .config import Settings
from .mcp_server import AGENT_HEADER, build_mcp, http_app
from .models import Session, SessionCreate
from .runtime import Runtime, RuntimeError_
from .sessions import SessionError, SessionManager, probe_cdp

log = logging.getLogger("dbrowser.api")
PUBLIC_PATHS = {"/", "/healthz", "/favicon.ico"}


class BearerAuth:
    """Pure ASGI middleware (safe for MCP streaming responses).

    Admin token: full REST + MCP access. Agent tokens: MCP only, and the agent identity
    header is forced from the token so agents cannot impersonate each other.
    """

    def __init__(self, app, admin_token: str, agent_tokens: dict[str, str]) -> None:
        self.app = app
        self.admin = admin_token.encode()
        self.agents = {t.encode(): a for t, a in agent_tokens.items()}

    @staticmethod
    async def _deny(scope, receive, send, status: int, detail: str) -> None:
        resp = JSONResponse({"detail": detail}, status_code=status, headers={"WWW-Authenticate": "Bearer"})
        await resp(scope, receive, send)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] in PUBLIC_PATHS:
            return await self.app(scope, receive, send)
        auth = dict(scope["headers"]).get(b"authorization", b"")
        presented = auth[7:] if auth[:7].lower() == b"bearer " else b""
        headers = [(k, v) for k, v in scope["headers"] if k != AGENT_HEADER.encode()]
        if presented and hmac.compare_digest(presented, self.admin):
            return await self.app(scope, receive, send)
        agent = next(
            (a for t, a in self.agents.items() if presented and hmac.compare_digest(presented, t)), None
        )
        if agent is None:
            return await self._deny(scope, receive, send, 401, "missing or invalid bearer token")
        if not scope["path"].startswith("/mcp"):
            return await self._deny(scope, receive, send, 403, "agent tokens may only use /mcp")
        headers.append((AGENT_HEADER.encode(), agent.encode()))
        return await self.app({**scope, "headers": headers}, receive, send)


def create_app(
    settings: Settings,
    runtime: Runtime | None = None,
    ops: BrowserOps | None = None,
    probe: Callable[[str], bool] = probe_cdp,
) -> FastAPI:
    if runtime is None:
        from .runtime import DockerRuntime

        runtime = DockerRuntime()
    manager = SessionManager(runtime, settings, probe=probe)
    mcp = build_mcp(manager, ops or PlaywrightOps())
    mcp_app = http_app(mcp)

    async def reaper() -> None:
        while True:
            await asyncio.sleep(settings.reap_interval_seconds)
            try:
                await anyio.to_thread.run_sync(manager.reap)
            except Exception:  # keep reaping even if Docker hiccups
                log.exception("reaper failed")

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        task = asyncio.create_task(reaper())
        async with mcp.session_manager.run():
            yield
        task.cancel()

    app = FastAPI(title="Disposable Browser", version=__version__, lifespan=lifespan)
    app.state.manager = manager

    @app.exception_handler(SessionError)
    async def _session_error(_: Request, e: SessionError):
        return JSONResponse({"detail": str(e)}, status_code=e.status)

    @app.exception_handler(RuntimeError_)
    async def _runtime_error(_: Request, e: RuntimeError_):
        return JSONResponse({"detail": f"container runtime error: {e}"}, status_code=502)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return resources.files("dbrowser").joinpath("static/index.html").read_text(encoding="utf-8")

    @app.get("/v1/sessions")
    def list_sessions() -> list[Session]:
        return manager.list()

    @app.post("/v1/sessions", status_code=201)
    def create_session(req: SessionCreate) -> Session:
        return manager.create(req)

    @app.get("/v1/sessions/{session_id}")
    def get_session(session_id: str) -> Session:
        return manager.get(session_id)

    @app.delete("/v1/sessions/{session_id}", status_code=204)
    def delete_session(session_id: str) -> Response:
        manager.destroy(session_id)
        return Response(status_code=204)

    app.mount("/mcp", mcp_app)
    return BearerAuth(app, settings.resolved_token(), settings.agent_token_map())  # type: ignore[return-value]
