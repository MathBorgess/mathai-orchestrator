from pathlib import Path

from orch.graph import load_graph
from orch.runner import is_ready, ready_nodes
from orch.state import State, set_status

REPO = Path(__file__).resolve().parents[1]


def test_builder_not_ready_without_handoff(tmp_path: Path) -> None:
    graph = load_graph(REPO / "graphs" / "v0.yaml")
    state = State.initial(graph)
    session_dir = tmp_path / "session"
    session_dir.mkdir()

    assert is_ready(graph, state, session_dir, "scout")
    assert not is_ready(graph, state, session_dir, "builder")
    assert ready_nodes(graph, state, session_dir) == ["scout"]

    set_status(state, "scout", "done")
    assert not is_ready(graph, state, session_dir, "builder")

    (session_dir / "handoff.md").write_text("brief\n", encoding="utf-8")
    assert is_ready(graph, state, session_dir, "builder")


def test_builder_not_ready_if_scout_still_pending(tmp_path: Path) -> None:
    graph = load_graph(REPO / "graphs" / "v0.yaml")
    state = State.initial(graph)
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    (session_dir / "handoff.md").write_text("stale\n", encoding="utf-8")
    assert not is_ready(graph, state, session_dir, "builder")
