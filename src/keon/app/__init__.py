import os
import shutil
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Union


def _env_path(env_name: str, *parts: str) -> Optional[Path]:
    """
    Build a path from an environment variable and extra path parts.

    Args:
        env_name: Environment variable name.
        *parts: Extra path parts appended to the environment value.

    Returns:
        Path object if the environment variable exists, otherwise None.
    """
    base = os.environ.get(env_name)
    if not base:
        return None
    return Path(base, *parts)


def get_sys_start_menu() -> Optional[Path]:
    """
    Get the system-wide Windows Start Menu path.

    Returns:
        System Start Menu path if ALLUSERSPROFILE exists, otherwise None.
    """
    return _env_path("ALLUSERSPROFILE", "Microsoft", "Windows", "Start Menu")


def get_sys_programs() -> Optional[Path]:
    """
    Get the system-wide Windows Programs menu path.

    Returns:
        System Programs path if the system Start Menu path exists, otherwise None.
    """
    start_menu = get_sys_start_menu()
    return start_menu / "Programs" if start_menu else None


def get_user_start_menu() -> Optional[Path]:
    """
    Get the current user's Windows Start Menu path.

    Returns:
        User Start Menu path if APPDATA exists, otherwise None.
    """
    return _env_path("APPDATA", "Microsoft", "Windows", "Start Menu")


def get_user_programs() -> Optional[Path]:
    """
    Get the current user's Windows Programs menu path.

    Returns:
        User Programs path if the user Start Menu path exists, otherwise None.
    """
    start_menu = get_user_start_menu()
    return start_menu / "Programs" if start_menu else None


def get_all_programs() -> List[Path]:
    """
    Get all existing Windows Programs menu paths.

    Returns:
        Existing system and user Programs paths.
    """
    paths = [
        get_sys_programs(),
        get_user_programs(),
    ]

    return [p for p in paths if p is not None and p.exists()]


def find_dir_in_programs(dir_name: str) -> Optional[Path]:
    """
    Find a directory by name under Windows Programs menu paths.

    Args:
        dir_name: Directory name to search for.

    Returns:
        Matching directory path if found, otherwise None.
    """
    for programs in get_all_programs():
        for root, dirs, _files in os.walk(programs):
            if dir_name in dirs:
                return Path(root) / dir_name

    return None


def find_link_in_programs(link_name: str) -> Optional[Path]:
    """
    Find a shortcut by name under Windows Programs menu paths.

    Args:
        link_name: Shortcut name, with or without the .lnk suffix.

    Returns:
        Matching shortcut path if found, otherwise None.
    """
    if not link_name.lower().endswith(".lnk"):
        link_name += ".lnk"

    target_name = link_name.casefold()

    for programs in get_all_programs():
        for root, _dirs, files in os.walk(programs):
            for file in files:
                if file.casefold() == target_name:
                    return Path(root) / file

    return None


def find_executable_in_path(executable_name: str) -> Optional[Path]:
    """
    Find an executable from the PATH environment variable.

    Args:
        executable_name: Executable name to search for.

    Returns:
        Executable path if found, otherwise None.
    """
    target = shutil.which(executable_name)
    if target is None:
        return None
    return Path(target)


def get_lnk_target(lnk: Optional[Path]) -> Optional[Path]:
    """
    Get the target path of a Windows shortcut file.

    Args:
        lnk: Shortcut path.

    Returns:
        Shortcut target path if it exists and has a target, otherwise None.
    """
    if lnk is None or not lnk.exists():
        return None

    import win32com.client

    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortcut(str(lnk))

    target = shortcut.TargetPath
    if not target:
        return None

    return Path(target)


def parent(path: Path, level: int) -> Path:
    """
    Walk up a path by a given number of parent levels.

    Args:
        path: Original path.
        level: Number of parent levels to walk up.

    Returns:
        Parent path after walking up the requested levels.
    """
    res = path
    for _ in range(level):
        res = res.parent
    return res


class AppName(Enum):
    """
    Supported application names.
    """
    VIVADO_2018_3 = "Vivado 2018.3"
    VISUAL_STUDIO_2022 = "Visual Studio 2022"
    VISUAL_STUDIO_2017 = "Visual Studio 2017"
    VISUAL_STUDIO_2015 = "Visual Studio 2015"
    LABWINDOWS_CVI_2015 = "LabWindows CVI 2015"
    TOTAL_COMMANDER = "Total Commander"
    FFMPEG = "FFmpeg"


