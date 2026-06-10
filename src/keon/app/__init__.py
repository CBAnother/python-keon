import os
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional


def _env_path(env_name: str, *parts: str) -> Optional[Path]:
    base = os.environ.get(env_name)
    if not base:
        return None
    return Path(base, *parts)


def get_sys_start_menu() -> Optional[Path]:
    return _env_path("ALLUSERSPROFILE", "Microsoft", "Windows", "Start Menu")


def get_sys_programs() -> Optional[Path]:
    start_menu = get_sys_start_menu()
    return start_menu / "Programs" if start_menu else None


def get_user_start_menu() -> Optional[Path]:
    return _env_path("APPDATA", "Microsoft", "Windows", "Start Menu")


def get_user_programs() -> Optional[Path]:
    start_menu = get_user_start_menu()
    return start_menu / "Programs" if start_menu else None


def get_all_programs() -> List[Path]:
    paths = [
        get_sys_programs(),
        get_user_programs(),
    ]

    return [p for p in paths if p is not None and p.exists()]


def find_dir_in_programs(dir_name: str) -> Optional[Path]:
    for programs in get_all_programs():
        for root, dirs, _files in os.walk(programs):
            if dir_name in dirs:
                return Path(root) / dir_name

    return None


def find_link_in_programs(link_name: str) -> Optional[Path]:
    if not link_name.lower().endswith(".lnk"):
        link_name += ".lnk"

    target_name = link_name.casefold()

    for programs in get_all_programs():
        for root, _dirs, files in os.walk(programs):
            for file in files:
                if file.casefold() == target_name:
                    return Path(root) / file

    return None


def get_lnk_target(lnk: Optional[Path]) -> Optional[Path]:
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
    res = path
    for _ in range(level):
        res = res.parent
    return res


class AppName(Enum):
    VIVADO_2018_3 = "Vivado 2018.3"
    VISUAL_STUDIO_2022 = "Visual Studio 2022"
    VISUAL_STUDIO_2017 = "Visual Studio 2017"
    VISUAL_STUDIO_2015 = "Visual Studio 2015"
    LABWINDOWS_CVI_2015 = "LabWindows CVI 2015"
    TOTAL_COMMANDER = "Total Commander"


class AppFinder:
    @staticmethod
    def _find_vivado_2018_3() -> Optional[str]:
        xilinx_design_tools = find_dir_in_programs("Xilinx Design Tools")
        if xilinx_design_tools is None:
            return None

        lnk = xilinx_design_tools / "SDK 2018.3" / "Xilinx SDK 2018.3.lnk"
        xsdk_bat = get_lnk_target(lnk)
        if xsdk_bat is None:
            return None

        sdk_dir = parent(xsdk_bat, 4)
        return str(sdk_dir)

    @staticmethod
    def _find_visual_studio(version: str) -> Optional[str]:
        lnk = find_link_in_programs("Visual Studio {}".format(version))
        target = get_lnk_target(lnk)
        if target is None:
            return None

        vs_dir = parent(target, 3)
        return str(vs_dir)

    @staticmethod
    def _find_labwindows_cvi_2015() -> Optional[str]:
        lnk = find_link_in_programs("NI LabWindows CVI 2015")
        target = get_lnk_target(lnk)
        if target is None:
            return None

        cvi_dir = parent(target, 1)
        return str(cvi_dir)

    @staticmethod
    def _find_total_commander() -> Optional[str]:
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

    @staticmethod
    def find(name: AppName) -> Optional[str]:
        finders: Dict[AppName, Callable[[], Optional[str]]] = {
            AppName.VIVADO_2018_3: AppFinder._find_vivado_2018_3,
            AppName.VISUAL_STUDIO_2022: lambda: AppFinder._find_visual_studio("2022"),
            AppName.VISUAL_STUDIO_2017: lambda: AppFinder._find_visual_studio("2017"),
            AppName.VISUAL_STUDIO_2015: lambda: AppFinder._find_visual_studio("2015"),
            AppName.LABWINDOWS_CVI_2015: AppFinder._find_labwindows_cvi_2015,
            AppName.TOTAL_COMMANDER: AppFinder._find_total_commander,
        }

        finder = finders.get(name)
        if finder is None:
            return None

        return finder()


__all__ = [
    "AppFinder",
    "AppName",
    "find_dir_in_programs",
    "find_link_in_programs",
    "get_all_programs",
    "get_lnk_target",
    "get_sys_programs",
    "get_sys_start_menu",
    "get_user_programs",
    "get_user_start_menu",
    "parent",
]
