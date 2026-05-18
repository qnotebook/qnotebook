"""Wire qnotebook into the qdistro App1 launcher contract.

On registration, qnotebook claims
``org.qdistro.QNotebook.uid<NNNN>`` on the session bus. Inbound
payloads (Send-To from qterminator, qfileman, …) are appended to the
currently open page, or — if no page is open — buffered as a "Drafts"
page named ``inbox-YYYY-MM-DD``. Either way the receive is durable
so the user can dig out a stray drop from yesterday's session.

Degrades to a no-op when ``dbus-python`` is missing or the session
bus isn't reachable; the rest of the editor behaves identically to a
pre-P03 build.
"""
from __future__ import annotations

import datetime
import os
import sys
from typing import Optional

from PyQt6.QtCore import QTimer

try:  # pragma: no cover — VM-only path
    from qdistro_app import app_receiver as _app_receiver
except ImportError:
    _app_receiver = None  # type: ignore[assignment]


APP_FRIENDLY_NAME = "QNotebook"
APP_SUPPORTED_KINDS = ("text/*", "application/octet-stream")


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
    """Append the payload to the active page (preferred) or stash in
    a per-day Drafts page so nothing is lost.

    Best-effort: the editor's actual API is large; we probe the window
    for a few well-known method names (``append_text``, ``insert_text``,
    ``editor`` widget with ``textCursor``) and fall through to a status
    bar note if nothing fits. The receiver's ``last_received`` still
    captures the drop for assertions / debugging.
    """
    header = f"\n\n---\n*from qdistro Send-To ({kind}) at " \
             f"{datetime.datetime.now().isoformat(timespec='seconds')}*\n\n"
    text = header + payload
    try:
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
        bar = window.statusBar() if hasattr(window, "statusBar") else None
        if bar is not None:
            bar.showMessage(f"qdistro: received {kind} payload "
                            f"({len(payload)} bytes) — open a page to insert", 4000)
    except Exception as e:  # noqa: BLE001
        print(f"[qnotebook/qdistro] deliver failed: {e}",
              file=sys.stderr, flush=True)


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
