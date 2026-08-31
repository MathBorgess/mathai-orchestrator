"""SPEC §3.5-1 is a pre-condition, not a good practice: the child spawns
grandchildren (the Bash tool), and `kill()` leaves them holding the worktree and
writing to the artifact after the node was declared failed:timeout."""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path

import pytest

from orch.adapters.claude import kill_process_group, run_process_group
from orch.env import child_env
from orch.outcome import Spawn


def _spec(tmp_path: Path, script: str, timeout_s: int) -> Spawn:
    env, _ = child_env()
    return Spawn(
        argv=["/bin/sh", "-c", script],
        cwd=str(tmp_path),
        env=env,
        stdin_bytes=b"",
        timeout_s=timeout_s,
        stdout_path=str(tmp_path / "out.jsonl"),
        stderr_path=str(tmp_path / "out.err"),
    )


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_timeout_kills_the_grandchild_not_just_the_child(tmp_path: Path) -> None:
    marker = tmp_path / "grandchild.pid"
    script = f"( sleep 30 & echo $! > {marker} ); sleep 30"
    with pytest.raises(TimeoutError):
        run_process_group(_spec(tmp_path, script, timeout_s=1))
    # give the group a moment to die
    deadline = time.time() + 5
    pid = int(marker.read_text().strip())
    while time.time() < deadline and _alive(pid):
        time.sleep(0.05)
    assert not _alive(pid), "the grandchild survived: killpg did not reach the group"


def test_children_run_in_their_own_process_group(tmp_path: Path) -> None:
    spec = _spec(tmp_path, "ps -o pgid= -p $$ > pgid.txt", timeout_s=10)
    assert run_process_group(spec) == 0
    pgid = int((tmp_path / "pgid.txt").read_text().strip())
    assert pgid != os.getpgid(os.getpid())


def test_kill_process_group_is_a_no_op_on_a_finished_process(tmp_path: Path) -> None:
    spec = _spec(tmp_path, "true", timeout_s=10)
    assert run_process_group(spec) == 0

    class Finished:
        pid = os.getpid()  # would kill the test runner's group if poll() were ignored

        def poll(self) -> int:
            return 0

    kill_process_group(Finished())  # type: ignore[arg-type]
    assert _alive(os.getpid())


def test_no_timeout_binary_and_no_flock_binary_are_used() -> None:
    """If the resource exists in the standard library, do not outsource it to a system
    binary: `timeout(1)` and `flock(1)` do not ship on macOS by default."""
    sources = [
        Path(__file__).resolve().parents[1] / "orch" / name
        for name in ("adapters/claude.py", "runner.py", "scheduler.py", "session.py")
    ]
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"'):
                continue
            assert '"timeout"' not in stripped, f"{path}: {line}"
            assert '"flock"' not in stripped, f"{path}: {line}"
    session = (Path(__file__).resolve().parents[1] / "orch" / "session.py").read_text()
    assert "fcntl.flock" in session
    assert signal.SIGKILL is not None
