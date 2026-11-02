# Connecting MCP clients

Endpoint: `http://<controller>:8080/mcp/` (Streamable HTTP; note the trailing slash),
header `Authorization: Bearer <admin or agent token>`.

## Claude Code

```bash
claude mcp add --transport http disposable-browser http://localhost:8080/mcp/ \
  --header "Authorization: Bearer $DBROWSER_AGENT_TOKEN"
```

## Generic JSON config (Claude Desktop, Cursor, Windsurf, ...)

```json
{
  "mcpServers": {
    "disposable-browser": {
      "url": "http://localhost:8080/mcp/",
      "headers": { "Authorization": "Bearer <token>" }
    }
  }
}
```

## stdio (no controller container, talks to local Docker directly)

```json
{
  "mcpServers": {
    "disposable-browser": {
      "command": "dbrowser-mcp",
      "env": { "DBROWSER_BROWSER_IMAGE": "disposable-browser/browser:dev" }
    }
  }
}
```

Install with `pip install ./controller`. stdio mode uses the host-published CDP port.

## Tools

| Tool | Purpose |
|---|---|
| `browser_open` | Open/return your browser; options: `network`, `wireguard_profile`, `tailscale_exit_node`, `expose`, `ttl_seconds`, `start_url`, `fresh` |
| `browser_navigate` | Go to a URL, or search DuckDuckGo for plain text |
| `browser_snapshot` | Page text + links (LLM-friendly) |
| `browser_screenshot` | PNG image |
| `browser_click` / `browser_type` | Interact using CSS / Playwright selectors |
| `browser_evaluate` | Run a JS expression in the page |
| `browser_list` | Your live sessions |
| `browser_close` | Destroy the session and all its data |
