"""Plugin discovery and loading.

A plugin is a Python module exposing a `Plugin` class with at least:

    class Plugin:
        name: str
        description: str
        def setup(self, window): ...

Plugins are discovered from two locations:

- bundled: `qnotebook/plugins/builtin/*.py`
- per-notebook: `<notebook>/.qnotebook/plugins/*.py`

Per-notebook plugins are loaded by absolute filesystem path; bundled
plugins are imported as `qnotebook.plugins.builtin.<name>`.
"""

from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class PluginInfo:
    key: str        # unique identifier (module name or filename stem)
    name: str
    description: str
    source: str     # "builtin" | "user"
    plugin: Any     # the Plugin instance


def _instance_from_module(mod) -> Any | None:
    cls = getattr(mod, "Plugin", None)
    if cls is None:
        return None
    try:
        inst = cls()
    except Exception:
        return None
    if not hasattr(inst, "setup"):
        return None
    return inst


def discover(notebook_root: Path | None = None) -> list[PluginInfo]:
    """Find available plugins from builtin + (optional) notebook .qnotebook/plugins."""
    out: list[PluginInfo] = []
    builtin_dir = Path(__file__).parent / "builtin"
    if builtin_dir.is_dir():
        for f in sorted(builtin_dir.glob("*.py")):
            if f.name.startswith("_"):
                continue
            modname = f"qnotebook.plugins.builtin.{f.stem}"
            try:
                mod = importlib.import_module(modname)
            except Exception:
                continue
            inst = _instance_from_module(mod)
            if inst is None:
                continue
            out.append(PluginInfo(
                key=f.stem,
                name=getattr(inst, "name", f.stem),
                description=getattr(inst, "description", ""),
                source="builtin",
                plugin=inst,
            ))
    if notebook_root is not None:
        user_dir = notebook_root / ".qnotebook" / "plugins"
        if user_dir.is_dir():
            for f in sorted(user_dir.glob("*.py")):
                if f.name.startswith("_"):
                    continue
                spec = importlib.util.spec_from_file_location(
                    f"qnotebook_user_plugin_{f.stem}", str(f)
                )
                if spec is None or spec.loader is None:
                    continue
                mod = importlib.util.module_from_spec(spec)
                try:
                    spec.loader.exec_module(mod)
                except Exception:
                    continue
                inst = _instance_from_module(mod)
                if inst is None:
                    continue
                out.append(PluginInfo(
                    key=f"user:{f.stem}",
                    name=getattr(inst, "name", f.stem),
                    description=getattr(inst, "description", ""),
                    source="user",
                    plugin=inst,
                ))
    return out


def setup_enabled(window, infos: list[PluginInfo], enabled_keys: set[str]) -> list[str]:
    """Call `setup(window)` on each enabled plugin. Returns list of activated keys."""
    activated: list[str] = []
    for info in infos:
        if info.key not in enabled_keys:
            continue
        try:
            info.plugin.setup(window)
            activated.append(info.key)
        except Exception:
            pass
    return activated
