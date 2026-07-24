"""本地 ↔ 云端冲突处理。"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Literal

from ..local import _atomic_write, _dump_yaml_bytes, _parse_mapping

logger = logging.getLogger(__name__)

ConflictChoice = Literal["use_local", "use_remote", "show_diff", "cancel"]


@dataclass
class ConflictEvent:
    name: str
    base_sha256: str | None
    local_sha256: str
    remote_revision: str
    conflict_dir: str


def conflict_dir_for(config_dir: str, name: str) -> str:
    return os.path.join(config_dir, ".config_conflict", name)


def save_conflict_snapshots(
    config_dir: str,
    name: str,
    *,
    base_yaml: str | None,
    local_yaml: str,
    remote_yaml: str,
) -> str:
    """写入 base/local/remote.yaml，返回冲突目录。"""
    d = conflict_dir_for(config_dir, name)
    os.makedirs(d, exist_ok=True)
    if base_yaml is not None:
        _atomic_write(
            os.path.join(d, "base.yaml"), base_yaml.encode("utf-8")
        )
    _atomic_write(os.path.join(d, "local.yaml"), local_yaml.encode("utf-8"))
    _atomic_write(
        os.path.join(d, "remote.yaml"), remote_yaml.encode("utf-8")
    )
    return d


def clear_conflict_snapshots(config_dir: str, name: str) -> None:
    d = conflict_dir_for(config_dir, name)
    if not os.path.isdir(d):
        return
    for fname in ("base.yaml", "local.yaml", "remote.yaml"):
        path = os.path.join(d, fname)
        try:
            os.unlink(path)
        except OSError:
            pass
    try:
        os.rmdir(d)
    except OSError:
        pass


def read_conflict_local(config_dir: str, name: str) -> str | None:
    path = os.path.join(conflict_dir_for(config_dir, name), "local.yaml")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


def read_conflict_remote(config_dir: str, name: str) -> str | None:
    path = os.path.join(conflict_dir_for(config_dir, name), "remote.yaml")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


class SyncConflictError(RuntimeError):
    """本地与云端同时修改，拒绝自动覆盖。"""

    def __init__(self, event: ConflictEvent) -> None:
        self.event = event
        super().__init__(
            f"配置 {event.name!r} 本地与云端冲突；"
            f"快照目录：{event.conflict_dir}。"
            f"请调用 resolve_conflict({event.name!r}, ...)"
        )


def cli_choose(
    local_content: str,
    remote_content: str,
    base_content: str | None = None,
) -> ConflictChoice:
    """简易 CLI 冲突选择。"""
    print("检测到本地与云端配置冲突：")
    print("  [1] use_local   — 使用本地并覆盖云端")
    print("  [2] use_remote  — 使用云端并覆盖本地")
    print("  [3] show_diff   — 查看差异")
    print("  [4] cancel      — 取消同步")
    while True:
        try:
            raw = input("请选择 [1-4]: ").strip().lower()
        except EOFError:
            return "cancel"
        mapping = {
            "1": "use_local",
            "use_local": "use_local",
            "2": "use_remote",
            "use_remote": "use_remote",
            "3": "show_diff",
            "show_diff": "show_diff",
            "4": "cancel",
            "cancel": "cancel",
        }
        choice = mapping.get(raw)
        if choice == "show_diff":
            print("--- local ---")
            print(local_content)
            print("--- remote ---")
            print(remote_content)
            if base_content is not None:
                print("--- base ---")
                print(base_content)
            continue
        if choice in ("use_local", "use_remote", "cancel"):
            return choice  # type: ignore[return-value]
        print("无效输入，请重试。")


def validate_yaml_mapping_text(text: str, label: str) -> dict:
    """校验 YAML 文本根为 mapping，返回解析结果。"""
    raw = text.encode("utf-8")
    return _parse_mapping(raw, label)


def dump_mapping(data: dict) -> str:
    return _dump_yaml_bytes(data).decode("utf-8")
