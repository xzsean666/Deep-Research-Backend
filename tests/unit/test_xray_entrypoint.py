"""docker/xray/entrypoint.py is deliberately outside the `app` package (see
its own docstring) — loaded here via importlib rather than a normal import.
"""

import importlib.util
from pathlib import Path

from app.config import Settings
from app.services.proxy import get_crawl4ai_proxy_url, get_outbound_proxy_url

_ENTRYPOINT_PATH = Path(__file__).parents[2] / "docker" / "xray" / "entrypoint.py"
_spec = importlib.util.spec_from_file_location("xray_entrypoint", _ENTRYPOINT_PATH)
xray_entrypoint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(xray_entrypoint)


def _settings(**overrides) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://test:test@localhost:5432/test",
        searxng_url="http://searxng.test",
        crawl4ai_url="http://crawl4ai.test",
        crawl4ai_api_token="test-token",
        **overrides,
    )


def test_parses_plain_tcp_no_security():
    target = xray_entrypoint.parse_vless_uri("vless://11111111-1111-1111-1111-111111111111@example.com:443?encryption=none&type=tcp&security=none")

    assert target["uuid"] == "11111111-1111-1111-1111-111111111111"
    assert target["address"] == "example.com"
    assert target["port"] == 443
    assert target["network"] == "tcp"
    assert target["security"] == "none"


def test_parses_tcp_tls():
    target = xray_entrypoint.parse_vless_uri(
        "vless://uuid-a@proxy.example.com:8443?encryption=none&security=tls&type=tcp&sni=cdn.example.com&fp=chrome"
    )

    assert target["security"] == "tls"
    assert target["sni"] == "cdn.example.com"
    assert target["fingerprint"] == "chrome"

    config = xray_entrypoint.build_xray_config(target, socks_port=10808)
    outbound = config["outbounds"][0]
    assert outbound["streamSettings"]["tlsSettings"]["serverName"] == "cdn.example.com"
    assert config["inbounds"][0]["port"] == 10808


def test_parses_tcp_reality_with_vision_flow():
    target = xray_entrypoint.parse_vless_uri(
        "vless://uuid-b@1.2.3.4:443?encryption=none&security=reality&type=tcp"
        "&flow=xtls-rprx-vision&sni=www.microsoft.com&fp=chrome"
        "&pbk=abcDEF123&sid=deadbeef&spx=%2F"
    )

    assert target["security"] == "reality"
    assert target["flow"] == "xtls-rprx-vision"
    assert target["public_key"] == "abcDEF123"
    assert target["short_id"] == "deadbeef"

    config = xray_entrypoint.build_xray_config(target, socks_port=10808)
    outbound = config["outbounds"][0]
    reality = outbound["streamSettings"]["realitySettings"]
    assert reality["publicKey"] == "abcDEF123"
    assert reality["shortId"] == "deadbeef"
    assert outbound["settings"]["vnext"][0]["users"][0]["flow"] == "xtls-rprx-vision"


def test_parses_ws_tls():
    target = xray_entrypoint.parse_vless_uri(
        "vless://uuid-c@proxy.example.com:443?encryption=none&security=tls&type=ws"
        "&host=ws.example.com&path=%2Fapi%2Fws"
    )

    assert target["network"] == "ws"
    assert target["ws_host"] == "ws.example.com"
    assert target["ws_path"] == "/api/ws"

    config = xray_entrypoint.build_xray_config(target, socks_port=10808)
    ws_settings = config["outbounds"][0]["streamSettings"]["wsSettings"]
    assert ws_settings["path"] == "/api/ws"
    assert ws_settings["headers"]["Host"] == "ws.example.com"


def test_socks_inbound_has_no_auth_and_no_udp():
    target = xray_entrypoint.parse_vless_uri("vless://uuid-d@example.com:443?security=none&type=tcp")
    config = xray_entrypoint.build_xray_config(target, socks_port=10808)

    inbound = config["inbounds"][0]
    assert inbound["protocol"] == "socks"
    assert inbound["settings"]["auth"] == "noauth"
    assert inbound["settings"]["udp"] is False


def test_get_outbound_proxy_url_passthrough_for_http_and_socks5():
    assert get_outbound_proxy_url(_settings(outbound_proxy_url="")) is None
    assert (
        get_outbound_proxy_url(_settings(outbound_proxy_url="http://proxy:8080"))
        == "http://proxy:8080"
    )
    assert (
        get_outbound_proxy_url(_settings(outbound_proxy_url="socks5://proxy:1080"))
        == "socks5://proxy:1080"
    )


def test_get_outbound_proxy_url_resolves_vless_to_xray_service():
    settings = _settings(outbound_proxy_url="vless://uuid@host:443?security=tls&type=tcp")
    assert get_outbound_proxy_url(settings) == "socks5://xray:1080"


def test_get_crawl4ai_proxy_url_is_always_none():
    # Crawl4AI's own server refuses proxy_config from any network request,
    # for any value — forwarding one there always 400s, regardless of scheme.
    assert get_crawl4ai_proxy_url(_settings(outbound_proxy_url="")) is None
    assert get_crawl4ai_proxy_url(_settings(outbound_proxy_url="http://proxy:8080")) is None
    assert get_crawl4ai_proxy_url(_settings(outbound_proxy_url="socks5://proxy:1080")) is None
    assert (
        get_crawl4ai_proxy_url(_settings(outbound_proxy_url="vless://uuid@host:443?type=tcp"))
        is None
    )
