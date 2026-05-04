import base64
import json
import yaml
from urllib.parse import unquote


def _decode_vmess_link(link: str) -> dict:
    """
    将 vmess://base64 链接解码成 Python dict。
    """
    if not link.startswith("vmess://"):
        raise ValueError("不是 vmess:// 链接")

    b64 = link[len("vmess://"):].strip()
    # base64 可能缺少 = 补齐
    b64 += "=" * (-len(b64) % 4)

    return json.loads(base64.urlsafe_b64decode(b64))


def _vmess_json_to_clash_node(v: dict) -> dict:
    """
    将 V2Ray VMess JSON 转为 Clash / Mihomo 节点 dict。
    """
    name = v.get("ps") or "vmess-node"
    server = v["add"]
    port = int(v["port"])
    uuid = v["id"]

    net = v.get("net", "tcp")
    host = v.get("host", "")
    path = unquote(v.get("path", "/") or "/")
    tls_enabled = v.get("tls", "") == "tls"

    node = {
        "name": name,
        "type": "vmess",
        "server": server,
        "port": port,
        "uuid": uuid,
        "alterId": int(v.get("aid", 0) or 0),
        "cipher": "auto",
        "udp": True,
    }

    if tls_enabled:
        node["tls"] = True
        node["skip-cert-verify"] = False
        node["servername"] = host or server

    if net == "ws":
        node["network"] = "ws"
        node["ws-opts"] = {
            "path": path,
            "headers": {
                "Host": host or server
            }
        }

    return node


def _build_clash_config(node: dict) -> dict:
    """
    生成一个最小可用 Clash Verge 配置。
    """
    return {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "info",
        "ipv6": False,
        "proxies": [node],
        "proxy-groups": [
            {
                "name": "PROXY",
                "type": "select",
                "proxies": [
                    node["name"],
                    "DIRECT",
                ],
            }
        ],
        "rules": [
            "MATCH,PROXY"
        ],
    }

_YAML_SPECIAL_CHARS = frozenset(',:{[]}#')


def _dict_to_inline_yaml(obj) -> str:
    """
    将 Python dict/list 转成 Clash 常见的单行 YAML flow style 格式。

    例如：
    {
        "name": "aaaa",
        "type": "vmess",
        "ws-opts": {
            "path": "/cccc",
            "headers": {
                "Host": "bbbb"
            }
        }
    }

    转成：
    { name: aaaa, type: vmess, ws-opts: { path: /cccc, headers: { Host: bbbb } } }
    """
    if isinstance(obj, dict):
        return "{ " + ", ".join(f"{k}: {_dict_to_inline_yaml(v)}" for k, v in obj.items()) + " }"

    if isinstance(obj, list):
        return "[ " + ", ".join(_dict_to_inline_yaml(item) for item in obj) + " ]"

    if isinstance(obj, bool):
        return "true" if obj else "false"

    if obj is None:
        return "null"

    if isinstance(obj, (int, float)):
        return str(obj)

    # 字符串包含特殊字符时加引号
    text = str(obj)
    if _YAML_SPECIAL_CHARS.intersection(text):
        return '"' + text.replace('"', '\\"') + '"'

    return text


def v2ray_to_clash(vmess_link: str, strip: bool) -> str:
    """
    将 vmess:// 链接转换为 Clash Verge 配置字符串。
    strip=True 时返回单行 flow style，strip=False 时返回标准多行 YAML。
    """
    vmess_json = _decode_vmess_link(vmess_link)
    node = _vmess_json_to_clash_node(vmess_json)
    clash_config = _build_clash_config(node)

    if strip:
        return "- " + _dict_to_inline_yaml(clash_config)

    return yaml.safe_dump(clash_config, allow_unicode=True, sort_keys=False)
