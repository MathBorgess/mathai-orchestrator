"""The product test: clone, run one command, get a number.

    python -m orch up graphs/v1.yaml --session-dir .sessions/tN

Everything below runs against the CLI double from conftest — no subscription window
is spent to prove the pipeline is wired.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orch.cli import main
from tests.conftest import set_knobs
from orch.errors import EXIT_BASELINE, EXIT_OK, EXIT_PERMISSION


def _up(repo: Path, session: Path, *extra: str) -> int:
    return main(
        [
            "up",
            str(repo / "graphs" / "v1.yaml"),
            "--session-dir",
            str(session),
            *extra,
        ]
    )


def test_zero_to_verdict(fake_claude: Path, graph_repo: Path, tmp_path: Path, capsys) -> None:
    session = tmp_path / "sess"
    code = _up(graph_repo, session)
    out = capsys.readouterr().out
    assert code == EXIT_OK, out

    state = json.loads((session / "state.json").read_text())
    for node in ("scout", "build.a", "build.b", "build.c", "merge", "gate", "contract"):
        assert state["nodes"][node]["status"] == "done", (node, out)
    assert state["violations"] == []
    assert state["preflight"]["comparable"] is True
    assert state["preflight"]["baseline"] == "reached_stop"

    # The control arm ran first, serial, in its own namespace with its own ledger.
    assert (session / "baseline" / "out" / "REPORT.md").is_file()
    assert (session / "baseline" / "state.json").is_file()
    assert (session / "baseline" / "logs" / "baseline.jsonl").is_file()

    # Three numbers and one sentence, plus the mandatory footer.
    assert "speedup" in out
    assert "cost_ratio" in out
    assert "delta_gate" in out
    assert "VEREDITO:" in out
    assert "1 seed não decide." in out

    verdict = json.loads((session / "verdict.json").read_text())
    assert verdict["comparable"] is True
    assert verdict["thresholds"]["speedup_min"] == 1.50
    assert verdict["thresholds"]["cost_ratio_max"] == 2.50
    assert verdict["arms"]["baseline"]["gate_total"] == 2
    assert verdict["arms"]["graph"]["gate_total"] == 2
    assert verdict["headline"]["delta_gate"] == 0.0
    # speedup uses the graph arm's wall only; the baseline's wall is excluded.
    assert verdict["arms"]["graph"]["wall_seconds"] < (
        verdict["arms"]["graph"]["wall_seconds"] + verdict["arms"]["baseline"]["wall_seconds"]
    )
    assert verdict["diagnostic"]["branches"] == 3
    assert verdict["diagnostic"]["critical_path"][0] == "scout"


def test_worktree_per_instance_and_cleanup(
    fake_claude: Path, graph_repo: Path, tmp_path: Path, capsys
) -> None:
    session = tmp_path / "sess"
    assert _up(graph_repo, session) == EXIT_OK, capsys.readouterr().out
    state = json.loads((session / "state.json").read_text())
    assert state["preflight"]["isolation"] == "worktree"
    assert state["preflight"]["concurrency_effective"] == 3
    # Removed in `verifying`, not at the end of the session.
    assert list((session / "wt").iterdir()) == []
    # The artifacts still landed in the session namespace.
    for name in ("a", "b", "c"):
        assert (session / "out" / f"{name}.md").is_file()


def test_concurrency_1_uses_no_worktree(
    fake_claude: Path, graph_repo: Path, tmp_path: Path, capsys
) -> None:
    session = tmp_path / "sess"
    assert _up(graph_repo, session, "--max-concurrency", "1") == EXIT_OK, (
        capsys.readouterr().out
    )
    state = json.loads((session / "state.json").read_text())
    assert state["preflight"]["isolation"] == "cwd"
    assert state["preflight"]["concurrency_effective"] == 1
    for name in ("a", "b", "c"):
        assert (session / "out" / f"{name}.md").is_file()


def test_baseline_that_misses_the_stop_exits_41(
    fake_claude: Path, graph_repo: Path, tmp_path: Path, double_control: Path, capsys
) -> None:
    set_knobs(double_control, nowrite=True)
    session = tmp_path / "sess"
    code = _up(graph_repo, session)
    captured = capsys.readouterr()
    assert code == EXIT_BASELINE
    assert "TASK is broken" in captured.err
    state = json.loads((session / "state.json").read_text())
    # The graph's budget was not spent: nothing beyond the control arm ran.
    assert all(node["status"] == "pending" for node in state["nodes"].values())
    assert not (session / "verdict.json").exists()


def test_no_baseline_is_noisy_and_writes_no_verdict(
    fake_claude: Path, graph_repo: Path, tmp_path: Path, capsys
) -> None:
    session = tmp_path / "sess"
    code = _up(graph_repo, session, "--no-baseline")
    out = capsys.readouterr().out
    assert code == EXIT_OK, out
    assert "SEM BASELINE — esta sessão não produz veredito" in out
    assert out.index("SEM BASELINE") < out.index("orch: session")
    assert "veredito: INDISPONÍVEL" in out
    assert not (session / "verdict.json").exists()
    state = json.loads((session / "state.json").read_text())
    assert state["preflight"]["comparable"] is False
    assert state["nodes"]["contract"]["status"] == "done"


def test_permission_denial_fails_the_session(
    fake_claude: Path, graph_repo: Path, tmp_path: Path, double_control: Path, capsys
) -> None:
    set_knobs(double_control, deny=True)
    session = tmp_path / "sess"
    code = _up(graph_repo, session, "--no-baseline")
    captured = capsys.readouterr()
    assert code == EXIT_PERMISSION
    state = json.loads((session / "state.json").read_text())
    assert state["nodes"]["scout"]["failure"] == "permission"
    assert "Write" in captured.err or "Write" in (session / "events.jsonl").read_text()


@pytest.mark.parametrize("flag", ["auto", "3"])
def test_window_status_not_allowed_aborts_with_30(
    fake_claude: Path, graph_repo: Path, tmp_path: Path, double_control: Path, flag: str
) -> None:
    set_knobs(double_control, rl_status="throttled")
    session = tmp_path / "sess"
    code = _up(graph_repo, session, "--no-baseline", "--max-concurrency", flag)
    assert code == 30
    state = json.loads((session / "state.json").read_text())
    assert state["nodes"]["scout"]["status"] == "done"
    assert state["nodes"]["merge"]["status"] == "pending"
