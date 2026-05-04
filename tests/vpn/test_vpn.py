import base64
import json
import pytest
import yaml

from keon.vpn import v2ray_to_clash


def _make_vmess_link(payload: dict) -> str:
    """根据 dict 构造 vmess:// 链接，方便测试用例复用。"""
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    b64 = base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")
    return "vmess://" + b64


# ── 测试用 payload ─────────────────────────────────────────────────────────────

BASE_PAYLOAD = {
    "ps": "test-node",
    "add": "1.2.3.4",
    "port": "443",
    "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "aid": "0",
    "net": "tcp",
    "tls": "",
    "host": "",
    "path": "",
}

WS_TLS_PAYLOAD = {
    **BASE_PAYLOAD,
    "ps": "ws-tls-node",
    "net": "ws",
    "tls": "tls",
    "host": "example.com",
    "path": "/ws",
}


# ── strip=False：多行 YAML ─────────────────────────────────────────────────────

def test_multiline_top_level_keys():
    cfg = yaml.safe_load(v2ray_to_clash(_make_vmess_link(BASE_PAYLOAD), strip=False))
    for key in ("mixed-port", "allow-lan", "mode", "proxies", "proxy-groups", "rules"):
        assert key in cfg


def test_multiline_proxy_basic_fields():
    cfg = yaml.safe_load(v2ray_to_clash(_make_vmess_link(BASE_PAYLOAD), strip=False))
    proxy = cfg["proxies"][0]
    assert proxy["name"] == "test-node"
    assert proxy["type"] == "vmess"
    assert proxy["server"] == "1.2.3.4"
    assert proxy["port"] == 443
    assert proxy["uuid"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert proxy["alterId"] == 0
    assert proxy["cipher"] == "auto"
    assert proxy["udp"] is True


def test_multiline_proxy_group_references_node():
    cfg = yaml.safe_load(v2ray_to_clash(_make_vmess_link(BASE_PAYLOAD), strip=False))
    proxies = cfg["proxy-groups"][0]["proxies"]
    assert "test-node" in proxies
    assert "DIRECT" in proxies


def test_multiline_rules():
    cfg = yaml.safe_load(v2ray_to_clash(_make_vmess_link(BASE_PAYLOAD), strip=False))
    assert "MATCH,PROXY" in cfg["rules"]


def test_multiline_no_tls_fields_when_disabled():
    cfg = yaml.safe_load(v2ray_to_clash(_make_vmess_link(BASE_PAYLOAD), strip=False))
    proxy = cfg["proxies"][0]
    assert "tls" not in proxy
    assert "servername" not in proxy


def test_multiline_ws_tls_fields():
    cfg = yaml.safe_load(v2ray_to_clash(_make_vmess_link(WS_TLS_PAYLOAD), strip=False))
    proxy = cfg["proxies"][0]
    assert proxy["tls"] is True
    assert proxy["servername"] == "example.com"
    assert proxy["network"] == "ws"
    assert proxy["ws-opts"]["path"] == "/ws"
    assert proxy["ws-opts"]["headers"]["Host"] == "example.com"


def test_multiline_default_node_name():
    payload = {**BASE_PAYLOAD, "ps": ""}
    cfg = yaml.safe_load(v2ray_to_clash(_make_vmess_link(payload), strip=False))
    assert cfg["proxies"][0]["name"] == "vmess-node"


def test_multiline_port_is_int():
    cfg = yaml.safe_load(v2ray_to_clash(_make_vmess_link(BASE_PAYLOAD), strip=False))
    assert isinstance(cfg["proxies"][0]["port"], int)


# ── strip=True：单行 YAML ──────────────────────────────────────────────────────

def test_singleline_starts_with_dash():
    output = v2ray_to_clash(_make_vmess_link(BASE_PAYLOAD), strip=True)
    assert output.startswith("- ")


def test_singleline_is_one_line():
    output = v2ray_to_clash(_make_vmess_link(BASE_PAYLOAD), strip=True)
    assert "\n" not in output


def test_singleline_roundtrip_basic():
    output = v2ray_to_clash(_make_vmess_link(BASE_PAYLOAD), strip=True)
    result = yaml.safe_load(output)
    assert isinstance(result, list)
    assert result[0]["proxies"][0]["name"] == "test-node"


def test_singleline_roundtrip_ws_tls():
    output = v2ray_to_clash(_make_vmess_link(WS_TLS_PAYLOAD), strip=True)
    proxy = yaml.safe_load(output)[0]["proxies"][0]
    assert proxy["tls"] is True
    assert proxy["network"] == "ws"


# ── 非法输入 ───────────────────────────────────────────────────────────────────

def test_invalid_prefix_raises():
    with pytest.raises(ValueError):
        v2ray_to_clash("ss://somelink", strip=False)


def test_invalid_base64_raises():
    with pytest.raises(Exception):
        v2ray_to_clash("vmess://!!!not_base64!!!", strip=False)
