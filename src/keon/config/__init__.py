"""
全局配置模块。

让机器上不同的项目共享本地配置：``get_global(name)`` 按名称对应一份 YAML 文件，
同名即共享。有 ``~/.keon/s3.yaml``（或已 ``set_s3``）时，自动按间隔与云端同步。

核心 API：

- ``get_global()`` / ``get_global("app")`` —— 唯一读写入口；
- ``set_s3(...)`` —— 一次性配置 S3 / MinIO 凭证；
- ``init`` / ``sync`` / ``resolve_conflict`` —— 可选显式同步控制。

Example:
    >>> from keon import config
    >>> app = config.get_global("app")   # -> ~/.keon/app.yaml
    >>> app["theme"] = "dark"            # 这一行执行时就落盘
"""

from __future__ import annotations

from typing import Callable

from .backends import RemoteConflictError, RemoteConfig
from .local import (
    ConfigConflictError,
    ConfigList,
    GlobalConfig,
    _ConfigRegistry,
    _DEFAULT_NAME,
    _GlobalConfigManager,
    _validate_name,
)
from .sync.conflict import ConflictEvent, SyncConflictError
from .sync.manager import SyncManager
from .sync.settings import (
    DEFAULT_KEY_PREFIX,
    DEFAULT_SYNC_INTERVAL,
    S3Settings,
    SyncSettings,
)

# 模块级注册表与同步管理器
_registry = _ConfigRegistry()
_sync = SyncManager(_registry)


def get_global(
    name: str | None = None,
    save_on_set: bool = True,
    *,
    sync: bool | None = None,
) -> GlobalConfig:
    """
    获取全局配置对象（可读可写）。

    - ``get_global()``      返回默认配置（``config.yaml``）；
    - ``get_global("app")`` 返回独立配置文件 ``app.yaml``。

    有 S3 凭证时默认会登记后台同步。``sync=False`` 禁用该 name 的云端同步
    （写入 ``.config_sync_state.json``，跨进程持久；同进程内其它未指定
    ``sync`` 的 ``get_global`` 不会重新开启；需显式 ``sync=True`` 才恢复）。

    Args:
        name: 配置名；``None`` 表示默认名 ``config``。
        save_on_set: 为 True（默认）时每次赋值/删除立即落盘。
        sync: ``None``（默认）沿用当前策略；``False`` 禁用同步；
            ``True`` 强制启用同步。

    Returns:
        GlobalConfig: 可读可写的配置对象。
    """
    if name is None:
        resolved = _DEFAULT_NAME
    else:
        resolved = _validate_name(name)
    cfg = _registry.get_manager(resolved).get_config(save_on_set)
    _sync.on_get_global(resolved, sync=sync)
    return cfg


def set_path(new_path: str) -> None:
    """
    显式指定默认配置文件路径，并让具名配置使用同一目录下的 ``{name}.yaml``。

    Args:
        new_path: 默认配置文件路径，支持 ``~`` 展开。
    """
    _registry.set_default_path(new_path)


def set_s3(
    *,
    endpoint_url: str | None = None,
    bucket: str,
    access_key: str,
    secret_key: str,
    key_prefix: str = DEFAULT_KEY_PREFIX,
    region_name: str | None = "us-east-1",
    session_token: str | None = None,
    persist: bool = True,
    cred_path: str | None = None,
) -> None:
    """
    设置 S3 / MinIO 连接信息（本机通常只需配置一次）。

    默认 ``persist=True``，写入 ``~/.keon/s3.yaml``（可用 ``KEON_S3_CRED_PATH``
    或 ``cred_path`` 覆盖）。``key_prefix`` 默认为 ``keon-configs``。
    业务程序无需再调用本函数。
    """
    _sync.set_s3(
        endpoint_url=endpoint_url,
        bucket=bucket,
        access_key=access_key,
        secret_key=secret_key,
        key_prefix=key_prefix,
        region_name=region_name,
        session_token=session_token,
        persist=persist,
        cred_path=cred_path,
    )


def init(
    *,
    wait: bool = False,
    force: bool = False,
    sync_interval: float | None = None,
    conflict_mode: str | None = None,
    on_update: Callable[[str], None] | None = None,
    on_conflict: Callable[[ConflictEvent], None] | None = None,
) -> None:
    """
    可选：更新同步设置，并按需触发同步。

    未传入的字段沿用当前值（默认 interval=300）。日常程序不必调用；
    ``get_global`` 在有凭证时会自动登记并后台同步。
    """
    _sync.init(
        wait=wait,
        force=force,
        sync_interval=sync_interval,
        conflict_mode=conflict_mode,
        on_update=on_update,
        on_conflict=on_conflict,
    )


def sync(
    *, force: bool = False, wait: bool = True, name: str | None = None
) -> None:
    """显式同步。``force=True`` 忽略跨进程节流与间隔。"""
    _sync.sync(force=force, wait=wait, name=name)


def resolve_conflict(name: str, choice: str | None = None) -> None:
    """
    解决本地↔云端冲突。

    choice: ``use_local`` | ``use_remote`` | ``show_diff`` | ``cancel``；
    为 None 时进入 CLI 交互。
    """
    _sync.resolve_conflict(name, choice)


def set_on_update(cb: Callable[[str], None] | None) -> None:
    """后台下载并替换本地配置后的回调 ``cb(name)``。"""
    _sync.set_on_update(cb)


def set_on_conflict(cb: Callable[[ConflictEvent], None] | None) -> None:
    """检测到本地↔云端冲突时的回调 ``cb(event)``。"""
    _sync.set_on_conflict(cb)


def start_auto_sync(interval: float | None = None) -> None:
    """可选：提前/全局打开单调度线程（一般 ``get_global`` 已自动开启）。"""
    _sync.start_auto_sync(interval)


def stop_auto_sync() -> None:
    """关闭本进程定时同步。"""
    _sync.stop_auto_sync()


# 给 GlobalConfig.status 注入同步字段
_orig_status = GlobalConfig.status


def _status_with_sync(self: GlobalConfig) -> dict:
    if self._parts:
        return _orig_status(self)
    return _sync.status_for(self._manager.name)


GlobalConfig.status = _status_with_sync  # type: ignore[method-assign]


__all__ = [
    "get_global",
    "set_path",
    "set_s3",
    "init",
    "sync",
    "resolve_conflict",
    "set_on_update",
    "set_on_conflict",
    "start_auto_sync",
    "stop_auto_sync",
    "GlobalConfig",
    "ConfigList",
    "ConfigConflictError",
    "SyncConflictError",
    "RemoteConflictError",
    "ConflictEvent",
    "RemoteConfig",
    "S3Settings",
    "SyncSettings",
    "DEFAULT_SYNC_INTERVAL",
    "DEFAULT_KEY_PREFIX",
    # 测试 / 高级用途
    "_GlobalConfigManager",
    "_registry",
    "_sync",
]
