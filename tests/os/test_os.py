import os
import sys

import pytest

from keon.os import (
    list_env_vars,
    get_env_var,
    print_env_vars,
    get_path,
    set_env_var,
    delete_env_var,
    set_path,
    add_to_path,
    remove_from_path,
)


on_windows = sys.platform == "win32"
skip_non_windows = pytest.mark.skipif(
    not on_windows, reason="注册表读取仅在 Windows 上可用"
)


# ── list_env_vars (process 级别，跨平台) ───────────────────────────────────────

def test_list_env_vars_process_returns_dict(monkeypatch):
    monkeypatch.setenv("KEON_TEST_VAR", "hello")
    env = list_env_vars("process")
    assert isinstance(env, dict)
    assert env["KEON_TEST_VAR"] == "hello"


def test_list_env_vars_process_is_copy(monkeypatch):
    """返回的字典是副本，修改它不应影响 os.environ"""
    monkeypatch.setenv("KEON_TEST_VAR", "hello")
    env = list_env_vars("process")
    env["KEON_TEST_VAR"] = "changed"
    assert os.environ["KEON_TEST_VAR"] == "hello"


def test_list_env_vars_process_alias(monkeypatch):
    """'p' / 'proc' 是 'process' 的别名"""
    monkeypatch.setenv("KEON_TEST_VAR", "hello")
    assert list_env_vars("p")["KEON_TEST_VAR"] == "hello"
    assert list_env_vars("proc")["KEON_TEST_VAR"] == "hello"


def test_list_env_vars_scope_case_insensitive(monkeypatch):
    monkeypatch.setenv("KEON_TEST_VAR", "hello")
    assert list_env_vars("PROCESS")["KEON_TEST_VAR"] == "hello"


def test_list_env_vars_invalid_scope_raises():
    with pytest.raises(ValueError, match="不支持的 scope"):
        list_env_vars("nope")


# ── get_env_var (process 级别，跨平台) ─────────────────────────────────────────

def test_get_env_var_process(monkeypatch):
    monkeypatch.setenv("KEON_TEST_VAR", "hello")
    assert get_env_var("KEON_TEST_VAR", "process") == "hello"


def test_get_env_var_case_insensitive(monkeypatch):
    monkeypatch.setenv("KEON_TEST_VAR", "hello")
    assert get_env_var("keon_test_var", "process") == "hello"


def test_get_env_var_missing_returns_default(monkeypatch):
    monkeypatch.delenv("KEON_TEST_MISSING", raising=False)
    assert get_env_var("KEON_TEST_MISSING", "process") is None
    assert get_env_var("KEON_TEST_MISSING", "process", default="fallback") == "fallback"


def test_get_env_var_invalid_scope_raises():
    with pytest.raises(ValueError, match="不支持的 scope"):
        get_env_var("KEON_TEST_VAR", "nope")


# ── print_env_vars ─────────────────────────────────────────────────────────────

def test_print_env_vars_process(monkeypatch, capsys):
    monkeypatch.setenv("KEON_TEST_VAR", "hello")
    print_env_vars("process")
    captured = capsys.readouterr()
    assert "KEON_TEST_VAR=hello" in captured.out


# ── get_path (process 级别，跨平台) ────────────────────────────────────────────

def test_get_path_returns_list(monkeypatch):
    raw = os.pathsep.join(["/a/bin", "/b/bin", "/c/bin"])
    monkeypatch.setenv("PATH", raw)
    result = get_path("process")
    assert isinstance(result, list)
    assert result == ["/a/bin", "/b/bin", "/c/bin"]


def test_get_path_strips_and_filters_empty(monkeypatch):
    """去掉空项和首尾空白"""
    raw = os.pathsep.join(["  /a/bin  ", "", "/b/bin", "   "])
    monkeypatch.setenv("PATH", raw)
    result = get_path("process")
    assert result == ["/a/bin", "/b/bin"]


def test_get_path_empty(monkeypatch):
    monkeypatch.setenv("PATH", "")
    assert get_path("process") == []


