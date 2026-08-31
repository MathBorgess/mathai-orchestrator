"""orch doctor | orch up — load a graph, run the control arm, run the graph, judge it.

    python -m orch up graphs/v1.yaml --session-dir .sessions/t1

goes from zero to a printed verdict: preflight, baseline (serial, first), the graph
under the ready-set scheduler, then three numbers and one sentence.
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from orch import __version__
from orch import verdict as verdict_mod
from orch import worktree as wt
from orch.adapters.claude import ClaudeAdapter
from orch.baseline import run_baseline
from orch.env import parent_had_api_key
from orch.errors import (
    EXIT_BASELINE,
    EXIT_BUG,
    EXIT_OK,
    GraphError,
    OrchError,
    PreflightError,
    SessionError,
    UsageError,
)
from orch.gate import Gate
from orch.graph import Graph, load_graph
from orch.scheduler import NodeFailed, SessionResult, run_session
from orch.session import Session, create_session
from orch.verdict import ArmMetrics

CONCURRENCY_HELP = (
    "auto|1..3 (default auto = min(graph width, 3)). This is a ceiling on what goes "
    "up, not the thing that creates parallelism — graph width creates it. In a chain "
    "scout -> builder the effective concurrency is 1 for any value, because the ready "
    "set never holds two nodes. 4+ is refused, not clamped."
)
NO_BASELINE_HELP = (
    "run without the control arm. The session still exits 0 if it reaches the stop, "
    "but it produces no verdict.json and no verdict. Command line only: it cannot be "
    "expressed in the YAML, in project config, or in an environment variable."
)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.cmd == "doctor":
            return cmd_doctor()
        if args.cmd == "up":
            return cmd_up(args)
        raise UsageError(f"unknown command {args.cmd}")
    except GraphError as exc:
        print(f"orch: invalid graph ({exc.message})", file=sys.stderr)
        return exc.exit_code
    except PreflightError as exc:
        print(f"orch: preflight failed: {exc.message}", file=sys.stderr)
        return exc.exit_code
    except SessionError as exc:
        print(f"orch: {exc.message}", file=sys.stderr)
        return exc.exit_code
    except UsageError as exc:
        print(f"orch: {exc.message}", file=sys.stderr)
        return exc.exit_code
    except NodeFailed as exc:
        print(f"orch: {exc.message}", file=sys.stderr)
        return exc.exit_code
    except OrchError as exc:
        print(f"orch: {exc.message}", file=sys.stderr)
        return exc.exit_code
    except Exception:  # noqa: BLE001
        # Exit 1 is "unclassified failure"; SPEC §6.1 says that if it shows up, it is
        # a bug in orch. Print the traceback rather than hiding it behind a code.
        traceback.print_exc()
        print(
            "orch: unclassified failure (exit 1). This is a bug in orch, not in the "
            "graph — the traceback above is the report.",
            file=sys.stderr,
        )
        return EXIT_BUG


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orch",
        description=(
            "MathAI agent-team orchestrator. One session = one team. "
            "Graph engineering above Claude Code CLI (subscription, never API)."
        ),
    )
    parser.add_argument("--version", action="version", version=f"orch {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="preflight: claude CLI, auth, result schema (5s)")

    up = sub.add_parser("up", help="load a graph, run baseline + graph, print the verdict")
    up.add_argument("graph", help="path to graphs/<id>.yaml")
    up.add_argument(
        "--session-dir",
        help="session directory (required unless --validate-only)",
    )
    up.add_argument("--max-concurrency", default="auto", help=CONCURRENCY_HELP)
    up.add_argument("--seed", type=int, default=1)
    up.add_argument("--no-baseline", action="store_true", help=NO_BASELINE_HELP)
    up.add_argument("--node", help="spawn only this node id (or derived instance id)")
    up.add_argument(
        "--validate-only",
        action="store_true",
        help="load and refuse; do not create a session or spawn",
    )
    up.add_argument(
        "--force-unlock",
        action="store_true",
        help="recover an orphan lock (permanent mark in preflight)",
    )
    return parser


def cmd_doctor() -> int:
    adapter = ClaudeAdapter()
    report = adapter.preflight(timeout_s=5.0)
    stripped = "yes" if report["api_key_stripped"] else "no"
    print("orch doctor: ok")
    print(f"  claude:     {report['binary']}")
    print(f"  version:    {report['version'] or '(empty)'}")
    print(f"  auth:       {report['auth_status']}")
    print(f"  probe:      fields {', '.join(report['probe']['fields'])} present")
    print(f"  api_key:    stripped={stripped} (never used; login with claude auth login)")
    print("  adapter:    CLI subprocess only; --bare forbidden")
    return EXIT_OK


def cmd_up(args: argparse.Namespace) -> int:
    graph = load_graph(args.graph)
    if args.validate_only:
        runnable = graph.runnable_nodes()
        print(
            f"orch: graph ok  id={graph.id}  sha256={graph.sha256[:12]}  "
            f"declared={len(graph.nodes)}  runnable={len(runnable)}  "
            f"width={graph.width}  stop={list(graph.stop.all_of)}"
        )
        return EXIT_OK

    if not args.session_dir:
        raise UsageError("--session-dir is required (one session = one team)")

    requested = _requested_concurrency(args.max_concurrency)
    concurrency = min(requested, graph.width) if requested else 1
    if graph.width < 2:
        print(
            "orch: graph width is 1 — parallelism only pays when the width is >= 2 and "
            "the session fits the window without sleeping (SPEC §3.6).",
            file=sys.stderr,
        )
    elif requested > graph.width:
        print(
            f"orch: --max-concurrency {requested} exceeds graph width {graph.width}; "
            "k above the width buys exactly zero and costs more than zero.",
            file=sys.stderr,
        )

    isolate, concurrency, isolation_note = _isolation(
        graph, concurrency, args.max_concurrency
    )

    if args.no_baseline:
        # SPEC §7: the escape hatch exists, and it is noisy.
        print("SEM BASELINE — esta sessão não produz veredito")

    session = create_session(graph, Path(args.session_dir), force_unlock=args.force_unlock)
    adapter = ClaudeAdapter()
    preflight_base: dict[str, Any] = {
        "graph_sha256": graph.sha256,
        "concurrency_requested": args.max_concurrency,
        "concurrency_effective": concurrency,
        "graph_width": graph.width,
        "isolation": "worktree" if isolate else "cwd",
        "isolation_note": isolation_note,
        "seed": args.seed,
        "baseline": "skipped" if args.no_baseline else "pending",
        "comparable": not args.no_baseline,
        "api_key_stripped": parent_had_api_key(),
        "force_unlock": bool(args.force_unlock),
    }
    try:
        report = adapter.preflight(timeout_s=5.0)
    except PreflightError:
        session.ledger.preflight = {**preflight_base, "failed": True}
        session.ledger.write()
        raise
    session.ledger.preflight = {
        **preflight_base,
        "cli_version": report["version"],
        "auth_status": report["auth_status"],
        "api_key_stripped": report["api_key_stripped"],
    }
    session.ledger.write()

    gate = Gate(
        session_units=graph.budget.session_units,
        wall_seconds=graph.budget.wall_seconds,
        started_at=time.time(),
    )

    baseline_metrics: ArmMetrics | None = None
    if not args.no_baseline and not args.node:
        code = _run_control_arm(session, graph, adapter, gate, args.seed)
        if code is not None:
            return code
        arm = session.ledger.preflight["baseline_arm"]
        baseline_metrics = ArmMetrics(
            wall_seconds=arm["wall_seconds"],
            sum_node_wall=arm["node_wall_seconds"],
            log_bytes=arm["log_bytes"],
            gate_passed=arm["gate_passed"],
            gate_total=arm["gate_total"],
            cost_units=arm["cost_units"],
        )
    elif args.node and not args.no_baseline:
        print(
            "orch: --node runs a single node; the control arm is skipped and the "
            "session is not comparable.",
            file=sys.stderr,
        )
        session.ledger.preflight["comparable"] = False
        session.ledger.preflight["baseline"] = "skipped:single-node"
        session.ledger.write()

    result = run_session(
        session,
        adapter,
        gate=gate,
        concurrency=concurrency,
        isolate=isolate,
        seed=args.seed,
        only_node=args.node,
    )
    session.ledger.budget["wall_seconds"] = round(result.wall_seconds, 3)
    session.ledger.write()

    print()
    print(
        f"orch: session {session.path}  graph {graph.id}  "
        f"stop_reason={result.stop_reason}  exit {result.exit_code}"
    )
    print(f"  state:   {session.path / 'state.json'}")
    print(f"  events:  {session.path / 'events.jsonl'}")
    if result.failure is not None:
        print(f"  failure: {result.failure.message}", file=sys.stderr)
    if args.node:
        node = session.ledger.nodes.get(args.node)
        print(f"  node {args.node}: {node.status if node else 'missing'}")

    print()
    _emit_verdict(session, graph, args, result, baseline_metrics)
    return result.exit_code


# ------------------------------------------------------------------ control arm


def _run_control_arm(
    session: Session, graph: Graph, adapter: ClaudeAdapter, gate: Gate, seed: int
) -> int | None:
    """Serial, first, same seed, same stop. Returns an exit code when it must stop."""
    print(
        f"orch: control arm first, serial, in {session.path / 'baseline'} "
        f"(same seed {seed}, same stop {list(graph.stop.all_of)}). "
        "The session costs ~2x of clock on purpose: a concurrent baseline competes "
        "for the same window and contaminates wall_seconds."
    )
    arm = run_baseline(graph, session.path, session.id, adapter, seed=seed)
    if arm.outcome is not None:
        gate.observe(arm.outcome)
    session.ledger.preflight["baseline"] = "reached_stop" if arm.reached_stop else "failed"
    session.ledger.preflight["baseline_arm"] = arm.as_dict()
    session.ledger.write()
    session.ledger.append_event(
        {
            "ts": _utc(),
            "node": "baseline",
            "from": "running",
            "to": "done" if arm.reached_stop else "failed",
            "failure": arm.failure,
            "wall_seconds": round(arm.node_wall_seconds, 3),
            "gate": f"{arm.gate_passed}/{arm.gate_total}",
        }
    )
    if not arm.reached_stop:
        print(
            f"orch: baseline did not reach the stop ({arm.failure}: {arm.detail}).\n"
            "  The TASK is broken, not the topology. The graph's budget was not spent.\n"
            f"  Look at {session.path / 'baseline'}/logs before touching the graph.",
            file=sys.stderr,
        )
        return EXIT_BASELINE
    print(
        f"orch: baseline reached the stop in {arm.node_wall_seconds:.1f}s "
        f"(gate {arm.gate_passed}/{arm.gate_total}, log_bytes {arm.log_bytes})."
    )
    return None


# ------------------------------------------------------------------ verdict


def _emit_verdict(
    session: Session,
    graph: Graph,
    args: argparse.Namespace,
    result: SessionResult,
    baseline_metrics: ArmMetrics | None,
) -> None:
    if args.no_baseline:
        print(
            verdict_mod.render_unavailable(
                "--no-baseline: nenhum braço de controle rodou, então não há "
                "denominador. Nada foi gravado em verdict.json."
            )
        )
        return
    if baseline_metrics is None:
        print(
            verdict_mod.render_unavailable(
                "--node: uma sessão de um nó só não é comparável com o baseline."
            )
        )
        return
    payload = verdict_mod.compute(
        graph_arm=result.metrics,
        baseline_arm=baseline_metrics,
        graph_id=str(args.graph),
        session_dir=session.path,
        seed=args.seed,
        stop_reason=result.stop_reason,
        concurrency=result.concurrency,
        diagnostic=result.diagnostic,
    )
    verdict_mod.write(session.path, payload)
    print(verdict_mod.render(payload))


# ------------------------------------------------------------------ helpers


def _requested_concurrency(flag: str) -> int:
    if flag == "auto":
        return 3  # auto = min(graph width, 3); the width is applied by the caller
    try:
        value = int(flag)
    except ValueError as exc:
        raise UsageError("--max-concurrency must be auto or 1..3") from exc
    if value < 1 or value > 3:
        raise UsageError(
            "--max-concurrency 4+ is refused, not clamped (SPEC §2). 3->5 is marginal "
            "or negative, and aggressive structural parallelism cost accuracy."
        )
    return value


def _isolation(graph: Graph, concurrency: int, flag: str) -> tuple[bool, int, str]:
    """One worktree per fanout instance when concurrency > 1 (SPEC §2.4): a distinct
    cwd is a distinct project directory in the CLI cache.

    Missing `git worktree` is a refusal for an explicit --max-concurrency 2|3, and a
    degrade to 1 for `auto` — degrading is what `auto` means, and it already degrades
    on window utilization. Running k>1 without per-instance isolation is never an
    option: that is the branch where the fanout corrupts itself."""
    if concurrency <= 1:
        return False, concurrency, "concurrency 1: no worktree, instances run in cwd"
    usable, why = wt.availability(graph.root)
    if usable:
        return True, concurrency, "one git worktree per fanout instance, parent owns it"
    if flag == "auto":
        print(
            f"orch: git worktree is unavailable ({why}); --max-concurrency auto "
            "degrades to 1 rather than refusing. Pass an explicit 1..3 to make the "
            "missing worktree a refusal.",
            file=sys.stderr,
        )
        return False, 1, f"degraded to concurrency 1: {why}"
    raise PreflightError(
        f"--max-concurrency {concurrency} needs git worktree, and it is unavailable: "
        f"{why}. Concurrency > 1 without per-instance isolation is refused at load, "
        "not patched at runtime (SPEC §2.1, §2.4)."
    )


def _utc() -> str:
    from orch.state import utc_now

    return utc_now()


if __name__ == "__main__":
    raise SystemExit(main())
