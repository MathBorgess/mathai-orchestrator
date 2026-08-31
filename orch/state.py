"""Session ledger: graph + node status + which artifacts exist. Single writer."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from orch.graph import Graph

Status = Literal["pending", "running", "done", "failed"]


@dataclass
class State:
    graph_id: str
    nodes: dict[str, Status]
    artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "graph": self.graph_id,
            "nodes": {node_id: {"status": status} for node_id, status in self.nodes.items()},
            "artifacts": list(self.artifacts),
        }

    @classmethod
    def initial(cls, graph: Graph) -> State:
        return cls(
            graph_id=graph.id,
            nodes={node_id: "pending" for node_id in graph.nodes},
        )


def write_state(session_dir: Path, state: State) -> None:
    path = session_dir / "state.json"
    tmp = session_dir / "state.json.tmp"
    payload = json.dumps(state.to_dict(), indent=2, sort_keys=True) + "\n"
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def read_state(session_dir: Path) -> State:
    raw = json.loads((session_dir / "state.json").read_text(encoding="utf-8"))
    nodes = {node_id: info["status"] for node_id, info in raw["nodes"].items()}
    return State(graph_id=raw["graph"], nodes=nodes, artifacts=list(raw.get("artifacts", [])))


def set_status(state: State, node_id: str, status: Status) -> None:
    state.nodes[node_id] = status


def record_artifact(state: State, relpath: str) -> None:
    if relpath not in state.artifacts:
        state.artifacts.append(relpath)
