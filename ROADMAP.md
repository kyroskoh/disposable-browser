# Roadmap

## Now: v0.1.x (MVP, shipped 2026-11-01)

- [x] Disposable Chromium sessions (read-only container, tmpfs profile, destroyed on close)
- [x] DuckDuckGo default search and privacy policies
- [x] WireGuard (kill switch) and Tailscale egress, with Cloudflare / Tailscale live-view sharing
- [x] Controller: REST, dashboard, TTL reaper, stateless design
- [x] MCP server (HTTP + stdio) with one browser per agent and per-agent tokens
- [x] Hermes / Grok-bot multi-agent examples
- [x] CI: lint, unit, hadolint, smoke and e2e against real Docker

## Next: v0.2 (target 2026-12)

- [ ] Multi-arch images on GHCR, signed (E-1)
- [ ] docker-socket-proxy (E-2)
- [ ] Idle timeout (E-3) and per-agent quotas (E-4)
- [ ] More MCP tools: back/forward, tabs, wait-for, accessibility snapshot (E-9)
- [ ] uBlock Origin Lite bundled (E-11)

## Later: v0.3 to v1.0

- [ ] Chromium sandbox with a seccomp profile (E-5)
- [ ] Download hand-off (E-6), audio and clipboard (E-8)
- [ ] Metrics and tracing (E-10), OIDC dashboard login (E-15)
- [ ] Alternative engines (E-12), Kubernetes runtime (E-13)
- [ ] v1.0: frozen REST and MCP contract, external security review
