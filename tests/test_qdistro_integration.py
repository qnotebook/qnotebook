"""Inbound-payload hardening tests for the qdistro App1 integration
(review finding: "qnotebook accepts unbounded qdistro App1 payloads
into the active document").

These assert the three boundaries added to
``qnotebook.qdistro_integration._deliver_to_page``:

  1. an oversized payload is rejected (not appended, not silently
     truncated into the page);
  2. ``application/octet-stream`` (and any non-text kind) is refused —
     never blindly inserted into the editor;
  3. inbound text is *staged* for explicit confirmation and only lands
     in the active page after the user says yes.

Runnable headless (``QT_QPA_PLATFORM=offscreen`` is set by conftest).
A real ``QTextEdit`` stands in for the editor so the cursor/insert path
is exercised exactly as in the app.

Before the fix ``_deliver_to_page`` concatenated *any* kind/size
payload straight into the editor with no confirmation, so:
  - the octet-stream test would find binary text in the editor,
  - the oversized test would find the payload appended, and
  - the staging test would find the text auto-appended with no
    pending inbox entry.
"""

from __future__ import annotations

import os
import sys

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PyQt6 = pytest.importorskip("PyQt6", reason="PyQt6 not installed")
from PyQt6.QtWidgets import QMainWindow, QTextEdit  # noqa: E402

from qnotebook import qdistro_integration as qi  # noqa: E402


def test_binding_is_pyqt6():
    """Guard against PySide6 silently shadowing PyQt6."""
    assert "PySide6" not in sys.modules
    from PyQt6.QtCore import PYQT_VERSION_STR  # noqa: F401


class _FakeWindow(QMainWindow):
    """Minimal stand-in: a real QTextEdit editor + a status bar, the two
    surfaces _deliver_to_page touches. ``_qdistro_autoconfirm`` lets the
    test decide the confirmation outcome without a modal dialog."""

    def __init__(self, autoconfirm=None):
        super().__init__()
        self.editor = QTextEdit(self)
        self.setCentralWidget(self.editor)
        self.editor.setPlainText("# Existing note\n")
        if autoconfirm is not None:
            self._qdistro_autoconfirm = autoconfirm
        self.status_messages = []
        self.statusBar().messageChanged.connect(
            lambda m: m and self.status_messages.append(m))


@pytest.fixture
def win(qapp):
    w = _FakeWindow()
    yield w
    w.close()


def _editor_text(w):
    return w.editor.toPlainText()


# --------------------------------------------------------------------------
# 2. content-kind enforcement
# --------------------------------------------------------------------------
@pytest.mark.cheat_aware(
    protects="binary/non-text App1 payloads are never inserted into the "
    "active document",
    severity="medium",
    cheats=[
        "advertise application/octet-stream again and append it as text",
        "weaken _is_text_kind to accept octet-stream",
    ],
    consequence="a sender can splat arbitrary binary into the user's note, "
    "corrupting or bloating the page",
)
def test_octet_stream_is_refused(qapp):
    w = _FakeWindow(autoconfirm=True)  # even if confirmed, must not insert
    before = _editor_text(w)
    result = qi._deliver_to_page(w, "application/octet-stream",
                                 "\x00\x01\x02binary\xff")
    assert result is None, "octet-stream should be rejected, not staged"
    assert _editor_text(w) == before, "binary payload leaked into the editor"
    assert getattr(w, "_qdistro_inbox", []) == []
    w.close()


def test_non_text_kind_is_refused(qapp):
    w = _FakeWindow(autoconfirm=True)
    before = _editor_text(w)
    assert qi._deliver_to_page(w, "image/png", "PNGDATA") is None
    assert _editor_text(w) == before
    w.close()


def test_octet_stream_not_in_advertised_kinds():
    assert "application/octet-stream" not in qi.APP_SUPPORTED_KINDS
    assert qi.APP_SUPPORTED_KINDS == ("text/*",)


