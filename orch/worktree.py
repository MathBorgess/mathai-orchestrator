"""Git worktree per fanout instance. The parent owns the lifecycle (SPEC §2.4, §3.6).

One worktree per instance when concurrency > 1: a distinct cwd is a distinct project
directory in the CLI cache, which closes the cross-context leak that is not the model's.
Creation is the parent's, removal is the parent's, and it happens in `verifying` —
never at the end of the session, or a 12-node graph keeps 12 checkouts alive.

The branch is left behind on purpose: it is the forensic record of a node that died.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from orch.errors import OrchError, EXIT_PREFLIGHT


class WorktreeError(OrchError):
    exit_code = EXIT_PREFLIGHT


def _git(root: Path, *args: str, timeout: float = 30.0) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def availability(root: Path) -> tuple[bool, str]:
    """(usable, reason). Never raises: the caller decides refuse vs degrade."""
    try:
        rev = _git(root, "rev-parse", "--show-toplevel", timeout=10.0)
    except FileNotFoundError:
        return False, "git is not on PATH"
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"git rev-parse failed: {exc}"
    if rev.returncode != 0:
        return False, f"{root} is not inside a git work tree"
    try:
        listing = _git(root, "worktree", "list", timeout=10.0)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"git worktree list failed: {exc}"
    if listing.returncode != 0:
        err = listing.stderr.decode("utf-8", "replace").strip()
        return False, f"git worktree is unavailable: {err or 'exit ' + str(listing.returncode)}"
    return True, "ok"


def branch_name(session_id: str, node_id: str) -> str:
    return f"orch/{session_id}/{node_id}"


def add(root: Path, path: Path, branch: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    proc = _git(root, "worktree", "add", str(path), "-b", branch, timeout=120.0)
    if proc.returncode != 0:
        raise WorktreeError(
            f"git worktree add {path} -b {branch} failed "
            f"(exit {proc.returncode}): {proc.stderr.decode('utf-8', 'replace').strip()}"
        )


def remove(root: Path, path: Path) -> str | None:
    """Best effort. Returns an error string instead of raising: a stuck worktree must
    not turn a `done` node into a failed one, but it must be visible in the log."""
    if not path.exists():
        return None
    proc = _git(root, "worktree", "remove", "--force", str(path), timeout=120.0)
    if proc.returncode != 0:
        return proc.stderr.decode("utf-8", "replace").strip() or f"exit {proc.returncode}"
    _git(root, "worktree", "prune", timeout=30.0)
    return None
