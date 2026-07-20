#!/bin/bash
# Transparently routes this container's outbound TCP through the `xray`
# compose service's SOCKS5 proxy (see docker-compose.cn.yml / app/services/
# proxy/__init__.py), without crawl4ai's own code ever knowing a proxy
# exists. This exists because crawl4ai's own hardened server deliberately
# refuses proxy_config from any network request (see
# UNTRUSTED_FORBIDDEN_FIELDS in vendor/crawl4ai/crawl4ai/async_configs.py —
# a real SSRF/secret-exfiltration guard, not a bug) — so the browser's
# outbound traffic can only be proxied below the application, at the OS
# network layer. Setting HTTP_PROXY/HTTPS_PROXY env vars instead was tried
# and rejected: crawl4ai's own internal httpx/requests calls pick those up
# too and broke (this image doesn't have socks-capable HTTP client deps
# installed), whereas a kernel-level redirect is invisible to the app.
#
# Runs as root (see Dockerfile.cn's `USER root` before ENTRYPOINT); drops to
# appuser via gosu at the end to run the original entrypoint unchanged.
#
# Known limitation: redsocks only redirects TCP. DNS (UDP) resolution stays
# direct — fine for this deployment (verified: direct TCP connect fails,
# DNS resolution does not), but wouldn't help if DNS itself were blocked.
set -euo pipefail

XRAY_HOST="${EGRESS_PROXY_HOST:-xray}"
XRAY_PORT="${EGRESS_PROXY_PORT:-1080}"
REDSOCKS_PORT=12345

XRAY_IP=""
for _ in $(seq 1 20); do
    XRAY_IP="$(getent hosts "$XRAY_HOST" 2>/dev/null | awk '{print $1}' | head -n1 || true)"
    [ -n "$XRAY_IP" ] && break
    sleep 0.5
done

if [ -z "$XRAY_IP" ]; then
    echo "docker-entrypoint-proxy: could not resolve $XRAY_HOST after 10s — proceeding with direct egress (no vless proxy configured, or the xray service/profile isn't running)" >&2
else
    cat > /etc/redsocks.conf <<EOF
base {
    log_debug = off;
    log_info = on;
    log = stderr;
    daemon = off;
    redirector = iptables;
}
redsocks {
    local_ip = 127.0.0.1;
    local_port = ${REDSOCKS_PORT};
    ip = ${XRAY_IP};
    port = ${XRAY_PORT};
    type = socks5;
}
EOF

    redsocks -c /etc/redsocks.conf -p /var/run/redsocks.pid &

    for _ in $(seq 1 20); do
        if (exec 3<>"/dev/tcp/127.0.0.1/${REDSOCKS_PORT}") 2>/dev/null; then
            exec 3>&- 3<&-
            break
        fi
        sleep 0.25
    done

    iptables -t nat -N REDSOCKS 2>/dev/null || iptables -t nat -F REDSOCKS
    iptables -t nat -A REDSOCKS -d 127.0.0.0/8 -j RETURN
    iptables -t nat -A REDSOCKS -d 10.0.0.0/8 -j RETURN
    iptables -t nat -A REDSOCKS -d 172.16.0.0/12 -j RETURN
    iptables -t nat -A REDSOCKS -d 192.168.0.0/16 -j RETURN
    iptables -t nat -A REDSOCKS -d 169.254.0.0/16 -j RETURN
    iptables -t nat -A REDSOCKS -d "${XRAY_IP}" -j RETURN
    iptables -t nat -A REDSOCKS -p tcp -j REDIRECT --to-ports "${REDSOCKS_PORT}"
    iptables -t nat -A OUTPUT -p tcp -j REDSOCKS

    echo "docker-entrypoint-proxy: outbound TCP transparently routed via ${XRAY_HOST}(${XRAY_IP}):${XRAY_PORT}"
fi

# Reopening /dev/stdout by path after a root->appuser setuid fails with
# EACCES — a real Linux kernel restriction: a pipe's /proc/$PID/fd entry
# can only be reopened via path by the uid that originally owned it (root,
# in this container's case, since the runtime sets up stdio before this
# script runs); `ls` shows it as appuser-owned, but only root can actually
# reopen it (see moby/moby#31243). supervisord's own stdout/stderr are
# fine (inherited via fork/exec, not reopened) — the break is specifically
# supervisord's *children* (redis, gunicorn), whose stdout_logfile config
# tries to open("/dev/stdout") fresh as appuser. Fix: point those at real
# files instead (see the supervisord.conf override in Dockerfile.cn's
# proxy stage — a regular fs path has no such restriction), and forward
# them back to the container's actual stdout/stderr here, while still
# root, so `docker logs` keeps showing everything.
mkdir -p /var/log/crawl4ai-proxy
touch /var/log/crawl4ai-proxy/redis-stdout.log /var/log/crawl4ai-proxy/redis-stderr.log \
      /var/log/crawl4ai-proxy/gunicorn-stdout.log /var/log/crawl4ai-proxy/gunicorn-stderr.log
chown -R appuser:appuser /var/log/crawl4ai-proxy

tail -F -n0 /var/log/crawl4ai-proxy/redis-stdout.log /var/log/crawl4ai-proxy/gunicorn-stdout.log &
tail -F -n0 /var/log/crawl4ai-proxy/redis-stderr.log /var/log/crawl4ai-proxy/gunicorn-stderr.log >&2 &

exec gosu appuser "$@"
