from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError

from dbrowser.models import ExposeMode, NetworkMode, SessionCreate
from dbrowser.sessions import (
    SessionError,
    SessionLimitReached,
    SessionManager,
    SessionNotFound,
    SessionNotReady,
)


def test_create_direct_session_is_locked_down(manager, runtime):
    s = manager.create(SessionCreate())
    spec = runtime.specs[f"dbrowser-{s.id}"]

    assert s.network == NetworkMode.direct and s.expose == ExposeMode.none
    assert s.viewer_url.startswith("http://localhost:") and f"password={s.vnc_password}" in s.viewer_url
    assert s.cdp_url.startswith("http://localhost:")
    assert len(s.vnc_password) == 8
    assert spec.env["NET_MODE"] == "direct" and spec.env["START_URL"] == "https://duckduckgo.com/"
    assert "NET_ADMIN" not in spec.cap_add and not spec.sysctls
    assert spec.publish_bind == "127.0.0.1"
    assert (s.expires_at - s.created_at).total_seconds() == 3600


def test_cdp_endpoint_uses_container_ip_internally(manager, runtime):
    s = manager.create(SessionCreate())
    assert manager.cdp_endpoint(s.id).startswith("http://172.30.0.")


def test_cdp_endpoint_published_mode(runtime, settings, clock):
    settings.cdp_access = "published"
    m = SessionManager(runtime, settings, clock=clock, probe=lambda u: True, sleep=lambda s: None)
    s = m.create(SessionCreate())
    assert manager_cdp_port(m.cdp_endpoint(s.id)) == manager_cdp_port(s.cdp_url)


def manager_cdp_port(url: str) -> str:
    return url.rsplit(":", 1)[1]


def test_agent_reuses_its_session(manager):
    a = manager.create(SessionCreate(agent_id="grok-1"))
    again = manager.create(SessionCreate(agent_id="grok-1"))
    other = manager.create(SessionCreate(agent_id="grok-2"))
    assert a.id == again.id and other.id != a.id


def test_fresh_replaces_agent_session(manager, runtime):
    a = manager.create(SessionCreate(agent_id="grok-1"))
    b = manager.create(SessionCreate(agent_id="grok-1", reuse=False))
    assert a.id != b.id
    assert f"dbrowser-{a.id}" in runtime.removed
    assert [s.id for s in manager.list()] == [b.id]


def test_session_limit(manager):
    for _ in range(3):
        manager.create(SessionCreate())
    with pytest.raises(SessionLimitReached):
        manager.create(SessionCreate())


def test_wireguard_profile_injected_with_caps(manager, runtime, settings):
    (settings.wireguard_profiles_dir / "mullvad-sg.conf").write_text("[Interface]\nPrivateKey = x\n")
    s = manager.create(SessionCreate(network="wireguard", wireguard_profile="mullvad-sg"))
    spec = runtime.specs[f"dbrowser-{s.id}"]
    assert base64.b64decode(spec.env["WG_CONFIG_B64"]).startswith(b"[Interface]")
    assert {"NET_ADMIN", "NET_RAW"} <= set(spec.cap_add)
    assert spec.sysctls["net.ipv4.conf.all.src_valid_mark"] == "1"


def test_wireguard_missing_profile(manager):
    with pytest.raises(SessionError, match="not found"):
        manager.create(SessionCreate(network="wireguard", wireguard_profile="nope"))


def test_tailscale_requires_authkey(manager):
    with pytest.raises(SessionError, match="TAILSCALE_AUTHKEY"):
        manager.create(SessionCreate(network="tailscale"))
    with pytest.raises(SessionError, match="TAILSCALE_AUTHKEY"):
        manager.create(SessionCreate(expose="tailscale"))


def test_tailscale_env(manager, runtime, settings):
    settings.tailscale_authkey = "tskey-auth-ephemeral"
    s = manager.create(SessionCreate(agent_id="bot", network="tailscale", tailscale_exit_node="exit-sg"))
    env = runtime.specs[f"dbrowser-{s.id}"].env
    assert env["TS_AUTHKEY"] == "tskey-auth-ephemeral"
    assert env["TS_EXIT_NODE"] == "exit-sg" and env["TS_HOSTNAME"] == "dbrowser-bot"


def test_public_url_parsed_from_logs(manager, runtime):
    s = manager.create(SessionCreate(expose="cloudflare"))
    assert manager.get(s.id).public_url is None
    runtime.logs_by_name[f"dbrowser-{s.id}"] = (
        "x\nDBROWSER_PUBLIC_URL=https://abc-def.trycloudflare.com/vnc.html\n"
    )
    assert manager.get(s.id).public_url == "https://abc-def.trycloudflare.com/vnc.html"


def test_reap_only_expired(manager, clock):
    short = manager.create(SessionCreate(ttl_seconds=60))
    long = manager.create(SessionCreate(ttl_seconds=600))
    clock.advance(120)
    assert manager.reap() == [short.id]
    assert [s.id for s in manager.list()] == [long.id]


def test_ttl_capped(manager, settings):
    settings.max_ttl_seconds = 300
    s = manager.create(SessionCreate(ttl_seconds=10_000))
    assert (s.expires_at - s.created_at).total_seconds() == 300


def test_not_ready_cleans_up(runtime, settings, clock):
    m = SessionManager(runtime, settings, clock=clock, probe=lambda u: False, sleep=clock.advance)
    with pytest.raises(SessionNotReady):
        m.create(SessionCreate())
    assert runtime.removed and not runtime.list()


def test_browser_exit_during_startup(runtime, settings, clock):
    runtime.exit_on_start = True
    m = SessionManager(runtime, settings, clock=clock, probe=lambda u: False, sleep=clock.advance)
    with pytest.raises(SessionNotReady, match="exited"):
        m.create(SessionCreate())


def test_closed_browser_disappears(manager, runtime):
    """Closing Chromium exits the container; auto_remove deletes it, so the session is gone."""
    s = manager.create(SessionCreate())
    runtime.containers.clear()
    with pytest.raises(SessionNotFound):
        manager.get(s.id)


@pytest.mark.parametrize("bad", ["", "../etc", "DBROWSER", "abc", "0123456789ab0"])
def test_invalid_ids_are_not_found(manager, bad):
    with pytest.raises(SessionNotFound):
        manager.destroy(bad)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"network": "wireguard"},
        {"wireguard_profile": "x"},
        {"tailscale_exit_node": "x"},
        {"start_url": "javascript:alert(1)"},
        {"start_url": 'https://x.com/" --evil'},
        {"agent_id": "has space"},
        {"ttl_seconds": 5},
    ],
)
def test_request_validation(kwargs):
    with pytest.raises(ValidationError):
        SessionCreate(**kwargs)
