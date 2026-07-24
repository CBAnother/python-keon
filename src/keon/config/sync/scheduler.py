"""单一后台调度线程：按间隔驱动所有已登记 name 的同步。"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)


class SyncScheduler:
    """
    全进程一个调度线程。

    - ``register(name)``：幂等登记，首次登记立即到期；
    - 每次 tick 现读 ``interval_getter``；
    - ``paused_checker(name)`` 为 True 时跳过；
    - ``sync_fn(name)`` 执行实际同步。
    """

    def __init__(
        self,
        *,
        sync_fn: Callable[[str], None],
        interval_getter: Callable[[], float],
        paused_checker: Callable[[str], bool],
    ) -> None:
        self._sync_fn = sync_fn
        self._interval_getter = interval_getter
        self._paused_checker = paused_checker
        self._lock = threading.RLock()
        self._due: dict[str, float] = {}  # name -> next due monotonic
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def register(self, name: str, *, due_immediately: bool = True) -> None:
        with self._lock:
            if name not in self._due:
                self._due[name] = 0.0 if due_immediately else (
                    time.monotonic() + self._interval_getter()
                )
            elif due_immediately:
                self._due[name] = min(self._due[name], time.monotonic())
        self._wake.set()
        self.ensure_running()

    def kick(self, name: str) -> None:
        """把 name 标为立即到期。"""
        with self._lock:
            if name in self._due:
                self._due[name] = 0.0
            else:
                self._due[name] = 0.0
        self._wake.set()
        self.ensure_running()

    def unregister(self, name: str) -> None:
        """从调度表移除（不再自动同步）。"""
        with self._lock:
            self._due.pop(name, None)

    def registered_names(self) -> list[str]:
        with self._lock:
            return list(self._due.keys())

    def ensure_running(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name="keon-config-sync",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        t = self._thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=2.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                interval = max(1.0, float(self._interval_getter()))
            except Exception:
                interval = 300.0

            now = time.monotonic()
            due_names: list[str] = []
            next_wake = now + interval
            with self._lock:
                for name, due in list(self._due.items()):
                    if due <= now:
                        due_names.append(name)
                    else:
                        next_wake = min(next_wake, due)

            for name in due_names:
                if self._stop.is_set():
                    break
                try:
                    if self._paused_checker(name):
                        # 冲突暂停：推迟到下一轮再看
                        with self._lock:
                            self._due[name] = time.monotonic() + interval
                        continue
                    self._sync_fn(name)
                except Exception:
                    logger.exception("同步 %s 失败", name)
                with self._lock:
                    self._due[name] = time.monotonic() + interval

            wait = max(0.2, next_wake - time.monotonic())
            self._wake.wait(timeout=wait)
            self._wake.clear()