# --------------------------------------------------------------------------
# 1. size cap
# --------------------------------------------------------------------------
@pytest.mark.cheat_aware(
    protects="an oversized inbound payload cannot be forced into the page",
    severity="medium",
    cheats=[
        "raise MAX_PAYLOAD_BYTES so the test payload fits",
        "truncate-and-append instead of refusing",
    ],
    consequence="a hostile/runaway sender freezes the editor and bloats the "
    "active note",
)
def test_oversized_payload_is_rejected(win):
    big = "A" * (qi.MAX_PAYLOAD_BYTES + 1)
    before = _editor_text(win)
    result = qi._deliver_to_page(win, "text/plain", big)
    assert result is None, "oversized payload should be rejected"
    assert _editor_text(win) == before, "oversized payload was appended"
    # not even a truncated fragment landed
    assert "A" * 100 not in _editor_text(win)
    assert getattr(win, "_qdistro_inbox", []) == []


def test_at_limit_payload_is_accepted(qapp):
    w = _FakeWindow(autoconfirm=True)
    ok_payload = "B" * qi.MAX_PAYLOAD_BYTES
    drop = qi._deliver_to_page(w, "text/plain", ok_payload)
    assert drop is not None
    assert ok_payload in _editor_text(w)
    w.close()


# --------------------------------------------------------------------------
# 3. staging + confirmation
# --------------------------------------------------------------------------
@pytest.mark.cheat_aware(
    protects="inbound text is staged and requires explicit user confirmation "
    "before it mutates the active page",
    severity="medium",
    cheats=[
        "auto-append without consulting _confirm_drop",
        "treat a dismissed dialog as 'yes'",
    ],
    consequence="a remote sender silently edits the user's open document",
)
def test_text_staged_and_held_when_declined(qapp):
    w = _FakeWindow(autoconfirm=False)  # user says No
    before = _editor_text(w)
    drop = qi._deliver_to_page(w, "text/plain", "hello from afar")
    assert drop is not None, "text should be staged"
    assert _editor_text(w) == before, "text appended despite decline"
    # declined drop is retained in the inbox so it isn't lost
    assert drop in w._qdistro_inbox
    assert drop.sender, "staged record must carry sender provenance"
    assert drop.kind == "text/plain"
    w.close()


def test_text_appended_only_after_confirmation(qapp):
    w = _FakeWindow(autoconfirm=True)  # user says Yes
    drop = qi._deliver_to_page(w, "text/plain", "approved content")
    assert drop is not None
    assert "approved content" in _editor_text(w)
    # confirmed drop is cleared from the inbox
    assert drop not in getattr(w, "_qdistro_inbox", [])
    # provenance header was written
    assert "from" in _editor_text(w) and drop.kind in _editor_text(w)
    w.close()


def test_confirm_drop_consults_dialog_by_default(qapp, monkeypatch):
    """Without _qdistro_autoconfirm, _confirm_drop must go through the
    QMessageBox path (proves we don't auto-append in production)."""
    w = _FakeWindow()  # no autoconfirm attribute
    calls = {"n": 0}

    from PyQt6.QtWidgets import QMessageBox as _RealBox

    class _FakeBox:
        Icon = _RealBox.Icon
        StandardButton = _RealBox.StandardButton

        def __init__(self, *a, **k):
            calls["n"] += 1

        def setIcon(self, *a):
            pass

        def setWindowTitle(self, *a):
            pass

        def setText(self, *a):
            pass

        def setInformativeText(self, *a):
            pass

        def setStandardButtons(self, *a):
            pass

        def setDefaultButton(self, *a):
            pass

        def exec(self):
            return _RealBox.StandardButton.No

    monkeypatch.setattr(qi, "QMessageBox", _FakeBox)
    before = _editor_text(w)
    qi._deliver_to_page(w, "text/plain", "needs a click")
    assert calls["n"] == 1, "confirmation dialog was not shown"
    assert _editor_text(w) == before, "appended without a real yes"
    w.close()
