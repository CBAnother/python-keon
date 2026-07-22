# knock — 端口敲门（Port Knocking）

向目标主机按顺序发送 TCP/UDP 敲门包，用于触发防火墙或 knock 守护进程临时开放受保护的服务。

## 函数

### `port_knock(ip, sequence, delay_ms=100, tcp_wait_ms=250, verbose=True)`

按顺序向 `ip` 发送敲门序列。

| 参数 | 说明 |
|------|------|
| `ip` | 目标主机或 IP |
| `sequence` | 有序敲门列表；每项为 `"端口:协议"`（如 `"42102:udp"`）或 `(端口, 协议)` |
| `delay_ms` | 两次敲门之间的间隔（毫秒），默认 100 |
| `tcp_wait_ms` | TCP 连接尝试最长等待（毫秒），默认 250 |
| `verbose` | 是否打印进度，默认 `True` |

支持的协议：`tcp`、`udp`。

- TCP：发起一次短连接尝试（端口通常是关闭的，只需 SYN 发出去）。
- UDP：发送一个空字节数据报。

## 使用示例

```python
from keon import knock

knock.port_knock(
    "203.0.113.10",
    [
        "42102:udp",
        "42103:tcp",
        (42104, "udp"),
    ],
    delay_ms=150,
)
```

安静模式（不打印）：

```python
knock.port_knock(
    "203.0.113.10",
    ["42102:udp", "42103:tcp"],
    verbose=False,
)
```

## 依赖

仅使用 Python 标准库（`socket` / `time`），无第三方依赖。
