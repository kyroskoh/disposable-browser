# Disposable Browser: Product Requirements

| | |
|---|---|
| Owner | Kyros Koh |
| Status | v0.2.1 (Hardening & Distribution) |
| Last updated | 2026-11-01 |

## 1. Problem

Ordinary browsers pile up identity: cookies, history, cache, storage, fingerprintable state and the
real IP address. Private windows reduce this but share a process, an OS profile and a network path.
AI agents make it worse. They need real browsers, but sharing one browser between agents leaks
sessions between tasks and users, and running browsers by hand for every agent is painful.

## 2. Users

| Persona | Need |
|---|---|
| **Privacy-minded person** | A one-click browser that keeps nothing and can go through their VPN |
| **Agent builder** (Hermes Agent, Grok bot, custom) | Every agent gets its own isolated browser through MCP or CDP, created and destroyed by API |
| **Operator / self-hoster** | Run it on a home server or VPS, reach it remotely without opening ports |

## 3. Goals

1. **G1 – Zero persistence:** once a session ends, nothing from it survives on disk.
2. **G2 – Fresh on demand:** a new, clean session starts in under 10 seconds.
3. **G3 – Private by default:** DuckDuckGo, no telemetry or sync, third-party cookies blocked, no WebRTC IP leaks.
4. **G4 – Flexible egress and exposure:** WireGuard, Tailscale and Cloudflare Tunnel.
5. **G5 – Agent-native:** a standard MCP server plus CDP, with one isolated browser per agent.
6. **G6 – Docker-only install:** `docker compose up`.

## 4. Non-goals (v0.x)

- Anti-detect or fingerprint-spoofing browsing, and evading bot protections or site terms.
- Persisting profiles or logins between sessions (it contradicts G1; see ENHANCEMENT E-7).
- Multi-host scheduling (Kubernetes / Nomad). Single Docker host only.
- Desktop-native app wrappers.

## 5. Functional requirements

| ID | Requirement | Priority | Status |
|---|---|---|---|
| FR-1 | Start an isolated Chromium session in its own container with a tmpfs profile and read-only rootfs | Must | ✅ |
| FR-2 | Closing Chromium (window, `Browser.close`, crash) destroys the container and its data | Must | ✅ |
| FR-3 | API, MCP and dashboard can destroy a session at any time | Must | ✅ |
| FR-4 | Sessions expire after a TTL (default 1h, configurable maximum) | Must | ✅ |
| FR-5 | DuckDuckGo is the default search, home page and new-tab page, set by managed policy | Must | ✅ |
| FR-6 | Privacy policies: no sync, sign-in, password manager, autofill, metrics or Privacy Sandbox; third-party cookies blocked; WebRTC limited to proxied UDP | Must | ✅ |
| FR-7 | Live view in a web browser (noVNC) protected by a per-session VNC password | Must | ✅ |
| FR-8 | CDP endpoint per session for Playwright / Puppeteer | Must | ✅ |
| FR-9 | WireGuard egress per session from named profiles, with a kill switch | Must | ✅ |
| FR-10 | Tailscale egress per session (userspace, ephemeral, optional exit node) | Should | ✅ |
| FR-11 | Share a session's live view through a Cloudflare quick or named tunnel, or Tailscale Serve | Should | ✅ |
| FR-12 | MCP server (Streamable HTTP + stdio) with open / navigate / snapshot / screenshot / click / type / evaluate / list / close tools | Must | ✅ |
| FR-13 | One session per `agent_id`; `fresh` replaces it | Must | ✅ |
| FR-14 | Per-agent tokens: an agent can only see and drive its own session | Must | ✅ |
| FR-15 | Standalone mode: a single `docker run` or script, no controller | Must | ✅ |
| FR-16 | Dashboard to create, list, open and destroy sessions | Should | ✅ |
| FR-17 | Optional DNS-over-HTTPS template for all sessions | Could | ✅ |
| FR-18 | Remote access to the controller through Tailscale or Cloudflare compose profiles | Should | ✅ |

## 6. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-1 | **Security:** containers drop all capabilities except a minimal set (NET_ADMIN/NET_RAW only for WireGuard), run with `no-new-privileges` and non-root GUI processes, and publish ports on 127.0.0.1 by default. |
| NFR-2 | **Auth:** every non-health endpoint needs a bearer token; tokens are compared in constant time. |
| NFR-3 | **Statelessness:** the controller keeps no database. Docker labels are the source of truth, and a restart loses nothing. |
| NFR-4 | **Resource limits** for each session: memory, CPU, PIDs and shm. |
| NFR-5 | **Startup:** a session is ready in under 10 s on a warm host (p50). |
| NFR-6 | **Quality:** CI runs lint, unit tests, hadolint, a standalone smoke test and end-to-end tests against real Docker on every push. |
| NFR-7 | **Portability:** runs on linux/amd64 and linux/arm64 hosts, and on Docker Desktop for Windows/macOS. |

## 7. Success metrics

- Zero persisted artifacts after a session ends, verified by the e2e "new session starts clean" test.
- p50 time-to-ready under 10 s, and p95 under 20 s.
- An agent can be integrated by config only (MCP), with no custom code.

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| The Docker socket gives the controller root-equivalent access | The controller only reaches Docker through `docker-socket-proxy` (container endpoints only, on an internal network sessions can't join); bind to localhost, use bearer auth, and allow remote access only over a tailnet or Access |
| Classic VNC auth is weak (8 characters) | Viewer bound to 127.0.0.1; remote sharing only through Cloudflare Access or a tailnet; per-session random password |
| Chromium runs with `--no-sandbox` inside the container | The container is the sandbox (no caps, read-only, no-new-privileges, non-root); `CHROMIUM_SANDBOX=1` plus a seccomp profile is on the roadmap |
| VPN leaks | WireGuard kill switch, plus a `WebRtcIPHandling` policy |
| Abuse (scraping, ToS violations) | Documented acceptable use; rate and session limits |

## 9. Milestones

| Version | Scope |
|---|---|
| v0.1.0 | MVP: everything marked ✅ above |
| v0.2.0 | Published multi-arch images (GHCR), docker-socket-proxy, idle timeout, per-agent quotas |
| v0.3.0 | Chromium sandbox with a seccomp profile, file download hand-off, audio, clipboard |
| v1.0.0 | Stable API and MCP tool contract, security review, observability |
