"""配置远端后端协议与数据类。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class RemoteConflictError(RuntimeError):
    """S3 条件写失败（412）：远端在读取后又被改动。"""

    def __init__(self, name: str, message: str | None = None) -> None:
        self.name = name
        super().__init__(message or f"远端配置已被其他端修改：{name}")


@dataclass
class RemoteConfig:
    name: str
    revision: str
    sha256: str
    content: str
    updated_at: str
    updated_by: str | None = None
    meta_etag: str | None = None
    content_key: str | None = None
    history_key: str | None = None


class ConfigBackend(Protocol):
    def get_meta(self, name: str) -> tuple[dict, str] | None:
        """返回 (meta_dict, etag)；对象不存在返回 None。"""
        ...

    def get(self, name: str) -> RemoteConfig | None:
        ...

    def put(
        self,
        name: str,
        content: str,
        *,
        expected_etag: str | None = None,
        create_only: bool = False,
    ) -> RemoteConfig:
        """条件失败抛 RemoteConflictError。"""
        ...

    def exists(self, name: str) -> bool:
        ...
