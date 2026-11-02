# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | ✅ |

## Reporting a vulnerability

Please report vulnerabilities privately through **GitHub Security Advisories** ("Report a vulnerability"
on the repository's Security tab), or by email to the maintainer. Don't open public issues for them.
We aim to acknowledge reports within 72 hours.

## Threat model (summary)

**Assets:** the user's browsing data and real IP, VPN and Tailscale credentials, the Docker host.

| Entry point | Threat | Mitigation |
|---|---|---|
| Controller HTTP (`/v1`, `/mcp/`) | Unauthorised session control | Bearer tokens (constant-time compare); bound to 127.0.0.1 by default; remote access only through a tailnet or Cloudflare Access |
| Agent tokens | One agent drives another's browser | The agent identity is taken from the token and the client header is overwritten; ownership is checked on every tool |
| Docker socket | Controller compromise means host root | Minimal API surface, input validation (strict id regex, typed requests), non-root read-only controller; socket proxy on the roadmap |
| Malicious web content | Escape from Chromium | `--no-sandbox` inside a container with all capabilities dropped (except setup caps), `no-new-privileges`, read-only rootfs, non-root uid 10001, memory/CPU/PID limits. Run untrusted browsing on a host you're willing to lose. |
| noVNC viewer | Session hijack | Per-session random password; ports on 127.0.0.1. Classic VNC auth uses only 8 characters, so **always put Cloudflare Access or a tailnet in front of shared viewers.** |
| Network egress | IP leak while on a VPN | WireGuard kill switch (iptables OUTPUT DROP except wg0 and the local subnet); WebRTC limited to proxied UDP; Tailscale traffic goes through a SOCKS5 proxy with remote DNS |
| Persistence | Data survives a session | No volumes; profile, policies and VPN config live only on tmpfs; the container is auto-removed; ephemeral Tailscale nodes are logged out on exit |
| Secrets | Leaked keys | WireGuard configs and auth keys are passed as env vars to session containers and are visible to anyone with Docker access (who is already root). `.env` and `wireguard/` are git-ignored. |

## Hardening checklist for operators

- Use a long random `DBROWSER_API_TOKEN` and per-agent tokens.
- Keep `DBROWSER_BIND` and `DBROWSER_PUBLISH_BIND` at `127.0.0.1`.
- Use **ephemeral, pre-approved** Tailscale auth keys with tags and ACLs.
- Put Cloudflare Access in front of any Cloudflare-exposed hostname.
- Rebuild images regularly to pick up Chromium security updates.
