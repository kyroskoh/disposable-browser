#!/usr/bin/env bash
# One disposable browser for a human, no controller needed.
# Usage: scripts/browse.sh [--wg path/to/wg0.conf]
# Close the Chromium window (or Ctrl+C) and the whole session is deleted.
set -euo pipefail

IMAGE="${DBROWSER_BROWSER_IMAGE:-disposable-browser/browser:dev}"
PORT="${PORT:-6080}"
PW="$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
# shellcheck disable=SC2054  # commas belong to --tmpfs options
args=(--rm -it --read-only --tmpfs /tmp:rw,nosuid,nodev,mode=1777 --shm-size=1g
      -p "127.0.0.1:${PORT}:6080" -e VNC_PASSWORD="$PW" -e ENABLE_CDP=0)

if [[ "${1:-}" == "--wg" ]]; then
  conf="${2:?usage: --wg path/to/wg0.conf}"
  args+=(--cap-add NET_ADMIN --cap-add NET_RAW
         --sysctl net.ipv4.conf.all.src_valid_mark=1 --sysctl net.ipv6.conf.all.disable_ipv6=0
         -e NET_MODE=wireguard -v "$(cd "$(dirname "$conf")" && pwd)/$(basename "$conf"):/etc/wireguard/wg0.conf:ro")
fi

echo "Open: http://127.0.0.1:${PORT}/vnc.html?autoconnect=1&resize=remote&password=${PW}"
exec docker run "${args[@]}" "$IMAGE"
