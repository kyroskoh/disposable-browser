# Contributing to Disposable Browser

Thanks for helping. This project puts privacy and disposability first, so changes that persist
user data or weaken isolation are out of scope (see [PRD.md](PRD.md) non-goals).

## Setup

```bash
git clone https://github.com/kyroskoh/disposable-browser && cd disposable-browser
cd controller && python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Docker is needed for the browser image and end-to-end tests:

```bash
docker compose --profile build build && cp .env.example .env && docker compose up -d
```

## Layout

| Path | What lives there |
|---|---|
| `browser/` | Chromium image: `Dockerfile`, `entrypoint.sh` (networking + lifecycle), `policies/` |
| `controller/src/dbrowser/` | `sessions.py` (lifecycle core), `runtime.py` (Docker seam), `api.py` (REST + auth), `mcp_server.py` (MCP tools), `browser_ops.py` (Playwright) |
| `controller/tests/` | Unit tests with fakes; `integration/` runs against real Docker |
| `scripts/` | Standalone browse scripts and the smoke test |
| `examples/` | Hermes, MCP clients, Playwright |
| `docs/adr/` | Architecture decision records |

## Workflow

1. Branch from `main`: `feat/…`, `fix/…`, `docs/…`, `chore/…`.
2. Use Conventional Commits, for example `feat(mcp): add browser_back tool`. **Don't add AI co-author trailers.**
3. Write tests first for bug fixes. Business logic goes in `SessionManager` and is tested with `FakeRuntime`.
4. Before pushing, run:
   ```bash
   cd controller && ruff check . && ruff format --check . && pytest
   shellcheck ../browser/entrypoint.sh ../scripts/*.sh
   ```
5. Add a line under `[Unreleased]` in [CHANGELOG.md](CHANGELOG.md).
6. Open a PR. CI runs lint, unit tests, hadolint, the smoke test and the end-to-end tests, and all must pass.

## PR checklist

- [ ] Tests added or updated, and passing locally
- [ ] E2E is green in CI
- [ ] Docs updated (README, `.env.example`, MCP tool docs)
- [ ] CHANGELOG `[Unreleased]` updated
- [ ] No secrets, and no new persistent volumes for session data

## Reporting bugs and requesting features

- Bugs: open an issue with steps to reproduce, the output of `docker compose logs controller`, and the session container logs.
- Features: follow [ENHANCEMENT.md](ENHANCEMENT.md).
- Security issues: follow [SECURITY.md](SECURITY.md), not public issues.
