from pathlib import Path

import pytest

from orch.graph import GraphError, load_graph

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REPO = Path(__file__).resolve().parents[1]


def test_parse_v0_yaml() -> None:
    graph = load_graph(REPO / "graphs" / "v0.yaml")
    assert graph.id == "v0"
    assert list(graph.nodes) == ["scout", "builder"]
    assert graph.nodes["scout"].role == "scout"
    assert graph.nodes["scout"].prompt == "prompts/scout.md"
    assert graph.nodes["builder"].prompt_path.is_file()
    assert len(graph.edges) == 1
    edge = graph.edges[0]
    assert edge.source == "scout"
    assert edge.target == "builder"
    assert edge.on == "artifact_exists"
    assert edge.artifact == "handoff.md"
    assert graph.stop.node == "builder"
    assert graph.stop.artifact == "DONE.md"


def test_reject_cycle() -> None:
    with pytest.raises(GraphError, match="cycle"):
        load_graph(FIXTURES / "cycle.yaml")


def test_reject_missing_node() -> None:
    with pytest.raises(GraphError, match="missing node: builder"):
        load_graph(FIXTURES / "missing.yaml")


def test_reject_orphan_node() -> None:
    with pytest.raises(GraphError, match="orphan node: leftover"):
        load_graph(FIXTURES / "orphan.yaml")


def test_reject_id_not_stem() -> None:
    with pytest.raises(GraphError, match="file stem"):
        load_graph(FIXTURES / "wrongstem.yaml")
