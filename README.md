# Disposable Browser

Private Chromium sessions that leave nothing behind, for people and for AI agents. Each session runs in its own container with DuckDuckGo search and hardened privacy policies. It can route traffic through WireGuard or Tailscale, and share its live view through Cloudflare Tunnel or Tailscale Serve. Close the window, call `DELETE`, or let the TTL run out, and the container goes with its tmpfs profile, so cookies, history, cache and storage are gone. The next session starts clean.

[![CI](https://github.com/kyroskoh/disposable-browser/actions/workflows/ci.yml/badge.svg)](https://github.com/kyroskoh/disposable-browser/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE.md)
[![Release](https://img.shields.io/github/v/release/kyroskoh/disposable-browser?include_prereleases)](https://github.com/kyroskoh/disposable-browser/releases)
[![Status: alpha](https://img.shields.io/badge/status-alpha-orange.svg)](ROADMAP.md)
[![Docker](https://img.shields.io/badge/runs%20on-Docker-2496ED?logo=docker&logoColor=white)](docker-compose.yml)
[![MCP](https://img.shields.io/badge/MCP-server-6E56CF)](examples/mcp-clients.md)

**Version:** 0.1.0 · **Live demo:** self-hosted (see [Getting Started](#-getting-started)) · **Changelog:** [CHANGELOG.md](./CHANGELOG.md)

## 🚀 Features

### Disposable by Design
- **One container per session**: read-only rootfs, tmpfs profile, `--rm`. When Chromium exits, the session is destroyed.
- **Many ways to end a session**: close the window, call `Browser.close`, `DELETE` it, or let its TTL expire. Each one removes everything.
- **A fresh identity on demand**: `fresh=true` / `reuse=false` throws away the old session and starts a clean one.

### Privacy-First Chromium
- **DuckDuckGo** is the default search, home page and new-tab page, set by managed policy.
- **Off by default**: sync, sign-in, password manager, autofill, telemetry, translate and Privacy Sandbox.
- **Blocked**: third-party cookies; geolocation, camera, microphone and other sensors are denied.
- **No IP leak through WebRTC**: `WebRtcIPHandling=disable_non_proxied_udp`.
- **Optional DNS-over-HTTPS** for all sessions.

### Networking per Session
- **WireGuard**: bring a `.conf`; an iptables kill switch is on by default.
- **Tailscale**: userspace mode with in-memory state and an optional exit node.
- **Sharing the live view**: a Cloudflare quick or named tunnel, or Tailscale Serve.

### Built for AI Agents
- **CDP endpoint** for Playwright or Puppeteer on every session.
- **MCP server** (Streamable HTTP + stdio) for Hermes Agents, Grok bots, Claude, Cursor and more.
- **One browser per agent**, enforced by per-agent tokens. Agents can't see or drive each other's sessions.

### Two Ways to Use It
- **Standalone**: `scripts/browse.sh` or `browse.ps1` starts one throwaway browser, no controller needed.
- **Managed**: a dashboard, REST API, MCP server and TTL reaper for fleets of sessions.

## 🏗️ Architecture

```mermaid
flowchart LR
  user([Human]) -->|HTTPS dashboard| ctl
  agent([Hermes / Grok bot / any MCP client]) -->|MCP streamable HTTP + bearer| ctl
  subgraph host[Docker host]
    ctl[controller\nFastAPI + MCP + reaper] -->|docker.sock| dockerd[(Docker)]
    dockerd -->|run --rm, read-only, tmpfs| s1[session A\nChromium + noVNC + CDP]
    dockerd --> s2[session B]
    ctl -->|CDP over dbrowser network| s1
  end
  user -->|noVNC 127.0.0.1:port| s1
  s1 -->|direct / WireGuard / Tailscale exit| internet((Internet))
  s2 -.->|cloudflared / tailscale serve| share([Shared live view])
```

```mermaid
stateDiagram-v2
  [*] --> Starting: POST /v1/sessions or browser_open
  Starting --> Running: CDP ready
  Starting --> Destroyed: failed to start (auto cleanup)
  Running --> Destroyed: window closed / Browser.close
  Running --> Destroyed: DELETE / browser_close
  Running --> Destroyed: TTL expired (reaper)
  Destroyed --> [*]: container and tmpfs profile deleted
```

```
disposable-browser/
├── browser/            # Chromium image: Dockerfile, entrypoint.sh (networking + lifecycle), policies/
├── controller/         # Python package: REST API, MCP server, session manager, dashboard, tests
├── deploy/tailscale/   # Tailscale Serve config for remote controller access
├── examples/           # Hermes / Grok-bot multi-agent, MCP clients, Playwright
├── scripts/            # browse.sh / browse.ps1 (standalone), smoke-standalone.sh
├── wireguard/          # your <profile>.conf files (git-ignored)
└── docs/adr/           # architecture decision records
```

### Tech Stack

**Browser image**
- Debian bookworm-slim, Chromium, Xvfb, x11vnc, noVNC/websockify, socat (CDP)
- wireguard-tools + iptables, tailscale, cloudflared, tini

**Controller**
- Python 3.12, FastAPI + Uvicorn, Pydantic v2
- Docker SDK for Python; the controller is stateless, with Docker labels as the source of truth
- MCP Python SDK 2.x (`MCPServer`, Streamable HTTP), Playwright (CDP client)

**Infrastructure**
- Docker Compose with optional `cloudflare` / `tailscale` profiles
- GitHub Actions: ruff, pytest, shellcheck, hadolint, smoke and e2e tests on real Docker

## 🚦 Getting Started

### Prerequisites
- Docker Engine 24+ with Compose v2 (Linux), or Docker Desktop (Windows/macOS)
- Python 3.11+ (only for development or running the tests)

### Installation
```bash
git clone https://github.com/kyroskoh/disposable-browser.git
cd disposable-browser
cp .env.example .env                    # set DBROWSER_API_TOKEN (openssl rand -hex 24)
# Linux only: let the non-root controller use the Docker socket
echo "DOCKER_GID=$(getent group docker | cut -d: -f3)" >> .env
```

### Using Docker (Recommended)
```bash
docker compose --profile build build    # builds browser + controller images
docker compose up -d                    # dashboard: http://localhost:8080
```

### Just One Browser (no controller)
```bash
docker build -t disposable-browser/browser:dev browser
scripts/browse.sh                       # prints a noVNC URL; close Chromium to destroy everything
scripts/browse.sh --wg ~/vpn/wg0.conf   # same, through WireGuard with a kill switch
# Windows: powershell -File scripts/browse.ps1
```

## 📊 Usage

### Web Interface
1. Open `http://localhost:8080` and paste your API token.
2. Pick the egress (Direct, WireGuard or Tailscale), the sharing option and the lifetime, then click **Start fresh browser**.
3. The live view opens in a new tab. Use **Destroy** to delete the session (or just close Chromium).

### API Usage
All `/v1` calls need `Authorization: Bearer $DBROWSER_API_TOKEN`.

```bash
# Create a session through a WireGuard profile, valid for 15 minutes
curl -s -H "Authorization: Bearer $T" -H 'Content-Type: application/json' \
  -d '{"agent_id":"grok-bot","network":"wireguard","wireguard_profile":"mullvad-sg","ttl_seconds":900}' \
  http://localhost:8080/v1/sessions

# List / inspect / destroy
curl -s -H "Authorization: Bearer $T" http://localhost:8080/v1/sessions
curl -s -H "Authorization: Bearer $T" http://localhost:8080/v1/sessions/<id>
curl -s -X DELETE -H "Authorization: Bearer $T" http://localhost:8080/v1/sessions/<id>
```

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/sessions` | Create a session. Returns `id`, `viewer_url`, `cdp_url`, `public_url`, `expires_at`. |
| `GET` | `/v1/sessions` | List live sessions |
| `GET` | `/v1/sessions/{id}` | One session (`404` once closed or expired) |
| `DELETE` | `/v1/sessions/{id}` | Destroy the session now |
| `GET` | `/healthz` | Liveness (no auth) |

Request fields:

| Field | Values |
|---|---|
| `agent_id` | Owner. An agent gets one session; set `reuse:false` to replace it with a fresh one. |
| `network` | `direct` (default), `wireguard` (needs `wireguard_profile`), `tailscale` (optional `tailscale_exit_node`) |
| `expose` | `none` (default), `cloudflare`, `tailscale` |
| `ttl_seconds` | Defaults to 3600. Capped by `DBROWSER_MAX_TTL_SECONDS`. |
| `start_url` | Defaults to `https://duckduckgo.com/` |

### MCP & AI Agents
- Endpoint: `http://localhost:8080/mcp/` (Streamable HTTP), plus a `dbrowser-mcp` stdio entry point.
- Tools: `browser_open`, `browser_navigate`, `browser_snapshot`, `browser_screenshot`, `browser_click`, `browser_type`, `browser_evaluate`, `browser_list`, `browser_close`.
- Client setup is in [examples/mcp-clients.md](examples/mcp-clients.md), and Hermes / Grok bot fleets in [examples/hermes/](examples/hermes/multi-agent.md).
- To give each agent its own isolated browser, set `DBROWSER_AGENT_TOKENS=agent-a:<token>,agent-b:<token>`.

### Networking Options
| Need | How |
|---|---|
| Hide your IP behind a VPN | Put `wireguard/<name>.conf` in place and use `network=wireguard`. The kill switch blocks non-tunnel egress. |
| Exit through a machine on your tailnet | Set `DBROWSER_TAILSCALE_AUTHKEY` (ephemeral key) and use `network=tailscale` with `tailscale_exit_node`. |
| Let someone watch or drive a session | `expose=cloudflare` (quick tunnel, no account needed) or `expose=tailscale` |

## 🧪 Testing

```bash
cd controller
ruff check . && ruff format --check .
pytest                                   # 43 unit tests: fake Docker, real MCP over HTTP

# End-to-end against real Docker (CI runs this on every push)
docker compose --profile build build && docker compose up -d
bash ../scripts/smoke-standalone.sh      # standalone image: CDP, noVNC, close = removed
DBROWSER_API_TOKEN=... pytest -m integration tests/integration
```

The end-to-end suite checks that the DuckDuckGo and privacy policies are active, that closing the browser destroys the session, that a new session starts with no cookies or storage, that MCP can drive a real browser, and that the Cloudflare quick tunnel works.

## 🛠️ Development

### Project Structure
| Path | Purpose |
|---|---|
| `controller/src/dbrowser/sessions.py` | Session lifecycle core (create, reuse, limits, TTL reaping, readiness) |
| `controller/src/dbrowser/runtime.py` | Docker seam (`Runtime` protocol + `DockerRuntime`) |
| `controller/src/dbrowser/api.py` | REST, dashboard, bearer / per-agent auth middleware |
| `controller/src/dbrowser/mcp_server.py` | MCP tools and agent isolation |
| `controller/src/dbrowser/browser_ops.py` | Playwright operations over CDP |
| `browser/entrypoint.sh` | Egress setup, display/VNC, exposure, Chromium lifecycle |

### Available Scripts
```bash
scripts/browse.sh [--wg wg0.conf]   # standalone disposable browser (Linux/macOS)
scripts/browse.ps1                  # standalone disposable browser (Windows)
scripts/smoke-standalone.sh         # image smoke test
dbrowser --port 8080                # run the controller from source
dbrowser-mcp                        # stdio MCP server using local Docker
```

## 🔧 Configuration

### Environment Variables
| Variable | Default | Description |
|---|---|---|
| `DBROWSER_API_TOKEN` | *(generated per run)* | Admin token for dashboard, REST and MCP |
| `DBROWSER_AGENT_TOKENS` | | `agent:token,...`: each agent gets its own isolated browser over MCP |
| `DBROWSER_BROWSER_IMAGE` | `disposable-browser/browser:dev` | Image launched for each session |
| `DBROWSER_MAX_SESSIONS` | `10` | Maximum concurrent sessions |
| `DBROWSER_DEFAULT_TTL_SECONDS` / `DBROWSER_MAX_TTL_SECONDS` | `3600` / `86400` | Session lifetime |
| `DBROWSER_PUBLIC_HOST` / `DBROWSER_PUBLISH_BIND` | `localhost` / `127.0.0.1` | Host used in returned URLs, and the interface session ports bind to |
| `DBROWSER_MEMORY_LIMIT` / `DBROWSER_SHM_SIZE` / `DBROWSER_CPUS` | `2g` / `1g` / `1.0` | Resource limits per session |
| `DBROWSER_DOH_TEMPLATE` | | DNS-over-HTTPS template, e.g. `https://dns.quad9.net/dns-query` |
| `DBROWSER_TAILSCALE_AUTHKEY` | | Ephemeral auth key for `tailscale` network/expose |
| `DBROWSER_CLOUDFLARE_TUNNEL_TOKEN` / `_HOSTNAME` | | Named tunnel (empty means a free quick tunnel) |
| `DOCKER_GID` | `0` | Docker socket group id (Linux) |

See [.env.example](.env.example) for the annotated list.

## 🚀 Deployment

```bash
docker compose --profile build build
docker compose up -d
curl -fsS http://localhost:8080/healthz          # {"status":"ok",...}
```

Remote access to the dashboard and MCP, without opening any ports:

```bash
docker compose --profile tailscale up -d    # https://dbrowser.<tailnet>.ts.net (needs TS_AUTHKEY)
docker compose --profile cloudflare up -d   # named tunnel (needs CLOUDFLARE_TUNNEL_TOKEN); add Cloudflare Access
```

Read [SECURITY.md](SECURITY.md) before exposing anything. The controller holds the Docker socket.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feat/amazing-feature`)
3. Commit using Conventional Commits (`git commit -m 'feat: add amazing feature'`)
4. Push to the branch (`git push origin feat/amazing-feature`)
5. Open a Pull Request

### Development Guidelines
- Ruff lint and format must be clean; shellcheck and hadolint must pass
- Write tests for new features (unit tests with `FakeRuntime`; e2e for anything touching the image)
- Never add persistence for session data (see PRD non-goals)
- Update documentation and CHANGELOG `[Unreleased]` for user-visible changes

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## 📈 Roadmap

### Phase 1: Core MVP (Current, v0.1)
- [x] Disposable Chromium sessions with DuckDuckGo and privacy policies
- [x] WireGuard / Tailscale egress, Cloudflare / Tailscale sharing
- [x] REST API, dashboard and MCP server with one browser per agent
- [x] CI with end-to-end tests on real Docker

### Phase 2: Hardening & Distribution (v0.2)
- [ ] Multi-arch images on GHCR, docker-socket-proxy, idle timeout, per-agent quotas
- [ ] More MCP tools (tabs, back/forward, wait-for, accessibility snapshot), bundled uBlock Origin Lite

### Phase 3: Platform (v0.3 to v1.0)
- [ ] Chromium sandbox with seccomp, download hand-off, audio and clipboard
- [ ] Metrics and tracing, OIDC login, alternative engines, Kubernetes runtime

See [ROADMAP.md](ROADMAP.md) and [ENHANCEMENT.md](ENHANCEMENT.md).

## 📄 License

This project is licensed under the MIT License. See [LICENSE.md](LICENSE.md) for details.

## 📦 Key libraries (maintained)

| Concern | Package | Notes |
|---------|---------|--------|
| HTTP API | `fastapi` >=0.115, `uvicorn` >=0.30 | REST, dashboard, ASGI auth middleware |
| MCP | `mcp` >=2.3,<3 | `MCPServer` + Streamable HTTP (stateless) |
| Browser automation | `playwright` >=1.48 | `connect_over_cdp`; no bundled browsers needed |
| Container runtime | `docker` >=7.1 | Behind the `Runtime` protocol, so it can be swapped |
| Config / validation | `pydantic` v2, `pydantic-settings` | Typed `DBROWSER_*` settings and request validation |
| Browser | Debian `chromium` | Tracks Debian security updates; rebuild regularly |

## 🙏 Acknowledgments

- [Chromium](https://www.chromium.org/) and its enterprise policy system
- [DuckDuckGo](https://duckduckgo.com/) for private search
- [noVNC](https://novnc.com/), [x11vnc](https://github.com/LibVNC/x11vnc) and Xvfb for the live view
- [WireGuard](https://www.wireguard.com/), [Tailscale](https://tailscale.com/) and [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) for private networking
- [Model Context Protocol](https://modelcontextprotocol.io/) and [Hermes Agent](https://github.com/NousResearch/hermes-agent) for agent integration
- [Playwright](https://playwright.dev/) for CDP automation
- Community feedback and contributions

## 📞 Support

- 🐛 Issues: [GitHub Issues](https://github.com/kyroskoh/disposable-browser/issues)
- 💬 Discussions: [GitHub Discussions](https://github.com/kyroskoh/disposable-browser/discussions)
- 🔒 Security: see [SECURITY.md](SECURITY.md) (private advisories, not public issues)

---

Made with ❤️ by [Kyros Koh](https://github.com/kyroskoh)
