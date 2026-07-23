"""
全局配置模块。

让机器上不同的项目共享本地配置：``get_global(name)`` 按名称对应一份 YAML 文件，
同名即共享。

核心 API 只有一个 :func:`get_global`，它返回一个**可读可写**的配置对象：

- ``get_global()``      —— 默认配置文件 ``config.yaml``；
- ``get_global("app")`` —— 独立文件 ``app.yaml``（与默认配置是不同实例）。

这个对象像普通 dict 一样用，且**写入时会落盘**。落盘前会检查文件是否被别的
程序改过（对比 load 时的内容 hash）：

- 若未变化：原子写入，正常落盘；
- 若已变化：**拒绝覆盖**，把当前内存中的版本另存为带时间戳的备份文件，并抛出
  :class:`ConfigConflictError`，磁盘上的文件保持别的程序写入的版本，便于日后合并。

默认目录为 ``~/.keon/``。可用环境变量 ``KEON_CONFIG_PATH`` 覆盖**默认**配置文件
的完整路径，或调用 :func:`set_path` 指定；具名配置则落在同一目录下的
``{name}.yaml``。

Example:
    >>> from keon import config
    >>> app = config.get_global("app")   # -> ~/.keon/app.yaml
    >>> app["theme"] = "dark"            # 这一行执行时就落盘
    >>> app.has("theme")
    True
    >>> app.path()
    '.../app.yaml'
"""

# official module
import os
import copy
import hashlib
import threading
from collections.abc import MutableMapping
from datetime import datetime, timezone
from typing import Any

# third party module
import yaml


# 默认全局配置目录：用户主目录下的 .keon，方便机器上所有项目共享
_DEFAULT_DIR = os.path.join(os.path.expanduser("~"), ".keon")
_DEFAULT_NAME = "config"
_DEFAULT_FILENAME = f"{_DEFAULT_NAME}.yaml"

# 允许通过环境变量覆盖「默认」全局配置文件路径
_ENV_PATH = "KEON_CONFIG_PATH"

# Windows / 跨平台文件名非法字符，以及控制字符
_INVALID_NAME_CHARS = frozenset('<>:"/\\|?*') | {chr(i) for i in range(32)}
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


class ConfigConflictError(RuntimeError):
    """
    落盘时检测到配置文件已被其他程序修改，拒绝覆盖。

    当前内存中的配置已另存为带时间戳的备份文件（``backup_path``），磁盘上的
    配置文件保持其他程序写入的版本不变，便于之后手动合并。

    Attributes:
        config_path: 目标配置文件路径（未被覆盖）。
        backup_path: 当前内存版本的备份文件路径。
    """

    def __init__(self, config_path: str, backup_path: str) -> None:
        self.config_path = config_path
        self.backup_path = backup_path
        super().__init__(
            f"配置文件已被其他程序修改，拒绝覆盖：{config_path}；"
            f"当前修改已备份到：{backup_path}"
        )


def _default_path() -> str:
    """返回默认的全局配置文件路径（受环境变量 KEON_CONFIG_PATH 影响）。"""
    env = os.environ.get(_ENV_PATH)
    if env:
        return os.path.abspath(os.path.expanduser(env))
    return os.path.join(_DEFAULT_DIR, _DEFAULT_FILENAME)


def _validate_name(name: str) -> str:
    """
    校验配置名是否可安全用作文件名。

    Raises:
        TypeError: name 不是字符串。
        ValueError: name 为空或含非法字符，会导致创建文件失败。
    """
    if not isinstance(name, str):
        raise TypeError(f"配置名必须是字符串，收到 {type(name).__name__}")
    if name == "":
        raise ValueError("配置名不能为空字符串")
    if name in (".", ".."):
        raise ValueError(f"配置名非法：{name!r}")
    if os.path.sep in name or (os.path.altsep and os.path.altsep in name):
        raise ValueError(f"配置名不能包含路径分隔符：{name!r}")
    bad = sorted({c for c in name if c in _INVALID_NAME_CHARS})
    if bad:
        shown = "".join(bad)
        raise ValueError(f"配置名含有非法字符 {shown!r}，无法创建文件：{name!r}")
    if name.endswith(" ") or name.endswith("."):
        raise ValueError(f"配置名不能以空格或点结尾：{name!r}")
    if name.startswith("."):
        raise ValueError(f"配置名不能以点开头：{name!r}")
    # Windows 保留设备名（含带扩展的形式，如 CON.txt）
    stem = name.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED:
        raise ValueError(f"配置名是系统保留名，无法创建文件：{name!r}")
    return name


