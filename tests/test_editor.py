from __future__ import annotations

from PyQt6.QtGui import QTextCursor

from qnotebook.editor import MarkdownEditor


def test_load_and_read(qapp):
    ed = MarkdownEditor()
    ed.load_markdown("# Hello\n\nBody.\n")
    out = ed.markdown()
    assert "# Hello" in out
    assert "Body." in out
    ed.deleteLater()


def test_load_clears_dirty(qapp):
    ed = MarkdownEditor()
    ed.load_markdown("# A\n")
    assert not ed.is_dirty()
    ed.deleteLater()


def test_editing_marks_dirty(qapp):
    ed = MarkdownEditor()
    ed.load_markdown("hello\n")
    assert not ed.is_dirty()
    cur = ed.textCursor()
    cur.movePosition(QTextCursor.MoveOperation.End)
    cur.insertText(" world")
    qapp.processEvents()
    assert ed.is_dirty()
    ed.deleteLater()


def test_clear_dirty(qapp):
    ed = MarkdownEditor()
    ed.load_markdown("x\n")
    cur = ed.textCursor()
    cur.insertText("y")
    qapp.processEvents()
    assert ed.is_dirty()
    ed.clear_dirty()
    assert not ed.is_dirty()
    ed.deleteLater()


def test_toggle_bold(qapp):
    ed = MarkdownEditor()
    ed.load_markdown("hello\n")
    cur = ed.textCursor()
    cur.movePosition(QTextCursor.MoveOperation.Start)
    cur.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
    ed.setTextCursor(cur)
    ed.toggle_bold()
    out = ed.markdown()
    assert "**hello**" in out
    ed.deleteLater()


def test_toggle_italic(qapp):
    ed = MarkdownEditor()
    ed.load_markdown("hello\n")
    cur = ed.textCursor()
    cur.movePosition(QTextCursor.MoveOperation.Start)
    cur.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
    ed.setTextCursor(cur)
    ed.toggle_italic()
    out = ed.markdown()
    assert "_hello_" in out
    ed.deleteLater()


def test_set_heading(qapp):
    ed = MarkdownEditor()
    ed.load_markdown("hello\n")
    ed.set_heading(2)
    out = ed.markdown()
    assert out.startswith("## hello")
    ed.deleteLater()


def test_clear_heading(qapp):
    ed = MarkdownEditor()
    ed.load_markdown("# hello\n")
    ed.set_heading(0)
    out = ed.markdown()
    assert not out.startswith("#")
    assert "hello" in out
    ed.deleteLater()


def test_link_activated_signal(qapp, qtbot):
    ed = MarkdownEditor()
    ed.load_markdown("See [[Target]] here.\n")
    with qtbot.waitSignal(ed.linkActivated, timeout=500) as blocker:
        ed.linkActivated.emit("Target")
    assert blocker.args == ["Target"]
    ed.deleteLater()


def test_wikilink_roundtrip_via_editor(qapp):
    ed = MarkdownEditor()
    src = "Go to [[Foo:Bar]] now.\n"
    ed.load_markdown(src)
    out = ed.markdown()
    assert "[[Foo:Bar]]" in out
    ed.deleteLater()


def test_load_markdown_preserves_current_path(qapp):
    ed = MarkdownEditor()
    ed.load_markdown("x\n", page_path="Foo:Bar")
    assert ed._current_path == "Foo:Bar"
    ed.deleteLater()


# ---- image insertion ----


def _make_png(path):
    from PyQt6.QtGui import QImage
    img = QImage(32, 16, QImage.Format.Format_RGB32)
    img.fill(0xFF00FF00)
    img.save(str(path), "PNG")


def test_insert_image_via_api(qapp, tmp_path):
    from pathlib import Path
    page_dir = tmp_path
    resdir = page_dir / "_resources"
    resdir.mkdir()
    img_path = resdir / "logo.png"
    _make_png(img_path)
    ed = MarkdownEditor()
    ed.load_markdown("hello\n", base_path=page_dir)
    ed.insert_image("_resources/logo.png", "logo", str(img_path))
    md = ed.markdown()
    assert "![logo](_resources/logo.png)" in md
    ed.deleteLater()


