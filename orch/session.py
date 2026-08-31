"""Create and lock a session directory. One session = one team."""

from __future__ import annotations

import fcntl
import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path

from orch.errors import SessionError
from orch.graph import Graph
from orch.state import Ledger, utc_now

SESSION_SUBDIRS = ("prompts", "logs", "artifacts", "wt", "baseline")


@dataclass
class Session:
    path: Path
    graph: Graph
    ledger: Ledger
    lock_fd: int | None = None
    session_id: str = ""

    @property
    def id(self) -> str:
        return self.session_id or self.path.name


def create_session(
    graph: Graph,
    session_dir: Path,
    *,
    force_unlock: bool = False,
) -> Session:
    session_dir = session_dir.resolve()
    if session_dir.exists():
        leftover = [p for p in session_dir.iterdir() if p.name != ".lock"]
        if leftover:
            raise SessionError(
                f"session dir {session_dir} exists and is not empty. "
                "One session = one team; pick a new --session-dir."
            )
    session_dir.mkdir(parents=True, exist_ok=True)
    lock_fd = _acquire_lock(session_dir, force_unlock=force_unlock)

    (session_dir / "graph.yaml").write_bytes(graph.raw_bytes)
    for name in SESSION_SUBDIRS:
        (session_dir / name).mkdir(exist_ok=True)
    (session_dir / "events.jsonl").touch()

    spec_src = graph.root / "spec"
    if spec_src.is_dir():
        _copytree(spec_src, session_dir / "spec")

    ledger = Ledger(session_dir)
    runnable = graph.runnable_nodes()
    ledger.init_nodes(sorted(runnable))
    ledger.write()
    return Session(path=session_dir, graph=graph, ledger=ledger, lock_fd=lock_fd, session_id=session_dir.name)


def _acquire_lock(session_dir: Path, *, force_unlock: bool) -> int:
    lock_path = session_dir / ".lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        owner = _read_lock(lock_path)
        pid = owner.get("pid")
        if pid and _pid_alive(int(pid)) and not force_unlock:
            os.close(fd)
            raise SessionError(
                f"session {session_dir} is locked by pid {pid} on {owner.get('hostname')}. "
                "Pass --force-unlock only if that process is dead (leaves a permanent mark)."
            )
        if not force_unlock and pid and not _pid_alive(int(pid)):
            os.close(fd)
            raise SessionError(
                f"lock looks orphan (pid {pid} is dead). Re-run with --force-unlock; "
                "the recovery is recorded permanently in preflight."
            )
        fcntl.flock(fd, fcntl.LOCK_EX)
    payload = {
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "ts": utc_now(),
        "force_unlock": force_unlock,
    }
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, (json.dumps(payload) + "\n").encode())
    os.fsync(fd)
    return fd


def _read_lock(path: Path) -> dict:
    try:
        return json.loads(path.read_text() or "{}")
    except json.JSONDecodeError:
        return {}


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _copytree(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(item.read_bytes())
