"""S3 / MinIO 配置后端（meta 条件写 CAS）。"""

from __future__ import annotations

import hashlib
import json
import logging
import socket
from datetime import datetime, timezone
from typing import Any
from uuid import getnode

from ..backends.base import RemoteConfig, RemoteConflictError

logger = logging.getLogger(__name__)


def _machine_id() -> str:
    try:
        host = socket.gethostname()
    except OSError:
        host = "unknown"
    mac = getnode()
    short = hashlib.sha256(f"{host}-{mac}".encode()).hexdigest()[:8]
    return f"{host}-{short}"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _revision(sha256: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}-{sha256[:8]}"


class S3Backend:
    """基于 boto3 的 S3 / MinIO 后端。"""

    def __init__(self, settings: Any) -> None:
        try:
            import boto3
            from botocore.client import Config as BotoConfig
        except ImportError as e:
            raise ImportError(
                "云端同步需要 boto3，请先安装：pip install boto3"
            ) from e

        self._settings = settings
        kwargs: dict[str, Any] = {
            "service_name": "s3",
            "aws_access_key_id": settings.access_key,
            "aws_secret_access_key": settings.secret_key,
            "region_name": settings.region_name or "us-east-1",
            "config": BotoConfig(signature_version="s3v4"),
        }
        if settings.endpoint_url:
            kwargs["endpoint_url"] = settings.endpoint_url
        if settings.session_token:
            kwargs["aws_session_token"] = settings.session_token
        self._client = boto3.client(**kwargs)
        self._bucket_checked = False

    @property
    def bucket(self) -> str:
        return self._settings.bucket

    @property
    def key_prefix(self) -> str:
        return self._settings.key_prefix

    def content_key(self, name: str) -> str:
        return f"{self.key_prefix}/{name}.yaml"

    def meta_key(self, name: str) -> str:
        return f"{self.key_prefix}/{name}.meta.json"

    def history_key(self, name: str, revision: str) -> str:
        return f"{self.key_prefix}/history/{name}/{revision}.yaml"

    def ensure_bucket(self) -> None:
        if self._bucket_checked:
            return
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except Exception as e:
            code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
            raise RuntimeError(
                f"S3 bucket 不存在或不可访问：{self.bucket}（{code or e}）。"
                f"请预先创建 bucket，set_s3 不会自动创建。"
            ) from e
        self._bucket_checked = True

    def get_meta(self, name: str) -> tuple[dict, str] | None:
        self.ensure_bucket()
        key = self.meta_key(name)
        try:
            resp = self._client.get_object(Bucket=self.bucket, Key=key)
        except Exception as e:
            code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey", "NotFound"):
                return None
            # botocore ClientError 404
            if hasattr(e, "response"):
                status = e.response.get("ResponseMetadata", {}).get(
                    "HTTPStatusCode"
                )
                if status == 404:
                    return None
            raise
        body = resp["Body"].read()
        meta = json.loads(body.decode("utf-8"))
        etag = resp.get("ETag") or ""
        return meta, etag

    def get(self, name: str) -> RemoteConfig | None:
        result = self.get_meta(name)
        if result is None:
            return None
        meta, etag = result
        ckey = meta.get("content_key") or self.content_key(name)
        resp = self._client.get_object(Bucket=self.bucket, Key=ckey)
        content = resp["Body"].read().decode("utf-8")
        sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if sha != meta.get("sha256"):
            raise RuntimeError(
                f"远端 {name} 内容 sha256 与 meta 不一致，停止同步"
            )
        return RemoteConfig(
            name=name,
            revision=meta["revision"],
            sha256=sha,
            content=content,
            updated_at=meta.get("updated_at", ""),
            updated_by=meta.get("updated_by"),
            meta_etag=etag,
            content_key=ckey,
            history_key=meta.get("history_key"),
        )

    def put(
        self,
        name: str,
        content: str,
        *,
        expected_etag: str | None = None,
        create_only: bool = False,
    ) -> RemoteConfig:
        self.ensure_bucket()
        raw = content.encode("utf-8")
        sha = hashlib.sha256(raw).hexdigest()
        rev = _revision(sha)
        ckey = self.content_key(name)
        mkey = self.meta_key(name)
        hkey = self.history_key(name, rev)
        now = _utc_now_iso()
        meta = {
            "name": name,
            "revision": rev,
            "sha256": sha,
            "updated_at": now,
            "updated_by": _machine_id(),
            "content_key": ckey,
            "history_key": hkey,
        }
        meta_bytes = json.dumps(meta, ensure_ascii=False, indent=2).encode(
            "utf-8"
        )

        # 历史与内容先传（非提交点）
        self._client.put_object(Bucket=self.bucket, Key=hkey, Body=raw)
        self._client.put_object(Bucket=self.bucket, Key=ckey, Body=raw)

        put_kwargs: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": mkey,
            "Body": meta_bytes,
            "ContentType": "application/json",
        }
        if create_only:
            put_kwargs["IfNoneMatch"] = "*"
        elif expected_etag:
            # ETag 可能带引号，条件写需原样
            put_kwargs["IfMatch"] = expected_etag

        try:
            resp = self._client.put_object(**put_kwargs)
        except Exception as e:
            code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
            status = getattr(e, "response", {}).get("ResponseMetadata", {}).get(
                "HTTPStatusCode"
            )
            if code in ("PreconditionFailed", "412") or status == 412:
                raise RemoteConflictError(name) from e
            raise

        new_etag = resp.get("ETag") or ""
        return RemoteConfig(
            name=name,
            revision=rev,
            sha256=sha,
            content=content,
            updated_at=now,
            updated_by=meta["updated_by"],
            meta_etag=new_etag,
            content_key=ckey,
            history_key=hkey,
        )

    def exists(self, name: str) -> bool:
        return self.get_meta(name) is not None


