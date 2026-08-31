"""Serial v0 runner: one node running at a time, artifact handoff, state.json."""

from __future__ import annotations

from pathlib import Path

from orch.claude import PreflightError, build_prompt, preflight_claude, spawn_claude
from orch.graph import Edge, Graph, GraphError
from orch.state import State, record_artifact, set_status, write_state


class SessionError(RuntimeError):
    """Session directory contract violated."""


def expected_artifact(graph: Graph, node_id: str) -> str:
    outgoing = graph.outgoing(node_id)
    if outgoing:
        return outgoing[0].artifact
    if graph.stop.node == node_id:
        return graph.stop.artifact
    raise GraphError(f"node {node_id} has no expected artifact")


def artifact_file(session_dir: Path, graph: Graph, node_id: str, relpath: str) -> Path:
    cwd = (session_dir / graph.node(node_id).cwd).resolve()
    return cwd / relpath


def edge_satisfied(graph: Graph, state: State, session_dir: Path, edge: Edge) -> bool:
    if state.nodes[edge.source] != "done":
        return False
    if edge.on != "artifact_exists":
        return False
    return artifact_file(session_dir, graph, edge.source, edge.artifact).is_file()


def is_ready(graph: Graph, state: State, session_dir: Path, node_id: str) -> bool:
    if state.nodes[node_id] != "pending":
        return False
    incoming = graph.incoming(node_id)
    if not incoming:
        return True
    return all(edge_satisfied(graph, state, session_dir, edge) for edge in incoming)


def ready_nodes(graph: Graph, state: State, session_dir: Path) -> list[str]:
    return [
        node_id
        for node_id in graph.nodes
        if is_ready(graph, state, session_dir, node_id)
    ]


def required_artifacts_exist(graph: Graph, session_dir: Path, node_id: str) -> bool:
    for edge in graph.outgoing(node_id):
        if not artifact_file(session_dir, graph, node_id, edge.artifact).is_file():
            return False
    if graph.stop.node == node_id:
        if not artifact_file(session_dir, graph, node_id, graph.stop.artifact).is_file():
            return False
    return True


def stop_reached(graph: Graph, state: State, session_dir: Path) -> bool:
    if state.nodes.get(graph.stop.node) != "done":
        return False
    return artifact_file(session_dir, graph, graph.stop.node, graph.stop.artifact).is_file()


def create_session(graph: Graph, session_dir: Path) -> State:
    if session_dir.exists():
        raise SessionError(
            f"session dir already exists (no resume in v0): {session_dir}"
        )
    session_dir.mkdir(parents=True)
    dest = session_dir / "graph.yaml"
    dest.write_bytes(graph.path.read_bytes())
    state = State.initial(graph)
    write_state(session_dir, state)
    return state


def run_session(graph: Graph, session_dir: Path) -> int:
    binary = preflight_claude()
    state = create_session(graph, session_dir)

    while True:
        if stop_reached(graph, state, session_dir):
            return 0
        if any(status == "failed" for status in state.nodes.values()):
            return 1

        ready = ready_nodes(graph, state, session_dir)
        if not ready:
            return 1

        node_id = ready[0]
        node = graph.node(node_id)
        cwd = (session_dir / node.cwd).resolve()
        cwd.mkdir(parents=True, exist_ok=True)
        artifact = expected_artifact(graph, node_id)
        prompt = build_prompt(node_id, session_dir.resolve(), artifact, node.prompt_path)
        log_path = session_dir / "logs" / f"{node_id}.log"

        set_status(state, node_id, "running")
        write_state(session_dir, state)

        rc = spawn_claude(binary=binary, prompt=prompt, cwd=cwd, log_path=log_path)
        ok = rc == 0 and required_artifacts_exist(graph, session_dir, node_id)
        if not ok:
            set_status(state, node_id, "failed")
            write_state(session_dir, state)
            return 1

        set_status(state, node_id, "done")
        for edge in graph.outgoing(node_id):
            if artifact_file(session_dir, graph, node_id, edge.artifact).is_file():
                record_artifact(state, edge.artifact)
        if graph.stop.node == node_id:
            if artifact_file(session_dir, graph, node_id, graph.stop.artifact).is_file():
                record_artifact(state, graph.stop.artifact)
        write_state(session_dir, state)

        for edge in graph.outgoing(node_id):
            print(
                f"handoff {edge.source} → {edge.target} artifact={edge.artifact}",
                flush=True,
            )


# Re-export for cli.py type checks without a circular import of unused names.
__all__ = [
    "GraphError",
    "PreflightError",
    "SessionError",
    "create_session",
    "edge_satisfied",
    "is_ready",
    "ready_nodes",
    "run_session",
    "stop_reached",
]
