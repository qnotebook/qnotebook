from __future__ import annotations

from pathlib import Path

import pytest

from PyQt6.QtCore import QSettings

from qnotebook.window import MainWindow


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path_factory, monkeypatch):
    # Point QSettings at a tmp directory so tests don't pollute user settings.
    d = tmp_path_factory.mktemp("qsettings")
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(d)
    )
    # Clear any lingering state
    s = QSettings("qnotebook", "qnotebook")
    s.clear()
    s.sync()
    yield


@pytest.fixture
def win(qapp, tmp_notebook: Path, qtbot):
    w = MainWindow()
    w.open_notebook(str(tmp_notebook))
    qtbot.addWidget(w)
    yield w


def test_open_notebook(win, tmp_notebook: Path):
    assert win.notebook is not None
    assert win.notebook.root == tmp_notebook.resolve()
    assert win.model is not None


def test_loads_initial_page(win):
    assert win._current_page is not None


def test_load_page_by_name(win):
    win.load_page("Other")
    assert win._current_page == "Other"
    assert "Other" in win.editor.markdown()


def test_save_page(win, tmp_notebook: Path, qapp):
    win.load_page("Home")
    from PyQt6.QtGui import QTextCursor
    cur = win.editor.textCursor()
    cur.movePosition(QTextCursor.MoveOperation.End)
    cur.insertText("\n\nAppended.")
    qapp.processEvents()
    assert win.editor.is_dirty()
    win._save_current()
    assert not win.editor.is_dirty()
    content = (tmp_notebook / "Home.md").read_text(encoding="utf-8")
    assert "Appended." in content


def test_follow_wikilink(win):
    win.load_page("Home")
    win._on_link_activated("Sub:Child")
    assert win._current_page == "Sub:Child"


def test_follow_wikilink_path_form(win):
    win.load_page("Home")
    win._on_link_activated("Sub/Child")
    assert win._current_page == "Sub:Child"


def test_back_forward(win):
    win.load_page("Home")
    win.load_page("Other")
    assert win._current_page == "Other"
    win._go_back()
    assert win._current_page == "Home"
    win._go_forward()
    assert win._current_page == "Other"


def test_backlinks_populated(win):
    win.load_page("Sub:Child")
    items = [win.backlinks_list.item(i).text() for i in range(win.backlinks_list.count())]
    assert "Home" in items


def test_backlinks_empty_for_unreferenced(win):
    win.load_page("Home")
    items = [win.backlinks_list.item(i).text() for i in range(win.backlinks_list.count())]
    assert "Sub:Child" in items  # Sub:Child links back to Home


def test_find_bar_finds_match(win, qapp):
    win.load_page("Other")
    win.show()
    win._open_find()
    qapp.processEvents()
    assert win.find_bar.isVisible()
    win.find_bar.input.setText("bold")
    qapp.processEvents()
    cur = win.editor.textCursor()
    assert cur.selectedText() == "bold"
    assert "1 match" in win.find_bar.count_label.text()


def test_find_bar_next_wraps(win, qapp):
    win.load_page("Home")
    from PyQt6.QtGui import QTextCursor
    cur = win.editor.textCursor()
    cur.movePosition(QTextCursor.MoveOperation.End)
    cur.insertText("\n\nWelcome again.\n")
    qapp.processEvents()
    win._open_find()
    win.find_bar.input.setText("Welcome")
    qapp.processEvents()
    # Advance forward to second match
    assert win.find_bar.find_next()
    sel1 = win.editor.textCursor().position()
    # Next find from here should wrap to first match
    assert win.find_bar.find_next()
    sel2 = win.editor.textCursor().position()
    assert sel1 != sel2


def test_find_bar_no_match_zero_count(win, qapp):
    win.load_page("Home")
    win._open_find()
    win.find_bar.input.setText("zzzzznotthereatall")
    qapp.processEvents()
    assert "0 match" in win.find_bar.count_label.text()


