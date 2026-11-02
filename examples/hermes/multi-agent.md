# One browser per Hermes agent (e.g. a Grok-powered bot fleet)

1. Mint one token per agent and register them with the controller:

   ```bash
   # .env
   DBROWSER_AGENT_TOKENS=grok-bot:$(openssl rand -hex 24),research-bot:$(openssl rand -hex 24)
   docker compose up -d
   ```

2. In each agent's Hermes config (see `config.yaml` here) set `DBROWSER_AGENT_TOKEN`
   to that agent's token. The bot can run on any model (Grok via xAI/OpenRouter,
   Hermes, Claude...) because the browser is reached over MCP.

3. What each agent gets:
   - `browser_navigate("query or url")` auto-creates the agent's own Chromium on first use.
   - `browser_snapshot`, `browser_accessibility_snapshot`, `browser_click`, `browser_type`,
     `browser_wait_for`, `browser_back` / `browser_forward`, `browser_tabs`, `browser_screenshot`, `browser_evaluate`.
   - `browser_open(fresh=true)` gives a brand-new identity (new cookies, new fingerprint state).
   - `browser_open(network="wireguard", wireguard_profile="mullvad-sg")` routes that agent via a VPN.
   - `browser_open(expose="cloudflare")` returns a `public_url` so a human can watch or take over.
   - `browser_close()` destroys everything. Sessions also expire after their TTL, or after
     `idle_timeout_seconds` with no activity.
   - Limit what each bot may do with `DBROWSER_AGENT_QUOTAS`, for example
     `{"grok-bot": {"networks": ["wireguard"], "expose": ["none"], "max_ttl_seconds": 900}}`.

4. Isolation guarantees: the agent identity comes from the token (the controller overwrites
   any `X-Dbrowser-Agent` header), `browser_list` only shows the caller's sessions, and
   acting on another agent's `session_id` is rejected.

Suggested system-prompt line for the bot:

> You have a private, disposable web browser via the `disposable_browser` MCP tools.
> Use `browser_navigate` for searches (DuckDuckGo) or URLs, read pages with `browser_snapshot`,
> and call `browser_close` when the task is done.
