# 0001. One container per browser session, controller is stateless

Status: Accepted (2026-11-01)

## Context

The quality attributes, in priority order, are: privacy (zero persistence) > isolation between users
and agents > simplicity of install (Docker only) > startup latency > density.

## Decision

- Each session is a fresh container created from the browser image, with `--rm`, a read-only rootfs,
  and a tmpfs at `/tmp` holding the profile, policies, VPN config and X socket. Chromium is the
  foreground process, so closing it ends the container.
- Egress and exposure (WireGuard, Tailscale, cloudflared) run **inside** the session container.
  Each session therefore has its own network identity, and its keys die with it.
- The controller (FastAPI + MCP) keeps no state. Docker labels hold the session metadata
  (owner, TTL, mode), so the controller can restart at any time.
- Docker access sits behind a `Runtime` protocol, so tests use a fake and a Kubernetes adapter can come later.

## Consequences

- \+ Strong isolation and true deletion. Deleting the container is the whole cleanup.
- \+ Simple mental model; works the same standalone (`docker run`) and managed.
- − About 2–5 s startup and roughly 300–600 MB RAM per session (Chromium); density is limited by RAM.
- − The controller needs to create containers, which is close to root-equivalent. Mitigated by a localhost bind, auth, and (since v0.2) a docker-socket-proxy that only exposes container endpoints.
- − Classic VNC is weak; shared viewers must sit behind Access or a tailnet.

## Alternatives considered

- **One Chromium with many incognito contexts:** cheap, but contexts share a process, a network path and the host. Rejected for isolation.
- **Sidecar VPN containers (`network_mode: container:`):** a standard pattern, but it doubles the containers per session and complicates cleanup. Rejected for v0.1.
- **Persistent database for sessions:** unnecessary, because labels suffice and that keeps the controller stateless.