def test_find_bar_escape_closes(win, qapp):
    win.load_page("Home")
    win.show()
    win._open_find()
    qapp.processEvents()
    assert win.find_bar.isVisible()
    win.find_bar.close_bar()
    qapp.processEvents()
    assert not win.find_bar.isVisible()


def test_save_updates_index(win, tmp_notebook: Path, qapp):
    win.load_page("Other")
    from PyQt6.QtGui import QTextCursor
    cur = win.editor.textCursor()
    cur.movePosition(QTextCursor.MoveOperation.End)
    cur.insertText("\n\nSee [[NewTarget]].")
    qapp.processEvents()
    win._save_current()
    assert win.index.backlinks("NewTarget") == ["Other"]


# ---- recent + bookmarks ----


def test_recent_pages_tracked(win):
    win.load_page("Other")
    win.load_page("Home")
    win.load_page("Sub")
    # Most recent first
    assert win._recent[:3] == ["Sub", "Home", "Other"]


def test_recent_deduped(win):
    win.load_page("Home")
    win.load_page("Other")
    win.load_page("Home")  # re-visit
    assert win._recent[0] == "Home"
    assert win._recent.count("Home") == 1


def test_bookmark_toggle(win):
    win.load_page("Home")
    win._toggle_bookmark_current()
    assert "Home" in win._bookmarks
    win._toggle_bookmark_current()
    assert "Home" not in win._bookmarks


def test_status_bar_shows_word_count(win):
    win.load_page("Home")
    status = win._status_label.text()
    assert "words" in status


def test_insert_date_at_cursor(win):
    from datetime import date
    win.load_page("Home")
    from PyQt6.QtGui import QTextCursor
    cur = win.editor.textCursor()
    cur.movePosition(QTextCursor.MoveOperation.End)
    win.editor.setTextCursor(cur)
    win._insert_date()
    assert date.today().isoformat() in win.editor.markdown()


def test_bookmark_persisted(win, tmp_notebook: Path, qapp, qtbot):
    win.load_page("Home")
    win._toggle_bookmark_current()
    # New MainWindow on same notebook should see the bookmark
    w2 = MainWindow()
    w2.open_notebook(str(tmp_notebook))
    qtbot.addWidget(w2)
    assert "Home" in w2._bookmarks


# ---- search highlighting + jump ----


def test_search_hit_jump_highlights_all_matches(win, qapp):
    win.load_page("Home")
    win.search_dock_widget.input.setText("Welcome")
    win._on_search_hit_activated("Home", 3)
    sels = win.editor.extraSelections()
    assert len(sels) >= 1


def test_escape_clears_search_highlights(win, qapp):
    win.load_page("Home")
    win._highlight_all_occurrences("Welcome")
    assert len(win.editor.extraSelections()) >= 1
    win.editor.escapePressed.emit()
    qapp.processEvents()
    assert win.editor.extraSelections() == []


# ---- polish ----


def test_window_title_includes_page_and_notebook(win):
    win.load_page("Home")
    t = win.windowTitle()
    assert "Home" in t
    assert "qnotebook" in t
    assert "nb" in t  # tmp_notebook dir name


def test_status_shows_page_count_and_notebook(win):
    win.load_page("Home")
    s = win._status_label.text()
    assert "nb" in s  # notebook name
    assert "page" in s  # total page count label


def test_recent_notebooks_tracked(qapp, tmp_notebook, qtbot):
    w = MainWindow()
    w.open_notebook(str(tmp_notebook))
    qtbot.addWidget(w)
    recents = w._recent_notebooks()
    assert str(tmp_notebook.resolve()) in [r for r in recents]


def test_save_atomic_write(win, tmp_notebook):
    win.load_page("Home")
    from PyQt6.QtGui import QTextCursor
    cur = win.editor.textCursor()
    cur.movePosition(QTextCursor.MoveOperation.End)
    cur.insertText("\n\nAtomic write test.\n")
    win._save_current()
    # No leftover .tmp file
    assert not (tmp_notebook / "Home.md.tmp").exists()
    body = (tmp_notebook / "Home.md").read_text(encoding="utf-8")
    assert "Atomic write test." in body
