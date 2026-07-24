"""
本地配置：按名分文件的 YAML 读写、写时落盘、本地冲突检测、可写视图。

使用 ruamel.yaml 以保留行尾注释；可通过 cfg["key"].comment 读写。
"""

from __future__ import annotations

import copy
import hashlib
import os
import tempfile
import threading
from collections.abc import MutableMapping, MutableSequence
from datetime import datetime, timezone
from io import StringIO
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

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
_MAX_NAME_LEN = 255


class ConfigConflictError(RuntimeError):
    """
    落盘时检测到配置文件已被其他程序修改，拒绝覆盖。

    当前内存中的配置已另存为带时间戳的备份文件（backup_path），磁盘上的
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
    if len(name) > _MAX_NAME_LEN:
        raise ValueError(f"配置名长度不能超过 {_MAX_NAME_LEN}：{len(name)}")
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


def _yaml_rt() -> YAML:
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.default_flow_style = False
    y.allow_unicode = True
    y.width = 4096
    return y


def _to_plain(obj: Any) -> Any:
    """CommentedMap/Seq → 普通 dict/list（不含注释）。"""
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_plain(v) for v in obj]
    return copy.deepcopy(obj)


def _to_commented(obj: Any) -> Any:
    """普通 dict/list → CommentedMap/Seq，便于挂注释。"""
    if isinstance(obj, CommentedMap | CommentedSeq):
        return obj
    if isinstance(obj, dict):
        out = CommentedMap()
        for k, v in obj.items():
            out[k] = _to_commented(v)
        return out
    if isinstance(obj, list):
        out = CommentedSeq()
        for v in obj:
            out.append(_to_commented(v))
        return out
    return obj


def _dump_yaml_bytes(data: dict) -> bytes:
    buf = StringIO()
    _yaml_rt().dump(data, buf)
    return buf.getvalue().encode("utf-8")


def _atomic_write(path: str, data: bytes) -> None:
    """唯一临时名 + fsync + os.replace，多进程安全。"""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=directory,
        prefix=f"{os.path.basename(path)}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _parse_mapping(raw: bytes | None, path: str) -> CommentedMap:
    """解析 YAML 根节点为 CommentedMap；None / 空 -> 空映射。"""
    if raw is None or not raw.strip():
        return CommentedMap()
    loaded = _yaml_rt().load(raw.decode("utf-8"))
    if loaded is None:
        return CommentedMap()
    if not isinstance(loaded, dict):
        raise ValueError(
            f"全局配置文件根节点必须是映射(dict)，实际为 "
            f"{type(loaded).__name__}: {path}"
        )
    if isinstance(loaded, CommentedMap):
        return loaded
    return _to_commented(loaded)


def _token_comment_text(token: Any) -> str | None:
    """从 ruamel CommentToken（或列表）提取不含 # 的注释正文。"""
    if token is None:
        return None
    if isinstance(token, list):
        parts = [p for t in token if (p := _token_comment_text(t)) is not None]
        return "\n".join(parts) if parts else None
    val = getattr(token, "value", None)
    if not isinstance(val, str):
        return None
    lines: list[str] = []
    for line in val.splitlines():
        s = line.strip()
        if s.startswith("#"):
            s = s[1:].lstrip()
        lines.append(s)
    text = "\n".join(lines).strip("\n")
    return text if text != "" else None


def _read_eol_comment(parent: Any, key: Any) -> str | None:
    ca = getattr(parent, "ca", None)
    if ca is None:
        return None
    items = ca.items.get(key) if getattr(ca, "items", None) else None
    if not items:
        return None
    # CommentedMap 行尾注释多在 [2]；CommentedSeq 多在 [0]
    order = (0, 2, 1, 3) if isinstance(parent, list) else (2, 0, 1, 3)
    for idx in order:
        if idx < len(items) and items[idx] is not None:
            text = _token_comment_text(items[idx])
            if text is not None:
                return text
    return None


