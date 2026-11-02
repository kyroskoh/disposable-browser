from __future__ import annotations

import json
import secrets
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from .models import AgentQuota


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
    # Destroy a session after this many seconds with no CDP or VNC connection (0 = off).
    idle_timeout_seconds: int = Field(default=0, ge=0)
    # Load the bundled uBlock Origin Lite extension in every session (overridable per session).
    adblock: bool = True
    # JSON object of per-agent limits, keyed by agent id or "*" (every other agent), e.g.
    # {"grok-bot": {"max_ttl_seconds": 900, "networks": ["wireguard"], "expose": ["none"]}}
    agent_quotas: str = ""

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

    @field_validator("idle_timeout_seconds")
    @classmethod
    def _idle_floor(cls, v: int) -> int:
        if 0 < v < 30:
            raise ValueError("DBROWSER_IDLE_TIMEOUT_SECONDS must be 0 (off) or >= 30")
        return v

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

    def agent_quota_map(self) -> dict[str, AgentQuota]:
        """agent_id (or "*") -> quota. Raises ValueError on malformed JSON or unknown keys."""
        from .models import AgentQuota

        if not self.agent_quotas.strip():
            return {}
        try:
            raw = json.loads(self.agent_quotas)
        except json.JSONDecodeError as e:
            raise ValueError(f"DBROWSER_AGENT_QUOTAS is not valid JSON: {e}") from e
        if not isinstance(raw, dict):
            raise ValueError("DBROWSER_AGENT_QUOTAS must be a JSON object keyed by agent id")
        return {agent: AgentQuota.model_validate(q) for agent, q in raw.items()}

    def resolved_token(self) -> str:
        if not self.api_token:
            self.api_token = secrets.token_urlsafe(24)
        return self.api_token


@lru_cache
def get_settings() -> Settings:
    return Settings()
