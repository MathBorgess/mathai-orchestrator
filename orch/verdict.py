"""The verdict: 3 numbers and 1 sentence (SPEC §7).

The diagnostic block has the rest and is printed ONLY when the verdict fails —
the volume of text is inversely proportional to success, which is the right
incentive. `verdict.json` has everything, always.

  speedup    = Σ node.wall_seconds ÷ session.wall_seconds   (graph arm; the
               baseline's wall is excluded, because the baseline is serial and
               ran before the graph)
  cost_ratio = log_bytes(graph) ÷ log_bytes(baseline)        (declared proxy for
               output tokens, never called tokens)
  delta_gate = gate_first_pass(graph) − gate_first_pass(baseline)

  useful parallelism  <=>  speedup >= 1.50 ∧ cost_ratio <= 2.50 ∧ delta_gate >= 0

The thresholds are pre-registered and change by dated amendment, never after
seeing a result. The exit code never encodes the verdict: a session where the
graph lost badly still exits 0, because the race was valid and the number was
produced. An instrument that punishes the negative result stops receiving
negative results.
"""

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
        # Two runs are aggregable only if this matches. Summing the verdicts of two
        # different teams measures the change of team, not the change of task.
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
        "arms": {
            "graph": _arm_dict(graph_arm),
            "baseline": _arm_dict(baseline_arm),
        },
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
    lines: list[str] = []
    lines.append(
        f"veredito  {verdict['graph']}  vs  baseline(1 nó)"
        f"        seed {verdict['seed']}"
    )
    lines.append(RULE)

    speedup = head["speedup"]
    lines.append(
        _metric_line(
            "speedup",
            f"{speedup:.2f}×" if speedup is not None else "n/a",
            f"(Σ nós {hms(graph['sum_node_wall_seconds'])} ÷ parede {hms(graph['wall_seconds'])})",
            passes["speedup"],
            f">= {SPEEDUP_MIN:.2f}",
        )
    )
    cost = head["cost_ratio"]
    lines.append(
        _metric_line(
            "cost_ratio",
            f"{cost:.2f}×" if cost is not None else "n/a",
            f"(log_bytes {_mb(graph['log_bytes'])} ÷ {_mb(base['log_bytes'])})",
            passes["cost_ratio"],
            f"<= {COST_RATIO_MAX:.2f}",
        )
    )
    delta = head["delta_gate"]
    lines.append(
        _metric_line(
            "delta_gate",
            f"{delta:+.2f}",
            f"(grafo {graph['gate_passed']}/{graph['gate_total']} · "
            f"baseline {base['gate_passed']}/{base['gate_total']})",
            passes["delta_gate"],
            f">= {DELTA_GATE_MIN:.2f}",
        )
    )
    lines.append("")

    if not verdict["measurable"]:
        lines.append("  VEREDITO: INCONCLUSIVO — um dos braços não produziu denominador.")
        lines.append(f"  {_why_unmeasurable(graph, base)}")
    elif verdict["useful_parallelism"]:
        lines.append("  VEREDITO: paralelismo ÚTIL.")
        lines.append(f"  {_sentence_pass(head, verdict)}")
    else:
        lines.append("  VEREDITO: paralelismo DECORATIVO.")
        lines.append(f"  {_sentence_fail(head, verdict)}")

    if not verdict["useful_parallelism"]:
        lines.append("")
        lines.append("  diagnóstico (impresso porque o veredito reprovou)")
        lines.extend(_diagnostic_lines(verdict))

    lines.append("")
    lines.append(
        f"  {FOOTER} o piso é 5 seeds por célula.   "
        f"→  {Path(verdict['session_dir']) / 'verdict.json'}"
    )
    return "\n".join(lines)


def _metric_line(name: str, value: str, detail: str, ok: bool, threshold: str) -> str:
    verdict_word = "ok     " if ok else "REPROVA"
    return f"  {name:<13}{value:>8}   {detail:<46}{verdict_word} {threshold}"


def _why_unmeasurable(graph: dict[str, Any], base: dict[str, Any]) -> str:
    if not graph["wall_seconds"]:
        return "a parede do braço do grafo é zero: nenhum nó chegou a rodar."
    return "log_bytes do baseline é zero: o braço de controle não deixou stream para comparar."


def _sentence_pass(head: dict[str, Any], verdict: dict[str, Any]) -> str:
    branches = verdict["diagnostic"].get("branches", 0) or verdict["concurrency"].get(
        "effective", 1
    )
    return (
        f"{branches} ramos compraram {head['speedup']:.1f}× de relógio por "
        f"{head['cost_ratio']:.1f}× de custo, com delta_gate {head['delta_gate']:+.2f}."
    )


def _sentence_fail(head: dict[str, Any], verdict: dict[str, Any]) -> str:
    branches = verdict["diagnostic"].get("branches", 0) or verdict["concurrency"].get(
        "effective", 1
    )
    share = head["speedup"] and (1.0 / head["speedup"])
    tail = f"em {share:.0%} do tempo" if share else "sem ganho de parede"
    return (
        f"os {branches} ramos custaram {head['cost_ratio']:.1f}× e entregaram "
        f"delta_gate {head['delta_gate']:+.2f}, {tail}."
    )


def _diagnostic_lines(verdict: dict[str, Any]) -> list[str]:
    diag = verdict["diagnostic"]
    graph = verdict["arms"]["graph"]
    out: list[str] = []
    ceiling = diag.get("speedup_max")
    if ceiling:
        share = diag.get("critical_path_share")
        share_txt = f"{share:.0%} da parede está no caminho crítico" if share else ""
        out.append(f"    {'speedup_max':<17}{ceiling:.2f}×  teto do seu DAG: {share_txt}")
        path = diag.get("critical_path") or []
        if path:
            out.append(f"    {'':<17}       {' → '.join(path)}")
    if diag.get("join_wall"):
        pct = diag["join_wall"] / graph["wall_seconds"] if graph["wall_seconds"] else 0
        out.append(
            f"    {'join_wall':<17}{hms(diag['join_wall'])}   "
            f"{pct:.0%} da parede inteira num nó só"
        )
    branch = diag.get("branch_wall") or {}
    if branch:
        parts = " · ".join(f"{k} {hms(v)}" for k, v in sorted(branch.items()))
        spread = _spread(list(branch.values()))
        out.append(f"    {'branch_wall':<17}{parts}   (desbalanço {spread:.0%})")
    for key in ("orphan_writes", "null_writes", "rework", "write_violations"):
        if key in diag:
            out.append(f"    {key:<17}{diag[key]}")
    out.append(f"    {'handoff_uptake':<17}n/a  [proxy não calibrado — não decide nada]")
    out.append(f"    {'stop_reason':<17}{verdict['stop_reason']}")
    rationale = diag.get("fanout_rationale") or {}
    for fanout_id in sorted(rationale):
        out.append(
            f"    {'rationale':<17}{fanout_id}: {rationale[fanout_id]}"
        )
    out.append("")
    out.append(
        "  leitura: se speedup_max já é baixo, o problema é a topologia, não o "
        "escalonador."
    )
    out.append("  mova trabalho do `join` para os ramos, ou pare de usar fanout aqui. "
               "não aumente `max`.")
    return out


def _spread(values: list[float]) -> float:
    if not values:
        return 0.0
    high, low = max(values), min(values)
    return 0.0 if not high else (high - low) / high


def render_unavailable(reason: str) -> str:
    return "\n".join(
        [
            RULE,
            "  veredito: INDISPONÍVEL",
            f"  {reason}",
            f"  {FOOTER}",
            RULE,
        ]
    )
