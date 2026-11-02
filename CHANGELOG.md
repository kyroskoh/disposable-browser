# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-11-01

### Added
- Release workflow (E-1): on `v*` tags, builds `linux/amd64` + `linux/arm64` images, pushes them to GHCR (`disposable-browser-browser`, `disposable-browser-controller`) with SBOM and provenance, and signs each digest keylessly with cosign.
- Idle timeout (E-3): `idle_timeout_seconds` per session and `DBROWSER_IDLE_TIMEOUT_SECONDS` as the default (off by default, otherwise at least 30 s). A watchdog in the browser closes Chromium once no CDP or VNC client has been connected for that long, which removes the session.
- Per-agent quotas (E-4): `DBROWSER_AGENT_QUOTAS` (JSON, with a `"*"` fallback) caps `max_ttl_seconds` and `max_idle_timeout_seconds`, and restricts `networks`, `expose` and `wireguard_profiles`. Violations return `403` over REST and a tool error over MCP. Malformed JSON stops the controller at startup.
- MCP tools (E-9): `browser_back`, `browser_forward`, `browser_tabs` (list/new/select/close), `browser_wait_for`, and `browser_accessibility_snapshot` (ARIA tree as YAML). The active tab is whichever one Chromium shows, so the controller stays stateless.
- uBlock Origin Lite (E-11) is bundled in the browser image: pinned to `2026.1012.1545`, SHA-256-verified, and on by default. Turn it off with `adblock: false` per session or `DBROWSER_ADBLOCK=false`.
- Sessions report `idle_timeout_seconds` and `adblock`. The dashboard has idle-timeout and ad-blocking options.
- `DBROWSER_CONTROLLER_IMAGE` lets Compose use a published controller image.

### Changed
- **docker-socket-proxy (E-2):** the controller no longer mounts the Docker socket. Compose runs `tecnativa/docker-socket-proxy` (container endpoints only) on an internal `docker-api` network and points `DOCKER_HOST` at it. `DOCKER_GID` is no longer needed. The controller also can't pull images any more, so build or `docker pull` the browser image first.
- MCP tool errors an agent can act on (session, quota, tab, Playwright and validation errors) now return their message instead of a generic "Error executing tool".
- Requires `playwright>=1.49` (for ARIA snapshots).
- Chromium's back-forward cache is disabled. Restored pages fire no lifecycle events, which stalled `browser_back` / `browser_forward` over CDP, and the cache keeps pages you've left alive in memory.
- ENHANCEMENT and ROADMAP: added DNS profiles (E-16) and the gaps found in the v0.2 review (E-17 to E-26), and planned v0.3 as a security and privacy release.
- README restructured to the house template: emoji sections, Key libraries, Acknowledgments, Support, footer.
- `CONTRIBUTION.md` renamed to `CONTRIBUTING.md`, the name GitHub recognises.

## [0.1.0] - 2026-11-01

### Added
- Browser image (Debian bookworm + Chromium + Xvfb + x11vnc + noVNC):
  - The read-only rootfs and tmpfs profile mean the container destroys itself when Chromium exits.
  - Managed policies for privacy, with DuckDuckGo as the default search, home and new-tab page.
  - Egress per session: `direct`, `wireguard` (with kill switch) or `tailscale` (userspace, in-memory state, exit node).
  - Exposure per session through a Cloudflare quick or named tunnel, or Tailscale Serve.
  - CDP is published on port 9223 for agents.
- Controller (FastAPI):
  - REST API at `/v1/sessions`, a dashboard at `/`, and `/healthz`.
  - A TTL reaper. The controller is stateless, with Docker labels as the source of truth.
- MCP server (Streamable HTTP at `/mcp/`, plus a `dbrowser-mcp` stdio entry point).
  - Tools: `browser_open`, `browser_navigate`, `browser_snapshot`, `browser_screenshot`, `browser_click`, `browser_type`, `browser_evaluate`, `browser_list`, `browser_close`.
- Per-agent tokens (`DBROWSER_AGENT_TOKENS`) that give each agent one isolated browser and stop agents impersonating each other.
- Docker Compose deployment, with optional `cloudflare` and `tailscale` profiles for remote access to the controller.
- Standalone scripts `scripts/browse.sh` and `scripts/browse.ps1`.
- Examples for Hermes Agent and multi-agent (Grok bot) setups, generic MCP clients, and Playwright.
- CI: ruff, pytest (43 unit tests), shellcheck, hadolint, a standalone image smoke test, and end-to-end tests against real Docker.
- Docs: PRD, README, ROADMAP, ENHANCEMENT, CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, ADR 0001.

[Unreleased]: https://github.com/kyroskoh/disposable-browser/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/kyroskoh/disposable-browser/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/kyroskoh/disposable-browser/releases/tag/v0.1.0
