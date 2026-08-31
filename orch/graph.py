"""Load and refuse a v0 graph YAML. Cycles, missing nodes, orphans do not load."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
ALLOWED_ON = frozenset({"artifact_exists"})
ALLOWED_STOP_WHEN = frozenset({"node_done"})


class GraphError(ValueError):
    """Graph is invalid and must not run."""


@dataclass(frozen=True)
class Node:
    id: str
    role: str
    prompt: str
    cwd: str
    prompt_path: Path


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    on: str
    artifact: str


@dataclass(frozen=True)
class Stop:
    when: str
    node: str
    artifact: str


@dataclass(frozen=True)
class Graph:
    id: str
    path: Path
    nodes: dict[str, Node]
    edges: tuple[Edge, ...]
    stop: Stop

    def node(self, node_id: str) -> Node:
        return self.nodes[node_id]

    def incoming(self, node_id: str) -> tuple[Edge, ...]:
        return tuple(e for e in self.edges if e.target == node_id)

    def outgoing(self, node_id: str) -> tuple[Edge, ...]:
        return tuple(e for e in self.edges if e.source == node_id)


def load_graph(path: Path) -> Graph:
    path = path.resolve()
    if not path.is_file():
        raise GraphError(f"graph file not found: {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise GraphError(f"invalid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise GraphError("graph YAML must be a mapping")

    graph_id = _require_str(raw, "id")
    _check_id(graph_id, "graph id")
    stem = path.stem
    if graph_id != stem:
        raise GraphError(f"graph id {graph_id!r} != file stem {stem!r}")

    nodes_raw = raw.get("nodes")
    if not isinstance(nodes_raw, list) or not nodes_raw:
        raise GraphError("graph must declare a non-empty nodes list")

    nodes: dict[str, Node] = {}
    for item in nodes_raw:
        if not isinstance(item, dict):
            raise GraphError("each node must be a mapping")
        node_id = _require_str(item, "id")
        _check_id(node_id, "node id")
        if node_id in nodes:
            raise GraphError(f"duplicate node id: {node_id}")
        role = _require_str(item, "role")
        prompt = _require_str(item, "prompt")
        cwd = item.get("cwd", ".")
        if not isinstance(cwd, str) or not cwd:
            raise GraphError(f"node {node_id}: cwd must be a non-empty string")
        nodes[node_id] = Node(
            id=node_id,
            role=role,
            prompt=prompt,
            cwd=cwd,
            prompt_path=Path(),  # filled after structure checks
        )

    edges_raw = raw.get("edges")
    if not isinstance(edges_raw, list):
        raise GraphError("graph must declare an edges list")

    edges: list[Edge] = []
    for item in edges_raw:
        if not isinstance(item, dict):
            raise GraphError("each edge must be a mapping")
        source = _require_str(item, "from")
        target = _require_str(item, "to")
        on = _require_str(item, "on")
        artifact = _require_str(item, "artifact")
        if source not in nodes:
            raise GraphError(f"edge points to missing node: {source}")
        if target not in nodes:
            raise GraphError(f"edge points to missing node: {target}")
        if on not in ALLOWED_ON:
            raise GraphError(f"unsupported edge predicate: {on}")
        edges.append(Edge(source=source, target=target, on=on, artifact=artifact))

    _reject_cycles(nodes, edges)
    _reject_orphans(nodes, edges)

    stop_raw = raw.get("stop")
    if not isinstance(stop_raw, dict):
        raise GraphError("graph must declare a stop mapping")
    when = _require_str(stop_raw, "when")
    stop_node = _require_str(stop_raw, "node")
    stop_artifact = _require_str(stop_raw, "artifact")
    if when not in ALLOWED_STOP_WHEN:
        raise GraphError(f"unsupported stop.when: {when}")
    if stop_node not in nodes:
        raise GraphError(f"stop.node points to missing node: {stop_node}")
    stop = Stop(when=when, node=stop_node, artifact=stop_artifact)

    resolved: dict[str, Node] = {}
    for node_id, node in nodes.items():
        prompt_path = _resolve_prompt(path, node.prompt)
        resolved[node_id] = Node(
            id=node.id,
            role=node.role,
            prompt=node.prompt,
            cwd=node.cwd,
            prompt_path=prompt_path,
        )

    return Graph(id=graph_id, path=path, nodes=resolved, edges=tuple(edges), stop=stop)


def _require_str(mapping: dict, key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise GraphError(f"missing or empty {key!r}")
    return value


def _check_id(value: str, label: str) -> None:
    if not ID_RE.fullmatch(value):
        raise GraphError(f"{label} {value!r} does not match {ID_RE.pattern}")


def _reject_cycles(nodes: dict[str, Node], edges: list[Edge]) -> None:
    indeg = {node_id: 0 for node_id in nodes}
    for edge in edges:
        indeg[edge.target] += 1
    ready = [node_id for node_id, degree in indeg.items() if degree == 0]
    seen = 0
    while ready:
        node_id = ready.pop()
        seen += 1
        for edge in edges:
            if edge.source != node_id:
                continue
            indeg[edge.target] -= 1
            if indeg[edge.target] == 0:
                ready.append(edge.target)
    if seen != len(nodes):
        raise GraphError("graph has a cycle")


def _reject_orphans(nodes: dict[str, Node], edges: list[Edge]) -> None:
    connected: set[str] = set()
    for edge in edges:
        connected.add(edge.source)
        connected.add(edge.target)
    orphans = [node_id for node_id in nodes if node_id not in connected]
    if orphans:
        raise GraphError("orphan node: " + ", ".join(orphans))


def _resolve_prompt(graph_path: Path, prompt: str) -> Path:
    candidate = Path(prompt)
    if candidate.is_absolute():
        if candidate.is_file():
            return candidate
        raise GraphError(f"prompt not found: {prompt}")
    search = [
        Path.cwd() / candidate,
        graph_path.parent / candidate,
        graph_path.parent.parent / candidate,
    ]
    for path in search:
        if path.is_file():
            return path.resolve()
    raise GraphError(f"prompt not found: {prompt}")
