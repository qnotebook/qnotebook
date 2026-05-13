from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from PyQt6.QtCore import QSettings

from qnotebook import versioning
from qnotebook.window import MainWindow


def _has_git() -> bool:
    try:
        subprocess.run(["git", "--version"], check=True, capture_output=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


pytestmark = pytest.mark.skipif(not _has_git(), reason="git not installed")


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path_factory):
    d = tmp_path_factory.mktemp("qsettings-ver")
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(d)
    )
    s = QSettings("qnotebook", "qnotebook")
    s.clear()
    s.sync()
    yield


def test_init_and_commit_page(tmp_notebook: Path):
    assert versioning.init_repo(tmp_notebook)
    assert versioning.is_repo(tmp_notebook)
    assert versioning.commit_page(tmp_notebook, "Home")
    assert versioning.commit_count(tmp_notebook) == 1


def test_commit_noop_when_clean(tmp_notebook: Path):
    versioning.init_repo(tmp_notebook)
    versioning.commit_page(tmp_notebook, "Home")
    # Second commit with no changes should be a no-op (returns False)
    assert not versioning.commit_page(tmp_notebook, "Home")


def test_commit_page_includes_rung_in_message(tmp_notebook: Path):
    versioning.init_repo(tmp_notebook)
    (tmp_notebook / "Home.md").write_text("hello\n")
    assert versioning.commit_page(tmp_notebook, "Home", rung="trivial")
    res = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=str(tmp_notebook), capture_output=True, text=True,
    )
    assert "[trivial]" in res.stdout


def test_nb_settings_default_versioning_on_for_new_notebooks(tmp_path: Path):
    from qnotebook import nb_settings
    assert nb_settings.is_new_notebook(tmp_path)
    assert nb_settings.get(tmp_path, "versioning_enabled") is True


def test_nb_settings_roundtrip(tmp_path: Path):
    from qnotebook import nb_settings
    nb_settings.set_value(tmp_path, "versioning_enabled", False)
    assert nb_settings.get(tmp_path, "versioning_enabled") is False
    assert not nb_settings.is_new_notebook(tmp_path)


def test_new_notebook_auto_enables_versioning(qapp, tmp_path: Path, qtbot):
    from qnotebook import nb_settings
    w = MainWindow()
    qtbot.addWidget(w)
    w.open_notebook(str(tmp_path))
    assert nb_settings.get(tmp_path, "versioning_enabled") is True
    assert versioning.is_repo(tmp_path)


def test_save_commit_message_tagged_with_rung(qapp, tmp_notebook: Path, qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    w.open_notebook(str(tmp_notebook))
    w.act_toggle_versioning.setChecked(True)
    w._toggle_versioning(True)
    w.load_page("Home")
    from PyQt6.QtGui import QTextCursor
    cur = w.editor.textCursor()
    cur.movePosition(QTextCursor.MoveOperation.End)
    cur.insertText("\nnew line\n")
    qapp.processEvents()
    w._save_current()
    res = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=str(tmp_notebook), capture_output=True, text=True,
    )
    # Any of the rungs we might take — at minimum the message has a bracket tag
    assert "[" in res.stdout and "]" in res.stdout


def test_window_save_commits_when_versioning_on(qapp, tmp_notebook: Path, qtbot):
    w = MainWindow()
    w.open_notebook(str(tmp_notebook))
    qtbot.addWidget(w)
    w.act_toggle_versioning.setChecked(True)
    w._toggle_versioning(True)
    assert versioning.is_repo(tmp_notebook)
    w.load_page("Home")
    from PyQt6.QtGui import QTextCursor
    cur = w.editor.textCursor()
    cur.movePosition(QTextCursor.MoveOperation.End)
    cur.insertText("\n\nextra line\n")
    qapp.processEvents()
    before = versioning.commit_count(tmp_notebook)
    w._save_current()
    after = versioning.commit_count(tmp_notebook)
    assert after == before + 1
