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
import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class PluginInfo:
    key: str        # unique identifier (module name or filename stem)
    name: str
    description: str
    source: str     # "builtin" | "user"
    plugin: Any | None     # the Plugin instance; user plugins load only when enabled
    path: Path | None = None


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
                path=f,
            ))
    if notebook_root is not None:
        user_dir = notebook_root / ".qnotebook" / "plugins"
        if user_dir.is_dir():
            for f in sorted(user_dir.glob("*.py")):
                if f.name.startswith("_"):
                    continue
                name, description = _read_user_plugin_metadata(f)
                out.append(PluginInfo(
                    key=f"user:{f.stem}",
                    name=name or f.stem,
                    description=description or "",
                    source="user",
                    plugin=None,
                    path=f,
                ))
    return out


def _read_user_plugin_metadata(path: Path) -> tuple[str | None, str | None]:
    """Read Plugin.name/description constants without executing plugin code."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None, None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Plugin":
            values: dict[str, str] = {}
            for stmt in node.body:
                target_name = None
                value = None
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                    target = stmt.targets[0]
                    if isinstance(target, ast.Name):
                        target_name = target.id
                    value = stmt.value
                elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    target_name = stmt.target.id
                    value = stmt.value
                if target_name in ("name", "description"):
                    try:
                        const = ast.literal_eval(value)
                    except (TypeError, ValueError):
                        continue
                    if isinstance(const, str):
                        values[target_name] = const
            return values.get("name"), values.get("description")
    return None, None


def _load_user_plugin(path: Path, key: str) -> Any | None:
    spec = importlib.util.spec_from_file_location(
        f"qnotebook_user_plugin_{key.replace(':', '_')}", str(path)
    )
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        return None
    return _instance_from_module(mod)


def setup_enabled(window, infos: list[PluginInfo], enabled_keys: set[str]) -> list[str]:
    """Call `setup(window)` on each enabled plugin. Returns list of activated keys."""
    activated: list[str] = []
    for info in infos:
        if info.key not in enabled_keys:
            continue
        plugin = info.plugin
        if plugin is None and info.source == "user" and info.path is not None:
            plugin = _load_user_plugin(info.path, info.key)
        if plugin is None:
            continue
        try:
            plugin.setup(window)
            activated.append(info.key)
        except Exception:
            pass
    return activated
