from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Controller configuration, read from DBROWSER_* environment variables."""

    model_config = SettingsConfigDict(env_prefix="DBROWSER_", env_file=".env", extra="ignore")

    api_token: str = Field(default="", description="Admin bearer token for REST + MCP. Generated if empty.")
    # "agent-a:token-a,agent-b:token-b" -> each agent authenticates as itself on /mcp.
    agent_tokens: str = ""
    browser_image: str = "disposable-browser/browser:dev"
    docker_network: str = "dbrowser"

    max_sessions: int = Field(default=10, ge=1)
    default_ttl_seconds: int = Field(default=3600, ge=60)
    max_ttl_seconds: int = Field(default=86400, ge=60)
    reap_interval_seconds: int = Field(default=30, ge=5)
    ready_timeout_seconds: float = Field(default=30.0, gt=0)

    # How URLs handed back to clients are built.
    public_host: str = "localhost"
    publish_bind: str = "127.0.0.1"
    # internal: reach CDP via container IP (controller runs inside Docker).
    # published: reach CDP via the host-published port (controller runs on the host).
    cdp_access: Literal["internal", "published"] = "internal"

    memory_limit: str = "2g"
    shm_size: str = "1g"
    cpus: float = Field(default=1.0, gt=0)
    pids_limit: int = 1024

    wireguard_profiles_dir: Path = Path("/wg-profiles")
    tailscale_authkey: str = ""
    cloudflare_tunnel_token: str = ""
    cloudflare_tunnel_hostname: str = ""
    doh_template: str = ""

    def agent_token_map(self) -> dict[str, str]:
        """token -> agent_id."""
        out: dict[str, str] = {}
        for pair in filter(None, (p.strip() for p in self.agent_tokens.split(","))):
            agent, sep, token = pair.partition(":")
            if not sep or not agent or len(token) < 16:
                raise ValueError(
                    f"DBROWSER_AGENT_TOKENS entry '{agent}' must be agent:token (token >= 16 chars)"
                )
            out[token] = agent
        return out

    def resolved_token(self) -> str:
        if not self.api_token:
            self.api_token = secrets.token_urlsafe(24)
        return self.api_token


@lru_cache
def get_settings() -> Settings:
    return Settings()
