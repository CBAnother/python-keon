import subprocess
from types import SimpleNamespace

import pytest

import keon.vmware as kv


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")
    return path


def test_find_git_files_filters_split_vmdk_parts(tmp_path):
    vmx = _touch(tmp_path / "machine.vmx")
    nested_vmx = _touch(tmp_path / "nested" / "other.VMX")
    disk = _touch(tmp_path / "disk.vmdk")
    descriptor = _touch(tmp_path / "disk-snapshot.vmdk")
    split_part = _touch(tmp_path / "disk-s001.vmdk")
    upper_split_part = _touch(tmp_path / "disk-S002.VMDK")
    _touch(tmp_path / "notes.txt")

    files = kv.find_git_files(tmp_path)

    assert files == sorted([disk, descriptor, vmx, nested_vmx], key=lambda p: str(p).casefold())
    assert split_part not in files
    assert upper_split_part not in files


def test_find_git_files_can_include_split_vmdk_parts(tmp_path):
    disk = _touch(tmp_path / "disk.vmdk")
    split_part = _touch(tmp_path / "disk-s001.vmdk")

    assert kv.find_git_files(
        tmp_path,
        include_split_vmdk_parts=True,
    ) == sorted([disk, split_part], key=lambda p: str(p).casefold())


def test_sync_to_git_adds_files_and_commits(monkeypatch, tmp_path):
    _touch(tmp_path / "machine.vmx")
    _touch(tmp_path / "disk.vmdk")
    _touch(tmp_path / "disk-s001.vmdk")
    calls = []

    def fake_run(cmd, check=False, cwd=None, stdout=None, stderr=None):
        calls.append(SimpleNamespace(cmd=cmd, check=check, cwd=cwd, stdout=stdout, stderr=stderr))
        if cmd[:2] == ["git", "diff"]:
            return SimpleNamespace(returncode=1)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(kv.subprocess, "run", fake_run)

    added = kv.sync_to_git(tmp_path, commit_message="sync")

    add_cmds = [call.cmd for call in calls if call.cmd[:2] == ["git", "add"]]
    assert [cmd[-1] for cmd in add_cmds] == ["disk.vmdk", "machine.vmx"]
    assert ["git", "commit", "-m", "sync"] in [call.cmd for call in calls]
    assert [path.name for path in added] == ["disk.vmdk", "machine.vmx"]


def test_sync_to_git_uses_default_commit_message(monkeypatch, tmp_path):
    _touch(tmp_path / "machine.vmx")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ["git", "diff"]:
            return SimpleNamespace(returncode=1)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(kv.subprocess, "run", fake_run)

    kv.sync_to_git(tmp_path)

    assert ["git", "commit", "-m", "sync vmware files"] in calls


def test_sync_to_git_without_commit_skips_diff_and_commit(monkeypatch, tmp_path):
    _touch(tmp_path / "machine.vmx")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(kv.subprocess, "run", fake_run)

    kv.sync_to_git(tmp_path, commit=False)

    assert ["git", "diff", "--cached", "--quiet"] not in calls
    assert not any(cmd[:2] == ["git", "commit"] for cmd in calls)


def test_sync_to_git_no_changes_skips_commit(monkeypatch, tmp_path, capsys):
    _touch(tmp_path / "machine.vmx")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(kv.subprocess, "run", fake_run)

    kv.sync_to_git(tmp_path)

    assert not any(cmd[:2] == ["git", "commit"] for cmd in calls)
    assert "没有文件产生更改" in capsys.readouterr().out


def test_sync_to_git_rejects_non_git_repo(monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["git", "status"]:
            raise subprocess.CalledProcessError(128, cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(kv.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="不是一个 git 仓库"):
        kv.sync_to_git(tmp_path)


def test_sync_to_git_rejects_missing_directory(tmp_path):
    with pytest.raises(NotADirectoryError):
        kv.sync_to_git(tmp_path / "missing")
