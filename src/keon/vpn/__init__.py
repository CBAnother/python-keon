"""网络代理配置转换模块，提供 V2Ray 到 Clash 的配置转换功能。"""
import base64
import json
import yaml
from dataclasses import dataclass, field
from typing import Optional, Dict
from urllib.parse import unquote


@dataclass
class WebSocketOptions:
    """
    WebSocket 传输配置。
    """
    path: str = "/"
    headers: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """
        转换为字典格式。
        """
        return {
            "path": self.path,
            "headers": self.headers
        }


@dataclass
class ProxyNode:
    """
    代理节点数据结构。
    """
    name: str
    type: str
    server: str
    port: int
    uuid: str
    alter_id: int = 0
    cipher: str = "auto"
    udp: bool = True
    
    # TLS 相关
    tls: bool = False
    skip_cert_verify: bool = False
    servername: Optional[str] = None
    
    # 传输协议
    network: Optional[str] = None
    ws_opts: Optional[WebSocketOptions] = None
    
    def to_dict(self) -> dict:
        """
        转换为 Clash 配置字典格式。
        """
        result = {
            "name": self.name,
            "type": self.type,
            "server": self.server,
            "port": self.port,
            "uuid": self.uuid,
            "alterId": self.alter_id,
            "cipher": self.cipher,
            "udp": self.udp,
        }
        
        if self.tls:
            result["tls"] = True
            result["skip-cert-verify"] = self.skip_cert_verify
            if self.servername:
                result["servername"] = self.servername
        
        if self.network:
            result["network"] = self.network
            if self.network == "ws" and self.ws_opts:
                result["ws-opts"] = self.ws_opts.to_dict()
        
        return result


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


def _vmess_json_to_clash_node(v: dict) -> ProxyNode:
    """
    将 V2Ray VMess JSON 转为 ProxyNode 对象。
    """
    name = v.get("ps") or "vmess-node"
    server = v["add"]
    port = int(v["port"])
    uuid = v["id"]

    net = v.get("net", "tcp")
    host = v.get("host", "")
    path = unquote(v.get("path", "/") or "/")
    tls_enabled = v.get("tls", "") == "tls"

    # 创建节点对象
    node = ProxyNode(
        name=name,
        type="vmess",
        server=server,
        port=port,
        uuid=uuid,
        alter_id=int(v.get("aid", 0) or 0),
        cipher="auto",
        udp=True,
    )

    # 配置 TLS
    if tls_enabled:
        node.tls = True
        node.skip_cert_verify = False
        node.servername = host or server

    # 配置 WebSocket
    if net == "ws":
        node.network = "ws"
        node.ws_opts = WebSocketOptions(
            path=path,
            headers={"Host": host or server}
        )

    return node


def _build_clash_config(node: ProxyNode) -> dict:
    """
    生成一个最小可用 Clash Verge 配置。
    """
    return {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "info",
        "ipv6": False,
        "proxies": [node.to_dict()],
        "proxy-groups": [
            {
                "name": "PROXY",
                "type": "select",
                "proxies": [
                    node.name,
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
