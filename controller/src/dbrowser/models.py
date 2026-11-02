from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"


class NetworkMode(StrEnum):
    direct = "direct"
    wireguard = "wireguard"
    tailscale = "tailscale"


class ExposeMode(StrEnum):
    none = "none"
    cloudflare = "cloudflare"
    tailscale = "tailscale"


class SessionCreate(BaseModel):
    agent_id: str | None = Field(
        default=None, pattern=NAME_PATTERN, description="Owner agent; one session each."
    )
    network: NetworkMode = NetworkMode.direct
    wireguard_profile: str | None = Field(default=None, pattern=NAME_PATTERN)
    tailscale_exit_node: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,252}$")
    expose: ExposeMode = ExposeMode.none
    ttl_seconds: int | None = Field(default=None, ge=60)
    start_url: str = "https://duckduckgo.com/"
    reuse: bool = Field(default=True, description="Return the agent's existing session instead of a new one.")

    @field_validator("start_url")
    @classmethod
    def _http_only(cls, v: str) -> str:
        if not v.startswith(("https://", "http://")) or len(v) > 2048 or any(c in v for c in "\"'\\ \n"):
            raise ValueError("start_url must be a plain http(s) URL")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> SessionCreate:
        if self.network == NetworkMode.wireguard and not self.wireguard_profile:
            raise ValueError("network=wireguard requires wireguard_profile")
        if self.network != NetworkMode.wireguard and self.wireguard_profile:
            raise ValueError("wireguard_profile is only valid with network=wireguard")
        if self.tailscale_exit_node and self.network != NetworkMode.tailscale:
            raise ValueError("tailscale_exit_node is only valid with network=tailscale")
        return self


class Session(BaseModel):
    id: str
    agent_id: str | None
    status: str
    network: NetworkMode
    expose: ExposeMode
    created_at: datetime
    expires_at: datetime
    viewer_url: str | None = Field(description="noVNC URL (includes the one-time VNC password).")
    vnc_password: str
    cdp_url: str | None = Field(
        description="Chrome DevTools endpoint for Playwright/Puppeteer connectOverCDP."
    )
    public_url: str | None = Field(default=None, description="Cloudflare / Tailscale URL when exposed.")
