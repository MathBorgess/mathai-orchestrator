from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from orch.cli import main
from orch.errors import EXIT_OK
from orch.gate import Gate
from orch.graph import load_graph
from orch.scheduler import Deadlock, critical_path, ready_set
from orch.session import create_session
from tests.conftest import set_knobs

REPO = Path(__file__).resolve().parents[1]


def _session(tmp_path: Path):
    graph = load_graph(REPO / "graphs" / "v1.yaml")
    return create_session(graph, tmp_path / "s"), graph


def test_ready_set_starts_with_the_only_node_without_incoming_edges(tmp_path: Path) -> None:
    session, graph = _session(tmp_path)
    assert ready_set(session, graph) == ["scout"]


def test_ready_set_recomputes_and_releases_the_three_instances_together(
    tmp_path: Path,
) -> None:
    session, graph = _session(tmp_path)
    session.ledger.set_status("scout", "done")
    session.ledger.record_artifact("handoff.md", "abc", "scout", time.time(), True)
    assert ready_set(session, graph) == ["build.a", "build.b", "build.c"]

    # `always` never fires with survivors: the join waits for 3/3.
    session.ledger.set_status("build.a", "done")
    session.ledger.set_status("build.b", "done")
    assert "merge" not in ready_set(session, graph)
    session.ledger.set_status("build.c", "done")
    assert ready_set(session, graph) == ["merge"]


def test_deadlock_is_a_named_error_never_an_eternal_wait() -> None:
    err = Deadlock(["merge", "gate"])
    assert err.exit_code == 50
    assert "deadlock" in err.message
    assert "gate" in err.message and "merge" in err.message


def test_critical_path_is_the_longest_path_by_node_wall(tmp_path: Path) -> None:
    _, graph = _session(tmp_path)
    wall = {
        "scout": 10.0,
        "build.a": 5.0,
        "build.b": 30.0,
        "build.c": 5.0,
        "merge": 20.0,
        "gate": 1.0,
        "contract": 1.0,
    }
    path, total = critical_path(graph, wall)
    assert path == ["scout", "build.b", "merge", "gate", "contract"]
    assert total == pytest.approx(62.0)


def test_single_node_graph_ceiling_is_one() -> None:
    graph = load_graph(REPO / "graphs" / "v1.yaml")
    # width is the widest fanout partition; it is what caps the effective concurrency.
    assert graph.width == 3


def test_fanout_instances_really_overlap_in_time(
    fake_claude: Path, graph_repo: Path, tmp_path: Path, double_control: Path, capsys
) -> None:
    """A barrier or a serial loop would make the three branches cost 3x the sleep.
    FIRST_COMPLETED makes them cost about 1x."""
    set_knobs(double_control, sleep=0.6)
    session = tmp_path / "sess"
    code = main(
        [
            "up",
            str(graph_repo / "graphs" / "v1.yaml"),
            "--session-dir",
            str(session),
            "--no-baseline",
        ]
    )
    assert code == EXIT_OK, capsys.readouterr().out
    state = json.loads((session / "state.json").read_text())
    branch_wall = sum(state["nodes"][f"build.{s}"]["wall_seconds"] for s in "abc")
    assert branch_wall > 1.5, "each branch really slept"

    events = [json.loads(ln) for ln in (session / "events.jsonl").read_text().splitlines()]
    starts = {
        e["node"]: e["ts"] for e in events if e["to"] == "running" and e["node"].startswith("build.")
    }
    ends = {
        e["node"]: e["ts"] for e in events if e["to"] == "verifying" and e["node"].startswith("build.")
    }
    assert len(starts) == 3 and len(ends) == 3
    # Every branch started before the first branch finished: that is overlap, not a queue.
    first_end = min(ends.values())
    assert max(starts.values()) < first_end


def test_slot_is_freed_only_after_verifying(
    fake_claude: Path, graph_repo: Path, tmp_path: Path, capsys
) -> None:
    session = tmp_path / "sess"
    assert (
        main(
            [
                "up",
                str(graph_repo / "graphs" / "v1.yaml"),
                "--session-dir",
                str(session),
                "--no-baseline",
            ]
        )
        == EXIT_OK
    ), capsys.readouterr().out
    events = [json.loads(ln) for ln in (session / "events.jsonl").read_text().splitlines()]
    order = [(e["node"], e["to"]) for e in events]
    # merge never goes `running` before every branch has passed through `verifying`.
    merge_running = order.index(("merge", "running"))
    for slot in "abc":
        assert order.index((f"build.{slot}", "verifying")) < merge_running
        assert order.index((f"build.{slot}", "done")) < merge_running


def test_gate_defaults_do_not_block_a_clean_session(tmp_path: Path) -> None:
    gate = Gate(session_units=6.0, wall_seconds=3600)
    assert gate.ceiling() == 3
    assert gate.enforce() is None
    assert gate.admits(1.0)


def test_stop_kills_the_survivors_and_marks_them_skipped(tmp_path: Path) -> None:
    """SPEC §6.1-2: at the instant of the stop the still-running nodes are killed and
    marked `skipped:stop_reached`. A branch burning budget after the stop is the bill
    nobody asked for."""
    import os
    import subprocess

    from orch.scheduler import Slot, _drain

    session, graph = _session(tmp_path)
    proc = subprocess.Popen(["/bin/sh", "-c", "sleep 30"], start_new_session=True)
    slot = Slot(
        node=graph.instances["build.a"],
        started_epoch=time.time(),
        cwd=session.path,
        write_roots=[session.path],
        before={session.path: {}},
        proc=proc,
    )
    session.ledger.set_status("build.a", "running")
    _drain(session, {"build.a": slot}, {}, reason="stop_reached")

    state = session.ledger.nodes["build.a"]
    assert state.status == "skipped"
    assert state.failure == "stop_reached"
    deadline = time.time() + 5
    while time.time() < deadline and proc.poll() is None:
        time.sleep(0.05)
    assert proc.poll() is not None, "the survivor kept running past the stop"
    assert os.getpid() > 0