def test_image_roundtrip(qapp, tmp_path):
    page_dir = tmp_path
    (page_dir / "_resources").mkdir()
    img_path = page_dir / "_resources" / "logo.png"
    _make_png(img_path)
    src = "![logo](_resources/logo.png)\n"
    ed = MarkdownEditor()
    ed.load_markdown(src, base_path=page_dir)
    out = ed.markdown()
    assert "![logo](_resources/logo.png)" in out
    ed.deleteLater()


def test_image_alt_preserved(qapp, tmp_path):
    page_dir = tmp_path
    (page_dir / "_resources").mkdir()
    img_path = page_dir / "_resources" / "pic.png"
    _make_png(img_path)
    src = "![My caption](_resources/pic.png)\n"
    ed = MarkdownEditor()
    ed.load_markdown(src, base_path=page_dir)
    out = ed.markdown()
    assert "![My caption](_resources/pic.png)" in out
    ed.deleteLater()


def test_insert_image_collision_rename(qapp, tmp_path):
    from qnotebook.window import _unique_path
    resdir = tmp_path / "_resources"
    resdir.mkdir()
    (resdir / "logo.png").write_bytes(b"a")
    p2 = _unique_path(resdir / "logo.png")
    assert p2.name == "logo-1.png"
    # Simulate p2 existing; next one should be -2
    p2.write_bytes(b"b")
    p3 = _unique_path(resdir / "logo.png")
    assert p3.name == "logo-2.png"


def test_pygments_highlighting_colors_code(qapp):
    """When a fenced block has a language, Pygments should color some runs."""
    try:
        import pygments  # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("Pygments not available")
    ed = MarkdownEditor()
    ed.load_markdown("```python\ndef foo(x):\n    return x\n```\n")
    # Walk the document and look for any fragment with a non-default foreground
    from PyQt6.QtGui import QColor
    doc = ed.document()
    b = doc.firstBlock()
    found_color = False
    while b.isValid():
        it = b.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid():
                fg = frag.charFormat().foreground().color()
                # A default unset foreground typically has alpha=0 / black;
                # any explicit color from our palette will have non-default components.
                if fg.isValid() and (fg.red(), fg.green(), fg.blue()) not in ((0, 0, 0),):
                    found_color = True
            it += 1
        b = b.next()
    assert found_color, "Expected at least one Pygments-colored fragment"
    ed.deleteLater()


