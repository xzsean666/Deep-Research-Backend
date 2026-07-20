"""Turns a vless:// share link (OUTBOUND_PROXY_URL) into a local xray-core
SOCKS5 proxy. Stdlib-only by design — this runs inside a minimal image with
no access to the main app's dependencies (see docker/xray/Dockerfile).

Standalone script, not part of the `app` package: this container is a
separate deployable unit (docker-compose.yml's `xray` service), not
something the api/worker processes import.
"""

import json
import os
import sys
from urllib.parse import parse_qs, unquote, urlparse

SOCKS_PORT = 1080


def parse_vless_uri(uri: str) -> dict:
    if not uri.startswith("vless://"):
        raise ValueError(f"not a vless:// URI: {uri!r}")

    parsed = urlparse(uri)
    if not parsed.username:
        raise ValueError("vless URI is missing the uuid (user info before @)")
    if not parsed.hostname:
        raise ValueError("vless URI is missing a host")

    query = {key: values[0] for key, values in parse_qs(parsed.query).items()}

    return {
        "uuid": parsed.username,
        "address": parsed.hostname,
        "port": parsed.port or 443,
        "encryption": query.get("encryption", "none"),
        "flow": query.get("flow", ""),
        "security": query.get("security", "none"),
        "network": query.get("type", "tcp"),
        "sni": query.get("sni", parsed.hostname),
        "fingerprint": query.get("fp", "chrome"),
        "public_key": query.get("pbk", ""),
        "short_id": query.get("sid", ""),
        "spider_x": unquote(query.get("spx", "")) or "/",
        "ws_path": unquote(query.get("path", "/")),
        "ws_host": query.get("host", parsed.hostname),
        "grpc_service_name": query.get("serviceName", ""),
        "alpn": query.get("alpn", ""),
        "allow_insecure": query.get("allowInsecure", "0") in ("1", "true"),
    }


def build_xray_config(target: dict, socks_port: int) -> dict:
    stream_settings = {"network": target["network"], "security": target["security"]}

    if target["security"] == "tls":
        stream_settings["tlsSettings"] = {
            "serverName": target["sni"],
            "fingerprint": target["fingerprint"],
            "allowInsecure": target["allow_insecure"],
            **({"alpn": target["alpn"].split(",")} if target["alpn"] else {}),
        }
    elif target["security"] == "reality":
        stream_settings["realitySettings"] = {
            "serverName": target["sni"],
            "fingerprint": target["fingerprint"],
            "publicKey": target["public_key"],
            "shortId": target["short_id"],
            "spiderX": target["spider_x"],
        }

    if target["network"] == "ws":
        stream_settings["wsSettings"] = {
            "path": target["ws_path"],
            "headers": {"Host": target["ws_host"]} if target["ws_host"] else {},
        }
    elif target["network"] == "grpc":
        stream_settings["grpcSettings"] = {"serviceName": target["grpc_service_name"]}

    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "listen": "0.0.0.0",
                "port": socks_port,
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": False},
            }
        ],
        "outbounds": [
            {
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": target["address"],
                            "port": target["port"],
                            "users": [
                                {
                                    "id": target["uuid"],
                                    "encryption": target["encryption"] or "none",
                                    "flow": target["flow"],
                                }
                            ],
                        }
                    ]
                },
                "streamSettings": stream_settings,
            }
        ],
    }


def main() -> None:
    raw = os.environ.get("OUTBOUND_PROXY_URL", "")
    if not raw.startswith("vless://"):
        print(
            "OUTBOUND_PROXY_URL must be set to a vless:// link to run the xray "
            "service (this container has nothing to do otherwise) — see "
            ".env.example",
            file=sys.stderr,
        )
        sys.exit(1)

    target = parse_vless_uri(raw)
    config = build_xray_config(target, socks_port=SOCKS_PORT)

    config_path = "/tmp/xray_config.json"
    with open(config_path, "w") as f:
        json.dump(config, f)

    os.execvp("xray", ["xray", "run", "-c", config_path])


if __name__ == "__main__":
    main()
