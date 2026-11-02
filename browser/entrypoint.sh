#!/usr/bin/env bash
# Disposable browser entrypoint.
#
# Lifecycle: configure egress (direct | wireguard | tailscale) -> start Xvfb,
# x11vnc, noVNC -> optionally expose the viewer (cloudflare | tailscale) ->
# run Chromium in the foreground. When Chromium exits (window closed, CDP
# Browser.close, crash, or IDLE_TIMEOUT seconds with no CDP/VNC client) the
# container exits, and with --rm / auto_remove the whole session, including its
# tmpfs profile, is gone.
set -euo pipefail

log() { printf '[dbrowser] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

NET_MODE="${NET_MODE:-direct}"
EXPOSE_MODE="${EXPOSE_MODE:-none}"
SCREEN_WIDTH="${SCREEN_WIDTH:-1440}"
SCREEN_HEIGHT="${SCREEN_HEIGHT:-900}"
START_URL="${START_URL:-https://duckduckgo.com/}"
ENABLE_CDP="${ENABLE_CDP:-1}"
KILL_SWITCH="${KILL_SWITCH:-1}"
ADBLOCK="${ADBLOCK:-1}"
IDLE_TIMEOUT="${IDLE_TIMEOUT:-0}"
UBOL_SRC=/opt/dbrowser/extensions/ubol
UBOL_DIR=/tmp/extensions/ubol
TS_SOCKS="127.0.0.1:1055"
TS_SOCKET="/tmp/tailscale/tailscaled.sock"
RUN_AS=(setpriv --reuid=10001 --regid=10001 --init-groups --)

CHROMIUM_EXTRA=()
CHILD_PIDS=()

cleanup() {
  # Remove the ephemeral tailnet node so nothing lingers in the admin console.
  if [[ -S "$TS_SOCKET" ]]; then
    tailscale --socket="$TS_SOCKET" logout >/dev/null 2>&1 || true
  fi
  for pid in "${CHILD_PIDS[@]:-}"; do
    if [[ -n "$pid" ]]; then kill "$pid" 2>/dev/null || true; fi
  done
}
trap cleanup EXIT
trap 'exit 0' TERM INT

bg() { "$@" & CHILD_PIDS+=("$!"); }

prepare_tmp() {
  mkdir -p /tmp/home /tmp/profile /tmp/policies/managed /tmp/tailscale /tmp/wg /tmp/extensions
  mkdir -m 1777 /tmp/.X11-unix
  chown 10001:10001 /tmp/home /tmp/profile
  chmod 0700 /tmp/home /tmp/profile /tmp/wg
  cp /opt/dbrowser/policies/managed.json /tmp/policies/managed/00-dbrowser.json
  if [[ -n "${DOH_TEMPLATE:-}" ]]; then
    printf '{"DnsOverHttpsMode":"secure","DnsOverHttpsTemplates":"%s"}\n' "$DOH_TEMPLATE" \
      > /tmp/policies/managed/10-doh.json
  fi
  printf '{"RestoreOnStartup":4,"RestoreOnStartupURLs":["%s"]}\n' "$START_URL" \
    > /tmp/policies/managed/20-start.json
  chmod -R a+rX /tmp/policies
  if [[ "$ADBLOCK" == "1" && -f "$UBOL_SRC/manifest.json" ]]; then
    # Chromium writes indexed declarativeNetRequest rulesets into an unpacked
    # extension's own _metadata/ directory, so it needs a writable per-session copy.
    cp -r "$UBOL_SRC" "$UBOL_DIR"
    chown -R 10001:10001 "$UBOL_DIR"
  fi
}

setup_wireguard() {
  local conf=/tmp/wg/wg0.conf dns
  if [[ -n "${WG_CONFIG_B64:-}" ]]; then
    printf '%s' "$WG_CONFIG_B64" | base64 -d > "$conf"
  elif [[ -f /etc/wireguard/wg0.conf ]]; then
    cp /etc/wireguard/wg0.conf "$conf"
  else
    die "NET_MODE=wireguard needs WG_CONFIG_B64 or /etc/wireguard/wg0.conf"
  fi
  chmod 0600 "$conf"

  # Docker owns /etc/resolv.conf, so apply DNS ourselves instead of resolvconf.
  dns="$(sed -nE 's/^[[:space:]]*DNS[[:space:]]*=[[:space:]]*(.*)$/\1/Ip' "$conf" | head -n1)"
  sed -i -E '/^[[:space:]]*DNS[[:space:]]*=/Id' "$conf"
  log "bringing up WireGuard"
  wg-quick up "$conf"
  if [[ -n "$dns" ]]; then
    : > /etc/resolv.conf
    for d in ${dns//,/ }; do
      if [[ "$d" =~ ^[0-9a-fA-F:.]+$ ]]; then echo "nameserver $d" >> /etc/resolv.conf; fi
    done
  fi

  if [[ "$KILL_SWITCH" == "1" ]]; then
    local subnet port
    subnet="$(ip -4 -o addr show dev eth0 | awk '{print $4}' | head -n1)"
    port="$(wg show wg0 listen-port)"
    log "enabling kill switch (only wg0 and local subnet $subnet)"
    iptables -P OUTPUT DROP
    iptables -A OUTPUT -o lo -j ACCEPT
    iptables -A OUTPUT -o wg0 -j ACCEPT
    iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
    if [[ -n "$subnet" ]]; then iptables -A OUTPUT -o eth0 -d "$subnet" -j ACCEPT; fi
    # WireGuard's own encrypted UDP leaves via eth0 from its listen port.
    iptables -A OUTPUT -o eth0 -p udp --sport "$port" -j ACCEPT
    if command -v ip6tables >/dev/null; then
      ip6tables -P OUTPUT DROP 2>/dev/null || true
      ip6tables -A OUTPUT -o lo -j ACCEPT 2>/dev/null || true
      ip6tables -A OUTPUT -o wg0 -j ACCEPT 2>/dev/null || true
    fi
  fi
}

start_tailscale() {
  [[ -n "${TS_AUTHKEY:-}" ]] || die "Tailscale needs TS_AUTHKEY (use an ephemeral key)"
  log "starting tailscaled (userspace, in-memory state)"
  bg tailscaled --tun=userspace-networking --socks5-server="$TS_SOCKS" \
    --socket="$TS_SOCKET" --statedir=/tmp/tailscale --state=mem:
  for _ in $(seq 1 50); do [[ -S "$TS_SOCKET" ]] && break; sleep 0.2; done
  local args=(--authkey="$TS_AUTHKEY" --hostname="${TS_HOSTNAME:-dbrowser-$(hostname)}" --accept-dns=false)
  if [[ -n "${TS_EXIT_NODE:-}" ]]; then
    args+=(--exit-node="$TS_EXIT_NODE" --exit-node-allow-lan-access=false)
  fi
  tailscale --socket="$TS_SOCKET" up "${args[@]}"
}

start_display() {
  local pw="${VNC_PASSWORD:-}"
  if [[ -z "$pw" ]]; then
    # Classic VNC auth only uses the first 8 characters.
    pw="$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
    log "VNC password: $pw"
  fi
  "${RUN_AS[@]}" x11vnc -storepasswd "$pw" /tmp/home/.vncpass >/dev/null 2>&1
  bg "${RUN_AS[@]}" Xvfb "$DISPLAY" -screen 0 "${SCREEN_WIDTH}x${SCREEN_HEIGHT}x24" -nolisten tcp -ac
  for _ in $(seq 1 50); do [[ -e "/tmp/.X11-unix/X${DISPLAY#:}" ]] && break; sleep 0.1; done
  bg "${RUN_AS[@]}" x11vnc -display "$DISPLAY" -rfbauth /tmp/home/.vncpass -rfbport 5900 \
    -localhost -forever -shared -quiet -noxdamage
  bg "${RUN_AS[@]}" websockify --web /usr/share/novnc 6080 127.0.0.1:5900
}

expose_viewer() {
  case "$EXPOSE_MODE" in
    none) ;;
    cloudflare)
      if [[ -n "${CF_TUNNEL_TOKEN:-}" ]]; then
        log "starting Cloudflare named tunnel"
        bg "${RUN_AS[@]}" cloudflared tunnel --no-autoupdate run --token "$CF_TUNNEL_TOKEN"
        if [[ -n "${CF_TUNNEL_HOSTNAME:-}" ]]; then
          echo "DBROWSER_PUBLIC_URL=https://${CF_TUNNEL_HOSTNAME}/vnc.html"
        fi
      else
        log "starting Cloudflare quick tunnel"
        "${RUN_AS[@]}" cloudflared tunnel --no-autoupdate --url http://127.0.0.1:6080 \
          > /tmp/home/cloudflared.log 2>&1 &
        CHILD_PIDS+=("$!")
        (
          for _ in $(seq 1 120); do
            url="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/home/cloudflared.log | head -n1 || true)"
            if [[ -n "$url" ]]; then echo "DBROWSER_PUBLIC_URL=${url}/vnc.html"; exit 0; fi
            sleep 1
          done
          log "cloudflare quick tunnel URL not found"
        ) &
      fi
      ;;
    tailscale)
      if [[ ! -S "$TS_SOCKET" ]]; then start_tailscale; fi
      tailscale --socket="$TS_SOCKET" serve --bg http://127.0.0.1:6080 >/dev/null
      local name
      name="$(tailscale --socket="$TS_SOCKET" status --json \
        | sed -nE 's/.*"DNSName": *"([^"]+)\.".*/\1/p' | head -n1)"
      if [[ -n "$name" ]]; then echo "DBROWSER_PUBLIC_URL=https://${name}/vnc.html"; fi
      ;;
    *) die "unknown EXPOSE_MODE: $EXPOSE_MODE" ;;
  esac
}

