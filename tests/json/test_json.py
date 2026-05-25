import pytest

from keon.json import parse


# ── 基础功能测试 ───────────────────────────────────────────────────────────────

def test_simple_unquoted_keys():
    """测试简单的未加引号的键"""
    text = "{ name: 'test', age: 25 }"
    result = parse(text)
    assert result["name"] == "test"
    assert result["age"] == 25


def test_unquoted_string_values():
    """测试未加引号的字符串值"""
    text = "{ type: vless, protocol: vmess }"
    result = parse(text)
    assert result["type"] == "vless"
    assert result["protocol"] == "vmess"


def test_boolean_values():
    """测试布尔值"""
    text = "{ udp: true, tls: false }"
    result = parse(text)
    assert result["udp"] is True
    assert result["tls"] is False


def test_numeric_values():
    """测试数字值"""
    text = "{ port: 443, timeout: 30, ratio: 0.01 }"
    result = parse(text)
    assert result["port"] == 443
    assert result["timeout"] == 30
    assert result["ratio"] == 0.01


def test_null_value():
    """测试 null 值"""
    text = "{ value: null }"
    result = parse(text)
    assert result["value"] is None


# ── Unicode 和 Emoji 测试 ──────────────────────────────────────────────────────

def test_emoji_in_values():
    """测试值中包含 emoji"""
    text = "{ name: '🇺🇸美国01' }"
    result = parse(text)
    assert result["name"] == "🇺🇸美国01"


def test_chinese_characters():
    """测试中文字符"""
    text = "{ name: '美国服务器', location: '洛杉矶' }"
    result = parse(text)
    assert result["name"] == "美国服务器"
    assert result["location"] == "洛杉矶"


def test_mixed_unicode():
    """测试混合 Unicode 字符"""
    text = "{ name: '🇺🇸节点01 | 示例配置' }"
    result = parse(text)
    assert result["name"] == "🇺🇸节点01 | 示例配置"


# ── 嵌套对象测试 ──────────────────────────────────────────────────────────────

def test_nested_object():
    """测试嵌套对象"""
    text = "{ server: { host: 'example.com', port: 443 } }"
    result = parse(text)
    assert result["server"]["host"] == "example.com"
    assert result["server"]["port"] == 443


def test_deeply_nested_object():
    """测试深层嵌套对象"""
    text = "{ ws-opts: { path: '/pq/us1', headers: { Host: 'example.com' } } }"
    result = parse(text)
    assert result["ws-opts"]["path"] == "/pq/us1"
    assert result["ws-opts"]["headers"]["Host"] == "example.com"


# ── 复杂真实场景测试 ──────────────────────────────────────────────────────────

def test_vless_config_example():
    """测试真实的 VLESS 配置示例"""
    text = """{ 
        name: '🇺🇸节点01 | 示例配置', 
        type: vless, 
        server: example-server.example.com, 
        port: 443, 
        uuid: 12345678-abcd-1234-abcd-123456789abc, 
        udp: true, 
        tls: true, 
        skip-cert-verify: false, 
        client-fingerprint: chrome, 
        servername: node1.example.com, 
        network: ws, 
        ws-opts: { 
            path: /ws/path, 
            headers: { 
                Host: node1.example.com 
            } 
        } 
    }"""
    
    result = parse(text)
    
    assert result["name"] == "🇺🇸节点01 | 示例配置"
    assert result["type"] == "vless"
    assert result["server"] == "example-server.example.com"
    assert result["port"] == 443
    assert result["uuid"] == "12345678-abcd-1234-abcd-123456789abc"
    assert result["udp"] is True
    assert result["tls"] is True
    assert result["skip-cert-verify"] is False
    assert result["client-fingerprint"] == "chrome"
    assert result["servername"] == "node1.example.com"
    assert result["network"] == "ws"
    assert result["ws-opts"]["path"] == "/ws/path"
    assert result["ws-opts"]["headers"]["Host"] == "node1.example.com"


