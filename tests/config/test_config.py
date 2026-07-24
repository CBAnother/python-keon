"""Tests for keon.config (named per-file get_global, local + sync)."""

import os
import threading
import time

import pytest
import yaml

from keon import config
from keon.config.backends import MemoryBackend


@pytest.fixture
def cfg(tmp_path):
    """把全局配置指向临时目录，避免污染真实的 ~/.keon/。"""
    config.stop_auto_sync()
    config.set_path(str(tmp_path / "config.yaml"))
    # 重置同步运行期，避免跨测试污染；标记已尝试加载以免读真实 s3.yaml
    rt = config._sync.runtime
    rt.s3_settings = None
    rt.s3_loaded_attempted = True
    rt.backend_override = None
    rt._backend = None
    config._sync._kicked.clear()
    config.get_global().reload()
    yield config
    config.stop_auto_sync()
    rt.backend_override = None


def _write_file(path, text):
    """直接写配置文件（模拟另一个程序）。"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ── 路径解析 ────────────────────────────────────────────────────────────────

def test_default_path_uses_home(monkeypatch):
    monkeypatch.delenv("KEON_CONFIG_PATH", raising=False)
    m = config._GlobalConfigManager("config")
    expected = os.path.join(os.path.expanduser("~"), ".keon", "config.yaml")
    assert m.resolve_path() == expected


def test_env_var_overrides_default_path(monkeypatch, tmp_path):
    target = tmp_path / "custom.yaml"
    monkeypatch.setenv("KEON_CONFIG_PATH", str(target))
    m = config._GlobalConfigManager("config")
    assert m.resolve_path() == os.path.abspath(str(target))


def test_named_path_beside_default(monkeypatch, tmp_path):
    monkeypatch.delenv("KEON_CONFIG_PATH", raising=False)
    config.set_path(str(tmp_path / "config.yaml"))
    app = config.get_global("app")
    assert app.path() == os.path.join(str(tmp_path), "app.yaml")
    assert config.get_global().path() == os.path.abspath(str(tmp_path / "config.yaml"))


def test_set_path_wins_over_env(monkeypatch, tmp_path):
    monkeypatch.setenv("KEON_CONFIG_PATH", str(tmp_path / "env.yaml"))
    config.set_path(str(tmp_path / "explicit.yaml"))
    assert config.get_global().path() == os.path.abspath(str(tmp_path / "explicit.yaml"))
    assert config.get_global("app").path() == os.path.join(
        str(tmp_path), "app.yaml"
    )


# ── 不同 name = 不同文件 ────────────────────────────────────────────────────

def test_named_configs_are_separate_files(cfg, tmp_path):
    root = cfg.get_global()
    app = cfg.get_global("app")
    other = cfg.get_global("other")

    assert root.path() != app.path()
    assert app.path() != other.path()
    assert os.path.basename(root.path()) == "config.yaml"
    assert os.path.basename(app.path()) == "app.yaml"

    root["x"] = 1
    app["x"] = 2
    assert root["x"] == 1
    assert app["x"] == 2
    assert os.path.isfile(root.path())
    assert os.path.isfile(app.path())


def test_same_name_shares_instance_file(cfg):
    a = cfg.get_global("app")
    b = cfg.get_global("app")
    a["k"] = 1
    assert b["k"] == 1
    assert a.path() == b.path()


def test_get_global_config_alias(cfg):
    root = cfg.get_global()
    named = cfg.get_global("config")
    assert root.path() == named.path()
    root["a"] = 1
    assert named["a"] == 1


# ── get_global 返回可读写对象 ────────────────────────────────────────────────

def test_missing_is_empty_config(cfg):
    app = cfg.get_global("app")
    assert app.to_dict() == {}
    assert app == {}
    assert app.get("x") is None
    assert len(app) == 0


def test_set_and_get_via_object(cfg):
    app = cfg.get_global("app")
    app["theme"] = "dark"
    assert app["theme"] == "dark"
    assert cfg.get_global("app")["theme"] == "dark"


def test_write_persists_immediately(cfg):
    app = cfg.get_global("app", save_on_set=True)
    app["x"] = 1
    app.reload()
    assert cfg.get_global("app").get("x") == 1


def test_root_config(cfg):
    root = cfg.get_global()
    root["top"] = {"a": 1}
    cfg.get_global().reload()
    assert cfg.get_global().get("top") == {"a": 1}


def test_nested_inplace_assignment_persists(cfg):
    app = cfg.get_global("app")
    app["b"] = {"1": 123, "2": 456}
    app["b"]["3"] = 789
    assert app["b"].to_dict() == {"1": 123, "2": 456, "3": 789}

    app.reload()
    assert cfg.get_global("app")["b"].to_dict() == {
        "1": 123, "2": 456, "3": 789,
    }


def test_nested_multi_level_inplace(cfg):
    app = cfg.get_global("app")
    app["a"] = {"b": {"c": 1}}
    app["a"]["b"]["c"] = 2
    app["a"]["b"]["d"] = 3
    del app["a"]["b"]["c"]
    app.reload()
    assert cfg.get_global("app")["a"].to_dict() == {"b": {"d": 3}}


def test_nested_view_is_not_detached_copy(cfg):
    app = cfg.get_global("app")
    app["a"] = {"b": 1}
    view = app["a"]
    view["b"] = 2
    assert app["a"]["b"] == 2


def test_list_append_persists(cfg):
    app = cfg.get_global("app")
    app["tags"] = ["a", "b"]
    app["tags"].append("c")
    assert app["tags"].to_list() == ["a", "b", "c"]
    app.reload()
    assert cfg.get_global("app")["tags"].to_list() == ["a", "b", "c"]


def test_dict_like(cfg):
    app = cfg.get_global("app", save_on_set=False)
    app["a"] = 1
    app["b"] = 2
    assert dict(app) == {"a": 1, "b": 2}
    assert sorted(app.keys()) == ["a", "b"]
    assert list(app.keys_view()) == app.keys()
    assert app.get("missing", "d") == "d"
    assert "a" in app and "missing" not in app
    assert app.has("a") and not app.has("missing")


def test_update_saves_once(cfg):
    app = cfg.get_global("app")
    app.update({"m": 1, "n": 2, "o": 3})
    assert app.to_dict() == {"m": 1, "n": 2, "o": 3}
    app.reload()
    assert cfg.get_global("app").to_dict() == {"m": 1, "n": 2, "o": 3}


def test_cfg_path(cfg):
    root = cfg.get_global()
    app = cfg.get_global("app")
    assert root.path() == cfg.get_global().path()
    assert app.path() != cfg.get_global().path()
    assert os.path.isabs(root.path())
    assert os.path.isabs(app.path())


def test_delete_via_object(cfg):
    app = cfg.get_global("app", save_on_set=True)
    app["a"] = 1
    del app["a"]
    assert "a" not in app
    app.reload()
    assert "a" not in cfg.get_global("app")


def test_to_dict_is_copy(cfg):
    app = cfg.get_global("app")
    app["a"] = {"b": 1}
    d = app.to_dict()
    d["a"]["b"] = 999
    assert cfg.get_global("app")["a"] == {"b": 1}


def test_getitem_missing_raises(cfg):
    with pytest.raises(KeyError):
        _ = cfg.get_global("app")["nope"]


def test_unicode_values(cfg):
    app = cfg.get_global("app")
    app["name"] = "美国节点🇺🇸"
    app.reload()
    assert cfg.get_global("app")["name"] == "美国节点🇺🇸"


# ── save_on_set / 批量保存 ────────────────────────────────────────────────────

def test_save_on_set_false_defers(cfg):
    app = cfg.get_global("app", save_on_set=False)
    app["x"] = 1
    assert not os.path.exists(app.path())
    app.save()
    assert os.path.exists(app.path())


def test_manual_save(cfg):
    app = cfg.get_global("app", save_on_set=False)
    app["a"] = 1
    app["b"] = 2
    app.save()
    app.reload()
    assert cfg.get_global("app").to_dict() == {"a": 1, "b": 2}


# ── 跨项目共享 ────────────────────────────────────────────────────────────────

def test_cross_project_share_via_file(cfg):
    app = cfg.get_global("shared")
    _write_file(app.path(), "token: hello\n")
    app.reload()
    assert app["token"] == "hello"


# ── 冲突检测 ──────────────────────────────────────────────────────────────────

def test_consecutive_writes_no_conflict(cfg):
    app = cfg.get_global("app")
    app["a"] = 1
    app["b"] = 2
    assert app.to_dict() == {"a": 1, "b": 2}


def test_conflict_on_external_change(cfg):
    app = cfg.get_global("app")
    app["x"] = 1

    _write_file(app.path(), "x: 999\nother: 1\n")

    with pytest.raises(config.ConfigConflictError) as ei:
        app["y"] = 2

    backup = ei.value.backup_path
    assert os.path.exists(backup)

    with open(app.path(), "r", encoding="utf-8") as f:
        disk = f.read()
    assert "999" in disk

    with open(backup, "r", encoding="utf-8") as f:
        backed = yaml.safe_load(f)
    assert backed == {"x": 1, "y": 2}


def test_reload_clears_conflict_then_write_ok(cfg):
    app = cfg.get_global("app")
    app["x"] = 1
    _write_file(app.path(), "x: 999\n")
    with pytest.raises(config.ConfigConflictError):
        app["y"] = 2

    app.reload()
    assert app["x"] == 999

    app["z"] = 3
    app.reload()
    assert app["z"] == 3


def test_status_reports_external_change(cfg):
    root = cfg.get_global()
    root["x"] = 1
    st = root.status()
    assert st["external_change"] is False

    _write_file(root.path(), "x: 999\n")
    st = root.status()
    assert st["external_change"] is True


# ── snapshot ──────────────────────────────────────────────────────────────────

def test_snapshot_is_deep_copy(cfg):
    root = cfg.get_global()
    root["a"] = {"b": 1}
    snap = root.snapshot()
    snap["a"]["b"] = 999
    assert cfg.get_global()["a"]["b"] == 1


# ── 名称校验 ──────────────────────────────────────────────────────────────────

def test_empty_name_raises(cfg):
    with pytest.raises(ValueError):
        cfg.get_global("")


def test_non_string_name_raises(cfg):
    with pytest.raises(TypeError):
        cfg.get_global(123)


def test_name_too_long_raises(cfg):
    with pytest.raises(ValueError):
        cfg.get_global("a" * 256)


@pytest.mark.parametrize("bad", [
    "a/b",
    "a\\b",
    "a:b",
    "a*b",
    "a?b",
    "a|b",
    "a<b",
    "a>b",
    "a\"b",
    "con",
    "NUL",
    "com1",
    ".",
    "..",
    ".hidden",
    "end.",
    "end ",
])
def test_illegal_name_raises(cfg, bad):
    with pytest.raises(ValueError):
        cfg.get_global(bad)


def test_invalid_root_raises(cfg):
    _write_file(cfg.get_global().path(), "- just\n- a\n- list\n")
    with pytest.raises(ValueError):
        cfg.get_global().reload()


def test_empty_file_is_empty_config(cfg):
    _write_file(cfg.get_global().path(), "")
    cfg.get_global().reload()
    assert cfg.get_global().snapshot() == {}
    assert cfg.get_global("anything").to_dict() == {}


# ── S3 / 同步（MemoryBackend）────────────────────────────────────────────────

@pytest.fixture
def sync_env(cfg, tmp_path):
    """注入 MemoryBackend，并写入假凭证。"""
    config.stop_auto_sync()
    backend = MemoryBackend()
    config.set_s3(
        endpoint_url="http://127.0.0.1:9000",
        bucket="test-bucket",
        access_key="ak",
        secret_key="sk",
        key_prefix="configs",
        persist=True,
        cred_path=str(tmp_path / "s3.yaml"),
    )
    config._sync.runtime.backend_override = backend
    config._sync._kicked.clear()
    config.init(conflict_mode="raise", sync_interval=3600)
    return backend


def test_set_s3_persists(cfg, tmp_path):
    cred = tmp_path / "s3.yaml"
    config.set_s3(
        endpoint_url="http://127.0.0.1:9000",
        bucket="b",
        access_key="ak",
        secret_key="sk",
        key_prefix="/keon-configs/",
        persist=True,
        cred_path=str(cred),
    )
    assert cred.is_file()
    data = yaml.safe_load(cred.read_text(encoding="utf-8"))
    assert data["bucket"] == "b"
    assert data["key_prefix"] == "keon-configs"  # 归一化


def test_set_s3_default_key_prefix(cfg, tmp_path):
    cred = tmp_path / "s3.yaml"
    config.set_s3(
        endpoint_url="http://127.0.0.1:9000",
        bucket="b",
        access_key="ak",
        secret_key="sk",
        persist=True,
        cred_path=str(cred),
    )
    data = yaml.safe_load(cred.read_text(encoding="utf-8"))
    assert data["key_prefix"] == "keon-configs"


def test_upload_on_first_sync(sync_env, cfg):
    app = cfg.get_global("app")
    app["theme"] = "dark"
    config.sync(force=True, wait=True, name="app")
    remote = sync_env.get("app")
    assert remote is not None
    assert "dark" in remote.content
    st = app.status()
    assert st["last_sync_sha256"] is not None
    assert st["sync_conflict"] is False


def test_download_when_only_remote_changed(sync_env, cfg):
    app = cfg.get_global("app")
    app["theme"] = "light"
    config.sync(force=True, wait=True, name="app")

    # 远端被另一端改掉
    sync_env.put(
        "app",
        "theme: dark\n",
        expected_etag=sync_env.get_meta("app")[1],
        create_only=False,
    )
    # 本地保持 base（未改）
    config.sync(force=True, wait=True, name="app")
    app.reload()
    assert app["theme"] == "dark"


def test_conflict_when_both_changed(sync_env, cfg):
    app = cfg.get_global("app")
    app["theme"] = "light"
    config.sync(force=True, wait=True, name="app")

    sync_env.put(
        "app",
        "theme: remote\n",
        expected_etag=sync_env.get_meta("app")[1],
        create_only=False,
    )
    app["theme"] = "local"

    with pytest.raises(config.SyncConflictError):
        config.sync(force=True, wait=True, name="app")

    st = app.status()
    assert st["sync_conflict"] is True
    assert st["sync_paused"] is True
    cdir = os.path.join(
        os.path.dirname(app.path()), ".config_conflict", "app"
    )
    assert os.path.isfile(os.path.join(cdir, "local.yaml"))
    assert os.path.isfile(os.path.join(cdir, "remote.yaml"))


def test_resolve_use_local(sync_env, cfg):
    app = cfg.get_global("app")
    app["theme"] = "light"
    config.sync(force=True, wait=True, name="app")
    sync_env.put(
        "app",
        "theme: remote\n",
        expected_etag=sync_env.get_meta("app")[1],
        create_only=False,
    )
    app["theme"] = "local"
    with pytest.raises(config.SyncConflictError):
        config.sync(force=True, wait=True, name="app")

    config.resolve_conflict("app", "use_local")
    remote = sync_env.get("app")
    assert "local" in remote.content
    st = app.status()
    assert st["sync_conflict"] is False


def test_resolve_use_remote(sync_env, cfg):
    app = cfg.get_global("app")
    app["theme"] = "light"
    config.sync(force=True, wait=True, name="app")
    sync_env.put(
        "app",
        "theme: remote\n",
        expected_etag=sync_env.get_meta("app")[1],
        create_only=False,
    )
    app["theme"] = "local"
    with pytest.raises(config.SyncConflictError):
        config.sync(force=True, wait=True, name="app")

    config.resolve_conflict("app", "use_remote")
    app.reload()
    assert app["theme"] == "remote"


def test_on_update_callback(sync_env, cfg):
    updated = []
    config.set_on_update(lambda n: updated.append(n))
    app = cfg.get_global("app")
    app["theme"] = "light"
    config.sync(force=True, wait=True, name="app")

    sync_env.put(
        "app",
        "theme: dark\n",
        expected_etag=sync_env.get_meta("app")[1],
        create_only=False,
    )
    config.sync(force=True, wait=True, name="app")
    assert "app" in updated


def test_cas_conflict(sync_env, cfg):
    app = cfg.get_global("app")
    app["v"] = 1
    config.sync(force=True, wait=True, name="app")
    etag = sync_env.get_meta("app")[1]
    # 模拟他端先写
    sync_env.put("app", "v: 9\n", expected_etag=etag, create_only=False)
    app["v"] = 2
    # 本地相对 base 变了，远端也变了 → 双方冲突（不是纯 CAS）
    with pytest.raises(config.SyncConflictError):
        config.sync(force=True, wait=True, name="app")


def test_noop_when_unchanged(sync_env, cfg):
    app = cfg.get_global("app")
    app["x"] = 1
    config.sync(force=True, wait=True, name="app")
    rev1 = sync_env.get("app").revision
    config.sync(force=True, wait=True, name="app")
    assert sync_env.get("app").revision == rev1


def test_get_global_sync_false_skips(sync_env, cfg):
    local = cfg.get_global("localonly", sync=False)
    local["secret"] = 1
    assert local.status()["sync_enabled"] is False
    assert "localonly" not in config._sync._scheduler.registered_names()

    # 已写入状态文件
    entry = config._sync._state_store().get_entry("localonly")
    assert entry.sync_enabled is False

    config.sync(force=False, wait=True, name="localonly")
    assert sync_env.get("localonly") is None

    # force 仍可手动推一把
    config.sync(force=True, wait=True, name="localonly")
    assert sync_env.get("localonly") is not None
    assert "secret" in sync_env.get("localonly").content


def test_get_global_sync_true_reenable(sync_env, cfg):
    cfg.get_global("tog", sync=False)
    assert not config._sync.is_sync_enabled("tog")
    # 未指定 sync：保持禁用
    cfg.get_global("tog")
    assert not config._sync.is_sync_enabled("tog")
    assert "tog" not in config._sync._scheduler.registered_names()
    # 显式 sync=True 才恢复
    cfg.get_global("tog", sync=True)
    assert config._sync.is_sync_enabled("tog")
    assert config._sync._state_store().get_entry("tog").sync_enabled is True
    assert "tog" in config._sync._scheduler.registered_names()


def test_sync_disabled_persists_across_kicked_reset(sync_env, cfg):
    """模拟新进程：清空内存 kicked，仍应从状态文件读到禁用。"""
    cfg.get_global("persist", sync=False)
    config._sync._kicked.clear()
    config._sync._scheduler.unregister("persist")

    cfg.get_global("persist")  # 未指定 sync
    assert not config._sync.is_sync_enabled("persist")
    assert "persist" not in config._sync._scheduler.registered_names()


# ── YAML 注释 ────────────────────────────────────────────────────────────────

def test_scalar_comment_roundtrip(cfg):
    app = cfg.get_global("app")
    app["xx"] = 1
    app["xx"].comment = "注释 abc"
    assert app["xx"].comment == "注释 abc"
    assert app["xx"] == 1
    assert app["xx"].value == 1

    app.reload()
    assert app["xx"] == 1
    assert app["xx"].comment == "注释 abc"

    raw = open(app.path(), encoding="utf-8").read()
    assert "注释 abc" in raw


def test_read_existing_eol_comment(cfg):
    app = cfg.get_global("app")
    _write_file(app.path(), "xx: 1  # 注释 abc\n")
    app.reload()
    assert app["xx"] == 1
    assert app["xx"].comment == "注释 abc"


def test_nested_and_list_comment(cfg):
    app = cfg.get_global("app")
    app["sec"] = {"b": 2}
    app["sec"].comment = "section"
    app["sec"]["b"].comment = "b comment"
    app["tags"] = ["x", "y"]
    app["tags"].comment = "tag list"
    app["tags"][0].comment = "item0"

    app.reload()
    assert app["sec"].comment == "section"
    assert app["sec"]["b"].comment == "b comment"
    assert app["tags"].comment == "tag list"
    assert app["tags"][0].comment == "item0"
    assert app["tags"][0] == "x"
