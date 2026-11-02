"""stdio MCP entry point for desktop MCP clients that spawn a local process.

Talks to the local Docker daemon directly and reaches each browser through its
host-published CDP port, so no controller container is required.
"""

from __future__ import annotations

import os


def main() -> None:
    os.environ.setdefault("DBROWSER_CDP_ACCESS", "published")
    from .browser_ops import PlaywrightOps
    from .config import get_settings
    from .mcp_server import build_mcp
    from .runtime import DockerRuntime
    from .sessions import SessionManager

    manager = SessionManager(DockerRuntime(), get_settings())
    build_mcp(manager, PlaywrightOps()).run("stdio")


if __name__ == "__main__":
    main()
