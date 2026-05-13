"""Optional per-save git commits in the notebook root."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
    )


def is_repo(root: Path) -> bool:
    return (root / ".git").exists()


def init_repo(root: Path) -> bool:
    """Initialize a git repo at `root`. Returns True if the repo now exists."""
    if is_repo(root):
        return True
    res = _run(["git", "init", "-q"], root)
    if res.returncode != 0:
        return False
    # Set a local identity so commits succeed in sandboxes without global config.
    _run(["git", "config", "user.email", "qnotebook@local"], root)
    _run(["git", "config", "user.name", "qnotebook"], root)
    return is_repo(root)


def commit_page(root: Path, page: str) -> bool:
    """`git add -A && git commit -m "edit: <page>"`.

    Initializes the repo if missing. Returns True iff a new commit was made."""
    if not is_repo(root):
        if not init_repo(root):
            return False
    _run(["git", "add", "-A"], root)
    # Check for staged changes; if none, commit would fail.
    status = _run(["git", "status", "--porcelain"], root)
    if not status.stdout.strip():
        return False
    res = _run(
        ["git", "commit", "-q", "-m", f"edit: {page}"],
        root,
    )
    return res.returncode == 0


def commit_count(root: Path) -> int:
    if not is_repo(root):
        return 0
    res = _run(["git", "rev-list", "--count", "HEAD"], root)
    try:
        return int(res.stdout.strip())
    except ValueError:
        return 0
