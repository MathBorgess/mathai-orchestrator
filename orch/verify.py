"""Artifact verify lives on the graph artifacts block, not on the edge."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any

from orch.graph import ArtifactSpec, Node, write_glob_prefix


ORCH_META_FILES = frozenset(
    {".lock", "graph.yaml", "state.json", "events.jsonl", "state.json.tmp"}
)
ORCH_META_DIRS = frozenset({"logs", "prompts", "wt", "baseline", "artifacts"})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_tree(root: Path) -> dict[str, tuple[str, float]]:
    out: dict[str, tuple[str, float]] = {}
    if not root.exists():
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        top = rel_dir.split("/", 1)[0] if rel_dir != "." else ""
        if top in ORCH_META_DIRS:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in ORCH_META_DIRS and not d.startswith(".")]
        for name in filenames:
            if name in ORCH_META_FILES or name.startswith("."):
                continue
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            try:
                out[rel] = (sha256_file(path), path.stat().st_mtime)
            except OSError:
                continue
    return out


def write_violations(
    before: dict[str, tuple[str, float]],
    after: dict[str, tuple[str, float]],
    writes: tuple[str, ...],
    ignore: tuple[str, ...] = (),
) -> list[str]:
    allowed = writes
    changed = set()
    for path, (digest, _) in after.items():
        prev = before.get(path)
        if prev is None or prev[0] != digest:
            changed.add(path)
    for path in before:
        if path not in after:
            changed.add(path)
    bad = [
        p
        for p in sorted(changed)
        if not any(_matches_write(p, g) for g in allowed)
        and not any(_matches_write(p, g) for g in ignore)
    ]
    return bad


def _matches_write(path: str, glob: str) -> bool:
    prefix = write_glob_prefix(glob)
    if prefix is None:
        return path == glob
    if glob == prefix:
        return path == glob
    if glob.endswith("/**"):
        return path == prefix or path.startswith(prefix.rstrip("/") + "/")
    if "/*." in glob:
        ext = glob.rsplit("*.", 1)[-1]
        return path.startswith(prefix.rstrip("/") + "/") and path.endswith("." + ext)
    return path == glob


def verify_owned(
    session_dir: Path,
    specs: list[ArtifactSpec],
    started_at_epoch: float,
    root: Path,
) -> tuple[bool, str]:
    if not specs:
        return True, "no owned artifacts"
    for spec in specs:
        path = session_dir / spec.path
        if not path.is_file():
            return False, f"{spec.path} does not exist"
        if path.stat().st_size == 0 and spec.verify.get("non_empty", True):
            return False, f"{spec.path} is empty"
        if path.stat().st_mtime < started_at_epoch - 1:
            return False, f"{spec.path} mtime is not newer than node start"
        min_lines = spec.verify.get("min_lines")
        if min_lines:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            if len(lines) < int(min_lines):
                return False, f"{spec.path} has {len(lines)} lines, need >= {min_lines}"
        cmd = spec.verify.get("cmd")
        if cmd:
            argv = [str(_resolve(cmd[0], root)), *cmd[1:]]
            proc = subprocess.run(
                argv,
                cwd=session_dir,
                capture_output=True,
                timeout=60,
                check=False,
            )
            if proc.returncode != 0:
                return False, f"{spec.path} verify.cmd exited {proc.returncode}"
    return True, "ok"


def owned_specs(artifacts: dict[str, ArtifactSpec], node: Node) -> list[ArtifactSpec]:
    return [spec for spec in artifacts.values() if spec.owner == node.id]


def _resolve(exe: str, root: Path) -> Path:
    path = Path(exe)
    if path.is_absolute():
        return path
    return root / exe
