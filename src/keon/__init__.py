import importlib as _importlib
from typing import Any, TYPE_CHECKING

__all__ = [
    "app",
    "conda",
    "ffmpeg",
    "importlib",
    "json",
    "network",
    "os",
    "vpn",
]

if TYPE_CHECKING:
    from . import app, conda, ffmpeg, importlib, json, network, os, vpn  # type: ignore[no-redef]


def __getattr__(name) -> Any:
    if name in __all__:
        module = _importlib.import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(list(globals()) + __all__)
