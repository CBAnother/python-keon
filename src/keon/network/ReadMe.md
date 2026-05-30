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





# Linux

## 格式化 last 输出

在 linux 执行 `last -F` 之后，有时想做一些解析，可以使用函数 `parse_last_output` 实现

例如：先输出到 txt 中

```
last -F > last.txt
```

解析

```python
df = parse_last_output(Path("last.txt").read_text(encoding="utf-8"))
```