def test_file_drop_emits_file_dropped(qapp, tmp_path):
    """Non-image file drop routes to fileDropped, not imageDropped."""
    ed = MarkdownEditor()
    ed.load_markdown("x\n")
    got_file = []
    got_image = []
    ed.fileDropped.connect(lambda p: got_file.append(p))
    ed.imageDropped.connect(lambda p: got_image.append(p))
    # Build a drop event with a local pdf url
    from PyQt6.QtCore import QMimeData, QPoint, QPointF, QUrl, Qt
    from PyQt6.QtGui import QDropEvent
    mock_file = tmp_path / "report.pdf"
    mock_file.write_bytes(b"%PDF-1.4\n")
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(mock_file))])
    evt = QDropEvent(
        QPointF(10, 10), Qt.DropAction.CopyAction, md,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    ed.dropEvent(evt)
    assert got_file == [str(mock_file)]
    assert got_image == []
    ed.deleteLater()


def test_image_drop_still_emits_image(qapp, tmp_path):
    ed = MarkdownEditor()
    ed.load_markdown("x\n")
    got_file = []
    got_image = []
    ed.fileDropped.connect(lambda p: got_file.append(p))
    ed.imageDropped.connect(lambda p: got_image.append(p))
    from PyQt6.QtCore import QMimeData, QPointF, QUrl, Qt
    from PyQt6.QtGui import QDropEvent
    img = tmp_path / "x.png"
    img.write_bytes(b"\x89PNG\r\n")
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(img))])
    evt = QDropEvent(
        QPointF(10, 10), Qt.DropAction.CopyAction, md,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    ed.dropEvent(evt)
    assert got_image == [str(img)]
    assert got_file == []
    ed.deleteLater()


def test_autosave_fires_after_interval(qapp):
    ed = MarkdownEditor()
    ed.load_markdown("x\n")
    ed.set_autosave_interval_ms(10)
    fired = []
    ed.autoSaveRequested.connect(lambda: fired.append(1))
    from PyQt6.QtGui import QTextCursor
    cur = ed.textCursor()
    cur.movePosition(QTextCursor.MoveOperation.End)
    cur.insertText(" edited")
    # Wait longer than the interval
    from PyQt6.QtCore import QTimer, QEventLoop
    loop = QEventLoop()
    QTimer.singleShot(80, loop.quit)
    loop.exec()
    assert fired, "autoSaveRequested should fire after idle"
    ed.deleteLater()


def test_autosave_off_suppresses(qapp):
    ed = MarkdownEditor()
    ed.load_markdown("x\n")
    ed.set_autosave_interval_ms(10)
    ed.set_autosave_enabled(False)
    fired = []
    ed.autoSaveRequested.connect(lambda: fired.append(1))
    from PyQt6.QtGui import QTextCursor
    cur = ed.textCursor()
    cur.movePosition(QTextCursor.MoveOperation.End)
    cur.insertText(" edited")
    from PyQt6.QtCore import QTimer, QEventLoop
    loop = QEventLoop()
    QTimer.singleShot(80, loop.quit)
    loop.exec()
    assert not fired
    ed.deleteLater()


def test_focus_out_triggers_autosave(qapp):
    ed = MarkdownEditor()
    ed.load_markdown("x\n")
    fired = []
    ed.autoSaveRequested.connect(lambda: fired.append(1))
    from PyQt6.QtGui import QTextCursor, QFocusEvent
    from PyQt6.QtCore import Qt
    cur = ed.textCursor()
    cur.movePosition(QTextCursor.MoveOperation.End)
    cur.insertText(" edited")
    # Simulate focus out
    ed.focusOutEvent(QFocusEvent(QFocusEvent.Type.FocusOut, Qt.FocusReason.OtherFocusReason))
    assert fired
    ed.deleteLater()


def test_insert_text_at_cursor(qapp):
    ed = MarkdownEditor()
    ed.load_markdown("hello")
    from PyQt6.QtGui import QTextCursor
    cur = ed.textCursor()
    cur.movePosition(QTextCursor.MoveOperation.End)
    ed.setTextCursor(cur)
    ed.insert_text_at_cursor(" world")
    assert "hello world" in ed.markdown()
    ed.deleteLater()


def test_insert_horizontal_rule(qapp):
    ed = MarkdownEditor()
    ed.load_markdown("before\n")
    from PyQt6.QtGui import QTextCursor
    cur = ed.textCursor()
    cur.movePosition(QTextCursor.MoveOperation.End)
    ed.setTextCursor(cur)
    ed.insert_horizontal_rule()
    out = ed.markdown()
    assert "before" in out
    assert "---" in out
    ed.deleteLater()


def test_image_fragment_in_markdown_source(qapp, tmp_path):
    page_dir = tmp_path
    (page_dir / "_resources").mkdir()
    img_path = page_dir / "_resources" / "logo.png"
    _make_png(img_path)
    ed = MarkdownEditor()
    ed.load_markdown("Before.\n", base_path=page_dir)
    from PyQt6.QtGui import QTextCursor
    cur = ed.textCursor()
    cur.movePosition(QTextCursor.MoveOperation.End)
    ed.setTextCursor(cur)
    ed.insert_image("_resources/logo.png", "logo", str(img_path))
    md = ed.markdown()
    assert "Before." in md
    assert "![logo](_resources/logo.png)" in md
    ed.deleteLater()


# ---- autocomplete ----


def test_completer_detects_wikilink_prefix(qapp):
    ed = MarkdownEditor()
    ed.load_markdown("")
    ed.set_completion_sources(["Home", "Other", "Sub:Child"], [])
    from PyQt6.QtGui import QTextCursor
    cur = ed.textCursor()
    cur.insertText("See [[Ho")
    info = ed._active_prefix()
    assert info is not None
    mode, prefix, _ = info
    assert mode == "wiki"
    assert prefix == "Ho"
    ed.deleteLater()


def test_completer_detects_tag_prefix(qapp):
    ed = MarkdownEditor()
    ed.load_markdown("")
    ed.set_completion_sources([], ["todo", "urgent", "review"])
    from PyQt6.QtGui import QTextCursor
    cur = ed.textCursor()
    cur.insertText("foo #tod")
    info = ed._active_prefix()
    assert info is not None
    mode, prefix, _ = info
    assert mode == "tag"
    assert prefix == "tod"
    ed.deleteLater()


def test_completer_wikilink_activation_inserts_closing_brackets(qapp):
    ed = MarkdownEditor()
    ed.load_markdown("")
    ed.set_completion_sources(["Home", "Other"], [])
    from PyQt6.QtGui import QTextCursor
    cur = ed.textCursor()
    cur.insertText("See [[Ot")
    # Simulate activation
    ed._update_completer()
    ed._on_completer_activated("Other")
    text = ed.toPlainText()
    assert "[[Other]]" in text
    ed.deleteLater()


def test_completer_inactive_outside_brackets(qapp):
    ed = MarkdownEditor()
    ed.load_markdown("")
    ed.set_completion_sources(["Home"], [])
    from PyQt6.QtGui import QTextCursor
    cur = ed.textCursor()
    cur.insertText("just plain text")
    assert ed._active_prefix() is None
    ed.deleteLater()


# ---- live reparse ----


def test_live_reparse_makes_bold(qapp):
    ed = MarkdownEditor()
    ed.load_markdown("")
    ed.set_live_reparse_enabled(True)
    from PyQt6.QtGui import QTextCursor
    cur = ed.textCursor()
    cur.insertText("this is **bold** text")
    ed.live_reparse_now()
    # Find the character format at the "b" in "bold".
    full = ed.toPlainText()
    bold_start = full.index("bold")
    cur2 = ed.textCursor()
    cur2.setPosition(bold_start + 1)
    from PyQt6.QtGui import QFont
    assert cur2.charFormat().fontWeight() >= QFont.Weight.Bold
    ed.deleteLater()


def test_live_reparse_roundtrip_preserved(qapp):
    ed = MarkdownEditor()
    ed.load_markdown("hello **world**\n")
    ed.set_live_reparse_enabled(True)
    # Trigger reparse without changing text
    ed.live_reparse_now()
    md = ed.markdown()
    assert "**world**" in md
    ed.deleteLater()


def test_live_reparse_preserves_cursor_position(qapp):
    ed = MarkdownEditor()
    ed.load_markdown("")
    ed.set_live_reparse_enabled(True)
    from PyQt6.QtGui import QTextCursor
    cur = ed.textCursor()
    cur.insertText("alpha _italic_ beta")
    # Place cursor at a known position
    target = 3
    cur.setPosition(target)
    ed.setTextCursor(cur)
    ed.live_reparse_now()
    assert ed.textCursor().position() == target
    ed.deleteLater()


def test_live_reparse_wikilink_gets_anchor(qapp):
    ed = MarkdownEditor()
    ed.load_markdown("")
    ed.set_live_reparse_enabled(True)
    from PyQt6.QtGui import QTextCursor
    from qnotebook.md_to_qdoc import CHAR_WIKILINK
    cur = ed.textCursor()
    cur.insertText("see [[Target]] now")
    ed.live_reparse_now()
    # Move cursor into the wikilink
    txt = ed.toPlainText()
    pos = txt.index("Target") + 1
    c2 = ed.textCursor()
    c2.setPosition(pos)
    prop = c2.charFormat().property(CHAR_WIKILINK)
    assert prop == "Target"
    ed.deleteLater()
