#!/usr/bin/env bash
# Smoke test the browser image on its own: start it, check noVNC + CDP, close
# Chromium over CDP and verify the container removed itself (--rm).
set -euo pipefail

IMAGE="${DBROWSER_BROWSER_IMAGE:-disposable-browser/browser:dev}"
NAME="dbrowser-smoke-$$"

docker run -d --rm --name "$NAME" --read-only --tmpfs /tmp:rw,nosuid,nodev,mode=1777 \
  --shm-size=1g -p 127.0.0.1::6080 -p 127.0.0.1::9223 -e VNC_PASSWORD=smoketst "$IMAGE" >/dev/null
# On failure, show the container's logs before removing it. Inline rather than a
# function: shellcheck versions disagree on whether trap-only functions are "unused".
trap '[ $? -eq 0 ] || { echo "--- container logs ($NAME) ---"; docker logs "$NAME" 2>&1 | tail -n 100; };
      docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT

viewer_port="$(docker port "$NAME" 6080/tcp | head -n1 | cut -d: -f2)"
cdp_port="$(docker port "$NAME" 9223/tcp | head -n1 | cut -d: -f2)"

for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${cdp_port}/json/version" >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS "http://127.0.0.1:${cdp_port}/json/version" | grep -q '"Browser"' || { echo "CDP not ready"; docker logs "$NAME"; exit 1; }
curl -fsS "http://127.0.0.1:${viewer_port}/vnc.html" | grep -qi novnc || { echo "noVNC not serving"; exit 1; }
echo "ok: CDP + noVNC up"

python3 - "$cdp_port" <<'PY'
import json, sys, time, urllib.request
from playwright.sync_api import sync_playwright
base = f"http://127.0.0.1:{sys.argv[1]}"

def targets():
    return json.load(urllib.request.urlopen(f"{base}/json/list", timeout=5))

with sync_playwright() as pw:
    b = pw.chromium.connect_over_cdp(base)
    pages = [p for p in b.contexts[0].pages if not p.url.startswith("chrome-extension://")]
    print("pages:", [p.url for p in b.contexts[0].pages])
    page = pages[0]
    page.wait_for_load_state()
    assert "duckduckgo.com" in page.url, page.url
    print("ok: start page", page.url)
    deadline = time.time() + 20
    while time.time() < deadline and not any("chrome-extension://" in t["url"] for t in targets()):
        time.sleep(1)
    ext = [t["url"] for t in targets() if "chrome-extension://" in t["url"]]
    assert ext, f"uBlock Origin Lite not loaded; targets: {[(t['type'], t['url']) for t in targets()]}"
    print("ok: adblock extension running", ext[0])
    try:
        b.new_browser_cdp_session().send("Browser.close")
    except Exception:
        pass
PY

for _ in $(seq 1 30); do
  if ! docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
    echo "ok: closing Chromium removed the container"
    exit 0
  fi
  sleep 1
done
echo "FAIL: container still exists after Chromium closed"; docker logs "$NAME"; exit 1
