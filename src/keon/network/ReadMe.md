# 扫描端口

扫描内网中哪些 IP 的端口是开放的

```python
import keon

ps = keon.network.PortScanner('192.168.4.0/24', 3389)
ps.scan()
```

返回值是 tuple 类型，例如

```
[('192.168.4.38', 3389),
 ('192.168.4.229', 3389)]
```