def _hash_bytes(data: bytes | None) -> str | None:
    """对文件内容取 sha256；内容为 None（文件不存在）时返回 None。"""
    if data is None:
        return None
    return hashlib.sha256(data).hexdigest()


def _read_bytes(path: str) -> bytes | None:
    """读取文件字节；文件不存在返回 None。"""
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


class _GlobalConfigManager:
    """
    线程安全的单文件配置管理器。

    - 懒加载：首次访问时才读取磁盘文件；
    - 写时落盘：修改后立即原子写入（可关）；
    - 冲突检测：落盘前对比磁盘内容与 load 时的 hash，不一致则拒绝覆盖并备份。
    """

    def __init__(self, name: str, path: str | None = None) -> None:
        self._lock = threading.RLock()
        self._name = name
        self._path: str | None = (
            os.path.abspath(os.path.expanduser(path)) if path else None
        )
        # None 表示尚未从磁盘加载
        self._data: dict | None = None
        # load / 成功保存时磁盘内容的 sha256（None 表示当时文件不存在）
        self._baseline_hash: str | None = None
        # 当前冲突期间使用的备份文件路径（reload 后清空）
        self._conflict_backup: str | None = None

    @property
    def name(self) -> str:
        return self._name

    # ── 路径管理 ──────────────────────────────────────────────────────────

    def resolve_path(self) -> str:
        with self._lock:
            if self._path is not None:
                return self._path
            if self._name == _DEFAULT_NAME:
                return _default_path()
            directory = os.path.dirname(_default_path()) or _DEFAULT_DIR
            return os.path.join(directory, f"{self._name}.yaml")

    def set_path(self, path: str) -> None:
        with self._lock:
            self._path = os.path.abspath(os.path.expanduser(str(path)))
            self._data = None
            self._baseline_hash = None
            self._conflict_backup = None

    def bind_directory(self, directory: str) -> None:
        """把本管理器绑到 ``{directory}/{name}.yaml``。"""
        with self._lock:
            self._path = os.path.join(
                os.path.abspath(os.path.expanduser(directory)),
                f"{self._name}.yaml",
            )
            self._data = None
            self._baseline_hash = None
            self._conflict_backup = None

    # ── 加载 ──────────────────────────────────────────────────────────────

    def _ensure_loaded(self) -> None:
        if self._data is None:
            self._load()

    def _load(self) -> None:
        path = self.resolve_path()
        raw = _read_bytes(path)
        loaded = None if raw is None else yaml.safe_load(raw.decode("utf-8"))

        if loaded is None:
            loaded = {}
        if not isinstance(loaded, dict):
            raise ValueError(
                f"全局配置文件根节点必须是映射(dict)，实际为 "
                f"{type(loaded).__name__}: {path}"
            )
        self._data = loaded
        self._baseline_hash = _hash_bytes(raw)
        self._conflict_backup = None

    def reload(self) -> None:
        with self._lock:
            self._load()

    # ── 落盘（含冲突检测）────────────────────────────────────────────────

    def _dump_bytes(self) -> bytes:
        text = yaml.safe_dump(
            self._data,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
        return text.encode("utf-8")

    def _atomic_write(self, path: str, data: bytes) -> None:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def _new_conflict_path(self) -> str:
        path = self.resolve_path()
        directory = os.path.dirname(path) or "."
        stem, ext = os.path.splitext(os.path.basename(path))
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        return os.path.join(directory, f"{stem}.conflict-{ts}{ext}")

    def _save(self) -> None:
        """
        带冲突检测的落盘。未加锁，调用方需持锁。

        Raises:
            ConfigConflictError: 磁盘文件自 load 后被别的程序改过，拒绝覆盖。
        """
        self._ensure_loaded()
        path = self.resolve_path()
        new_bytes = self._dump_bytes()

        disk_hash = _hash_bytes(_read_bytes(path))
        if disk_hash != self._baseline_hash:
            # 别的程序改过了：不覆盖，把当前版本另存为带时间戳的备份
            if self._conflict_backup is None:
                self._conflict_backup = self._new_conflict_path()
            self._atomic_write(self._conflict_backup, new_bytes)
            raise ConfigConflictError(path, self._conflict_backup)

        self._atomic_write(path, new_bytes)
        self._baseline_hash = _hash_bytes(new_bytes)
        self._conflict_backup = None

    def save(self) -> None:
        with self._lock:
            self._save()

    # ── 只读辅助 ──────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        with self._lock:
            self._ensure_loaded()
            return copy.deepcopy(self._data)

    def status(self) -> dict:
        with self._lock:
            self._ensure_loaded()
            path = self.resolve_path()
            disk_hash = _hash_bytes(_read_bytes(path))
            return {
                "name": self._name,
                "path": path,
                "baseline_hash": self._baseline_hash,
                "disk_hash": disk_hash,
                "external_change": disk_hash != self._baseline_hash,
                "conflict_backup": self._conflict_backup,
            }

    # ── section（可写视图，支持 cfg["a"]["b"] = v 落盘）──────────────────

    def _section_dict(self, parts: list[Any], create: bool) -> dict | None:
        """
        返回 parts 指向的 dict。未加锁，调用方需持锁。

        Args:
            parts: 路径片段（空列表表示根）。
            create: 缺失的层级是否自动创建为空 dict。

        Returns:
            对应的 dict；create=False 且不存在时返回 None。

        Raises:
            ValueError: 路径中某一级已存在但不是 dict。
            KeyError: create=False 且中间某一级缺失（仅在需要区分时由调用方处理）。
        """
        cur = self._data
        walked: list[Any] = []
        for part in parts:
            walked.append(part)
            nxt = cur.get(part) if isinstance(cur, dict) else None
            if isinstance(nxt, dict):
                cur = nxt
                continue
            if nxt is None and part not in cur:
                if not create:
                    return None
                nxt = {}
                cur[part] = nxt
                cur = nxt
                continue
            if nxt is None and part in cur:
                # 显式 null：当作可写空 dict（create 时替换）
                if not create:
                    return None
                nxt = {}
                cur[part] = nxt
                cur = nxt
                continue
            raise ValueError(
                f"配置键 {'.'.join(str(p) for p in walked)} 已存在且不是字典，"
                f"无法继续嵌套访问"
            )
        return cur

    def get_config(self, save_on_set: bool) -> "GlobalConfig":
        with self._lock:
            self._ensure_loaded()
            return GlobalConfig(self, [], save_on_set)

    def section_is_mapping(self, parts: list[Any], key: Any) -> bool:
        """key 对应值是否为 dict（调用方据此决定返回嵌套视图还是拷贝）。"""
        with self._lock:
            self._ensure_loaded()
            d = self._section_dict(parts, create=False)
            if not isinstance(d, dict) or key not in d:
                raise KeyError(key)
            return isinstance(d[key], dict)

    def section_getitem(self, parts: list[Any], key: Any) -> Any:
        """读取非 dict 值的深拷贝；dict 请用嵌套 GlobalConfig，不要走这里。"""
        with self._lock:
            self._ensure_loaded()
            d = self._section_dict(parts, create=False)
            if not isinstance(d, dict) or key not in d:
                raise KeyError(key)
            return copy.deepcopy(d[key])

    def section_setitem(self, parts: list[Any], key: Any, value: Any,
                        save: bool) -> None:
        with self._lock:
            self._ensure_loaded()
            if isinstance(value, GlobalConfig):
                value = value.to_dict()
            else:
                value = copy.deepcopy(value)
            d = self._section_dict(parts, create=True)
            d[key] = value
            if save:
                self._save()

    def section_delitem(self, parts: list[Any], key: Any, save: bool) -> None:
        with self._lock:
            self._ensure_loaded()
            d = self._section_dict(parts, create=False)
            if not isinstance(d, dict) or key not in d:
                raise KeyError(key)
            del d[key]
            if save:
                self._save()

    def section_keys(self, parts: list[Any]) -> list:
        with self._lock:
            self._ensure_loaded()
            d = self._section_dict(parts, create=False)
            return [] if d is None else list(d.keys())

    def section_contains(self, parts: list[Any], key: object) -> bool:
        with self._lock:
            self._ensure_loaded()
            d = self._section_dict(parts, create=False)
            return isinstance(d, dict) and key in d

    def section_to_dict(self, parts: list[Any]) -> dict:
        with self._lock:
            self._ensure_loaded()
            d = self._section_dict(parts, create=False)
            return {} if d is None else copy.deepcopy(d)


class _ConfigRegistry:
    """按名称管理多个配置文件实例；同名共享同一管理器。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._managers: dict[str, _GlobalConfigManager] = {}
        # 显式指定的默认配置文件路径（None 表示走环境变量 / 默认路径）
        self._default_path: str | None = None

    def _config_dir(self) -> str:
        if self._default_path is not None:
            return os.path.dirname(self._default_path) or "."
        return os.path.dirname(_default_path()) or _DEFAULT_DIR

    def _path_for(self, name: str) -> str:
        if name == _DEFAULT_NAME:
            if self._default_path is not None:
                return self._default_path
            return _default_path()
        return os.path.join(self._config_dir(), f"{name}.yaml")

    def get_manager(self, name: str) -> _GlobalConfigManager:
        with self._lock:
            mgr = self._managers.get(name)
            if mgr is None:
                mgr = _GlobalConfigManager(name, self._path_for(name))
                self._managers[name] = mgr
            return mgr

    def set_default_path(self, path: str) -> None:
        """指定默认配置文件路径，并让具名配置使用同一目录。"""
        with self._lock:
            self._default_path = os.path.abspath(os.path.expanduser(str(path)))
            directory = os.path.dirname(self._default_path) or "."
            # 重置已有管理器，避免仍指向旧目录
            for name, mgr in self._managers.items():
                if name == _DEFAULT_NAME:
                    mgr.set_path(self._default_path)
                else:
                    mgr.bind_directory(directory)

    def default_manager(self) -> _GlobalConfigManager:
        return self.get_manager(_DEFAULT_NAME)


class GlobalConfig(MutableMapping):
    """
    :func:`get_global` 返回的可读可写配置对象，用起来就像普通 dict。

    - ``get_global()`` / ``get_global("config")`` 对应 ``config.yaml``；
    - ``get_global("app")`` 对应独立的 ``app.yaml``；
    - ``save_on_set=True`` 时，每次 ``cfg[k] = v`` / ``del cfg[k]`` 都会立即落盘；
    - 取到的 **dict 值** 仍是可写视图，因此 ``cfg["a"]["b"] = 1`` 也会落盘；
    - 落盘前会检测文件是否被别的程序改过，冲突时拒绝覆盖并备份（见模块文档）；
    - 文件不存在时视为空 config，首次写入才真正创建。

    注意：list 等非 dict 容器仍返回拷贝，对其原地修改不会落盘。

    Example:
        >>> app = config.get_global("app", save_on_set=True)
        >>> app["b"] = {"1": 123, "2": 456}
        >>> app["b"]["3"] = 789          # 嵌套赋值也会落盘
        >>> app.has("b")
        True
        >>> app.path()
        '.../app.yaml'
    """

    def __init__(self, manager: "_GlobalConfigManager", parts: list[Any],
                 save_on_set: bool) -> None:
        self._manager = manager
        self._parts = list(parts)
        self._save_on_set = bool(save_on_set)

    def __getitem__(self, key: Any) -> Any:
        # dict -> 嵌套可写视图；其它类型 -> 深拷贝
        if self._manager.section_is_mapping(self._parts, key):
            return GlobalConfig(
                self._manager, self._parts + [key], self._save_on_set
            )
        return self._manager.section_getitem(self._parts, key)

    def __setitem__(self, key: Any, value: Any) -> None:
        self._manager.section_setitem(
            self._parts, key, value, self._save_on_set
        )

    def __delitem__(self, key: Any) -> None:
        self._manager.section_delitem(self._parts, key, self._save_on_set)

    def __iter__(self):
        return iter(self._manager.section_keys(self._parts))

    def __len__(self) -> int:
        return len(self._manager.section_keys(self._parts))

    def __contains__(self, key: object) -> bool:
        return self._manager.section_contains(self._parts, key)

    def has(self, key: object) -> bool:
        """判断当前这一层是否存在 ``key``（等价于 ``key in cfg``）。"""
        return key in self

    def path(self) -> str:
        """返回本配置实例对应的 YAML 文件路径。"""
        return self._manager.resolve_path()

    def to_dict(self) -> dict:
        """返回该 config（当前子树）的深拷贝（普通 dict）。"""
        return self._manager.section_to_dict(self._parts)

    def save(self) -> None:
        """把本文件落盘（用于 save_on_set=False 时批量修改后手动保存）。"""
        self._manager.save()

    def reload(self) -> None:
        """丢弃内存快照，重新从磁盘加载（也会清除冲突状态）。"""
        self._manager.reload()

    def __repr__(self) -> str:
        sub = ".".join(str(p) for p in self._parts) if self._parts else "<root>"
        return (f"GlobalConfig(name={self._manager.name!r}, section={sub!r}, "
                f"save_on_set={self._save_on_set}, data={self.to_dict()!r})")


# 模块级注册表：同名配置共享同一管理器（进而共享同一份文件）
_registry = _ConfigRegistry()


def get_global(name: str | None = None,
               save_on_set: bool = True) -> GlobalConfig:
    """
    获取全局配置对象（可读可写）。

    - ``get_global()``      返回默认配置（``config.yaml``）；
    - ``get_global("app")`` 返回独立配置文件 ``app.yaml``。

    同名在机器上共享同一份文件；不同名是不同实例。返回的对象像普通 dict 一样用，
    写入时会落盘（见模块文档的冲突检测说明）。

    Args:
        name: 配置名；``None`` 表示默认名 ``config``。会用作文件名
            ``{name}.yaml``（默认配置的路径仍可被 ``KEON_CONFIG_PATH`` /
            :func:`set_path` 覆盖）。
        save_on_set: 为 True（默认）时，每次 ``cfg[k]=v`` / ``del cfg[k]`` 都会
            立即落盘；为 False 时只改内存，需要之后 ``cfg.save()`` 或（仅默认
            配置）:func:`save` 才写入磁盘。

    Returns:
        GlobalConfig: 可读可写的配置对象；对应文件不存在时视为空 config。

    Raises:
        TypeError: ``name`` 不是字符串。
        ValueError: ``name`` 含非法字符，无法用作文件名。

    Example:
        >>> from keon import config
        >>> app = config.get_global("app")   # ~/.keon/app.yaml
        >>> app["theme"] = "dark"            # 立即落盘
        >>> app.get("theme", "light")
        'dark'
        >>> config.get_global("not_set").to_dict()   # 文件不存在 -> 空
        {}
    """
    if name is None:
        resolved = _DEFAULT_NAME
    else:
        resolved = _validate_name(name)
    return _registry.get_manager(resolved).get_config(save_on_set)


def save() -> None:
    """把默认配置（``get_global()``）落盘（带冲突检测）。"""
    _registry.default_manager().save()


def reload() -> None:
    """丢弃默认配置的内存快照，重新从磁盘加载。"""
    _registry.default_manager().reload()


def snapshot() -> dict:
    """返回默认配置的深拷贝（只读）。"""
    return _registry.default_manager().snapshot()


def status() -> dict:
    """
    返回默认配置的当前状态，便于排查冲突。

    Returns:
        dict: 含 ``name`` / ``path`` / ``baseline_hash`` / ``disk_hash`` /
        ``external_change`` / ``conflict_backup``。
    """
    return _registry.default_manager().status()


def path() -> str:
    """返回默认配置文件路径（``get_global()`` 对应的文件）。"""
    return _registry.default_manager().resolve_path()


def set_path(new_path: str) -> None:
    """
    显式指定默认配置文件路径，并让具名配置使用同一目录下的 ``{name}.yaml``。

    Args:
        new_path: 默认配置文件路径，支持 ``~`` 展开。
    """
    _registry.set_default_path(new_path)


__all__ = [
    "get_global",
    "save",
    "reload",
    "snapshot",
    "status",
    "path",
    "set_path",
    "GlobalConfig",
    "ConfigConflictError",
]
