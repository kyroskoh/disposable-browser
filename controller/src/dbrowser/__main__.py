from __future__ import annotations

import argparse
import logging


def main() -> None:
    import uvicorn

    from .api import create_app
    from .config import get_settings

    p = argparse.ArgumentParser(prog="dbrowser", description="Disposable browser controller (REST + MCP).")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    generated = not settings.api_token
    token = settings.resolved_token()
    if generated:
        logging.getLogger("dbrowser").warning(
            "DBROWSER_API_TOKEN not set; generated token for this run: %s", token
        )
    uvicorn.run(create_app(settings), host=args.host, port=args.port, proxy_headers=True)


if __name__ == "__main__":
    main()