# Close Chromium once no client has been connected for IDLE_TIMEOUT seconds.
# Activity means an established TCP connection to Chromium's CDP port (every agent
# and Playwright call, through socat) or to x11vnc (an open noVNC viewer). The image
# healthcheck only touches the noVNC web server on 6080, so it doesn't count.
idle_watchdog() {
  local chrome="$1" limit="$2" last now
  last="$(date +%s)"
  while kill -0 "$chrome" 2>/dev/null; do
    sleep 5
    now="$(date +%s)"
    # Capture, don't pipe into grep -q: with pipefail an early grep exit can SIGPIPE ss.
    if [[ -n "$(ss -Htn state established '( sport = :9222 or sport = :5900 )')" ]]; then
      last="$now"
    elif (( now - last >= limit )); then
      log "idle for ${limit}s with no CDP or VNC client; closing Chromium"
      kill -TERM "$chrome" 2>/dev/null || true
      return 0
    fi
  done
}

run_chromium() {
  # shellcheck disable=SC2054  # commas belong to flag values, not separators
  local flags=(
    --user-data-dir=/tmp/profile
    --no-first-run --no-default-browser-check --disable-sync
    --disable-background-networking --disable-component-update
    --disable-breakpad --disable-crash-reporter
    --disable-features=Translate,MediaRouter,OptimizationHints
    --password-store=basic
    --window-position=0,0 --window-size="${SCREEN_WIDTH},${SCREEN_HEIGHT}" --start-maximized
  )
  # The container is the sandbox boundary; Chromium's own namespace sandbox
  # needs privileges Docker's default seccomp profile withholds.
  if [[ "${CHROMIUM_SANDBOX:-0}" != "1" ]]; then flags+=(--no-sandbox --test-type); fi
  if [[ "$ENABLE_CDP" == "1" ]]; then
    flags+=(--remote-debugging-port=9222 --remote-allow-origins=*)
    # Chromium only listens on loopback; expose CDP to the container network.
    bg socat TCP-LISTEN:9223,fork,reuseaddr,bind=0.0.0.0 TCP:127.0.0.1:9222
  fi
  if [[ "$ADBLOCK" == "1" ]]; then
    if [[ -f "$UBOL_DIR/manifest.json" ]]; then
      flags+=(--load-extension="$UBOL_DIR")
    else
      log "ADBLOCK=1 but $UBOL_DIR is missing; continuing without it"
    fi
  fi
  flags+=("${CHROMIUM_EXTRA[@]}")
  log "starting Chromium (net=$NET_MODE expose=$EXPOSE_MODE)"
  # shellcheck disable=SC2086
  "${RUN_AS[@]}" env HOME=/tmp/home chromium "${flags[@]}" ${CHROMIUM_FLAGS:-} "$START_URL" &
  local chrome=$!
  if [[ "$IDLE_TIMEOUT" =~ ^[0-9]+$ ]] && (( IDLE_TIMEOUT > 0 )); then
    log "idle timeout: ${IDLE_TIMEOUT}s"
    bg idle_watchdog "$chrome" "$IDLE_TIMEOUT"
  fi
  echo "DBROWSER_READY=1"
  wait "$chrome" || true
  log "Chromium exited; destroying session"
}

main() {
  prepare_tmp
  case "$NET_MODE" in
    direct) ;;
    wireguard) setup_wireguard ;;
    tailscale)
      start_tailscale
      CHROMIUM_EXTRA+=(--proxy-server="socks5://$TS_SOCKS")
      ;;
    *) die "unknown NET_MODE: $NET_MODE" ;;
  esac
  start_display
  expose_viewer
  run_chromium
}

main "$@"
