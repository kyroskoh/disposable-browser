# Roadmap

## Done: v0.1.x (MVP, shipped 2026-11-01)

- [x] Disposable Chromium sessions (read-only container, tmpfs profile, destroyed on close)
- [x] DuckDuckGo default search and privacy policies
- [x] WireGuard (kill switch) and Tailscale egress, with Cloudflare / Tailscale live-view sharing
- [x] Controller: REST, dashboard, TTL reaper, stateless design
- [x] MCP server (HTTP + stdio) with one browser per agent and per-agent tokens
- [x] Hermes / Grok-bot multi-agent examples
- [x] CI: lint, unit, hadolint, smoke and e2e against real Docker

## Now: v0.2 (target 2026-12; implemented, awaiting release)

- [x] Multi-arch images on GHCR, signed (E-1)
- [x] docker-socket-proxy (E-2)
- [x] Idle timeout (E-3) and per-agent quotas (E-4)
- [x] More MCP tools: back/forward, tabs, wait-for, accessibility snapshot (E-9)
- [x] uBlock Origin Lite bundled (E-11)

## Next: v0.3 (security and privacy depth)

- [ ] DNS profiles: AdGuard DNS, Quad9, Mullvad, NextDNS, self-hosted Pi-hole / AdGuard Home (E-16)
- [ ] Egress guard against LAN, metadata and container-network access (E-17)
- [ ] Authenticated CDP (E-18) and token-gated viewer (E-19)
- [ ] Image scanning, dependency bots and scheduled security rebuilds (E-20)
- [ ] Secrets passed by tmpfs file instead of env (E-21)
- [ ] Chromium sandbox with a seccomp profile (E-5)
- [ ] Download hand-off (E-6), audio and clipboard (E-8)

## Later: v0.4 to v1.0

- [ ] Metrics and tracing (E-10), OIDC dashboard login (E-15), rate limiting and audit log (E-25)
- [ ] Upstream proxy and Tor egress (E-22), ref-based MCP targeting and PDF/upload (E-23)
- [ ] Fingerprint-correlation presets (E-14), warm session pool (E-24)
- [ ] Alternative engines (E-12), Kubernetes runtime (E-13)
- [ ] v1.0: contract tests (E-26), frozen REST and MCP contract, external security review
