"""S3 凭证与同步运行期设置。"""

from __future__ import annotations

import logging
import os
import sys
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

import yaml

from ..local import _DEFAULT_DIR, _atomic_write

if TYPE_CHECKING:
    from .conflict import ConflictEvent

logger = logging.getLogger(__name__)

_ENV_S3_CRED = "KEON_S3_CRED_PATH"
_S3_FILENAME = "s3.yaml"
DEFAULT_SYNC_INTERVAL = 300.0
DEFAULT_KEY_PREFIX = "keon-configs"


@dataclass
class S3Settings:
    endpoint_url: str | None
    bucket: str
    access_key: str
    secret_key: str
    key_prefix: str
    region_name: str | None = "us-east-1"
    session_token: str | None = None


def _default_conflict_mode() -> str:
    """交互环境默认 prompt，否则 raise。"""
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            return "prompt"
    except Exception:
        pass
    return "raise"


@dataclass
class SyncSettings:
    interval: float = DEFAULT_SYNC_INTERVAL
    conflict_mode: str = field(default_factory=_default_conflict_mode)
    on_update: Callable[[str], None] | None = None
    on_conflict: Callable[["ConflictEvent"], None] | None = None


def normalize_key_prefix(prefix: str) -> str:
    """去掉首尾多余的 ``/``。"""
    return prefix.strip().strip("/")


def default_cred_path() -> str:
    env = os.environ.get(_ENV_S3_CRED)
    if env:
        return os.path.abspath(os.path.expanduser(env))
    return os.path.join(_DEFAULT_DIR, _S3_FILENAME)


def _tighten_permissions(path: str) -> None:
    """POSIX 收紧为 0o600；目录建议 0o700。"""
    try:
        directory = os.path.dirname(path)
        if directory and os.path.isdir(directory):
            os.chmod(directory, 0o700)
        os.chmod(path, 0o600)
    except OSError:
        # Windows 等可能不支持同样语义
        pass


def load_s3_settings_from_file(path: str | None = None) -> S3Settings | None:
    cred = path or default_cred_path()
    try:
        with open(cred, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        return None
    except OSError as e:
        logger.warning("读取 S3 凭证失败：%s", e)
        return None
    if not isinstance(data, dict):
        return None
    bucket = data.get("bucket")
    access_key = data.get("access_key")
    secret_key = data.get("secret_key")
    if not bucket or not access_key or not secret_key:
        logger.warning("s3.yaml 缺少必要字段（bucket/access_key/secret_key）")
        return None
    key_prefix = data.get("key_prefix")
    if key_prefix is None or str(key_prefix).strip() == "":
        key_prefix = DEFAULT_KEY_PREFIX
    return S3Settings(
        endpoint_url=data.get("endpoint_url"),
        bucket=str(bucket),
        access_key=str(access_key),
        secret_key=str(secret_key),
        key_prefix=normalize_key_prefix(str(key_prefix)),
        region_name=data.get("region_name", "us-east-1"),
        session_token=data.get("session_token"),
    )


def save_s3_settings(settings: S3Settings, path: str | None = None) -> str:
    cred = path or default_cred_path()
    directory = os.path.dirname(cred)
    if directory:
        os.makedirs(directory, exist_ok=True)
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass
    data = {
        "endpoint_url": settings.endpoint_url,
        "bucket": settings.bucket,
        "access_key": settings.access_key,
        "secret_key": settings.secret_key,
        "region_name": settings.region_name,
        "session_token": settings.session_token,
        "key_prefix": settings.key_prefix,
    }
    raw = yaml.safe_dump(
        data, allow_unicode=True, sort_keys=False, default_flow_style=False
    ).encode("utf-8")
    _atomic_write(cred, raw)
    _tighten_permissions(cred)
    return cred


class RuntimeStore:
    """模块级运行期状态：S3 设置、同步设置、backend 缓存。"""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.s3_settings: S3Settings | None = None
        self.s3_loaded_attempted = False
        self.sync_settings = SyncSettings()
        self._backend = None
        self._backend_key: tuple | None = None
        # 测试可注入
        self.backend_override = None

    def ensure_s3_loaded(self) -> S3Settings | None:
        with self.lock:
            if self.s3_settings is not None:
                return self.s3_settings
            if self.s3_loaded_attempted:
                return None
            self.s3_loaded_attempted = True
            self.s3_settings = load_s3_settings_from_file()
            return self.s3_settings

    def set_s3(self, settings: S3Settings, *, persist: bool, cred_path: str | None) -> None:
        with self.lock:
            self.s3_settings = settings
            self.s3_loaded_attempted = True
            self._backend = None
            self._backend_key = None
            if persist:
                save_s3_settings(settings, cred_path)

    def get_backend(self):
        with self.lock:
            if self.backend_override is not None:
                return self.backend_override
            settings = self.ensure_s3_loaded()
            if settings is None:
                return None
            key = (
                settings.endpoint_url,
                settings.bucket,
                settings.access_key,
                settings.key_prefix,
                settings.region_name,
                settings.session_token,
            )
            if self._backend is not None and self._backend_key == key:
                return self._backend
            from ..backends.s3 import S3Backend

            self._backend = S3Backend(settings)
            self._backend_key = key
            return self._backend