def test_get_path_no_dedup_keeps_duplicates(monkeypatch):
    raw = os.pathsep.join(["/a/bin", "/a/bin", "/b/bin"])
    monkeypatch.setenv("PATH", raw)
    assert get_path("process") == ["/a/bin", "/a/bin", "/b/bin"]


def test_get_path_dedup(monkeypatch):
    raw = os.pathsep.join(["/a/bin", "/a/bin", "/b/bin"])
    monkeypatch.setenv("PATH", raw)
    assert get_path("process", dedup=True) == ["/a/bin", "/b/bin"]


def test_get_path_dedup_case_insensitive(monkeypatch):
    """去重不区分大小写，保留首次出现"""
    raw = os.pathsep.join(["/A/Bin", "/a/bin", "/b/bin"])
    monkeypatch.setenv("PATH", raw)
    assert get_path("process", dedup=True) == ["/A/Bin", "/b/bin"]


def test_get_path_invalid_scope_raises():
    with pytest.raises(ValueError, match="不支持的 scope"):
        get_path("nope")


# ── 注册表级别 (仅 Windows) ────────────────────────────────────────────────────

@skip_non_windows
def test_list_env_vars_user_scope_returns_dict():
    env = list_env_vars("user")
    assert isinstance(env, dict)


@skip_non_windows
def test_list_env_vars_system_scope_returns_dict():
    env = list_env_vars("system")
    assert isinstance(env, dict)
    # 系统级别一定存在 windir / SystemRoot 之类的键
    lowered = {k.lower() for k in env}
    assert "path" in lowered


@skip_non_windows
def test_get_path_user_scope_returns_list():
    assert isinstance(get_path("user"), list)


@skip_non_windows
def test_get_path_system_scope_not_empty():
    result = get_path("system")
    assert isinstance(result, list)
    assert len(result) > 0


@skip_non_windows
def test_get_path_all_scope_combines_system_and_user():
    system = get_path("system")
    combined = get_path("all")
    assert isinstance(combined, list)
    # all 至少包含系统级别的全部条目
    for p in system:
        assert p in combined


# ── set_env_var / delete_env_var (process 级别，跨平台) ─────────────────────────

def test_set_env_var_process_create(monkeypatch):
    monkeypatch.delenv("KEON_TEST_SET", raising=False)
    ret = set_env_var("KEON_TEST_SET", "v1", scope="process")
    assert ret == "v1"
    assert os.environ["KEON_TEST_SET"] == "v1"


def test_set_env_var_process_overwrite(monkeypatch):
    monkeypatch.setenv("KEON_TEST_SET", "old")
    set_env_var("KEON_TEST_SET", "new", scope="process")
    assert os.environ["KEON_TEST_SET"] == "new"


def test_set_env_var_casts_to_str(monkeypatch):
    monkeypatch.delenv("KEON_TEST_SET", raising=False)
    set_env_var("KEON_TEST_SET", 123, scope="process")
    assert os.environ["KEON_TEST_SET"] == "123"


def test_set_env_var_invalid_scope_raises():
    with pytest.raises(ValueError, match="不支持的 scope"):
        set_env_var("KEON_TEST_SET", "v", scope="nope")


def test_delete_env_var_process(monkeypatch):
    monkeypatch.setenv("KEON_TEST_SET", "v1")
    assert delete_env_var("KEON_TEST_SET", scope="process") is True
    assert "KEON_TEST_SET" not in os.environ


def test_delete_env_var_process_missing(monkeypatch):
    monkeypatch.delenv("KEON_TEST_SET", raising=False)
    assert delete_env_var("KEON_TEST_SET", scope="process") is False


# ── set_path / add_to_path / remove_from_path (process 级别，跨平台) ────────────

def test_set_path_from_list(monkeypatch):
    monkeypatch.setenv("PATH", "/x")
    set_path(["/a", "/b"], scope="process")
    assert get_path("process") == ["/a", "/b"]


