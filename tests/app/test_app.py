import os
import stat
from pathlib import Path

import keon.app as ka
from keon.app import AppName


def _make_programs(root: Path, appdata: Path):
    sys_programs = root / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    user_programs = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    sys_programs.mkdir(parents=True)
    user_programs.mkdir(parents=True)
    return sys_programs, user_programs


def _make_executable(path: Path):
    path.write_text("")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def test_program_paths_from_environment(monkeypatch, tmp_path):
    all_users = tmp_path / "all-users"
    appdata = tmp_path / "appdata"
    sys_programs, user_programs = _make_programs(all_users, appdata)

    monkeypatch.setenv("ALLUSERSPROFILE", str(all_users))
    monkeypatch.setenv("APPDATA", str(appdata))

    assert ka.get_sys_start_menu() == all_users / "Microsoft" / "Windows" / "Start Menu"
    assert ka.get_sys_programs() == sys_programs
    assert ka.get_user_start_menu() == appdata / "Microsoft" / "Windows" / "Start Menu"
    assert ka.get_user_programs() == user_programs
    assert ka.get_all_programs() == [sys_programs, user_programs]


def test_missing_program_paths_are_ignored(monkeypatch, tmp_path):
    all_users = tmp_path / "all-users"
    appdata = tmp_path / "appdata"
    sys_programs, _user_programs = _make_programs(all_users, appdata)

    monkeypatch.setenv("ALLUSERSPROFILE", str(all_users))
    monkeypatch.setenv("APPDATA", str(tmp_path / "missing-appdata"))

    assert ka.get_all_programs() == [sys_programs]


def test_find_dir_in_programs(monkeypatch, tmp_path):
    all_users = tmp_path / "all-users"
    appdata = tmp_path / "appdata"
    sys_programs, _user_programs = _make_programs(all_users, appdata)
    target = sys_programs / "Vendor" / "Total Commander"
    target.mkdir(parents=True)

    monkeypatch.setenv("ALLUSERSPROFILE", str(all_users))
    monkeypatch.setenv("APPDATA", str(appdata))

    assert ka.find_dir_in_programs("Total Commander") == target
    assert ka.find_dir_in_programs("Missing") is None


def test_find_link_in_programs_is_case_insensitive(monkeypatch, tmp_path):
    all_users = tmp_path / "all-users"
    appdata = tmp_path / "appdata"
    _sys_programs, user_programs = _make_programs(all_users, appdata)
    target = user_programs / "Visual Studio 2022.lnk"
    target.write_text("")

    monkeypatch.setenv("ALLUSERSPROFILE", str(all_users))
    monkeypatch.setenv("APPDATA", str(appdata))

    assert ka.find_link_in_programs("visual studio 2022") == target
    assert ka.find_link_in_programs("VISUAL STUDIO 2022.LNK") == target
    assert ka.find_link_in_programs("Missing") is None


def test_find_executable_in_path(monkeypatch, tmp_path):
    bin_dir = tmp_path / "ffmpeg" / "bin"
    bin_dir.mkdir(parents=True)
    executable_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    target = bin_dir / executable_name
    _make_executable(target)

    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("PATHEXT", ".EXE")

    assert ka.find_executable_in_path("ffmpeg") == target


def test_find_executable_in_path_returns_none(monkeypatch):
    monkeypatch.setattr(ka.shutil, "which", lambda _name: None)

    assert ka.find_executable_in_path("ffmpeg") is None


def test_find_finds_ffmpeg_from_app_name(monkeypatch, tmp_path):
    install_dir = tmp_path / "ffmpeg"
    bin_dir = install_dir / "bin"
    bin_dir.mkdir(parents=True)
    executable_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    target = bin_dir / executable_name
    _make_executable(target)

    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("PATHEXT", ".EXE")

    assert ka.find(AppName.FFMPEG) == str(install_dir)


def test_find_accepts_app_name_string(monkeypatch, tmp_path):
    install_dir = tmp_path / "ffmpeg"
    bin_dir = install_dir / "bin"
    bin_dir.mkdir(parents=True)
    executable_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    target = bin_dir / executable_name
    _make_executable(target)

    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("PATHEXT", ".EXE")

    assert ka.find("FFMPEG") == str(install_dir)
    assert ka.find("ffmpeg") == str(install_dir)
    assert ka.find("FFmpeg") == str(install_dir)


def test_find_accepts_enum_name_and_value_strings(monkeypatch):
    monkeypatch.setattr(ka, "_find_visual_studio", lambda version: "vs-{}".format(version))

    assert ka.find("VISUAL_STUDIO_2022") == "vs-2022"
    assert ka.find("Visual Studio 2022") == "vs-2022"
    assert ka.find("visual studio 2022") == "vs-2022"


def test_parent_walks_up_levels():
    assert ka.parent(Path("C:/a/b/c/d"), 2) == Path("C:/a/b")


def test_get_lnk_target_returns_none_for_missing_path():
    assert ka.get_lnk_target(None) is None
    assert ka.get_lnk_target(Path("C:/missing/link.lnk")) is None


def test_find_unknown_app_returns_none():
    assert ka.find("missing") is None
    assert ka.find(123) is None


def test_app_name_values():
    assert AppName.VISUAL_STUDIO_2022.value == "Visual Studio 2022"
    assert AppName.FFMPEG.value == "FFmpeg"
