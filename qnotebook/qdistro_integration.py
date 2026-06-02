"""Wire qnotebook into the qdistro App1 launcher contract.

On registration, qnotebook claims
``org.qdistro.QNotebook.uid<NNNN>`` on the session bus. Inbound
payloads (Send-To from qterminator, qfileman, …) are **staged** for
explicit user confirmation before they touch the active document — a
remote sender on the App1 relay must never be able to silently mutate
the user's open note. The staged record carries the sender / kind /
size / timestamp so the user can make an informed accept-or-discard
decision.

Hardening (see review finding: "qnotebook accepts unbounded qdistro
App1 payloads into the active document"):

  * payloads larger than ``MAX_PAYLOAD_BYTES`` are rejected with a
    clear status message — never appended, never truncated-silently;
  * ``application/octet-stream`` (and any non-``text/*`` kind) is
    refused: qnotebook has no file-attachment path, so binary must not
    be splatted into the editor as text;
  * accepted text is staged in an inbox and the user must confirm via
    a dialog before it is appended to the active page.

Degrades to a no-op when ``dbus-python`` is missing or the session
bus isn't reachable; the rest of the editor behaves identically to a
pre-P03 build.
"""
from __future__ import annotations

import datetime
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox

try:  # pragma: no cover — VM-only path
    from qdistro_app import app_receiver as _app_receiver
except ImportError:
    _app_receiver = None  # type: ignore[assignment]


APP_FRIENDLY_NAME = "Qnotebook"
# qnotebook is a *text* notebook. We advertise only text kinds so the
# broker / Send-To menu never offers qnotebook as a sink for binary.
# application/octet-stream is intentionally NOT here (no attachment
# path), and _deliver_to_page rejects it defensively even if a sender
# ignores the advertised kinds.
APP_SUPPORTED_KINDS = ("text/*",)

# Hard cap on an accepted inbound payload. Above this we refuse rather
# than freeze the editor / bloat the page. 256 KiB is generous for a
# Send-To text drop while still bounding a hostile or runaway sender.
MAX_PAYLOAD_BYTES = 256 * 1024


@dataclass
class StagedDrop:
    """An inbound App1 payload held for user confirmation.

    Nothing here has touched the active document yet. ``sender`` is
    best-effort: the App1 ``on_receive`` callback only carries
    ``(kind, payload)``, so unless the host wires through a richer
    record we record the kind/relay as the provenance the user sees.
    """

    kind: str
    payload: str
    sender: str = "qdistro Send-To (App1 relay)"
    received_at: str = field(
        default_factory=lambda:
        datetime.datetime.now().isoformat(timespec="seconds"))

    @property
    def size_bytes(self) -> int:
        return len(self.payload.encode("utf-8", errors="replace"))

    def header(self) -> str:
        return (f"\n\n---\n*from {self.sender} ({self.kind}) at "
                f"{self.received_at}*\n\n")


def _is_text_kind(kind: str) -> bool:
    """True only for ``text/...`` kinds. Everything else (including
    ``application/octet-stream``) is refused — qnotebook has no
    file-attachment path to land binary safely."""
    return isinstance(kind, str) and kind.lower().startswith("text/")


def _status(window, msg: str, timeout_ms: int = 6000) -> None:
    try:
        bar = window.statusBar() if hasattr(window, "statusBar") else None
        if bar is not None:
            bar.showMessage(msg, timeout_ms)
    except Exception:  # noqa: BLE001
        pass
    print(f"[qnotebook/qdistro] {msg}", flush=True)


def maybe_install(window) -> Optional[object]:
    if _app_receiver is None:
        print("[qnotebook/qdistro] qdistro_app SDK not importable; "
              "App1 registration skipped",
              file=sys.stderr, flush=True)
        return None

    def on_receive(kind: str, payload: str) -> None:
        QTimer.singleShot(0, lambda: _deliver_to_page(window, kind, payload))

    receiver = _app_receiver.register_app(
        APP_FRIENDLY_NAME,
        on_receive=on_receive,
        friendly_name=APP_FRIENDLY_NAME,
        supported_kinds=APP_SUPPORTED_KINDS,
    )
    if receiver is None:
        return None
    print(f"[qnotebook/qdistro] App1 receiver registered as "
          f"{receiver.service_name} (silo={receiver.silo!r})",
          flush=True)
    return receiver