def test_set_path_from_string(monkeypatch):
    monkeypatch.setenv("PATH", "/x")
    set_path(os.pathsep.join(["/a", "/b"]), scope="process")
    assert get_path("process") == ["/a", "/b"]


def test_set_path_dedup(monkeypatch):
    monkeypatch.setenv("PATH", "/x")
    set_path(["/a", "/A", "/b"], scope="process", dedup=True)
    assert get_path("process") == ["/a", "/b"]


def test_set_path_strips_and_filters_empty(monkeypatch):
    monkeypatch.setenv("PATH", "/x")
    set_path(["  /a  ", "", "/b"], scope="process")
    assert get_path("process") == ["/a", "/b"]


def test_add_to_path_append(monkeypatch):
    monkeypatch.setenv("PATH", os.pathsep.join(["/a", "/b"]))
    assert add_to_path("/c", scope="process") is True
    assert get_path("process") == ["/a", "/b", "/c"]


def test_add_to_path_prepend(monkeypatch):
    monkeypatch.setenv("PATH", os.pathsep.join(["/a", "/b"]))
    assert add_to_path("/c", scope="process", prepend=True) is True
    assert get_path("process") == ["/c", "/a", "/b"]


def test_add_to_path_existing_no_duplicate(monkeypatch):
    """已存在（不区分大小写）时不重复添加"""
    monkeypatch.setenv("PATH", os.pathsep.join(["/a", "/b"]))
    assert add_to_path("/A", scope="process") is False
    assert get_path("process") == ["/a", "/b"]


def test_add_to_path_empty_raises(monkeypatch):
    monkeypatch.setenv("PATH", "/a")
    with pytest.raises(ValueError, match="不能为空"):
        add_to_path("   ", scope="process")


def test_remove_from_path(monkeypatch):
    monkeypatch.setenv("PATH", os.pathsep.join(["/a", "/b", "/c"]))
    assert remove_from_path("/b", scope="process") is True
    assert get_path("process") == ["/a", "/c"]


def test_remove_from_path_case_insensitive(monkeypatch):
    monkeypatch.setenv("PATH", os.pathsep.join(["/a", "/b"]))
    assert remove_from_path("/A", scope="process") is True
    assert get_path("process") == ["/b"]


def test_remove_from_path_not_present(monkeypatch):
    monkeypatch.setenv("PATH", os.pathsep.join(["/a", "/b"]))
    assert remove_from_path("/zzz", scope="process") is False
    assert get_path("process") == ["/a", "/b"]


# ── 注册表写入回环 (仅 Windows，使用临时变量，绝不触碰已有变量/PATH) ──────────

@skip_non_windows
def test_set_and_delete_env_var_user_roundtrip():
    """
    在用户级别写入一个唯一命名的临时变量并读回，最后务必删除。
    全程不修改任何已存在的环境变量，也不触碰真实 PATH。
    """
    name = "KEON_TEST_TMP_ENV_DO_NOT_KEEP"

    # 前置保证：该变量本来不存在
    assert name not in list_env_vars("user")

    try:
        set_env_var(name, "hello-keon", scope="user", broadcast=False)
        assert list_env_vars("user")[name] == "hello-keon"
    finally:
        deleted = delete_env_var(name, scope="user", broadcast=False)
        assert deleted is True

    # 确认已清理干净
    assert name not in list_env_vars("user")


@skip_non_windows
def test_set_env_var_expandable_autodetect():
    """值中含 % 时自动以 REG_EXPAND_SZ 写入，读回展开后应得到真实路径。"""
    name = "KEON_TEST_TMP_EXPAND_DO_NOT_KEEP"
    assert name not in list_env_vars("user")

    try:
        set_env_var(name, "%SystemRoot%\\Temp", scope="user", broadcast=False)
        # 未展开应保留原样
        assert list_env_vars("user", expand=False)[name] == "%SystemRoot%\\Temp"
        # 展开后不应再包含 %
        expanded = list_env_vars("user", expand=True)[name]
        assert "%" not in expanded
    finally:
        delete_env_var(name, scope="user", broadcast=False)

    assert name not in list_env_vars("user")
