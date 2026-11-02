"""Session lifecycle. Docker labels are the source of truth, so the controller is stateless."""

from __future__ import annotations

import base64
import logging
import re
import secrets
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from .config import Settings
from .models import ExposeMode, NetworkMode, Session, SessionCreate
from .runtime import CDP_PORT, LABEL, VIEWER_PORT, ContainerInfo, ContainerSpec, Runtime

log = logging.getLogger("dbrowser.sessions")
PUBLIC_URL_RE = re.compile(r"DBROWSER_PUBLIC_URL=(\S+)")


class SessionError(Exception):
    status = 400


class SessionNotFound(SessionError):
    status = 404


class SessionLimitReached(SessionError):
    status = 429


class SessionNotReady(SessionError):
    status = 504


class QuotaExceeded(SessionError):
    status = 403


def probe_cdp(url: str) -> bool:
    try:
        return httpx.get(f"{url}/json/version", timeout=2.0).status_code == 200
    except httpx.HTTPError:
        return False


class SessionManager:
    def __init__(
        self,
        runtime: Runtime,
        settings: Settings,
        clock: Callable[[], float] = time.time,
        probe: Callable[[str], bool] = probe_cdp,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.runtime = runtime
        self.settings = settings
        self._clock = clock
        self._probe = probe
        self._sleep = sleep
        self._lock = threading.Lock()

    # ---- queries -------------------------------------------------------
    def list(self) -> list[Session]:
        return [self._to_session(c) for c in self.runtime.list()]

    def get(self, session_id: str) -> Session:
        c = self.runtime.get(self._name(session_id))
        if c is None:
            raise SessionNotFound(f"session {session_id} not found (closed or expired)")
        return self._to_session(c)

    def find_by_agent(self, agent_id: str) -> Session | None:
        for c in self.runtime.list():
            if c.labels.get("dbrowser.agent") == agent_id:
                return self._to_session(c)
        return None

    def cdp_endpoint(self, session_id: str) -> str:
        """CDP URL as reachable from the controller process itself."""
        c = self.runtime.get(self._name(session_id))
        if c is None:
            raise SessionNotFound(f"session {session_id} not found (closed or expired)")
        return self._cdp_internal(c)

    # ---- commands ------------------------------------------------------
    def create(self, req: SessionCreate) -> Session:
        req = self._apply_quota(req)
        with self._lock:
            if req.agent_id and req.reuse:
                existing = self.find_by_agent(req.agent_id)
                if existing:
                    return existing
            if req.agent_id and not req.reuse:
                old = self.find_by_agent(req.agent_id)
                if old:
                    self.destroy(old.id)
            if len(self.runtime.list()) >= self.settings.max_sessions:
                raise SessionLimitReached(f"max_sessions={self.settings.max_sessions} reached")
            spec, sid = self._spec(req)
            info = self.runtime.run(spec)
        try:
            self._wait_ready(info)
        except SessionNotReady:
            self.runtime.remove(spec.name)
            raise
        return self.get(sid)

    def destroy(self, session_id: str) -> None:
        name = self._name(session_id)
        if self.runtime.get(name) is None:
            raise SessionNotFound(f"session {session_id} not found (closed or expired)")
        self.runtime.remove(name)
        log.info("destroyed session %s", session_id)

    def reap(self) -> list[str]:
        """Destroy expired sessions. Returns the ids removed."""
        now = self._clock()
        removed = []
        for c in self.runtime.list():
            if float(c.labels.get("dbrowser.expires", "0")) <= now:
                self.runtime.remove(c.name)
                removed.append(c.labels.get("dbrowser.id", c.name))
        if removed:
            log.info("reaped expired sessions: %s", removed)
        return removed

    # ---- internals -----------------------------------------------------
    def _apply_quota(self, req: SessionCreate) -> SessionCreate:
        """Reject what the agent's quota forbids and clamp what it caps. No quota: unchanged."""
        if not req.agent_id:
            return req
        quotas = self.settings.agent_quota_map()
        q = quotas.get(req.agent_id) or quotas.get("*")
        if q is None:
            return req
        who = f"agent '{req.agent_id}'"
        if q.networks is not None and req.network not in q.networks:
            raise QuotaExceeded(f"{who} may not use network={req.network.value}")
        if q.expose is not None and req.expose not in q.expose:
            raise QuotaExceeded(f"{who} may not use expose={req.expose.value}")
        if (
            q.wireguard_profiles is not None
            and req.wireguard_profile
            and req.wireguard_profile not in q.wireguard_profiles
        ):
            raise QuotaExceeded(f"{who} may not use WireGuard profile '{req.wireguard_profile}'")
        update: dict[str, int] = {}
        if q.max_ttl_seconds:
            update["ttl_seconds"] = min(
                req.ttl_seconds or self.settings.default_ttl_seconds, q.max_ttl_seconds
            )
        if q.max_idle_timeout_seconds:
            # 0 means "off", which the cap must not allow, so it becomes the cap itself.
            idle = self._idle(req) or q.max_idle_timeout_seconds
            update["idle_timeout_seconds"] = min(idle, q.max_idle_timeout_seconds)
        return req.model_copy(update=update) if update else req

    def _idle(self, req: SessionCreate) -> int:
        if req.idle_timeout_seconds is not None:
            return req.idle_timeout_seconds
        return self.settings.idle_timeout_seconds

    @staticmethod
    def _name(session_id: str) -> str:
        if not re.fullmatch(r"[a-f0-9]{12}", session_id):
            raise SessionNotFound(f"session {session_id} not found")
        return f"dbrowser-{session_id}"

    def _spec(self, req: SessionCreate) -> tuple[ContainerSpec, str]:
        s = self.settings
        sid = secrets.token_hex(6)
        ttl = min(req.ttl_seconds or s.default_ttl_seconds, s.max_ttl_seconds)
        now = self._clock()
        vnc_password = secrets.token_hex(4)  # classic VNC auth uses 8 chars
        idle = self._idle(req)
        adblock = s.adblock if req.adblock is None else req.adblock
        env = {
            "NET_MODE": req.network.value,
            "EXPOSE_MODE": req.expose.value,
            "START_URL": req.start_url,
            "VNC_PASSWORD": vnc_password,
            "ENABLE_CDP": "1",
            "ADBLOCK": "1" if adblock else "0",
        }
        if idle:
            env["IDLE_TIMEOUT"] = str(idle)
        if s.doh_template:
            env["DOH_TEMPLATE"] = s.doh_template
        cap_add: list[str] = []
        sysctls: dict[str, str] = {}

        if req.network == NetworkMode.wireguard:
            env["WG_CONFIG_B64"] = base64.b64encode(self._wireguard_config(req.wireguard_profile)).decode()
            cap_add += ["NET_ADMIN", "NET_RAW"]
            sysctls = {"net.ipv4.conf.all.src_valid_mark": "1", "net.ipv6.conf.all.disable_ipv6": "0"}

        if req.network == NetworkMode.tailscale or req.expose == ExposeMode.tailscale:
            if not s.tailscale_authkey:
                raise SessionError("Tailscale requested but DBROWSER_TAILSCALE_AUTHKEY is not set")
            env["TS_AUTHKEY"] = s.tailscale_authkey
            env["TS_HOSTNAME"] = f"dbrowser-{req.agent_id or sid}"[:63]
            if req.tailscale_exit_node:
                env["TS_EXIT_NODE"] = req.tailscale_exit_node

        if req.expose == ExposeMode.cloudflare and s.cloudflare_tunnel_token:
            env["CF_TUNNEL_TOKEN"] = s.cloudflare_tunnel_token
            env["CF_TUNNEL_HOSTNAME"] = s.cloudflare_tunnel_hostname

        labels = {
            LABEL: "1",
            "dbrowser.id": sid,
            "dbrowser.agent": req.agent_id or "",
            "dbrowser.created": f"{now:.0f}",
            "dbrowser.expires": f"{now + ttl:.0f}",
            "dbrowser.network": req.network.value,
            "dbrowser.expose": req.expose.value,
            "dbrowser.vnc_password": vnc_password,
            "dbrowser.idle": str(idle),
            "dbrowser.adblock": "1" if adblock else "0",
        }
        spec = ContainerSpec(
            name=f"dbrowser-{sid}",
            image=s.browser_image,
            labels=labels,
            env=env,
            network=s.docker_network,
            publish_bind=s.publish_bind,
            memory_limit=s.memory_limit,
            shm_size=s.shm_size,
            cpus=s.cpus,
            pids_limit=s.pids_limit,
            cap_add=cap_add,
            sysctls=sysctls,
        )
        return spec, sid

    def _wireguard_config(self, profile: str | None) -> bytes:
        path = self.settings.wireguard_profiles_dir / f"{profile}.conf"
        if not path.is_file():
            raise SessionError(
                f"WireGuard profile '{profile}' not found in {self.settings.wireguard_profiles_dir}"
            )
        return path.read_bytes()

    def _wait_ready(self, info: ContainerInfo) -> None:
        deadline = self._clock() + self.settings.ready_timeout_seconds
        url = self._cdp_internal(info)
        while self._clock() < deadline:
            if self._probe(url):
                return
            current = self.runtime.get(info.name)
            if current is None:
                raise SessionNotReady("browser exited during startup; check the controller logs")
            info = current
            url = self._cdp_internal(info)
            self._sleep(0.5)
        raise SessionNotReady(f"browser not ready after {self.settings.ready_timeout_seconds}s")

    def _cdp_internal(self, c: ContainerInfo) -> str:
        if self.settings.cdp_access == "internal" and c.ip:
            return f"http://{c.ip}:{CDP_PORT}"
        port = c.host_ports.get(CDP_PORT)
        return f"http://127.0.0.1:{port}" if port else ""

    def _to_session(self, c: ContainerInfo) -> Session:
        lbl = c.labels
        host = self.settings.public_host
        pw = lbl.get("dbrowser.vnc_password", "")
        vport, cport = c.host_ports.get(VIEWER_PORT), c.host_ports.get(CDP_PORT)
        public_url = None
        if lbl.get("dbrowser.expose", "none") != "none":
            m = PUBLIC_URL_RE.search(self.runtime.logs(c.name))
            public_url = m.group(1) if m else None
        return Session(
            id=lbl.get("dbrowser.id", c.name.removeprefix("dbrowser-")),
            agent_id=lbl.get("dbrowser.agent") or None,
            status=c.status,
            network=NetworkMode(lbl.get("dbrowser.network", "direct")),
            expose=ExposeMode(lbl.get("dbrowser.expose", "none")),
            created_at=datetime.fromtimestamp(float(lbl.get("dbrowser.created", "0")), UTC),
            expires_at=datetime.fromtimestamp(float(lbl.get("dbrowser.expires", "0")), UTC),
            idle_timeout_seconds=int(lbl.get("dbrowser.idle", "0") or 0),
            adblock=lbl.get("dbrowser.adblock") == "1",
            viewer_url=(
                f"http://{host}:{vport}/vnc.html?autoconnect=1&resize=remote&password={pw}" if vport else None
            ),
            vnc_password=pw,
            cdp_url=f"http://{host}:{cport}" if cport else None,
            public_url=public_url,
        )
