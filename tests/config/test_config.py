"""Tests for keon.config (named per-file get_global, local step)."""

import os

import pytest
import yaml

from keon import config


@pytest.fixture
def cfg(tmp_path):
    """把全局配置指向临时目录，避免污染真实的 ~/.keon/。"""
    config.set_path(str(tmp_path / "config.yaml"))
    config.reload()
    return config


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
    # 通过 registry：默认在 ~/.keon，具名同目录
    # 用临时 set_path 验证具名落在同目录
    config.set_path(str(tmp_path / "config.yaml"))
    app = config.get_global("app")
    assert app.path() == os.path.join(str(tmp_path), "app.yaml")
    assert config.get_global().path() == os.path.abspath(str(tmp_path / "config.yaml"))


def test_set_path_wins_over_env(monkeypatch, tmp_path):
    monkeypatch.setenv("KEON_CONFIG_PATH", str(tmp_path / "env.yaml"))
    config.set_path(str(tmp_path / "explicit.yaml"))
    assert config.path() == os.path.abspath(str(tmp_path / "explicit.yaml"))
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
    # get_global() 与 get_global("config") 指向同一默认文件
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
    cfg.reload()
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


def test_dict_like(cfg):
    app = cfg.get_global("app", save_on_set=False)
    app["a"] = 1
    app["b"] = 2
    assert dict(app) == {"a": 1, "b": 2}
    assert sorted(app.keys()) == ["a", "b"]
    assert app.get("missing", "d") == "d"
    assert "a" in app and "missing" not in app
    assert app.has("a") and not app.has("missing")


def test_cfg_path(cfg):
    root = cfg.get_global()
    app = cfg.get_global("app")
    assert root.path() == cfg.path()
    assert app.path() != cfg.path()
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
    st = cfg.status()
    assert st["external_change"] is False

    _write_file(cfg.path(), "x: 999\n")
    st = cfg.status()
    assert st["external_change"] is True


# ── snapshot ──────────────────────────────────────────────────────────────────

def test_snapshot_is_deep_copy(cfg):
    root = cfg.get_global()
    root["a"] = {"b": 1}
    snap = cfg.snapshot()
    snap["a"]["b"] = 999
    assert cfg.get_global()["a"]["b"] == 1


# ── 名称校验 ──────────────────────────────────────────────────────────────────

def test_empty_name_raises(cfg):
    with pytest.raises(ValueError):
        cfg.get_global("")


def test_non_string_name_raises(cfg):
    with pytest.raises(TypeError):
        cfg.get_global(123)


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
    _write_file(cfg.path(), "- just\n- a\n- list\n")
    with pytest.raises(ValueError):
        cfg.reload()


def test_empty_file_is_empty_config(cfg):
    _write_file(cfg.path(), "")
    cfg.reload()
    assert cfg.snapshot() == {}
    assert cfg.get_global("anything").to_dict() == {}