def _find_vivado_2018_3() -> Optional[str]:
    """
    Find the Vivado 2018.3 installation directory.

    Returns:
        Vivado SDK directory path if found, otherwise None.
    """
    xilinx_design_tools = find_dir_in_programs("Xilinx Design Tools")
    if xilinx_design_tools is None:
        return None

    lnk = xilinx_design_tools / "SDK 2018.3" / "Xilinx SDK 2018.3.lnk"
    xsdk_bat = get_lnk_target(lnk)
    if xsdk_bat is None:
        return None

    sdk_dir = parent(xsdk_bat, 4)
    return str(sdk_dir)


def _find_visual_studio(version: str) -> Optional[str]:
    """
    Find a Visual Studio installation directory by version.

    Args:
        version: Visual Studio version string.

    Returns:
        Visual Studio directory path if found, otherwise None.
    """
    lnk = find_link_in_programs("Visual Studio {}".format(version))
    target = get_lnk_target(lnk)
    if target is None:
        return None

    vs_dir = parent(target, 3)
    return str(vs_dir)


def _find_labwindows_cvi_2015() -> Optional[str]:
    """
    Find the LabWindows CVI 2015 installation directory.

    Returns:
        LabWindows CVI directory path if found, otherwise None.
    """
    lnk = find_link_in_programs("NI LabWindows CVI 2015")
    target = get_lnk_target(lnk)
    if target is None:
        return None

    cvi_dir = parent(target, 1)
    return str(cvi_dir)


def _find_total_commander() -> Optional[str]:
    """
    Find the Total Commander installation directory.

    Returns:
        Total Commander directory path if found, otherwise None.
    """
    dir_names = [
        "Total Commander",
        "Total Commander x64",
    ]

    lnk_names = [
        "Total Commander 64 bit.lnk",
        "Total Commander x64.lnk",
    ]

    for dir_name in dir_names:
        tc_dir = find_dir_in_programs(dir_name)
        if tc_dir is None:
            continue

        for lnk_name in lnk_names:
            lnk = tc_dir / lnk_name
            target = get_lnk_target(lnk)
            if target is not None:
                return str(parent(target, 1))

    return None


def _find_ffmpeg() -> Optional[str]:
    """
    Find the FFmpeg installation directory from PATH.

    FFmpeg is usually installed as `<root>/bin/ffmpeg.exe`; this returns
    `<root>`, not the `bin` directory itself.

    Returns:
        FFmpeg installation directory if found, otherwise None.
    """
    target = find_executable_in_path("ffmpeg")
    if target is None:
        return None

    exe_dir = parent(target, 1)
    if exe_dir.name.casefold() == "bin":
        return str(exe_dir.parent)
    return str(exe_dir)


def _normalize_app_name(name: str) -> str:
    """
    Normalize an application name for fuzzy matching.

    Args:
        name: Application name text.

    Returns:
        Lowercase alphanumeric-only application name text.
    """
    return "".join(char for char in name.casefold() if char.isalnum())


def _to_app_name(name: Union[AppName, str]) -> Optional[AppName]:
    """
    Convert user input to an AppName value.

    Args:
        name: AppName value or application name text.

    Returns:
        Matching AppName value if matched, otherwise None.
    """
    if isinstance(name, AppName):
        return name
    if not isinstance(name, str):
        return None

    target = _normalize_app_name(name)
    for app_name in AppName:
        if target in {
            _normalize_app_name(app_name.name),
            _normalize_app_name(app_name.value),
        }:
            return app_name

    return None


def find(name: Union[AppName, str]) -> Optional[str]:
    """
    Find an application installation directory.

    Args:
        name: AppName value or application name text.

    Returns:
        Application directory path if found, otherwise None.
    """
    app_name = _to_app_name(name)
    if app_name is None:
        return None

    finders: Dict[AppName, Callable[[], Optional[str]]] = {
        AppName.VIVADO_2018_3: _find_vivado_2018_3,
        AppName.VISUAL_STUDIO_2022: lambda: _find_visual_studio("2022"),
        AppName.VISUAL_STUDIO_2017: lambda: _find_visual_studio("2017"),
        AppName.VISUAL_STUDIO_2015: lambda: _find_visual_studio("2015"),
        AppName.LABWINDOWS_CVI_2015: _find_labwindows_cvi_2015,
        AppName.TOTAL_COMMANDER: _find_total_commander,
        AppName.FFMPEG: _find_ffmpeg,
    }

    finder = finders.get(app_name)
    if finder is None:
        return None

    return finder()


__all__ = [
    "AppName",
    "find",
    "find_dir_in_programs",
    "find_executable_in_path",
    "find_link_in_programs",
    "get_all_programs",
    "get_lnk_target",
    "get_sys_programs",
    "get_sys_start_menu",
    "get_user_programs",
    "get_user_start_menu",
    "parent",
]
