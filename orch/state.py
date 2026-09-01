"""state.json is the ledger. Single writer: the orchestrator. Nodes never read it."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class NodeState:
    status: str = "pending"
    failure: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    iters_used: int = 0
    attempts: int = 0
    session_ref: str | None = None
    wall_seconds: float = 0.0
    log_bytes: int = 0
    cost_units: float = 0.0
    rc: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "failure": self.failure,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "iters_used": self.iters_used,
            "attempts": self.attempts,
            "session_ref": self.session_ref,
            "wall_seconds": round(self.wall_seconds, 3),
            "log_bytes": self.log_bytes,
            "cost_units": round(self.cost_units, 6),
            "rc": self.rc,
        }


@dataclass
class ArtifactRecord:
    path: str
    sha256: str | None
    writer_node: str | None
    mtime: float | None
    valid: bool
    hashes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "writer_node": self.writer_node,
            "mtime": self.mtime,
            "valid": self.valid,
            "hashes": list(self.hashes),
        }


class Ledger:
    def __init__(self, session_dir: Path):
        self.session_dir = session_dir
        self.path = session_dir / "state.json"
        self.events_path = session_dir / "events.jsonl"
        self.nodes: dict[str, NodeState] = {}
        self.artifacts: dict[str, ArtifactRecord] = {}
        self.budget: dict[str, Any] = {
            "iters_used": 0,
            "cost_units": 0.0,
            "wall_seconds": 0.0,
            "log_bytes": 0,
            "utilization": None,
        }
        self.violations: list[dict[str, Any]] = []
        self.deviations: list[dict[str, Any]] = []
        self.mutations: list[dict[str, Any]] = []
        self.preflight: dict[str, Any] = {}

    def init_nodes(self, ids: list[str]) -> None:
        for node_id in ids:
            self.nodes.setdefault(node_id, NodeState())

    def set_status(
        self,
        node_id: str,
        status: str,
        *,
        failure: str | None = None,
        session_ref: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        node = self.nodes.setdefault(node_id, NodeState())
        previous = node.status
        node.status = status
        if failure is not None:
            node.failure = failure
        if session_ref is not None:
            node.session_ref = session_ref
        if status == "running":
            node.started_at = utc_now()
            node.attempts += 1
        if status in {"done", "failed", "skipped"}:
            node.ended_at = utc_now()
        self.write()
        self.append_event(
            {
                "ts": utc_now(),
                "node": node_id,
                "from": previous,
                "to": status,
                "failure": failure,
                **(extra or {}),
            }
        )

    def record_artifact(
        self, path: str, sha256: str, writer: str, mtime: float, valid: bool
    ) -> None:
        rec = self.artifacts.get(path)
        if rec is None:
            rec = ArtifactRecord(path, sha256, writer, mtime, valid, [sha256])
            self.artifacts[path] = rec
        else:
            rec.sha256 = sha256
            rec.writer_node = writer
            rec.mtime = mtime
            rec.valid = valid
            rec.hashes.append(sha256)
        self.write()

    def add_deviation(
        self, kind: str, *, declared: Any, effective: Any, why: str = ""
    ) -> None:
        self.deviations.append(
            {
                "ts": utc_now(),
                "kind": kind,
                "declared": declared,
                "effective": effective,
                "why": why,
            }
        )
        self.write()

    def add_violation(self, node: str, path: str, kind: str) -> None:
        self.violations.append({"node": node, "path": path, "kind": kind})
        self.write()

    def as_dict(self) -> dict[str, Any]:
        return {
            "nodes": {k: v.as_dict() for k, v in self.nodes.items()},
            "artifacts": {k: v.as_dict() for k, v in self.artifacts.items()},
            "budget": dict(self.budget),
            "violations": list(self.violations),
            "deviations": list(self.deviations),
            "mutations": list(self.mutations),
            "preflight": dict(self.preflight),
        }

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.as_dict(), indent=2, sort_keys=True) + "\n")
        os.replace(tmp, self.path)

    def append_event(self, event: dict[str, Any]) -> None:
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")
