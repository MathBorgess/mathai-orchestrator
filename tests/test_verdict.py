from __future__ import annotations

from pathlib import Path

from orch.verdict import (
    COST_RATIO_MAX,
    DELTA_GATE_MIN,
    SPEEDUP_MIN,
    ArmMetrics,
    compute,
    render,
    render_unavailable,
)

DIAGNOSTIC = {
    "branches": 3,
    "speedup_max": 2.5,
    "critical_path": ["scout", "build.a", "merge"],
    "critical_path_seconds": 100.0,
    "critical_path_share": 0.8,
    "join_wall": 40.0,
    "branch_wall": {"build.a": 30.0, "build.b": 31.0, "build.c": 29.0},
    "orphan_writes": 0,
    "null_writes": 0,
    "rework": 0,
    "write_violations": 0,
    "handoff_uptake": None,
    "fanout_rationale": {"build": "P1 handoff: cabe numa página."},
}


def _verdict(
    *,
    sum_node_wall: float,
    wall: float,
    graph_log: int,
    base_log: int,
    graph_gate: int = 2,
    base_gate: int = 2,
) -> dict:
    return compute(
        graph_arm=ArmMetrics(
            wall_seconds=wall,
            sum_node_wall=sum_node_wall,
            log_bytes=graph_log,
            gate_passed=graph_gate,
            gate_total=2,
        ),
        baseline_arm=ArmMetrics(
            wall_seconds=200.0,
            sum_node_wall=200.0,
            log_bytes=base_log,
            gate_passed=base_gate,
            gate_total=2,
        ),
        graph_id="graphs/v1.yaml",
        session_dir=Path("/tmp/sess"),
        seed=3,
        stop_reason="stop_reached",
        concurrency={"requested": 3, "effective": 3},
        diagnostic=DIAGNOSTIC,
    )


def test_speedup_is_sum_of_nodes_over_the_graph_arm_wall() -> None:
    v = _verdict(sum_node_wall=120.0, wall=50.0, graph_log=1_000_000, base_log=600_000)
    assert v["headline"]["speedup"] == 2.4
    assert v["passes"]["speedup"] is True


def test_the_gate_is_a_conjunction_of_three() -> None:
    ok = _verdict(sum_node_wall=100.0, wall=50.0, graph_log=1_000_000, base_log=600_000)
    assert ok["useful_parallelism"] is True

    slow = _verdict(sum_node_wall=55.0, wall=50.0, graph_log=1_000_000, base_log=600_000)
    assert slow["headline"]["speedup"] < SPEEDUP_MIN
    assert slow["useful_parallelism"] is False

    pricey = _verdict(sum_node_wall=100.0, wall=50.0, graph_log=3_000_000, base_log=600_000)
    assert pricey["headline"]["cost_ratio"] > COST_RATIO_MAX
    assert pricey["useful_parallelism"] is False

    regressed = _verdict(
        sum_node_wall=100.0,
        wall=50.0,
        graph_log=1_000_000,
        base_log=600_000,
        graph_gate=1,
        base_gate=2,
    )
    assert regressed["headline"]["delta_gate"] < DELTA_GATE_MIN
    assert regressed["useful_parallelism"] is False


def test_diagnostic_is_printed_only_on_failure() -> None:
    passing = render(
        _verdict(sum_node_wall=100.0, wall=50.0, graph_log=1_000_000, base_log=600_000)
    )
    assert "VEREDITO: paralelismo ÚTIL." in passing
    assert "diagnóstico" not in passing
    assert "1 seed não decide." in passing

    failing = render(
        _verdict(sum_node_wall=52.0, wall=50.0, graph_log=1_000_000, base_log=600_000)
    )
    assert "VEREDITO: paralelismo DECORATIVO." in failing
    assert "diagnóstico (impresso porque o veredito reprovou)" in failing
    assert "speedup_max" in failing
    assert "branch_wall" in failing
    assert "handoff_uptake" in failing and "não calibrado" in failing
    assert "1 seed não decide." in failing


def test_three_numbers_and_one_sentence_only() -> None:
    text = render(
        _verdict(sum_node_wall=100.0, wall=50.0, graph_log=1_000_000, base_log=600_000)
    )
    metric_lines = [ln for ln in text.splitlines() if ln.startswith("  speedup")]
    assert len(metric_lines) == 1
    assert text.count("VEREDITO:") == 1
    assert "REPROVA" not in text


def test_zero_baseline_log_bytes_is_inconclusive_not_a_crash() -> None:
    v = _verdict(sum_node_wall=100.0, wall=50.0, graph_log=1_000_000, base_log=0)
    assert v["headline"]["cost_ratio"] is None
    assert v["measurable"] is False
    assert "INCONCLUSIVO" in render(v)


def test_render_unavailable_keeps_the_mandatory_footer() -> None:
    text = render_unavailable("sem braço de controle")
    assert "veredito: INDISPONÍVEL" in text
    assert "1 seed não decide." in text