class MemoryBackend:
    """进程内假后端，供测试使用。"""

    def __init__(self) -> None:
        self._meta: dict[str, dict] = {}
        self._content: dict[str, str] = {}
        self._etag: dict[str, str] = {}
        self._etag_counter = 0

    def _next_etag(self) -> str:
        self._etag_counter += 1
        return f'"{self._etag_counter}"'

    def get_meta(self, name: str) -> tuple[dict, str] | None:
        if name not in self._meta:
            return None
        return dict(self._meta[name]), self._etag[name]

    def get(self, name: str) -> RemoteConfig | None:
        result = self.get_meta(name)
        if result is None:
            return None
        meta, etag = result
        content = self._content[name]
        return RemoteConfig(
            name=name,
            revision=meta["revision"],
            sha256=meta["sha256"],
            content=content,
            updated_at=meta.get("updated_at", ""),
            updated_by=meta.get("updated_by"),
            meta_etag=etag,
        )

    def put(
        self,
        name: str,
        content: str,
        *,
        expected_etag: str | None = None,
        create_only: bool = False,
    ) -> RemoteConfig:
        exists = name in self._meta
        if create_only and exists:
            raise RemoteConflictError(name)
        if not create_only and expected_etag is not None:
            if not exists or self._etag.get(name) != expected_etag:
                raise RemoteConflictError(name)
        if not create_only and expected_etag is None and exists:
            # 无 etag 却已有对象：视为冲突（保守）
            raise RemoteConflictError(name)

        sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        rev = _revision(sha)
        now = _utc_now_iso()
        meta = {
            "name": name,
            "revision": rev,
            "sha256": sha,
            "updated_at": now,
            "updated_by": "memory",
            "content_key": f"{name}.yaml",
            "history_key": f"history/{name}/{rev}.yaml",
        }
        etag = self._next_etag()
        self._meta[name] = meta
        self._content[name] = content
        self._etag[name] = etag
        return RemoteConfig(
            name=name,
            revision=rev,
            sha256=sha,
            content=content,
            updated_at=now,
            updated_by="memory",
            meta_etag=etag,
        )

    def exists(self, name: str) -> bool:
        return name in self._meta
