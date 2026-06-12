from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings
from qnotebook import plugins as plugins_mod
from qnotebook.window import MainWindow


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path_factory):
    d = tmp_path_factory.mktemp("qsettings")
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(d))
    s = QSettings("qnotebook", "qnotebook")
    s.clear()
    s.sync()


def test_discover_finds_builtin_plugins(tmp_notebook: Path):
    infos = plugins_mod.discover(tmp_notebook)
    keys = {i.key for i in infos}
    assert "journal_plugin" in keys
    assert "linkmap_plugin" in keys
    assert "word_of_the_day" in keys


def test_user_plugin_loaded_from_notebook(tmp_path: Path):
    root = tmp_path / "nb"
    root.mkdir()
    plugdir = root / ".qnotebook" / "plugins"
    plugdir.mkdir(parents=True)
    (plugdir / "myplug.py").write_text(
        "class Plugin:\n"
        "    name = 'My Plug'\n"
        "    description = 'test'\n"
        "    def setup(self, w):\n"
        "        w._myplug_setup_called = True\n",
        encoding="utf-8",
    )
    infos = plugins_mod.discover(root)
    user = [i for i in infos if i.source == "user"]
    assert any(i.name == "My Plug" for i in user)
    assert all(i.plugin is None for i in user)


def test_user_plugin_discovery_does_not_execute_code(tmp_path: Path):
    root = tmp_path / "nb"
    root.mkdir()
    marker = tmp_path / "executed"
    plugdir = root / ".qnotebook" / "plugins"
    plugdir.mkdir(parents=True)
    (plugdir / "side_effect.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('ran')\n"
        "class Plugin:\n"
        "    name = 'Side Effect'\n"
        "    description = 'must not run on discover'\n"
        "    def setup(self, w):\n"
        "        w.side_effect = True\n",
        encoding="utf-8",
    )
    infos = plugins_mod.discover(root)
    assert any(i.name == "Side Effect" for i in infos)
    assert not marker.exists()


def test_enabled_user_plugin_executes_at_setup_only(tmp_path: Path):
    root = tmp_path / "nb"
    root.mkdir()
    marker = tmp_path / "executed"
    plugdir = root / ".qnotebook" / "plugins"
    plugdir.mkdir(parents=True)
    (plugdir / "side_effect.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('imported')\n"
        "class Plugin:\n"
        "    name = 'Side Effect'\n"
        "    description = 'runs only when enabled'\n"
        "    def setup(self, w):\n"
        "        w.side_effect = True\n",
        encoding="utf-8",
    )
    infos = plugins_mod.discover(root)
    assert not marker.exists()
    window = type("Window", (), {})()
    activated = plugins_mod.setup_enabled(window, infos, {"user:side_effect"})
    assert activated == ["user:side_effect"]
    assert marker.read_text(encoding="utf-8") == "imported"
    assert window.side_effect is True


def test_window_plugins_menu_populated(qapp, tmp_notebook: Path, qtbot):
    w = MainWindow()
    w.open_notebook(str(tmp_notebook))
    qtbot.addWidget(w)
    assert hasattr(w, "m_plugins")
    actions = [a.text() for a in w.m_plugins.actions()]
    assert any("Journal" in t for t in actions)


def test_enabling_plugin_persists(qapp, tmp_notebook: Path, qtbot):
    w = MainWindow()
    w.open_notebook(str(tmp_notebook))
    qtbot.addWidget(w)
    w._toggle_plugin("word_of_the_day", True)
    s = QSettings("qnotebook", "qnotebook")
    enabled = s.value("plugins_enabled", [], type=list) or []
    assert "word_of_the_day" in [str(x) for x in enabled]


def test_toggle_user_plugin_activates_immediately(qapp, tmp_path: Path, qtbot):
    root = tmp_path / "nb"
    root.mkdir()
    plugdir = root / ".qnotebook" / "plugins"
    plugdir.mkdir(parents=True)
    (plugdir / "myplug.py").write_text(
        "class Plugin:\n"
        "    name = 'My Plug'\n"
        "    description = 'test'\n"
        "    def setup(self, w):\n"
        "        w._myplug_setup_called = True\n",
        encoding="utf-8",
    )
    w = MainWindow()
    w.open_notebook(str(root))
    qtbot.addWidget(w)
    assert not hasattr(w, "_myplug_setup_called")
    w._toggle_plugin("user:myplug", True)
    assert w._myplug_setup_called is True
    s = QSettings("qnotebook", "qnotebook")
    enabled = s.value("plugins_enabled", [], type=list) or []
    assert "user:myplug" in [str(x) for x in enabled]


def test_word_count_plugin_runs(qapp, tmp_notebook: Path, qtbot):
    s = QSettings("qnotebook", "qnotebook")
    s.setValue("plugins_enabled", ["word_of_the_day"])
    s.sync()
    w = MainWindow()
    w.open_notebook(str(tmp_notebook))
    qtbot.addWidget(w)
    # Find the word-count label among the discovered plugin instances.
    labels = []
    for info in w._plugin_infos:
        if info.key == "word_of_the_day":
            label = getattr(info.plugin, "label", None)
            if label is not None:
                labels.append(label)
    assert labels, "word_of_the_day plugin should have a label"
    assert "words:" in labels[0].text()
