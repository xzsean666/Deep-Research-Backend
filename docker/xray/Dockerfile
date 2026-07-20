# Turns OUTBOUND_PROXY_URL=vless://... into a local xray-core SOCKS5 proxy
# that api/worker/crawl4ai all reach at socks5://xray:1080 over the compose
# network — see docker-compose.yml's `xray` service (profile "proxy") and
# entrypoint.py in this directory for why this has to be its own service
# rather than something api/worker spawn themselves.

FROM python:3.12-alpine

# Pinned release + hardcoded SHA2-256 (from the release's own .dgst file at
# https://github.com/XTLS/Xray-core/releases/download/v26.6.27/Xray-linux-*.zip.dgst)
# rather than fetched at build time, so a compromised release asset can't
# silently swap the binary out from under a rebuild.
ARG XRAY_VERSION=v26.6.27
ARG TARGETARCH

RUN set -eux; \
    case "$TARGETARCH" in \
        amd64) asset="Xray-linux-64"; sha256="b3e5902d06d6282fe53cfa2fc426058b9aeaa429b2c812e20887cd47f26d08bf" ;; \
        arm64) asset="Xray-linux-arm64-v8a"; sha256="13a251379bea366c2cf10363ad71e75734193d401f26f518bf0c25e5c8f8c931" ;; \
        *) echo "unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    apk add --no-cache curl unzip; \
    curl -fsSL -o /tmp/xray.zip \
        "https://github.com/XTLS/Xray-core/releases/download/${XRAY_VERSION}/${asset}.zip"; \
    echo "${sha256}  /tmp/xray.zip" | sha256sum -c -; \
    unzip -p /tmp/xray.zip xray > /usr/local/bin/xray; \
    chmod +x /usr/local/bin/xray; \
    rm /tmp/xray.zip; \
    apk del curl unzip

COPY entrypoint.py /entrypoint.py

EXPOSE 1080

ENTRYPOINT ["python3", "/entrypoint.py"]