def test_vmess_config_example():
    """测试 VMess 配置示例"""
    text = """{
        name: '香港节点',
        type: vmess,
        server: hk.example.com,
        port: 8443,
        uuid: 12345678-1234-1234-1234-123456789abc,
        alterId: 0,
        cipher: auto,
        udp: true,
        tls: true,
        network: ws,
        ws-opts: { path: '/v2ray' }
    }"""
    
    result = parse(text)
    
    assert result["name"] == "香港节点"
    assert result["type"] == "vmess"
    assert result["server"] == "hk.example.com"
    assert result["port"] == 8443
    assert result["uuid"] == "12345678-1234-1234-1234-123456789abc"
    assert result["alterId"] == 0
    assert result["cipher"] == "auto"
    assert result["udp"] is True
    assert result["tls"] is True
    assert result["network"] == "ws"
    assert result["ws-opts"]["path"] == "/v2ray"


# ── 带连字符的键测试 ──────────────────────────────────────────────────────────

def test_hyphenated_keys():
    """测试带连字符的键名"""
    text = "{ skip-cert-verify: false, client-fingerprint: chrome }"
    result = parse(text)
    assert result["skip-cert-verify"] is False
    assert result["client-fingerprint"] == "chrome"


def test_ws_opts_key():
    """测试 ws-opts 这样的键名"""
    text = "{ ws-opts: { path: '/test' } }"
    result = parse(text)
    assert result["ws-opts"]["path"] == "/test"


# ── 特殊字符测试 ──────────────────────────────────────────────────────────────

def test_domain_with_special_chars():
    """测试包含特殊字符的域名"""
    text = "{ server: 'xn--ghq880n3na965a.com' }"
    result = parse(text)
    assert result["server"] == "xn--ghq880n3na965a.com"


def test_path_with_slashes():
    """测试包含斜杠的路径"""
    text = "{ path: '/pq/us1/test' }"
    result = parse(text)
    assert result["path"] == "/pq/us1/test"


def test_uuid_format():
    """测试 UUID 格式"""
    text = "{ uuid: 'ebb7ed89-9659-4103-b2e3-c3b880c2856f' }"
    result = parse(text)
    assert result["uuid"] == "ebb7ed89-9659-4103-b2e3-c3b880c2856f"


# ── 空白字符处理测试 ──────────────────────────────────────────────────────────

def test_multiline_formatting():
    """测试多行格式"""
    text = """{
        name: 'test',
        port: 443
    }"""
    result = parse(text)
    assert result["name"] == "test"
    assert result["port"] == 443


def test_extra_whitespace():
    """测试额外的空白字符"""
    text = "{  name  :  'test'  ,  port  :  443  }"
    result = parse(text)
    assert result["name"] == "test"
    assert result["port"] == 443


# ── 边界情况测试 ──────────────────────────────────────────────────────────────

def test_empty_object():
    """测试空对象"""
    text = "{}"
    result = parse(text)
    assert result == {}


def test_single_field():
    """测试单个字段"""
    text = "{ name: 'test' }"
    result = parse(text)
    assert result == {"name": "test"}


def test_negative_numbers():
    """测试负数"""
    text = "{ temperature: -10, offset: -0.5 }"
    result = parse(text)
    assert result["temperature"] == -10
    assert result["offset"] == -0.5


# ── 错误处理测试 ──────────────────────────────────────────────────────────────

def test_missing_braces_raises():
    """测试缺少大括号时抛出异常"""
    with pytest.raises(ValueError):
        parse("name: 'test'")


def test_only_opening_brace_raises():
    """测试只有开括号时抛出异常"""
    with pytest.raises(ValueError):
        parse("{ name: 'test'")


def test_only_closing_brace_raises():
    """测试只有闭括号时抛出异常"""
    with pytest.raises(ValueError):
        parse("name: 'test' }")


def test_empty_string_raises():
    """测试空字符串时抛出异常"""
    with pytest.raises(ValueError):
        parse("")


def test_whitespace_only_raises():
    """测试只有空白字符时抛出异常"""
    with pytest.raises(ValueError):
        parse("   ")
