from __future__ import annotations

from pathlib import Path

import pytest

from PyQt6.QtCore import QSettings

from qnotebook.linkmap import LinkMapDock
from qnotebook.window import MainWindow


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path_factory):
    d = tmp_path_factory.mktemp("qsettings-linkmap")
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(d)
    )
    s = QSettings("qnotebook", "qnotebook")
    s.clear()
    s.sync()
    yield


def test_linkmap_builds_nodes(qapp, qtbot):
    dock = LinkMapDock()
    qtbot.addWidget(dock)
    dock.build("Home", ["Sub:Child", "Other"], ["Sub:Child"])
    # Should create center node + 2 distinct peers
    assert "Home" in dock._nodes
    assert "Sub:Child" in dock._nodes
    assert "Other" in dock._nodes


def test_linkmap_integration_with_window(qapp, tmp_notebook: Path, qtbot):
    w = MainWindow()
    w.open_notebook(str(tmp_notebook))
    qtbot.addWidget(w)
    w.load_page("Home")
    w._toggle_linkmap_dock(True)
    assert w._current_page == "Home"
    # Home has forward links to Sub:Child and Other
    assert "Home" in w.linkmap_widget._nodes
    assert "Sub:Child" in w.linkmap_widget._nodes or "Other" in w.linkmap_widget._nodes


def test_linkmap_click_navigates(qapp, tmp_notebook: Path, qtbot):
    w = MainWindow()
    w.open_notebook(str(tmp_notebook))
    qtbot.addWidget(w)
    w.load_page("Home")
    # Programmatically invoke the on_navigate callback (scene click simulation is brittle)
    w.linkmap_widget._on_navigate("Other")
    assert w._current_page == "Other"
