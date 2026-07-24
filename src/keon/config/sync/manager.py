"""同步编排：init / sync / resolve_conflict / get_global 挂钩。"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable

from ..backends.base import RemoteConflictError
from ..local import _ConfigRegistry, _DEFAULT_NAME, _hash_bytes, _validate_name
from .conflict import (
    ConflictEvent,
    SyncConflictError,
    clear_conflict_snapshots,
    cli_choose,
    dump_mapping,
    read_conflict_local,
    read_conflict_remote,
    save_conflict_snapshots,
    validate_yaml_mapping_text,
)
from .scheduler import SyncScheduler
from .settings import (
    DEFAULT_KEY_PREFIX,
    DEFAULT_SYNC_INTERVAL,
    RuntimeStore,
    S3Settings,
    normalize_key_prefix,
)
from .state import SyncStateStore

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        # 支持 ...Z
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts).timestamp()
    except ValueError:
        return None


class SyncManager:
    """云端同步总控。"""

    def __init__(self, registry: _ConfigRegistry) -> None:
        self._registry = registry
        self._runtime = RuntimeStore()
        self._lock = threading.RLock()
        self._syncing: set[str] = set()
        self._scheduler = SyncScheduler(
            sync_fn=self._background_sync_one,
            interval_getter=lambda: self._runtime.sync_settings.interval,
            paused_checker=self._is_paused,
        )
        # 本进程已 kick 过的 name（避免同进程重复首次检查）
        self._kicked: set[str] = set()

    @property
    def runtime(self) -> RuntimeStore:
        return self._runtime

    def _state_store(self) -> SyncStateStore:
        return SyncStateStore(self._registry.config_dir())

    def _is_paused(self, name: str) -> bool:
        try:
            entry = self._state_store().get_entry(name)
            return bool(entry.paused or entry.conflict)
        except Exception:
            return False

    def set_s3(
        self,
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
        settings = S3Settings(
            endpoint_url=endpoint_url,
            bucket=bucket,
            access_key=access_key,
            secret_key=secret_key,
            key_prefix=normalize_key_prefix(key_prefix),
            region_name=region_name,
            session_token=session_token,
        )
        self._runtime.set_s3(settings, persist=persist, cred_path=cred_path)

    def set_on_update(self, cb: Callable[[str], None] | None) -> None:
        with self._runtime.lock:
            self._runtime.sync_settings.on_update = cb

    def set_on_conflict(self, cb: Callable[[ConflictEvent], None] | None) -> None:
        with self._runtime.lock:
            self._runtime.sync_settings.on_conflict = cb

    def init(
        self,
        *,
        wait: bool = False,
        force: bool = False,
        sync_interval: float | None = None,
        conflict_mode: str | None = None,
        on_update: Callable[[str], None] | None = None,
        on_conflict: Callable[[ConflictEvent], None] | None = None,
    ) -> None:
        with self._runtime.lock:
            s = self._runtime.sync_settings
            if sync_interval is not None:
                s.interval = float(sync_interval)
            if conflict_mode is not None:
                if conflict_mode not in ("prompt", "raise"):
                    raise ValueError(
                        f"conflict_mode 必须是 prompt 或 raise，收到 {conflict_mode!r}"
                    )
                s.conflict_mode = conflict_mode
            if on_update is not None:
                s.on_update = on_update
            if on_conflict is not None:
                s.on_conflict = on_conflict

        if self._runtime.ensure_s3_loaded() is None:
            return

        self._scheduler.ensure_running()
        if force:
            self.sync(force=True, wait=wait)
        elif wait:
            self.sync(force=False, wait=True)

    def start_auto_sync(self, interval: float | None = None) -> None:
        if interval is not None:
            with self._runtime.lock:
                self._runtime.sync_settings.interval = float(interval)
        if self._runtime.ensure_s3_loaded() is None:
            logger.info("未配置 S3，start_auto_sync 无效")
            return
        # 登记已有管理器
        for name in self._registry.known_names():
            if not self.is_sync_enabled(name):
                continue
            self._scheduler.register(name, due_immediately=False)
        self._scheduler.ensure_running()

    def stop_auto_sync(self) -> None:
        self._scheduler.stop()

    def on_get_global(self, name: str, *, sync: bool | None = None) -> None:
        """
        get_global 挂钩。

        - ``sync=False``：禁用该 name 同步并写入状态文件（跨进程持久）
        - ``sync=True``：强制重新启用并登记
        - ``sync=None``（未指定）：读状态文件；已禁用则保持，否则登记同步
        """
        if sync is False:
            self._persist_sync_enabled(name, False)
            self._scheduler.unregister(name)
            self._kicked.discard(name)
            return

        if sync is True:
            self._persist_sync_enabled(name, True)
        elif not self.is_sync_enabled(name):
            return

        if self._runtime.ensure_s3_loaded() is None:
            return
        first = name not in self._kicked
        self._scheduler.register(name, due_immediately=first)
        if first:
            self._kicked.add(name)
            if not self._throttled(name):
                self._scheduler.kick(name)

    def is_sync_enabled(self, name: str) -> bool:
        """是否允许同步（读 `.config_sync_state.json`，默认 True）。"""
        try:
            return bool(self._state_store().get_entry(name).sync_enabled)
        except Exception:
            return True

    def _persist_sync_enabled(self, name: str, enabled: bool) -> None:
        settings = self._runtime.s3_settings or self._runtime.ensure_s3_loaded()
        bucket = settings.bucket if settings else None
        prefix = settings.key_prefix if settings else None

        def mut(state):
            state.entry(name).sync_enabled = enabled

        self._state_store().update(mut, bucket=bucket, key_prefix=prefix)

    def _throttled(self, name: str, *, force: bool = False) -> bool:
        if force:
            return False
        entry = self._state_store().get_entry(name)
        last = _parse_iso(entry.last_check_time)
        if last is None:
            return False
        interval = self._runtime.sync_settings.interval
        return (datetime.now(timezone.utc).timestamp() - last) < interval

    def sync(
        self,
        *,
        force: bool = False,
        wait: bool = True,
        name: str | None = None,
    ) -> None:
        if self._runtime.ensure_s3_loaded() is None and self._runtime.backend_override is None:
            logger.info("未配置 S3，跳过 sync")
            return

        if name is None:
            names = list(
                dict.fromkeys(
                    self._scheduler.registered_names()
                    + self._registry.known_names()
                    + list(self._state_store().load().configs.keys())
                )
            )
            if not names:
                names = [_DEFAULT_NAME]
            names = [n for n in names if self.is_sync_enabled(n)]
        else:
            names = [_validate_name(name)]
            if not self.is_sync_enabled(names[0]) and not force:
                logger.info(
                    "配置 %s 已 get_global(sync=False)，跳过 sync；"
                    "可用 sync(force=True) 或 get_global(sync=True) 后再同步",
                    names[0],
                )
                return

        for n in names:
            self._scheduler.register(n, due_immediately=False)

        if wait:
            for n in names:
                self.sync_one(n, force=force, interactive=True)
        else:
            for n in names:
                self._scheduler.kick(n)
            self._scheduler.ensure_running()

    def _background_sync_one(self, name: str) -> None:
        try:
            self.sync_one(name, force=False, interactive=False)
        except SyncConflictError:
            # 已置 conflict / 回调
            pass
        except Exception:
            logger.exception("后台同步 %s 出错", name)

    def sync_one(
        self,
        name: str,
        *,
        force: bool = False,
        interactive: bool = False,
    ) -> None:
        # 等待同名进行中的同步结束，避免前台 sync(wait=True) 与后台 kick 互相跳过
        while True:
            with self._lock:
                if name not in self._syncing:
                    self._syncing.add(name)
                    break
            time.sleep(0.02)
        try:
            self._sync_one_impl(name, force=force, interactive=interactive)
        finally:
            with self._lock:
                self._syncing.discard(name)

    def _touch_check_time(self, name: str) -> None:
        settings = self._runtime.s3_settings
        bucket = settings.bucket if settings else None
        prefix = settings.key_prefix if settings else None

        def mut(state):
            e = state.entry(name)
            e.last_check_time = _utc_now_iso()

        self._state_store().update(mut, bucket=bucket, key_prefix=prefix)

    def _sync_one_impl(
        self, name: str, *, force: bool, interactive: bool
    ) -> None:
        if not self.is_sync_enabled(name) and not force:
            logger.debug("配置 %s 已禁用同步，跳过", name)
            return

        backend = self._runtime.get_backend()
        if backend is None:
            return

        store = self._state_store()
        entry = store.get_entry(name)
        if (entry.paused or entry.conflict) and not force:
            logger.debug("配置 %s 处于冲突/暂停，跳过自动同步", name)
            return

        if self._throttled(name, force=force):
            logger.debug("配置 %s 跨进程节流，跳过检查", name)
            return

        self._touch_check_time(name)

        mgr = self._registry.get_manager(name)
        # 确保已加载，便于检测未落盘改动
        mgr.snapshot()

        disk_raw = mgr.read_disk_bytes()
        local_sha = _hash_bytes(disk_raw)
        local_text = (
            disk_raw.decode("utf-8") if disk_raw is not None else ""
        )
        local_exists = disk_raw is not None

        settings = self._runtime.s3_settings
        bucket = settings.bucket if settings else None
        prefix = settings.key_prefix if settings else None

        try:
            meta_result = backend.get_meta(name)
        except Exception:
            logger.exception("访问 S3 meta 失败（%s），继续使用本地", name)
            return

        base_sha = entry.last_sync_sha256
        base_rev = entry.last_sync_remote_revision
        has_base = base_sha is not None or base_rev is not None

        # ── 首次同步 ──
        if not has_base:
            if meta_result is None and not local_exists:
                return
            if meta_result is None and local_exists:
                self._do_upload(
                    name, mgr, local_text, expected_etag=None, create_only=True,
                    bucket=bucket, prefix=prefix,
                )
                return
            if meta_result is not None and not local_exists:
                self._do_download(name, mgr, backend, meta_result,
                                  bucket=bucket, prefix=prefix)
                return
            # 双方都有、无 base → 冲突
            remote = backend.get(name)
            if remote is None:
                return
            self._enter_conflict(
                name,
                base_sha256=None,
                local_sha256=local_sha or hashlib.sha256(b"").hexdigest(),
                local_text=local_text or "{}\n",
                remote=remote,
                interactive=interactive,
                bucket=bucket,
                prefix=prefix,
            )
            return

        # ── 有 base ──
        if meta_result is None:
            # 远端被删：若本地相对 base 有变则上传重建；否则视为远端空
            if local_sha != base_sha and local_exists:
                self._do_upload(
                    name, mgr, local_text, expected_etag=None, create_only=True,
                    bucket=bucket, prefix=prefix,
                )
            return

        meta, _etag = meta_result
        remote_rev = meta.get("revision")
        remote_sha = meta.get("sha256")

        local_changed = local_sha != base_sha
        remote_changed = remote_rev != base_rev

        if not local_changed and not remote_changed:
            return

        if local_changed and not remote_changed:
            self._do_upload(
                name,
                mgr,
                local_text,
                expected_etag=entry.last_sync_meta_etag,
                create_only=False,
                bucket=bucket,
                prefix=prefix,
            )
            return

        if remote_changed and not local_changed:
            # 未落盘内存改动：转冲突，避免静默覆盖
            if mgr.has_unsaved_changes():
                remote = backend.get(name)
                if remote is None:
                    return
                self._enter_conflict(
                    name,
                    base_sha256=base_sha,
                    local_sha256=local_sha or "",
                    local_text=dump_mapping(mgr.snapshot()),
                    remote=remote,
                    interactive=interactive,
                    bucket=bucket,
                    prefix=prefix,
                )
                return
            self._do_download(
                name, mgr, backend, meta_result, bucket=bucket, prefix=prefix
            )
            return

        # 双方都变
        remote = backend.get(name)
        if remote is None:
            return
        # 若内容其实相同（sha 一致）则对齐状态
        if remote.sha256 == local_sha:
            self._update_state_success(
                name,
                revision=remote.revision,
                sha256=remote.sha256,
                meta_etag=remote.meta_etag,
                bucket=bucket,
                prefix=prefix,
            )
            return
        self._enter_conflict(
            name,
            base_sha256=base_sha,
            local_sha256=local_sha or "",
            local_text=local_text or "{}\n",
            remote=remote,
            interactive=interactive,
            bucket=bucket,
            prefix=prefix,
        )

    def _do_upload(
        self,
        name,
        mgr,
        local_text: str,
        *,
        expected_etag: str | None,
        create_only: bool,
        bucket,
        prefix,
    ) -> None:
        backend = self._runtime.get_backend()
        if backend is None:
            return
        # 空文件按空 mapping 上传
        if not local_text.strip():
            local_text = "{}\n"
        try:
            validate_yaml_mapping_text(local_text, name)
        except ValueError:
            logger.error("本地 %s 根节点不是 mapping，跳过上传", name)
            return
        try:
            remote = backend.put(
                name,
                local_text,
                expected_etag=expected_etag,
                create_only=create_only,
            )
        except RemoteConflictError:
            # CAS 失败 → 当作远端已变，拉远端进冲突
            remote_cfg = backend.get(name)
            if remote_cfg is None:
                logger.warning("CAS 失败且无法读取远端 %s", name)
                return
            self._enter_conflict(
                name,
                base_sha256=self._state_store().get_entry(name).last_sync_sha256,
                local_sha256=_hash_bytes(local_text.encode("utf-8")) or "",
                local_text=local_text,
                remote=remote_cfg,
                interactive=False,
                bucket=bucket,
                prefix=prefix,
            )
            return
        self._update_state_success(
            name,
            revision=remote.revision,
            sha256=remote.sha256,
            meta_etag=remote.meta_etag,
            bucket=bucket,
            prefix=prefix,
        )
        # 对齐本地 baseline（内容未变，仅刷新 hash）
        mgr.reload()

    def _do_download(
        self, name, mgr, backend, meta_result, *, bucket, prefix
    ) -> None:
        remote = backend.get(name)
        if remote is None:
            return
        try:
            validate_yaml_mapping_text(remote.content, f"remote:{name}")
        except ValueError as e:
            logger.error("远端 %s YAML 非法，不替换本地：%s", name, e)
            return
        raw = remote.content.encode("utf-8")
        changed = True
        entry = self._state_store().get_entry(name)
        if entry.last_sync_remote_revision == remote.revision:
            changed = False
        mgr.apply_downloaded(raw)
        self._update_state_success(
            name,
            revision=remote.revision,
            sha256=remote.sha256,
            meta_etag=remote.meta_etag,
            bucket=bucket,
            prefix=prefix,
        )
        if changed:
            self._fire_on_update(name)

    def _update_state_success(
        self, name, *, revision, sha256, meta_etag, bucket, prefix
    ) -> None:
        def mut(state):
            e = state.entry(name)
            e.last_success_sync_time = _utc_now_iso()
            e.last_check_time = e.last_success_sync_time
            e.last_sync_remote_revision = revision
            e.last_sync_sha256 = sha256
            e.last_sync_meta_etag = meta_etag
            e.conflict = False
            e.paused = False

        self._state_store().update(mut, bucket=bucket, key_prefix=prefix)
        clear_conflict_snapshots(self._registry.config_dir(), name)

    def _enter_conflict(
        self,
        name: str,
        *,
        base_sha256: str | None,
        local_sha256: str,
        local_text: str,
        remote,
        interactive: bool,
        bucket,
        prefix,
    ) -> None:
        config_dir = self._registry.config_dir()
        # base 内容：若有 sha 但无文件，写空提示
        base_yaml = None
        cdir = save_conflict_snapshots(
            config_dir,
            name,
            base_yaml=base_yaml,
            local_yaml=local_text,
            remote_yaml=remote.content,
        )
        event = ConflictEvent(
            name=name,
            base_sha256=base_sha256,
            local_sha256=local_sha256,
            remote_revision=remote.revision,
            conflict_dir=cdir,
        )

        def mut(state):
            e = state.entry(name)
            e.conflict = True
            e.paused = True

        self._state_store().update(mut, bucket=bucket, key_prefix=prefix)

        mode = self._runtime.sync_settings.conflict_mode
        if interactive and mode == "prompt":
            choice = cli_choose(local_text, remote.content, base_yaml)
            if choice in ("use_local", "use_remote"):
                self.resolve_conflict(name, choice)
                return
            # cancel / show_diff 后仍 conflict
            self._fire_on_conflict(event)
            raise SyncConflictError(event)

        self._fire_on_conflict(event)
        if mode == "raise" or interactive:
            raise SyncConflictError(event)

    def _fire_on_update(self, name: str) -> None:
        cb = self._runtime.sync_settings.on_update
        if cb is None:
            logger.info("配置 %s 已从云端更新", name)
            return
        try:
            cb(name)
        except Exception:
            logger.exception("on_update(%s) 回调异常", name)

    def _fire_on_conflict(self, event: ConflictEvent) -> None:
        cb = self._runtime.sync_settings.on_conflict
        if cb is None:
            logger.warning(
                "配置 %s 本地↔云端冲突，目录 %s",
                event.name,
                event.conflict_dir,
            )
            return
        try:
            cb(event)
        except Exception:
            logger.exception("on_conflict(%s) 回调异常", event.name)

    def resolve_conflict(
        self, name: str, choice: str | None = None
    ) -> None:
        name = _validate_name(name)
        if choice is None:
            local = read_conflict_local(self._registry.config_dir(), name)
            remote = read_conflict_remote(self._registry.config_dir(), name)
            if local is None or remote is None:
                raise RuntimeError(f"没有找到 {name} 的冲突快照")
            choice = cli_choose(local, remote)

        if choice == "cancel" or choice == "show_diff":
            return
        if choice not in ("use_local", "use_remote"):
            raise ValueError(
                f"choice 必须是 use_local / use_remote / show_diff / cancel，"
                f"收到 {choice!r}"
            )

        settings = self._runtime.ensure_s3_loaded()
        backend = self._runtime.get_backend()
        if backend is None:
            raise RuntimeError("未配置 S3，无法 resolve_conflict")

        bucket = settings.bucket if settings else None
        prefix = settings.key_prefix if settings else None
        mgr = self._registry.get_manager(name)
        config_dir = self._registry.config_dir()

        if choice == "use_local":
            local = read_conflict_local(config_dir, name)
            if local is None:
                raw = mgr.read_disk_bytes()
                local = raw.decode("utf-8") if raw else "{}\n"
            # 解决冲突时故意覆盖云端：用当前远端 ETag 做 CAS，而非过期的 base
            meta_now = backend.get_meta(name)
            if meta_now is None:
                create_only = True
                expected_etag = None
            else:
                create_only = False
                expected_etag = meta_now[1]
            try:
                remote = backend.put(
                    name,
                    local if local.strip() else "{}\n",
                    expected_etag=expected_etag,
                    create_only=create_only,
                )
            except RemoteConflictError as e:
                raise RuntimeError(
                    f"resolve_conflict({name!r}, use_local) 时远端再次被改动，请重试"
                ) from e
            mgr.apply_downloaded(local.encode("utf-8"))
            self._update_state_success(
                name,
                revision=remote.revision,
                sha256=remote.sha256,
                meta_etag=remote.meta_etag,
                bucket=bucket,
                prefix=prefix,
            )
        else:  # use_remote
            remote_cfg = backend.get(name)
            if remote_cfg is None:
                remote_text = read_conflict_remote(config_dir, name)
                if remote_text is None:
                    raise RuntimeError(f"远端没有配置 {name}")
                # 仅有快照、远端已删：写回本地并清冲突，不上传
                validate_yaml_mapping_text(remote_text, f"remote:{name}")
                mgr.apply_downloaded(remote_text.encode("utf-8"))
                def mut_clear(state):
                    e = state.entry(name)
                    e.conflict = False
                    e.paused = False
                self._state_store().update(
                    mut_clear, bucket=bucket, key_prefix=prefix
                )
                clear_conflict_snapshots(config_dir, name)
                self._scheduler.register(name, due_immediately=False)
                return
            remote_text = remote_cfg.content
            validate_yaml_mapping_text(remote_text, f"remote:{name}")
            mgr.apply_downloaded(remote_text.encode("utf-8"))
            self._update_state_success(
                name,
                revision=remote_cfg.revision,
                sha256=remote_cfg.sha256,
                meta_etag=remote_cfg.meta_etag,
                bucket=bucket,
                prefix=prefix,
            )

        clear_conflict_snapshots(config_dir, name)

        def mut(state):
            e = state.entry(name)
            e.conflict = False
            e.paused = False

        self._state_store().update(mut, bucket=bucket, key_prefix=prefix)
        # 恢复调度
        self._scheduler.register(name, due_immediately=False)

    def status_for(self, name: str) -> dict:
        """扩展本地 status 的同步字段。"""
        st = self._registry.get_manager(name).status()
        try:
            entry = self._state_store().get_entry(name)
            st.update(
                {
                    "sync_conflict": entry.conflict,
                    "sync_paused": entry.paused,
                    "last_check_time": entry.last_check_time,
                    "last_success_sync_time": entry.last_success_sync_time,
                    "last_sync_remote_revision": entry.last_sync_remote_revision,
                    "last_sync_sha256": entry.last_sync_sha256,
                }
            )
        except Exception:
            pass
        st["s3_configured"] = self._runtime.ensure_s3_loaded() is not None
        st["sync_enabled"] = self.is_sync_enabled(name)
        return st
