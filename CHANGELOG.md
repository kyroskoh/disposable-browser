# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/).

## [Unreleased]

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
- Docs: PRD, README, ROADMAP, ENHANCEMENT, CONTRIBUTION, SECURITY, CODE_OF_CONDUCT, ADR 0001.

[Unreleased]: https://github.com/kyroskoh/disposable-browser/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/kyroskoh/disposable-browser/releases/tag/v0.1.0