def _deliver_to_page(window, kind: str, payload: str) -> None:
    """Validate, then **stage** an inbound payload for confirmation.

    This is the security boundary for finding "qnotebook accepts
    unbounded qdistro App1 payloads into the active document". It never
    writes to the editor directly; it screens the drop and hands a
    :class:`StagedDrop` to :func:`_stage_for_confirmation`, which asks
    the user before anything durable happens.

    Returns the :class:`StagedDrop` when one was staged (accepted for
    confirmation), else ``None`` (rejected). The return value is for
    callers/tests; the GUI path ignores it.
    """
    payload = "" if payload is None else str(payload)
    # 1. Content-kind enforcement: refuse binary / non-text outright.
    if not _is_text_kind(kind):
        _status(window,
                f"qdistro: refused {kind!r} payload — qnotebook only "
                f"accepts text (no file-attachment path)")
        return None
    # 2. Size cap: refuse (do not truncate-into-the-page) oversized drops.
    size = len(payload.encode("utf-8", errors="replace"))
    if size > MAX_PAYLOAD_BYTES:
        _status(window,
                f"qdistro: refused oversized {kind} payload "
                f"({size} bytes > {MAX_PAYLOAD_BYTES} limit)")
        return None
    # 3. Stage for explicit user confirmation; nothing is appended yet.
    drop = StagedDrop(kind=kind, payload=payload)
    _stage_for_confirmation(window, drop)
    return drop


def _confirm_drop(window, drop: "StagedDrop") -> bool:
    """Ask the user whether to append the staged drop. Overridable in
    tests / headless runs by setting ``window._qdistro_autoconfirm`` to
    True/False to skip the modal dialog."""
    auto = getattr(window, "_qdistro_autoconfirm", None)
    if auto is not None:
        return bool(auto)
    preview = drop.payload if len(drop.payload) <= 200 \
        else drop.payload[:200] + "…"
    box = QMessageBox(window)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("qdistro: incoming text")
    box.setText(f"{drop.sender} sent {drop.size_bytes} bytes ({drop.kind}).\n"
                f"Append it to the current page?")
    box.setInformativeText(preview)
    box.setStandardButtons(
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    return box.exec() == QMessageBox.StandardButton.Yes


def _stage_for_confirmation(window, drop: "StagedDrop") -> None:
    """Hold the drop in an inbox, prompt the user, and only on an
    explicit yes append it to the active page.

    The pending drop is recorded on ``window._qdistro_inbox`` so it is
    not lost if the dialog is dismissed and so it is inspectable for
    tests / debugging.
    """
    inbox = getattr(window, "_qdistro_inbox", None)
    if inbox is None:
        inbox = []
        try:
            window._qdistro_inbox = inbox
        except Exception:  # noqa: BLE001
            pass
    inbox.append(drop)

    try:
        if not _confirm_drop(window, drop):
            _status(window, f"qdistro: held {drop.size_bytes}-byte {drop.kind} "
                            f"drop in inbox (not appended)")
            return
        _append_confirmed(window, drop)
        try:
            inbox.remove(drop)
        except ValueError:
            pass
    except Exception as e:  # noqa: BLE001
        print(f"[qnotebook/qdistro] staging failed: {e}",
              file=sys.stderr, flush=True)


def _append_confirmed(window, drop: "StagedDrop") -> None:
    """Append a user-confirmed drop to the active page. Only reached
    after :func:`_confirm_drop` returns True."""
    text = drop.header() + drop.payload
    if hasattr(window, "append_text_to_current_page"):
        window.append_text_to_current_page(text)
        return
    editor = getattr(window, "editor", None)
    if editor is not None and hasattr(editor, "textCursor"):
        cur = editor.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        cur.insertText(text)
        editor.setTextCursor(cur)
        return
    _status(window, f"qdistro: {drop.kind} payload accepted "
                    f"({drop.size_bytes} bytes) — open a page to insert")


def send_to_targets(*, kind: str = "text/plain") -> list[dict]:
    if _app_receiver is None:
        return []
    try:
        self_service = f"org.qdistro.{APP_FRIENDLY_NAME}.uid{os.geteuid()}"
        return _app_receiver.send_to_menu_targets(
            self_service=self_service, kind=kind)
    except Exception as e:  # noqa: BLE001
        print(f"[qnotebook/qdistro] send_to_menu_targets failed: {e}",
              file=sys.stderr, flush=True)
        return []


def send_payload(target_uid: int, target_service: str, payload: str, *,
                 kind: str = "text/plain") -> bool:
    if _app_receiver is None:
        return False
    try:
        return bool(_app_receiver.send_to(int(target_uid),
                                          str(target_service),
                                          str(kind), str(payload)))
    except Exception as e:  # noqa: BLE001
        print(f"[qnotebook/qdistro] send_to({target_service}) failed: {e}",
              file=sys.stderr, flush=True)
        return False
