# Enhancements

## How to propose one

Open an issue titled `enhancement: <short name>` with:

1. **Problem:** who is affected and how.
2. **Proposal:** the behaviour or API you want, including the MCP tool or REST shape if relevant.
3. **Privacy impact:** does it persist, log, or expose anything? It must keep G1 (zero persistence).
4. **Alternatives considered.**
5. **Effort and risk.**

Maintainers triage weekly into the backlog below. Accepted items move to [ROADMAP.md](ROADMAP.md).

## Backlog

| ID | Enhancement | Value | Effort | Status |
|---|---|---|---|---|
| E-1 | Publish multi-arch images to GHCR, signed with cosign | High | S | planned v0.2 |
| E-2 | docker-socket-proxy between the controller and Docker (least privilege) | High | S | planned v0.2 |
| E-3 | Idle timeout (destroy after N minutes with no CDP or VNC activity) | High | M | planned v0.2 |
| E-4 | Per-agent quotas (max sessions, max TTL, allowed networks) | Medium | M | planned v0.2 |
| E-5 | Chromium namespace sandbox with a shipped seccomp profile (`CHROMIUM_SANDBOX=1`) | High | M | planned v0.3 |
| E-6 | Download hand-off: stream a file to the user or agent, then wipe it | Medium | M | planned v0.3 |
| E-7 | Opt-in encrypted "session snapshot" you carry yourself (never stored server-side) | Low | L | proposed |
| E-8 | Audio and clipboard in the viewer | Medium | M | planned v0.3 |
| E-9 | MCP tools: `browser_back`, `browser_tabs`, `browser_wait_for`, accessibility-tree snapshot | High | S | planned v0.2 |
| E-10 | Prometheus metrics and an OpenTelemetry trace per session | Medium | S | proposed |
| E-11 | Built-in uBlock Origin Lite (MV3) extension | Medium | S | proposed |
| E-12 | Choice of other engines (Firefox / Camoufox image) behind the same API | Medium | L | proposed |
| E-13 | Kubernetes runtime adapter (the `Runtime` seam already isolates Docker) | Low | L | proposed |
| E-14 | Per-session random timezone, locale and window size presets to reduce correlation | Medium | S | proposed |
| E-15 | OAuth / OIDC login for the dashboard | Medium | M | proposed |
