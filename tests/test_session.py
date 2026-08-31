from __future__ import annotations

from pathlib import Path

from orch.cli import main
from orch.graph import load_graph
from orch.runner import SessionError, create_session, run_session
from orch.state import read_state

REPO = Path(__file__).resolve().parents[1]
V0 = REPO / "graphs" / "v0.yaml"


def test_happy_path_prints_handoff_and_stops(
    claude_env: Path, session_dir: Path, capsys
) -> None:
    graph = load_graph(V0)
    rc = run_session(graph, session_dir)
    assert rc == 0
    out = capsys.readouterr().out
    assert "handoff scout → builder artifact=handoff.md" in out
    assert (session_dir / "handoff.md").is_file()
    assert (session_dir / "DONE.md").is_file()
    state = read_state(session_dir)
    assert state.nodes["scout"] == "done"
    assert state.nodes["builder"] == "done"
    assert "handoff.md" in state.artifacts
    assert "DONE.md" in state.artifacts
    assert (session_dir / "graph.yaml").is_file()
    assert (session_dir / "logs" / "scout.log").is_file()
    assert (session_dir / "logs" / "builder.log").is_file()


def test_builder_does_not_start_without_handoff(
    claude_env: Path, session_dir: Path, monkeypatch, capsys
) -> None:
    log = session_dir.parent / "fake.log"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setenv("FAKE_CLAUDE_SCOUT_SKIP_WRITE", "1")
    graph = load_graph(V0)
    rc = run_session(graph, session_dir)
    assert rc == 1
    state = read_state(session_dir)
    assert state.nodes["scout"] == "failed"
    assert state.nodes["builder"] == "pending"
    assert not (session_dir / "logs" / "builder.log").exists()
    recorded = log.read_text(encoding="utf-8")
    assert "node=scout" in recorded
    assert "node=builder" not in recorded
    assert "handoff scout → builder" not in capsys.readouterr().out


def test_failed_builder_exits_1(claude_env: Path, session_dir: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_BUILDER_SKIP_WRITE", "1")
    graph = load_graph(V0)
    rc = run_session(graph, session_dir)
    assert rc == 1
    state = read_state(session_dir)
    assert state.nodes["scout"] == "done"
    assert state.nodes["builder"] == "failed"


def test_second_up_raises(claude_env: Path, session_dir: Path) -> None:
    graph = load_graph(V0)
    assert run_session(graph, session_dir) == 0
    try:
        run_session(graph, session_dir)
        raise AssertionError("expected SessionError")
    except SessionError as exc:
        assert "already exists" in str(exc)


def test_cli_second_up_exits_1(claude_env: Path, session_dir: Path) -> None:
    assert main(["up", str(V0), "--session-dir", str(session_dir)]) == 0
    assert main(["up", str(V0), "--session-dir", str(session_dir)]) == 1


def test_missing_claude_points_at_login(
    monkeypatch, session_dir: Path, capsys
) -> None:
    monkeypatch.delenv("CLAUDE_BIN", raising=False)
    monkeypatch.setenv("PATH", "/nonexistent")
    rc = main(["up", str(V0), "--session-dir", str(session_dir)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "claude auth login" in err
    assert "ANTHROPIC_API_KEY" not in err
    assert "api key" not in err.lower()
    assert not session_dir.exists()


def test_unsets_anthropic_api_key(
    claude_env: Path, session_dir: Path, monkeypatch
) -> None:
    log = session_dir.parent / "key.log"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-never-reach-child")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    graph = load_graph(V0)
    assert run_session(graph, session_dir) == 0
    recorded = log.read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY=None" in recorded
    assert "should-never-reach-child" not in recorded


def test_spawn_uses_print_flags(
    claude_env: Path, session_dir: Path, monkeypatch
) -> None:
    log = session_dir.parent / "argv.log"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    graph = load_graph(V0)
    assert run_session(graph, session_dir) == 0
    recorded = log.read_text(encoding="utf-8")
    assert " -p " in recorded
    assert "--output-format text" in recorded
    assert "--model" not in recorded


def test_create_session_does_not_make_empty_subdirs(
    session_dir: Path,
) -> None:
    graph = load_graph(V0)
    create_session(graph, session_dir)
    names = sorted(p.name for p in session_dir.iterdir())
    assert names == ["graph.yaml", "state.json"]
