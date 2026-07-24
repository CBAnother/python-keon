"""同步状态文件 `.config_sync_state.json`（跨进程原子写 + filelock）。"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from typing import Any

from ..local import _atomic_write

_STATE_FILENAME = ".config_sync_state.json"

try:
    from filelock import FileLock
except ImportError:  # pragma: no cover
    FileLock = None  # type: ignore[misc, assignment]


@dataclass
class LocalSyncStateEntry:
    last_success_sync_time: str | None = None
    last_check_time: str | None = None
    last_sync_remote_revision: str | None = None
    last_sync_sha256: str | None = None
    last_sync_meta_etag: str | None = None
    conflict: bool = False
    paused: bool = False

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> LocalSyncStateEntry:
        if not d:
            return cls()
        return cls(
            last_success_sync_time=d.get("last_success_sync_time"),
            last_check_time=d.get("last_check_time"),
            last_sync_remote_revision=d.get("last_sync_remote_revision"),
            last_sync_sha256=d.get("last_sync_sha256"),
            last_sync_meta_etag=d.get("last_sync_meta_etag"),
            conflict=bool(d.get("conflict", False)),
            paused=bool(d.get("paused", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SyncStateFile:
    backend: str = "s3"
    bucket: str | None = None
    key_prefix: str | None = None
    configs: dict[str, LocalSyncStateEntry] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> SyncStateFile:
        if not d:
            return cls()
        configs = {
            k: LocalSyncStateEntry.from_dict(v)
            for k, v in (d.get("configs") or {}).items()
        }
        return cls(
            backend=d.get("backend") or "s3",
            bucket=d.get("bucket"),
            key_prefix=d.get("key_prefix"),
            configs=configs,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "bucket": self.bucket,
            "key_prefix": self.key_prefix,
            "configs": {k: v.to_dict() for k, v in self.configs.items()},
        }

    def entry(self, name: str) -> LocalSyncStateEntry:
        if name not in self.configs:
            self.configs[name] = LocalSyncStateEntry()
        return self.configs[name]


class SyncStateStore:
    """读写 `.config_sync_state.json`，读-改-写加文件锁。"""

    def __init__(self, directory: str) -> None:
        self._directory = os.path.abspath(directory)
        self._path = os.path.join(self._directory, _STATE_FILENAME)
        self._lock_path = self._path + ".lock"
        self._thread_lock = threading.RLock()

    @property
    def path(self) -> str:
        return self._path

    def _file_lock(self):
        if FileLock is None:
            return _NullLock()
        os.makedirs(self._directory, exist_ok=True)
        return FileLock(self._lock_path, timeout=30)

    def load(self) -> SyncStateFile:
        with self._thread_lock:
            with self._file_lock():
                return self._load_unlocked()

    def _load_unlocked(self) -> SyncStateFile:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return SyncStateFile()
        except (json.JSONDecodeError, OSError):
            return SyncStateFile()
        if not isinstance(data, dict):
            return SyncStateFile()
        return SyncStateFile.from_dict(data)

    def update(
        self,
        mutator,
        *,
        bucket: str | None = None,
        key_prefix: str | None = None,
    ) -> SyncStateFile:
        """
        在锁内加载、调用 ``mutator(state)``、写回。

        mutator 可就地修改 SyncStateFile。
        """
        with self._thread_lock:
            with self._file_lock():
                state = self._load_unlocked()
                if bucket is not None:
                    state.bucket = bucket
                if key_prefix is not None:
                    state.key_prefix = key_prefix
                mutator(state)
                raw = json.dumps(
                    state.to_dict(), ensure_ascii=False, indent=2
                ).encode("utf-8")
                _atomic_write(self._path, raw)
                return state

    def get_entry(self, name: str) -> LocalSyncStateEntry:
        return self.load().entry(name)


class _NullLock:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False
