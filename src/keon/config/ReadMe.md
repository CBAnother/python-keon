# keon.config

全局配置模块。让机器上不同的项目**按名称共享本地配置**：`get_global(name)`
对应一份独立的 YAML 文件，同名即共享。

核心 API 只有一个 `get_global`，它返回一个**可读可写**的配置对象：

- `get_global()` —— 默认配置文件 `config.yaml`；
- `get_global("app")` —— 独立文件 `app.yaml`（与默认配置是不同实例）。

这个对象像普通 dict 一样用，且**写入时会落盘**。



## 配置文件位置

默认目录：

```text
~/.keon/config.yaml   # get_global()
~/.keon/app.yaml      # get_global("app")
```

优先级（仅影响默认文件路径；具名配置落在同一目录）：

`set_path()` 指定的路径 > 环境变量 `KEON_CONFIG_PATH` > 默认 `~/.keon/config.yaml`。

文件内容为普通 YAML，可手动编辑：

```yaml
theme: dark
default_slot: 1
```



## 特性

- **按名分文件**：不同 `name` 对应不同 YAML；同名跨项目共享。
- **可读可写对象**：`get_global(...)` 返回的对象像 dict 一样读写。
- **写时落盘**：`save_on_set=True`（默认）时，每次赋值/删除都会立即原子写入。
- **冲突检测**：落盘前对比磁盘内容与 load 时的 hash，若被别的程序改过则**拒绝覆盖**，把当前内存版本另存为带时间戳的备份，抛出 `ConfigConflictError`。
- **名称校验**：`name` 含非法文件名字符时立即抛 `ValueError`，不会去创建文件。
- **线程安全**：内部使用可重入锁。



## API

| 函数 | 说明 |
|---|---|
| `get_global(name=None, save_on_set=True)` | 返回可读可写的配置对象；`name=None` 为 `config.yaml`，`name="x"` 为 `x.yaml` |
| `save()` | 把**默认**配置落盘（带冲突检测） |
| `reload()` | 丢弃**默认**配置内存快照，重新从磁盘加载 |
| `snapshot()` | 返回**默认**配置的深拷贝（只读 dict） |
| `status()` | 返回**默认**配置状态：路径、hash、`external_change` 等 |
| `path()` | 返回**默认**配置文件路径 |
| `set_path(new_path)` | 指定默认配置文件路径；具名配置使用同一目录 |

`get_global(...)` 返回的对象（`GlobalConfig`）还支持：`cfg[k]`、`cfg[k]=v`、
`del cfg[k]`、`k in cfg`、`cfg.has(k)`、`cfg.get(k, default)`、`cfg.keys()`、
`dict(cfg)`、`cfg.to_dict()`、`cfg.path()`、`cfg.save()`、`cfg.reload()`。
取到的 dict 值仍是可写视图，因此 `cfg["a"]["b"] = 1` 在 `save_on_set=True` 时也会落盘。



## 使用

```python
from keon import config

# 拿到 app 的独立配置文件（~/.keon/app.yaml）
app = config.get_global("app")
print(app.path())

# 写：save_on_set=True（默认）时，这一行执行就落盘
app["theme"] = "dark"
app["default_slot"] = 1

# 读 / 判断
theme = app.get("theme", "light")
if app.has("theme"):
    ...

# 文件尚不存在 -> 空 config
config.get_global("not_set").to_dict()   # -> {}
```



### 默认配置 vs 具名配置

```python
root = config.get_global()       # ~/.keon/config.yaml
app = config.get_global("app")   # ~/.keon/app.yaml（另一份文件）

root["shared"] = 1
app["theme"] = "dark"
```



### 批量修改，只落盘一次

```python
app = config.get_global("app", save_on_set=False)
app["a"] = 1
app["b"] = 2
app.save()          # 一次性写入 app.yaml
```



### 冲突处理

当另一个程序在你 load 之后改了配置文件，你的写入会被拒绝以免覆盖对方：

```python
app = config.get_global("app")
app["x"] = 1                       # 正常落盘

# ……此时别的程序改了 app.yaml……

try:
    app["y"] = 2
except config.ConfigConflictError as e:
    print("磁盘上的文件保持不变：", e.config_path)
    print("我的修改已备份到：", e.backup_path)   # app.conflict-<时间戳>.yaml
    app.reload()   # 采用磁盘版本
```

也可以主动查询默认配置是否被外部改过：

```python
if config.status()["external_change"]:
    config.reload()
```



## 依赖

- `pyyaml`：读写 YAML 文件。
