"""Audit: user-content writes in qnotebook/ must go through SafeWriter.

Internal state files (merge.log, session.json, lock, index.sqlite, exported
html/pdf/md destinations, copied resources) are exempt and listed below.
"""

from __future__ import annotations

import re
from pathlib import Path


SRC = Path(__file__).parent.parent / "qnotebook"


# Files/modules that are allowed to call Path.write_* directly:
EXEMPT_MODULES = {
    "safe_save.py",          # implements atomic_write itself
    "session.py",            # internal session state
    "locks.py",              # lock file
    "nb_settings.py",        # internal settings
    "export.py",             # exporting to user-chosen destination
    "cli.py",                # export destinations
    "importers/zim_wiki.py", # one-shot import
    "snapshots.py",          # routes through atomic_write via safe_save
}


PATTERNS = [
    re.compile(r"\.write_text\s*\("),
    re.compile(r"\.write_bytes\s*\("),
    re.compile(r"open\s*\([^)]*['\"][wab]+['\"]"),
]


def test_no_direct_write_outside_exempt() -> None:
    offenders: list[str] = []
    for p in SRC.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        rel = str(p.relative_to(SRC))
        if rel in EXEMPT_MODULES or rel.replace("\\", "/") in EXEMPT_MODULES:
            continue
        text = p.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            if "# safe-writer-exempt" in line:
                continue
            for rx in PATTERNS:
                if rx.search(line):
                    # Allow safe_save.atomic_write calls (false positive
                    # because atomic_write internally writes) — these are
                    # already exempted in EXEMPT_MODULES.
                    offenders.append(f"{rel}:{lineno}: {line.strip()}")
                    break
    assert offenders == [], "Unexpected direct writes:\n" + "\n".join(offenders)
