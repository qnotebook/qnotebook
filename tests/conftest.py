"""Test fixtures: tmp_notebook, qapp."""

from __future__ import annotations

import gc
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def tmp_notebook(tmp_path: Path) -> Path:
    """Create a small markdown notebook with a few pages."""
    root = tmp_path / "nb"
    root.mkdir()
    (root / "Home.md").write_text(
        "# Home\n\nWelcome. See [[Sub:Child]] and [[Other]].\n",
        encoding="utf-8",
    )
    sub = root / "Sub"
    sub.mkdir()
    (root / "Sub.md").write_text("# Sub\n\n- item\n- item2\n", encoding="utf-8")
    (sub / "Child.md").write_text(
        "# Child\n\nLinks back to [[Home]].\n", encoding="utf-8"
    )
    (root / "Other.md").write_text(
        "# Other\n\n**bold** and _italic_.\n", encoding="utf-8"
    )
    return root


@pytest.fixture(autouse=True)
def _flush_qt(qapp):
    yield
    qapp.processEvents()
    gc.collect()
    qapp.processEvents()
