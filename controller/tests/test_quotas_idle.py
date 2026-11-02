"""Idle timeout (E-3), adblock toggle (E-11) and per-agent quotas (E-4)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from dbrowser.config import Settings
from dbrowser.models import SessionCreate
from dbrowser.sessions import QuotaExceeded, SessionManager


def spec_of(runtime, session):
    return runtime.specs[f"dbrowser-{session.id}"]


def make_manager(runtime, settings, clock):
    return SessionManager(runtime, settings, clock=clock, probe=lambda u: True, sleep=clock.advance)


# ---- idle timeout ------------------------------------------------------------
def test_idle_timeout_off_by_default(manager, runtime):
    s = manager.create(SessionCreate())
    assert s.idle_timeout_seconds == 0
    assert "IDLE_TIMEOUT" not in spec_of(runtime, s).env


def test_idle_timeout_from_settings_and_request(manager, runtime, settings):
    settings.idle_timeout_seconds = 600
    s = manager.create(SessionCreate())
    assert s.idle_timeout_seconds == 600 and spec_of(runtime, s).env["IDLE_TIMEOUT"] == "600"

    s2 = manager.create(SessionCreate(idle_timeout_seconds=45))
    assert s2.idle_timeout_seconds == 45 and spec_of(runtime, s2).env["IDLE_TIMEOUT"] == "45"

    off = manager.create(SessionCreate(idle_timeout_seconds=0))
    assert off.idle_timeout_seconds == 0 and "IDLE_TIMEOUT" not in spec_of(runtime, off).env


@pytest.mark.parametrize("bad", [1, 29, -1])
def test_idle_timeout_floor(bad):
    with pytest.raises(ValidationError):
        SessionCreate(idle_timeout_seconds=bad)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, idle_timeout_seconds=bad)


# ---- adblock -----------------------------------------------------------------
def test_adblock_on_by_default_and_overridable(manager, runtime, settings):
    on = manager.create(SessionCreate())
    off = manager.create(SessionCreate(adblock=False))
    assert on.adblock and spec_of(runtime, on).env["ADBLOCK"] == "1"
    assert not off.adblock and spec_of(runtime, off).env["ADBLOCK"] == "0"

    settings.adblock = False
    assert manager.create(SessionCreate()).adblock is False


# ---- quotas ------------------------------------------------------------------
def quotas(settings, value: dict) -> None:
    settings.agent_quotas = json.dumps(value)


def test_no_quotas_means_no_limits(manager):
    s = manager.create(SessionCreate(agent_id="bot", ttl_seconds=7200))
    assert (s.expires_at - s.created_at).total_seconds() == 7200


def test_quota_rejects_network_and_expose(manager, settings):
    settings.tailscale_authkey = "tskey-auth-x"
    quotas(settings, {"bot": {"networks": ["direct"], "expose": ["none"]}})
    with pytest.raises(QuotaExceeded, match="network=tailscale"):
        manager.create(SessionCreate(agent_id="bot", network="tailscale"))
    with pytest.raises(QuotaExceeded, match="expose=cloudflare"):
        manager.create(SessionCreate(agent_id="bot", expose="cloudflare"))
    assert manager.create(SessionCreate(agent_id="bot")).network == "direct"


def test_quota_checked_before_reuse(manager, settings):
    """An existing session must not let a forbidden request slip through via reuse."""
    manager.create(SessionCreate(agent_id="bot"))
    quotas(settings, {"bot": {"expose": ["none"]}})
    with pytest.raises(QuotaExceeded):
        manager.create(SessionCreate(agent_id="bot", expose="cloudflare"))


def test_quota_wireguard_profiles(manager, settings):
    for name in ("allowed", "other"):
        (settings.wireguard_profiles_dir / f"{name}.conf").write_text("[Interface]\n")
    quotas(settings, {"bot": {"wireguard_profiles": ["allowed"]}})
    with pytest.raises(QuotaExceeded, match="'other'"):
        manager.create(SessionCreate(agent_id="bot", network="wireguard", wireguard_profile="other"))
    s = manager.create(SessionCreate(agent_id="bot", network="wireguard", wireguard_profile="allowed"))
    assert s.network == "wireguard"


def test_quota_caps_ttl_and_wildcard_applies(manager, settings):
    quotas(settings, {"*": {"max_ttl_seconds": 300}, "trusted": {}})
    capped = manager.create(SessionCreate(agent_id="anyone", ttl_seconds=7200))
    default_ttl = manager.create(SessionCreate(agent_id="someone"))
    trusted = manager.create(SessionCreate(agent_id="trusted", ttl_seconds=7200))
    assert (capped.expires_at - capped.created_at).total_seconds() == 300
    assert (default_ttl.expires_at - default_ttl.created_at).total_seconds() == 300
    # An agent's own entry replaces "*" entirely.
    assert (trusted.expires_at - trusted.created_at).total_seconds() == 7200


def test_quota_forces_and_caps_idle(runtime, settings, clock):
    quotas(settings, {"bot": {"max_idle_timeout_seconds": 120}})
    m = make_manager(runtime, settings, clock)
    forced = m.create(SessionCreate(agent_id="bot"))
    assert forced.idle_timeout_seconds == 120
    m.destroy(forced.id)
    assert (
        m.create(SessionCreate(agent_id="bot", idle_timeout_seconds=0, reuse=False)).idle_timeout_seconds
        == 120
    )
    lower = m.create(SessionCreate(agent_id="bot", idle_timeout_seconds=60, reuse=False))
    assert lower.idle_timeout_seconds == 60


def test_anonymous_sessions_ignore_quotas(manager, settings):
    quotas(settings, {"*": {"networks": ["wireguard"]}})
    assert manager.create(SessionCreate()).network == "direct"


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[1, 2]",
        '{"bot": {"max_ttl_seconds": 5}}',
        '{"bot": {"typo": 1}}',
        '{"bot": {"networks": ["x"]}}',
    ],
)
def test_malformed_quotas_rejected(raw):
    with pytest.raises(ValueError):
        Settings(_env_file=None, agent_quotas=raw).agent_quota_map()