def _write_eol_comment(parent: Any, key: Any, text: str | None) -> None:
    if text is None or str(text).strip() == "":
        ca = getattr(parent, "ca", None)
        if ca is not None and getattr(ca, "items", None) is not None:
            ca.items.pop(key, None)
        return
    body = str(text).strip()
    if not hasattr(parent, "yaml_add_eol_comment"):
        raise TypeError(
            f"当前节点不支持注释：{type(parent).__name__}"
        )
    parent.yaml_add_eol_comment(body, key)


def _unwrap_assign_value(value: Any) -> Any:
    if isinstance(value, ConfigScalar):
        return _to_commented(copy.deepcopy(value.value))
    if isinstance(value, GlobalConfig):
        return _to_commented(value.to_dict())
    if isinstance(value, ConfigList):
        return _to_commented(value.to_list())
    return _to_commented(copy.deepcopy(value))


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
        self._data: dict | None = None
        self._baseline_hash: str | None = None
        self._conflict_backup: str | None = None

    @property
    def name(self) -> str:
        return self._name

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
        """把本管理器绑到 {directory}/{name}.yaml。"""
        with self._lock:
            self._path = os.path.join(
                os.path.abspath(os.path.expanduser(directory)),
                f"{self._name}.yaml",
            )
            self._data = None
            self._baseline_hash = None
            self._conflict_backup = None

    def _ensure_loaded(self) -> None:
        if self._data is None:
            self._load()

    def _load(self) -> None:
        path = self.resolve_path()
        raw = _read_bytes(path)
        self._data = _parse_mapping(raw, path)
        self._baseline_hash = _hash_bytes(raw)
        self._conflict_backup = None

    def reload(self) -> None:
        with self._lock:
            self._load()

    def _dump_bytes(self) -> bytes:
        assert self._data is not None
        return _dump_yaml_bytes(self._data)

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
            if self._conflict_backup is None:
                self._conflict_backup = self._new_conflict_path()
            _atomic_write(self._conflict_backup, new_bytes)
            raise ConfigConflictError(path, self._conflict_backup)

        _atomic_write(path, new_bytes)
        self._baseline_hash = _hash_bytes(new_bytes)
        self._conflict_backup = None

    def save(self) -> None:
        with self._lock:
            self._save()

    def has_unsaved_changes(self) -> bool:
        """内存内容与磁盘是否不一致（含 save_on_set=False 未落盘改动）。"""
        with self._lock:
            self._ensure_loaded()
            path = self.resolve_path()
            mem_hash = _hash_bytes(self._dump_bytes())
            disk_hash = _hash_bytes(_read_bytes(path))
            return mem_hash != disk_hash

    def apply_downloaded(self, raw: bytes) -> None:
        """用已校验的远端 YAML 字节整体替换磁盘与内存。"""
        with self._lock:
            path = self.resolve_path()
            data = _parse_mapping(raw, path)
            _atomic_write(path, raw)
            self._data = data
            self._baseline_hash = _hash_bytes(raw)
            self._conflict_backup = None

    def read_disk_bytes(self) -> bytes | None:
        return _read_bytes(self.resolve_path())

    def snapshot(self) -> dict:
        with self._lock:
            self._ensure_loaded()
            return _to_plain(self._data)

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
                "unsaved_changes": (
                    _hash_bytes(self._dump_bytes()) != disk_hash
                ),
            }

    # ── 路径导航（支持 dict 键与 list 下标混用）────────────────────────────

    def _walk(self, parts: list[Any], *, create_dicts: bool = False) -> Any:
        """走到 parts 指向的值；create_dicts 时缺失的 dict 层级自动创建。"""
        assert self._data is not None
        if not parts:
            return self._data
        cur: Any = self._data
        walked: list[Any] = []
        for i, part in enumerate(parts):
            walked.append(part)
            is_last = i == len(parts) - 1
            if isinstance(cur, dict):
                if part in cur:
                    nxt = cur[part]
                    if nxt is None and create_dicts and not is_last:
                        nxt = CommentedMap()
                        cur[part] = nxt
                    cur = nxt
                    continue
                if create_dicts:
                    nxt = CommentedMap() if not is_last else None
                    if not is_last:
                        cur[part] = nxt
                        cur = nxt
                        continue
                    raise KeyError(part)
                raise KeyError(part)
            if isinstance(cur, list):
                cur = cur[part]
                continue
            raise ValueError(
                f"配置键 {'.'.join(str(p) for p in walked)} 已存在且不是"
                f"字典/列表，无法继续嵌套访问"
            )
        return cur

    def _parent_and_key(
        self, parts: list[Any], *, create: bool
    ) -> tuple[Any, Any]:
        """返回 (parent_container, last_key)。"""
        if not parts:
            raise ValueError("空路径没有父容器")
        parent_parts = parts[:-1]
        key = parts[-1]
        if create:
            parent = self._ensure_container(parent_parts, for_key=key)
        else:
            parent = self._walk(parent_parts, create_dicts=False)
        return parent, key

    def _ensure_container(self, parts: list[Any], *, for_key: Any) -> Any:
        """确保 parts 指向可写容器（dict 或 list）。"""
        assert self._data is not None
        if not parts:
            return self._data
        cur: Any = self._data
        walked: list[Any] = []
        for i, part in enumerate(parts):
            walked.append(part)
            if isinstance(cur, dict):
                if part not in cur or cur[part] is None:
                    # 下一级若是 int 键且像 list 下标，仍创建 dict（配置键均为 str）
                    cur[part] = CommentedMap()
                nxt = cur[part]
                if not isinstance(nxt, (dict, list)):
                    raise ValueError(
                        f"配置键 {'.'.join(str(p) for p in walked)} "
                        f"已存在且不是字典/列表，无法继续嵌套访问"
                    )
                cur = nxt
            elif isinstance(cur, list):
                cur = cur[part]
            else:
                raise ValueError(
                    f"配置键 {'.'.join(str(p) for p in walked)} "
                    f"已存在且不是字典/列表，无法继续嵌套访问"
                )
        return cur

    def _section_dict(self, parts: list[Any], create: bool) -> dict | None:
        self._ensure_loaded()
        if not parts:
            assert self._data is not None
            return self._data
        try:
            if create:
                # 逐级创建缺失的 dict
                assert self._data is not None
                cur: Any = self._data
                walked: list[Any] = []
                for part in parts:
                    walked.append(part)
                    if isinstance(cur, dict):
                        if part not in cur or cur[part] is None:
                            cur[part] = CommentedMap()
                        nxt = cur[part]
                        if not isinstance(nxt, dict):
                            raise ValueError(
                                f"配置键 {'.'.join(str(p) for p in walked)} "
                                f"已存在且不是字典，无法继续嵌套访问"
                            )
                        cur = nxt
                    elif isinstance(cur, list):
                        nxt = cur[part]
                        if not isinstance(nxt, dict):
                            raise ValueError(
                                f"配置键 {'.'.join(str(p) for p in walked)} "
                                f"不是字典，无法继续嵌套访问"
                            )
                        cur = nxt
                    else:
                        raise ValueError(
                            f"配置键 {'.'.join(str(p) for p in walked)} "
                            f"已存在且不是字典，无法继续嵌套访问"
                        )
                return cur
            val = self._walk(parts, create_dicts=False)
            if val is None:
                return None
            if not isinstance(val, dict):
                return None
            return val
        except (KeyError, IndexError, TypeError):
            return None

    def get_config(self, save_on_set: bool) -> GlobalConfig:
        with self._lock:
            self._ensure_loaded()
            return GlobalConfig(self, [], save_on_set)

    def section_get(self, parts: list[Any], key: Any) -> tuple[str, Any]:
        """
        一次加锁读取：返回 (kind, value)。

        kind: "dict" | "list" | "scalar"；scalar 时 value 为深拷贝。
        """
        with self._lock:
            self._ensure_loaded()
            d = self._section_dict(parts, create=False)
            if not isinstance(d, dict) or key not in d:
                raise KeyError(key)
            val = d[key]
            if isinstance(val, dict):
                return "dict", None
            if isinstance(val, list):
                return "list", None
            return "scalar", copy.deepcopy(val)

    def section_is_mapping(self, parts: list[Any], key: Any) -> bool:
        kind, _ = self.section_get(parts, key)
        return kind == "dict"

    def section_getitem(self, parts: list[Any], key: Any) -> Any:
        kind, val = self.section_get(parts, key)
        if kind != "scalar":
            raise TypeError(f"section_getitem 仅用于标量，实际为 {kind}")
        return val

    def section_setitem(
        self, parts: list[Any], key: Any, value: Any, save: bool
    ) -> None:
        with self._lock:
            self._ensure_loaded()
            value = _unwrap_assign_value(value)
            d = self._section_dict(parts, create=True)
            assert d is not None
            d[key] = value
            if save:
                self._save()

    def section_update(
        self, parts: list[Any], mapping: dict, save: bool
    ) -> None:
        with self._lock:
            self._ensure_loaded()
            d = self._section_dict(parts, create=True)
            assert d is not None
            for k, v in mapping.items():
                d[k] = _unwrap_assign_value(v)
            if save:
                self._save()

    def section_clear(self, parts: list[Any], save: bool) -> None:
        with self._lock:
            self._ensure_loaded()
            d = self._section_dict(parts, create=False)
            if d is None:
                return
            d.clear()
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
            return {} if d is None else _to_plain(d)

    def get_scalar_value(self, parts: list[Any]) -> Any:
        with self._lock:
            self._ensure_loaded()
            val = self._walk(parts, create_dicts=False)
            if isinstance(val, (dict, list)):
                raise TypeError(
                    f"路径 {parts!r} 不是标量，实际为 {type(val).__name__}"
                )
            return copy.deepcopy(val)

    def get_key_comment(self, parts: list[Any]) -> str | None:
        """返回 parts 所指键的行尾注释（不含 #）。根节点无注释。"""
        with self._lock:
            self._ensure_loaded()
            if not parts:
                return None
            parent = self._walk(parts[:-1], create_dicts=False)
            return _read_eol_comment(parent, parts[-1])

    def set_key_comment(
        self, parts: list[Any], text: str | None, save: bool
    ) -> None:
        with self._lock:
            self._ensure_loaded()
            if not parts:
                raise ValueError("根配置不支持 .comment")
            parent = self._walk(parts[:-1], create_dicts=False)
            key = parts[-1]
            # 确认键存在
            if isinstance(parent, dict):
                if key not in parent:
                    raise KeyError(key)
            elif isinstance(parent, list):
                _ = parent[key]
            else:
                raise TypeError(
                    f"无法为 {type(parent).__name__} 设置注释"
                )
            _write_eol_comment(parent, key, text)
            if save:
                self._save()

    # ── list 视图操作 ─────────────────────────────────────────────────────

    def _list_at(self, parts: list[Any]) -> list:
        self._ensure_loaded()
        val = self._walk(parts, create_dicts=False)
        if not isinstance(val, list):
            raise TypeError(
                f"路径 {parts!r} 不是 list，实际为 {type(val).__name__}"
            )
        return val

    def list_get(self, parts: list[Any], index: int) -> tuple[str, Any]:
        with self._lock:
            lst = self._list_at(parts)
            val = lst[index]
            if isinstance(val, dict):
                return "dict", None
            if isinstance(val, list):
                return "list", None
            return "scalar", copy.deepcopy(val)

    def list_set(self, parts: list[Any], index: int, value: Any, save: bool) -> None:
        with self._lock:
            lst = self._list_at(parts)
            lst[index] = _unwrap_assign_value(value)
            if save:
                self._save()

    def list_del(self, parts: list[Any], index: int, save: bool) -> None:
        with self._lock:
            lst = self._list_at(parts)
            del lst[index]
            if save:
                self._save()

    def list_insert(
        self, parts: list[Any], index: int, value: Any, save: bool
    ) -> None:
        with self._lock:
            lst = self._list_at(parts)
            lst.insert(index, _unwrap_assign_value(value))
            if save:
                self._save()

    def list_len(self, parts: list[Any]) -> int:
        with self._lock:
            return len(self._list_at(parts))

    def list_to_list(self, parts: list[Any]) -> list:
        with self._lock:
            return _to_plain(self._list_at(parts))

    def list_sort(
        self, parts: list[Any], *, key=None, reverse: bool = False, save: bool = True
    ) -> None:
        with self._lock:
            lst = self._list_at(parts)
            lst.sort(key=key, reverse=reverse)
            if save:
                self._save()


