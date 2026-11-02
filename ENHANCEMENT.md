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
| E-1 | Publish multi-arch images to GHCR, signed with cosign | High | S | done v0.2 |
| E-2 | docker-socket-proxy between the controller and Docker (least privilege) | High | S | done v0.2 |
| E-3 | Idle timeout (destroy after N minutes with no CDP or VNC activity) | High | M | done v0.2 |
| E-4 | Per-agent quotas (max sessions, max TTL, allowed networks) | Medium | M | done v0.2 |
| E-5 | Chromium namespace sandbox with a shipped seccomp profile (`CHROMIUM_SANDBOX=1`) | High | M | planned v0.3 |
| E-6 | Download hand-off: stream a file to the user or agent, then wipe it | Medium | M | planned v0.3 |
| E-7 | Opt-in encrypted "session snapshot" you carry yourself (never stored server-side) | Low | L | proposed |
| E-8 | Audio and clipboard in the viewer | Medium | M | planned v0.3 |
| E-9 | MCP tools: `browser_back`, `browser_tabs`, `browser_wait_for`, accessibility-tree snapshot | High | S | done v0.2 |
| E-10 | Prometheus metrics and an OpenTelemetry trace per session | Medium | S | proposed |
| E-11 | Built-in uBlock Origin Lite (MV3) extension | Medium | S | done v0.2 |
| E-12 | Choice of other engines (Firefox / Camoufox image) behind the same API | Medium | L | proposed |
| E-13 | Kubernetes runtime adapter (the `Runtime` seam already isolates Docker) | Low | L | proposed |
| E-14 | Per-session random timezone, locale and window size presets to reduce correlation | Medium | S | proposed |
| E-15 | OAuth / OIDC login for the dashboard | Medium | M | proposed |
| E-16 | DNS profiles: named, configurable ad-blocking / privacy resolvers (AdGuard DNS, Quad9, Mullvad, NextDNS, Control D, self-hosted Pi-hole / AdGuard Home), chosen per session | High | M | planned v0.3 |
| E-17 | Egress guard: block private, link-local and metadata ranges (RFC 1918, 169.254.0.0/16, the `dbrowser` network itself) from sessions by default | High | S | planned v0.3 |
| E-18 | Authenticated CDP: proxy CDP through the controller with a per-session token instead of an open host port | High | M | planned v0.3 |
| E-19 | Stronger viewer auth: a token-gated noVNC/websockify path through the controller, replacing 8-character VNC passwords | High | M | planned v0.3 |
| E-20 | Supply-chain hygiene: Trivy/Grype image scans in CI, Renovate/Dependabot for pinned versions (uBOL, socket proxy, sidecars, actions), weekly scheduled rebuilds for Chromium security fixes | High | S | planned v0.3 |
| E-21 | Secrets off the environment: pass WireGuard configs and Tailscale keys through a tmpfs file or stdin instead of env vars visible in `docker inspect` | Medium | M | planned v0.3 |
| E-22 | Generic upstream proxy egress (`network=proxy` with HTTP/SOCKS5) and a Tor mode | Medium | M | proposed |
| E-23 | Ref-based MCP targeting: element refs from the accessibility snapshot usable by click/type, plus `browser_pdf` and file upload | Medium | M | proposed |
| E-24 | Warm pool of pre-started sessions to hide the 2-5 s Chromium startup | Low | M | proposed |
| E-25 | API rate limiting and a privacy-preserving audit log (who created or destroyed what; never URLs or page content) | Medium | S | proposed |
| E-26 | Contract tests for the REST OpenAPI schema and MCP tool schemas, as groundwork for the v1.0 freeze | Medium | S | planned v1.0 |

## Details

### E-16: DNS profiles

**Problem.** v0.2 blocks ads in the page with uBlock Origin Lite. Network-level filtering stays unset unless you pass a single global `DBROWSER_DOH_TEMPLATE`. Users want a choice of filtering resolvers, including their own Pi-hole or AdGuard Home, per session or per agent.

**Proposal.**
- `DBROWSER_DNS_PROFILES` (JSON) maps names to resolvers, for example:
  `{"adguard": {"doh": "https://dns.adguard-dns.com/dns-query"}, "quad9": {"doh": "https://dns.quad9.net/dns-query"}, "mullvad-adblock": {"doh": "https://adblock.dns.mullvad.net/dns-query"}, "home-pihole": {"plain": ["192.168.1.53"]}}`.
  Ship a built-in set of well-known public profiles. Leave out any that need an account.
- Add a `dns_profile` request field and `browser_open` argument, plus a `DBROWSER_DEFAULT_DNS_PROFILE` setting. Quotas (E-4) gain an allowed `dns_profiles` list.
- `doh` profiles use the Chromium `DnsOverHttpsMode=secure` policy (already wired for `DOH_TEMPLATE`), so they work on every egress mode.
- `plain` profiles (a LAN Pi-hole or AdGuard Home) write `/etc/resolv.conf` in the session.
  - They make sense with `direct`, and with `wireguard` or `tailscale` when the resolver is reachable through the tunnel.
  - The WireGuard `DNS =` line and Tailscale's MagicDNS take precedence unless the profile says otherwise.
  - Also set `DnsOverHttpsMode=off` so Chromium doesn't upgrade around the filter.
- Optional Compose profile `adguard`: an AdGuard Home sidecar on the `dbrowser` network that sessions can use as a local filtering resolver.

**Privacy impact.** No persistence. The chosen resolver sees the session's lookups, so document which profiles log. Unfiltered `direct` mode keeps working.

**Interactions.** E-17 must allow the configured resolver's private IP (for example a LAN Pi-hole) while still blocking the rest of RFC 1918.

### Why E-17 to E-21 matter (gaps found in the v0.2 review)

- **E-17:** in `direct` mode a page (or an agent) can reach the host LAN, cloud metadata endpoints, and other containers on the `dbrowser` network, including the controller. Auth protects the controller, but SSRF into everything else is open.
- **E-18:** the CDP port gives full control of the browser without a password. It is bound to `127.0.0.1`, so any local process or user on the host can drive any session.
- **E-19:** classic VNC auth only uses 8 characters. Today the mitigation is "always put Access or a tailnet in front".
- **E-20:** the browser is only as current as its last build, and there is no automated signal when pinned components go stale or ship CVEs.
- **E-21:** anyone who can run `docker inspect` can read VPN private keys and auth keys. That's acceptable today because Docker access already means root, but it's avoidable.
