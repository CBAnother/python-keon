# keon.config

全局配置模块。让机器上不同的项目**按名称共享本地配置**，并可选同步到 S3 / MinIO。

核心 API 是 `get_global`：返回可读可写的配置对象。

- `get_global()` —— 默认配置文件 `config.yaml`
- `get_global("app")` —— 独立文件 `app.yaml`

有 `~/.keon/s3.yaml`（或已调用 `set_s3`）时，`get_global` 会登记该 name，由**单一调度线程**按间隔后台同步（跨进程限频）。



## 配置文件位置

```text
~/.keon/
├─ config.yaml / {name}.yaml   # 业务配置
├─ s3.yaml                     # S3 凭证（永不上传）
├─ .config_sync_state.json     # 同步状态（跨进程节流）
└─ .config_conflict/{name}/    # 本地↔云端冲突快照
```

路径覆盖：

| 机制 | 作用 |
|---|---|
| `set_path(path)` | 默认 `config.yaml` 路径；具名配置同目录 |
| `KEON_CONFIG_PATH` | 同上 |
| `KEON_S3_CRED_PATH` | 覆盖 `s3.yaml` 路径 |



## 本地用法

```python
from keon import config

app = config.get_global("app")
app["theme"] = "dark"            # save_on_set=True 时立即落盘
app["theme"].comment = "界面主题"
assert app["theme"].comment == "界面主题"
app["tags"] = ["x"]
app["tags"].append("y")          # list 回写视图也会落盘

theme = app.get("theme", "light")
print(app.path())
app.save(); app.reload(); app.snapshot(); app.status()
```

批量修改只落盘一次：

```python
batch = config.get_global("app", save_on_set=False)
batch.update({"a": 1, "b": 2})
batch.save()
```



## 云端同步（一次性配密钥）

```python
config.set_s3(
    endpoint_url="http://127.0.0.1:9000",
    bucket="my-config-bucket",
    access_key="xxx",
    secret_key="yyy",
    # key_prefix 默认 "keon-configs"
)
# 默认 persist=True → ~/.keon/s3.yaml
```

之后业务代码无需再 `set_s3`：

```python
app = config.get_global("app")              # 有凭证则后台限频同步
local_only = config.get_global("secret", sync=False)  # 仅本地，不同步
```

可选显式控制：

```python
config.init(wait=True, conflict_mode="raise", sync_interval=300)
config.sync(force=True, wait=True, name="app")
config.set_on_update(lambda name: ...)
config.set_on_conflict(lambda event: ...)
config.resolve_conflict("app", "use_local")  # 或 use_remote
config.stop_auto_sync()
```



## API

| 符号 | 说明 |
|---|---|
| `get_global(name=None, save_on_set=True, sync=None)` | 唯一读写入口；`sync=False` 仅本地（持久化到状态文件，需 `sync=True` 才恢复） |
| `set_path(path)` | 指定默认配置路径 |
| `set_s3(...)` | 一次性配置 S3 / MinIO |
| `init` / `sync` | 可选显式同步 |
| `resolve_conflict` | 解决本地↔云端冲突 |
| `set_on_update` / `set_on_conflict` | 后台回调 |
| `start_auto_sync` / `stop_auto_sync` | 调度线程控制 |
| `GlobalConfig` / `ConfigList` | 可写视图 |
| `ConfigConflictError` | 本地写盘冲突 |
| `SyncConflictError` | 本地↔云端冲突 |

读写、保存、状态一律走实例方法：`cfg.save()` / `cfg.reload()` / `cfg.snapshot()` / `cfg.status()` / `cfg.path()`。



## 特性

- **按名分文件**，同名跨项目共享
- **写时落盘**；嵌套 dict / list 原地修改同样落盘
- **本地冲突**：拒绝覆盖磁盘、保留内存、写 `.conflict-<ts>.yaml` 备份
- **云端**：meta 条件写 CAS、跨进程 `last_check_time` 节流、冲突后暂停该 name 直至 resolve
- **依赖**：`pyyaml`；云端另需 `boto3`、`filelock`
