# Disposable Chromium: Xvfb + noVNC viewer, CDP for agents, optional WireGuard /
# Tailscale egress and Cloudflare / Tailscale exposure. Everything mutable lives
# on a tmpfs at /tmp, so removing the container removes the session.
FROM debian:bookworm-slim

ARG DEBIAN_FRONTEND=noninteractive
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# hadolint ignore=DL3008
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg \
 && install -d -m 0755 /usr/share/keyrings \
 && curl -fsSL https://pkgs.tailscale.com/stable/debian/bookworm.noarmor.gpg \
      -o /usr/share/keyrings/tailscale-archive-keyring.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/tailscale-archive-keyring.gpg] https://pkgs.tailscale.com/stable/debian bookworm main" \
      > /etc/apt/sources.list.d/tailscale.list \
 && curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
      -o /usr/share/keyrings/cloudflare-main.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared bookworm main" \
      > /etc/apt/sources.list.d/cloudflared.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      chromium \
      xvfb x11vnc novnc websockify \
      socat tini procps \
      fonts-noto-core fonts-noto-cjk fonts-noto-color-emoji \
      wireguard-tools iproute2 iptables \
      tailscale cloudflared \
 && apt-get purge -y gnupg \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

# Unprivileged user that runs X, VNC and Chromium. The entrypoint starts as root
# only to configure networking, then drops to this user.
RUN groupadd --gid 10001 browser \
 && useradd --uid 10001 --gid 10001 --home-dir /tmp/home --no-create-home --shell /usr/sbin/nologin browser \
 # Chromium reads policies from here; point it at tmpfs so the entrypoint can add
 # runtime policies (DoH, start URL) even with a read-only root filesystem.
 && mkdir -p /etc/chromium/policies \
 && ln -s /tmp/policies/managed /etc/chromium/policies/managed \
 && ln -sf /usr/share/novnc/vnc.html /usr/share/novnc/index.html

COPY policies/managed.json /opt/dbrowser/policies/managed.json
COPY entrypoint.sh /opt/dbrowser/entrypoint.sh
RUN chmod 0755 /opt/dbrowser/entrypoint.sh

ENV DISPLAY=:99 \
    SCREEN_WIDTH=1440 \
    SCREEN_HEIGHT=900 \
    START_URL=https://duckduckgo.com/ \
    NET_MODE=direct \
    EXPOSE_MODE=none \
    ENABLE_CDP=1

# 6080 = noVNC web viewer, 9223 = Chrome DevTools Protocol (agents)
EXPOSE 6080 9223

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:6080/vnc.html >/dev/null || exit 1

# The entrypoint needs root briefly (wg-quick, iptables, tailscaled) and drops
# privileges with setpriv before starting any GUI process.
# hadolint ignore=DL3002
USER root
ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/opt/dbrowser/entrypoint.sh"]
