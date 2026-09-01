"""The verdict: 3 numbers and 1 sentence (SPEC §7)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SPEEDUP_MIN = 1.50
COST_RATIO_MAX = 2.50
DELTA_GATE_MIN = 0.0
FOOTER = "1 seed não decide."
RULE = "─" * 82


@dataclass
class ArmMetrics:
    wall_seconds: float
    sum_node_wall: float
    log_bytes: int
    gate_passed: int
    gate_total: int
    cost_units: float = 0.0

    @property
    def gate_first_pass(self) -> float:
        return self.gate_passed / self.gate_total if self.gate_total else 0.0


def hms(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    total = int(round(seconds))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def _mb(size: int) -> str:
    return f"{size / 1_000_000:.2f} MB" if size >= 100_000 else f"{size / 1000:.1f} kB"


def compute(
    *,
    graph_arm: ArmMetrics,
    baseline_arm: ArmMetrics,
    graph_id: str,
    session_dir: Path,
    seed: int,
    stop_reason: str,
    concurrency: dict[str, Any],
    diagnostic: dict[str, Any],
    team_fingerprint: str | None = None,
) -> dict[str, Any]:
    speedup = _ratio(graph_arm.sum_node_wall, graph_arm.wall_seconds)
    cost_ratio = _ratio(graph_arm.log_bytes, baseline_arm.log_bytes)
    delta_gate = graph_arm.gate_first_pass - baseline_arm.gate_first_pass
    checks = {
        "speedup": speedup is not None and speedup >= SPEEDUP_MIN,
        "cost_ratio": cost_ratio is not None and cost_ratio <= COST_RATIO_MAX,
        "delta_gate": delta_gate >= DELTA_GATE_MIN,
    }
    measurable = speedup is not None and cost_ratio is not None
    useful = measurable and all(checks.values())
    return {
        "schema": "orch/verdict/1",
        "graph": graph_id,
        "team_fingerprint": team_fingerprint,
        "session_dir": str(session_dir),
        "seed": seed,
        "comparable": True,
        "stop_reason": stop_reason,
        "thresholds": {
            "speedup_min": SPEEDUP_MIN,
            "cost_ratio_max": COST_RATIO_MAX,
            "delta_gate_min": DELTA_GATE_MIN,
            "note": "pre-registered; change only by dated amendment in SPEC.md",
        },
        "headline": {
            "speedup": _round(speedup),
            "cost_ratio": _round(cost_ratio),
            "delta_gate": round(delta_gate, 4),
        },
        "passes": checks,
        "measurable": measurable,
        "useful_parallelism": useful,
        "arms": {"graph": _arm_dict(graph_arm), "baseline": _arm_dict(baseline_arm)},
        "concurrency": concurrency,
        "diagnostic": diagnostic,
        "footer": FOOTER,
    }


def _arm_dict(arm: ArmMetrics) -> dict[str, Any]:
    return {
        "wall_seconds": round(arm.wall_seconds, 3),
        "sum_node_wall_seconds": round(arm.sum_node_wall, 3),
        "log_bytes": arm.log_bytes,
        "gate_passed": arm.gate_passed,
        "gate_total": arm.gate_total,
        "gate_first_pass": round(arm.gate_first_pass, 4),
        "cost_units": round(arm.cost_units, 6),
    }


def _ratio(num: float, den: float) -> float | None:
    if not den:
        return None
    return float(num) / float(den)


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def write(session_dir: Path, verdict: dict[str, Any]) -> Path:
    path = session_dir / "verdict.json"
    tmp = session_dir / "verdict.json.tmp"
    tmp.write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def render(verdict: dict[str, Any]) -> str:
    head = verdict["headline"]
    graph = verdict["arms"]["graph"]
    base = verdict["arms"]["baseline"]
    passes = verdict["passes"]
    lines = [f"veredito  {verdict['graph']}  vs  baseline(1 nó)        seed {verdict['seed']}", RULE]
    speedup = head["speedup"]
    lines.append(_metric_line("speedup", f"{speedup:.2f}×" if speedup is not None else "n/a", f"(Σ nós {hms(graph['sum_node_wall_seconds'])} ÷ parede {hms(graph['wall_seconds'])})", passes["speedup"], f">= {SPEEDUP_MIN:.2f}"))
    cost = head["cost_ratio"]
    lines.append(_metric_line("cost_ratio", f"{cost:.2f}×" if cost is not None else "n/a", f"(log_bytes {_mb(graph['log_bytes'])} ÷ {_mb(base['log_bytes'])})", passes["cost_ratio"], f"<= {COST_RATIO_MAX:.2f}"))
    delta = head["delta_gate"]
    lines.append(_metric_line("delta_gate", f"{delta:+.2f}", f"(grafo {graph['gate_passed']}/{graph['gate_total']} · baseline {base['gate_passed']}/{base['gate_total']})", passes["delta_gate"], f">= {DELTA_GATE_MIN:.2f}"))
    lines.append("")
    if not verdict["measurable"]:
        lines.append("  VEREDITO: INCONCLUSIVO — um dos braços não produziu denominador.")
    elif verdict["useful_parallelism"]:
        lines.append("  VEREDITO: paralelismo ÚTIL.")
    else:
        lines.append("  VEREDITO: paralelismo DECORATIVO.")
    lines.append(f"  {FOOTER} o piso é 5 seeds por célula.")
    return "\n".join(lines)


def _metric_line(name: str, value: str, detail: str, ok: bool, threshold: str) -> str:
    verdict_word = "ok     " if ok else "REPROVA"
    return f"  {name:<13}{value:>8}   {detail:<46}{verdict_word} {threshold}"


def render_unavailable(reason: str) -> str:
    return "\n".join([RULE, "  veredito: INDISPONÍVEL", f"  {reason}", f"  {FOOTER}", RULE])
