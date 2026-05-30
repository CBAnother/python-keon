"""
Import utilities.
"""

import importlib
import sys


def import_or_reload(pkg_name: str, recursive: bool = True):
    importlib.invalidate_caches()

    if pkg_name not in sys.modules:
        return importlib.import_module(pkg_name)

    if not recursive:
        return importlib.reload(sys.modules[pkg_name])

    prefix = pkg_name + "."

    module_names = [
        name
        for name in sys.modules
        if name == pkg_name or name.startswith(prefix)
    ]

    # Reload child modules before reloading the package itself.
    module_names.sort(key=lambda name: name.count("."), reverse=True)

    for name in module_names:
        module = sys.modules.get(name)
        if module is not None:
            importlib.reload(module)

    return sys.modules[pkg_name]


__all__ = ["import_or_reload"]
