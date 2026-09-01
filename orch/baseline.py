"""The control arm: one node, the whole procedure, serial, before the graph.

SPEC §2.3 order of ascent: preflight, then the control arm in `session_dir/baseline/`
with the same --seed and the same `stop`, then the graph. If the baseline does not
reach the `stop`, `up` stops here with exit 41 and says the *task* is broken, not the
topology — and the graph's budget is never spent.

SPEC §1.6/§2.3, arbitration 4: serial and first, not a concurrent reserved slot. A
concurrent baseline competes for the same subscription window and contaminates
`wall_seconds`, which is the headline number of the verdict. An instrument cannot
contaminate the metric it exists to produce.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orch.adapters.claude import ClaudeAdapter
from orch.graph import Graph, Node, Tools
from orch.outcome import Outcome
from orch.runner import Completion, preamble_text, run_agent, run_check
from orch.state import utc_now
from orch.verify import snapshot_tree, write_violations

BASELINE_NODE_ID = "baseline"


@dataclass
class BaselineArm:
    reached_stop: bool = False
    failure: str | None = None
    detail: str = ""
    wall_seconds: float = 0.0
    node_wall_seconds: float = 0.0
    log_bytes: int = 0
    cost_units: float = 0.0
    turns: int | None = None
    gate_passed: int = 0
    gate_total: int = 0
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)
    violations: list[dict[str, str]] = field(default_factory=list)
    outcome: Outcome | None = None

    @property
    def gate_first_pass(self) -> float:
        if not self.gate_total:
            return 0.0
        return self.gate_passed / self.gate_total

    def as_dict(self) -> dict[str, Any]:
        return {
            "reached_stop": self.reached_stop,
            "failure": self.failure,
            "detail": self.detail,
            "wall_seconds": round(self.wall_seconds, 3),
            "node_wall_seconds": round(self.node_wall_seconds, 3),
            "log_bytes": self.log_bytes,
            "cost_units": round(self.cost_units, 6),
            "turns": self.turns,
            "gate_first_pass": round(self.gate_first_pass, 4),
            "gate_passed": self.gate_passed,
            "gate_total": self.gate_total,
            "checks": self.checks,
            "violations": self.violations,
        }


def baseline_node(graph: Graph) -> Node:
    spec = graph.baseline
    return Node(
        id=BASELINE_NODE_ID,
        type="agent",
        adapter=spec.adapter,
        prompt=spec.prompt,
        cwd=spec.cwd,
        reads=(),
        writes=spec.writes,
        budget_units=spec.budget_units,
        timeout_seconds=spec.timeout_seconds,
        tools=Tools(spec.tools.allow, spec.tools.deny),
    )


def run_baseline(
    graph: Graph,
    session_path: Path,
    session_id: str,
    adapter: ClaudeAdapter,
    *,
    seed: int,
) -> BaselineArm:
    arm = BaselineArm()
    started = time.time()
    root = session_path / "baseline"
    root.mkdir(parents=True, exist_ok=True)
    logs = root / "logs"
    prompts = root / "prompts"

    node = baseline_node(graph)
    prompt_path = graph.root / (node.prompt or "")
    prompt = prompt_path.read_text(encoding="utf-8")
    preamble = preamble_text(
        session_dir=root,
        node=node,
        write_root=root,
        owned=[],
        incoming_sections=[],
        seed=seed,
    )

    before = snapshot_tree(root)
    completion: Completion = run_agent(
        adapter,
        node,
        session_id=session_id,
        session_dir=root,
        cwd=root,
        preamble=preamble,
        prompt=prompt,
        prompt_dir=prompts,
        log_dir=logs,
        seed=seed,
    )
    arm.node_wall_seconds = completion.elapsed
    arm.log_bytes = _log_bytes(logs)

    if completion.error is not None:
        arm.failure = "spawn"
        arm.detail = f"{type(completion.error).__name__}: {completion.error}"
        arm.wall_seconds = time.time() - started
        return arm
    if completion.timed_out:
        arm.failure = "timeout"
        arm.detail = f"baseline exceeded timeout_seconds={node.timeout_seconds}"
        arm.wall_seconds = time.time() - started
        return arm

    outcome = adapter.parse(completion.rc or 0, completion.stdout_path, completion.stderr_path)
    arm.outcome = outcome
    arm.cost_units = float(outcome.cost_units or 0.0)
    arm.turns = outcome.turns

    after = snapshot_tree(root)
    bad = write_violations(before, after, node.writes)
    arm.violations = [
        {"node": BASELINE_NODE_ID, "path": p, "kind": "orphan_write"} for p in bad
    ]

    # The baseline arm keeps its own ledger so that the *same* `stop` checks can run
    # against it: `bin/check-writes state.json` needs a state.json in the arm it judges.
    _write_arm_state(root, arm, node, outcome, completion)

    if bad:
        arm.failure = "contract"
        arm.detail = "baseline wrote outside its declared writes: " + ", ".join(bad[:5])
        arm.wall_seconds = time.time() - started
        return arm
    if outcome.denials:
        arm.failure = "permission"
        arm.detail = "denied tools: " + ", ".join(d.tool_name for d in outcome.denials)
        arm.wall_seconds = time.time() - started
        return arm
    if not outcome.ok:
        arm.failure = outcome.failure or "verify"
        arm.detail = f"baseline exited rc={outcome.rc} is_error={outcome.is_error}"
        arm.wall_seconds = time.time() - started
        return arm

    # Same `stop` as the graph arm, run against the baseline namespace.
    for check_id in graph.stop.all_of:
        check = graph.nodes[check_id]
        done = run_check(check, cwd=root / check.cwd, root=graph.root, log_dir=logs)
        passed = done.rc == 0 and not done.timed_out and done.error is None
        arm.gate_total += 1
        arm.gate_passed += 1 if passed else 0
        arm.checks[check_id] = {
            "rc": done.rc,
            "timed_out": done.timed_out,
            "passed": passed,
            "wall_seconds": round(done.elapsed, 3),
            "attempts": 1,
        }
    arm.log_bytes = _log_bytes(logs)
    arm.reached_stop = arm.gate_total > 0 and arm.gate_passed == arm.gate_total
    if not arm.reached_stop:
        failed = [c for c, d in arm.checks.items() if not d["passed"]]
        arm.failure = "stop"
        arm.detail = "stop checks that did not pass: " + ", ".join(failed)
    arm.wall_seconds = time.time() - started
    _write_arm_state(root, arm, node, outcome, completion)
    return arm


def _log_bytes(logs: Path) -> int:
    if not logs.is_dir():
        return 0
    return sum(p.stat().st_size for p in logs.glob("*.jsonl") if p.is_file())


def _write_arm_state(
    root: Path,
    arm: BaselineArm,
    node: Node,
    outcome: Outcome | None,
    completion: Completion,
) -> None:
    payload = {
        "arm": "baseline",
        "nodes": {
            BASELINE_NODE_ID: {
                "status": "done" if arm.failure is None else "failed",
                "failure": arm.failure,
                "rc": completion.rc,
                "wall_seconds": round(arm.node_wall_seconds, 3),
                "iters_used": outcome.turns if outcome else None,
                "cost_units": round(arm.cost_units, 6),
                "ended_at": utc_now(),
            }
        },
        "checks": arm.checks,
        "violations": arm.violations,
        "budget": {
            "cost_units": round(arm.cost_units, 6),
            "log_bytes": arm.log_bytes,
            "wall_seconds": round(arm.wall_seconds, 3),
        },
    }
    tmp = root / "state.json.tmp"
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(root / "state.json")