class _ConfigRegistry:
    """按名称管理多个配置文件实例；同名共享同一管理器。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._managers: dict[str, _GlobalConfigManager] = {}
        self._default_path: str | None = None

    def config_dir(self) -> str:
        with self._lock:
            return self._config_dir()

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

    def known_names(self) -> list[str]:
        with self._lock:
            return list(self._managers.keys())

    def set_default_path(self, path: str) -> None:
        """指定默认配置文件路径，并让具名配置使用同一目录。"""
        with self._lock:
            self._default_path = os.path.abspath(os.path.expanduser(str(path)))
            directory = os.path.dirname(self._default_path) or "."
            for name, mgr in self._managers.items():
                if name == _DEFAULT_NAME:
                    mgr.set_path(self._default_path)
                else:
                    mgr.bind_directory(directory)

    def default_manager(self) -> _GlobalConfigManager:
        return self.get_manager(_DEFAULT_NAME)


class GlobalConfig(MutableMapping):
    """
    get_global 返回的可读可写配置对象，用起来就像普通 dict。

    - save_on_set=True 时，每次赋值 / 删除都会立即落盘；
    - 取到的 dict 仍是可写视图；list 返回 ConfigList；
      标量返回 ConfigScalar（可用 .comment / .value）；
    - 落盘前会检测文件是否被别的程序改过。
    """

    def __init__(
        self,
        manager: _GlobalConfigManager,
        parts: list[Any],
        save_on_set: bool,
    ) -> None:
        self._manager = manager
        self._parts = list(parts)
        self._save_on_set = bool(save_on_set)

    def __getitem__(self, key: Any) -> Any:
        kind, _val = self._manager.section_get(self._parts, key)
        if kind == "dict":
            return GlobalConfig(
                self._manager, self._parts + [key], self._save_on_set
            )
        if kind == "list":
            return ConfigList(
                self._manager, self._parts + [key], self._save_on_set
            )
        return ConfigScalar(
            self._manager, self._parts + [key], self._save_on_set
        )

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

    def update(self, other=(), /, **kwargs) -> None:  # type: ignore[override]
        mapping = dict(other, **kwargs) if kwargs else dict(other)
        self._manager.section_update(self._parts, mapping, self._save_on_set)

    def clear(self) -> None:
        self._manager.section_clear(self._parts, self._save_on_set)

    def has(self, key: object) -> bool:
        """判断当前这一层是否存在 key（等价于 key in cfg）。"""
        return key in self

    def keys(self) -> list:  # type: ignore[override]
        """
        返回当前层键名的普通 list。

        这里故意不返回 MutableMapping 默认的 KeysView：交互打印时
        KeysView 会嵌套整份 GlobalConfig 的冗长 repr，看起来不像 dict。
        需要标准视图时用 keys_view()。

            >>> cfg.keys()       # ['theme', 'default_slot']
            >>> cfg.keys_view()  # KeysView(...)
        """
        return self._manager.section_keys(self._parts)

    def keys_view(self):
        """
        返回标准的 KeysView（与 collections.abc.Mapping.keys 相同）。

        一般查看键名请用 keys()；本方法留给需要视图语义
        （随映射变化、可做集合运算等）的场景。
        """
        return super().keys()

    @property
    def comment(self) -> str | None:
        """本节点在父级中的行尾注释（根配置为 None）。"""
        return self._manager.get_key_comment(self._parts)

    @comment.setter
    def comment(self, text: str | None) -> None:
        self._manager.set_key_comment(self._parts, text, self._save_on_set)

    def path(self) -> str:
        """返回本配置实例对应的 YAML 文件路径。"""
        return self._manager.resolve_path()

    def to_dict(self) -> dict:
        """返回该 config（当前子树）的深拷贝（普通 dict）。"""
        return self._manager.section_to_dict(self._parts)

    def snapshot(self) -> dict:
        """返回整份配置文件的深拷贝（不只是当前子树）。"""
        if self._parts:
            return self.to_dict()
        return self._manager.snapshot()

    def status(self) -> dict:
        """返回本文件状态（含同步相关字段，由上层注入时扩展）。"""
        return self._manager.status()

    def save(self) -> None:
        """把本文件落盘（用于 save_on_set=False 时批量修改后手动保存）。"""
        self._manager.save()

    def reload(self) -> None:
        """丢弃内存快照，重新从磁盘加载（也会清除冲突状态）。"""
        self._manager.reload()

    def __repr__(self) -> str:
        sub = ".".join(str(p) for p in self._parts) if self._parts else "<root>"
        return (
            f"GlobalConfig(name={self._manager.name!r}, section={sub!r}, "
            f"save_on_set={self._save_on_set}, data={self.to_dict()!r})"
        )


class ConfigScalar:
    """
    标量配置值的包装：可用 == / .value 取值，用 .comment 读写行尾注释。

    Example:
        >>> cfg["xx"] = 1
        >>> cfg["xx"].comment = "注释 abc"
        >>> cfg["xx"].comment
        '注释 abc'
        >>> cfg["xx"] == 1
        True
    """

    def __init__(
        self,
        manager: _GlobalConfigManager,
        parts: list[Any],
        save_on_set: bool,
    ) -> None:
        self._manager = manager
        self._parts = list(parts)
        self._save_on_set = bool(save_on_set)

    @property
    def value(self) -> Any:
        """底层 Python 标量。"""
        return self._manager.get_scalar_value(self._parts)

    @property
    def comment(self) -> str | None:
        return self._manager.get_key_comment(self._parts)

    @comment.setter
    def comment(self, text: str | None) -> None:
        self._manager.set_key_comment(self._parts, text, self._save_on_set)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ConfigScalar):
            return self.value == other.value
        return self.value == other

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return hash(self.value)

    def __bool__(self) -> bool:
        return bool(self.value)

    def __str__(self) -> str:
        return str(self.value)

    def __repr__(self) -> str:
        return f"ConfigScalar({self.value!r})"

    def __int__(self) -> int:
        return int(self.value)

    def __float__(self) -> float:
        return float(self.value)

    def __index__(self) -> int:
        return self.value.__index__()


class ConfigList(MutableSequence):
    """list 可写回写视图：原地修改会写回配置并按 save_on_set 落盘。"""

    def __init__(
        self,
        manager: _GlobalConfigManager,
        parts: list[Any],
        save_on_set: bool,
    ) -> None:
        self._manager = manager
        self._parts = list(parts)
        self._save_on_set = bool(save_on_set)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return self.to_list()[index]
        kind, _val = self._manager.list_get(self._parts, index)
        if kind == "dict":
            return GlobalConfig(
                self._manager, self._parts + [index], self._save_on_set
            )
        if kind == "list":
            return ConfigList(
                self._manager, self._parts + [index], self._save_on_set
            )
        return ConfigScalar(
            self._manager, self._parts + [index], self._save_on_set
        )

    def __setitem__(self, index, value) -> None:
        if isinstance(index, slice):
            raise TypeError("ConfigList 暂不支持 slice 赋值")
        self._manager.list_set(self._parts, index, value, self._save_on_set)

    def __delitem__(self, index) -> None:
        if isinstance(index, slice):
            raise TypeError("ConfigList 暂不支持 slice 删除")
        self._manager.list_del(self._parts, index, self._save_on_set)

    def __len__(self) -> int:
        return self._manager.list_len(self._parts)

    def insert(self, index: int, value: Any) -> None:
        self._manager.list_insert(self._parts, index, value, self._save_on_set)

    def sort(self, *, key=None, reverse: bool = False) -> None:
        self._manager.list_sort(
            self._parts, key=key, reverse=reverse, save=self._save_on_set
        )

    @property
    def comment(self) -> str | None:
        """本 list 在父级中的行尾注释。"""
        return self._manager.get_key_comment(self._parts)

    @comment.setter
    def comment(self, text: str | None) -> None:
        self._manager.set_key_comment(self._parts, text, self._save_on_set)

    def to_list(self) -> list:
        """返回普通 list 深拷贝（脱离视图）。"""
        return self._manager.list_to_list(self._parts)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ConfigList):
            return self.to_list() == other.to_list()
        if isinstance(other, list):
            return self.to_list() == other
        return NotImplemented

    def __repr__(self) -> str:
        return f"ConfigList({self.to_list()!r})"
