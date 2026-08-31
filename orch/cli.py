"""orch doctor | orch up — the MAT-97 start slice."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from orch import __version__
from orch.adapters.claude import ClaudeAdapter
from orch.env import parent_had_api_key
from orch.errors import (
    EXIT_OK,
    EXIT_USAGE,
    GraphError,
    OrchError,
    PreflightError,
    SessionError,
    UsageError,
)
from orch.graph import load_graph
from orch.scheduler import NodeFailed, run_session
from orch.session import create_session

CONCURRENCY_HELP = (
    "Limits how many nodes spawn at once (auto|1..3). Does not create "
    "parallelism — graph width does. This slice stubs the scheduler at "
    "concurrency 1 (fanout instances still expand and run one at a time)."
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

    up = sub.add_parser("up", help="load a graph, create a session, spawn nodes")
    up.add_argument("graph", help="path to graphs/<id>.yaml")
    up.add_argument(
        "--session-dir",
        help="session directory (required unless --validate-only)",
    )
    up.add_argument(
        "--max-concurrency",
        default="auto",
        help=CONCURRENCY_HELP,
    )
    up.add_argument("--seed", type=int, default=1)
    up.add_argument(
        "--no-baseline",
        action="store_true",
        help="skip the control arm (session is not comparable; required in this slice)",
    )
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

    concurrency, warning = _concurrency(args.max_concurrency, graph.width)
    if warning:
        print(f"orch: {warning}", file=sys.stderr)

    if not args.no_baseline:
        raise UsageError(
            "baseline runner is stubbed in this slice. Re-run with --no-baseline "
            "(prints SEM BASELINE; session is not comparable; no verdict.json)."
        )

    print("SEM BASELINE — esta sessão não produz veredito")
    session = create_session(
        graph, Path(args.session_dir), force_unlock=args.force_unlock
    )
    adapter = ClaudeAdapter()
    try:
        preflight = adapter.preflight(timeout_s=5.0)
    except PreflightError:
        session.ledger.preflight = {
            "failed": True,
            "graph_sha256": graph.sha256,
            "concurrency_requested": args.max_concurrency,
            "concurrency_effective": concurrency,
            "concurrency_stubbed": True,
            "seed": args.seed,
            "baseline": "skipped",
            "comparable": False,
            "api_key_stripped": parent_had_api_key(),
            "force_unlock": bool(args.force_unlock),
        }
        session.ledger.write()
        raise

    session.ledger.preflight = {
        "cli_version": preflight["version"],
        "auth_status": preflight["auth_status"],
        "graph_sha256": graph.sha256,
        "concurrency_requested": args.max_concurrency,
        "concurrency_effective": concurrency,
        "concurrency_stubbed": True,
        "seed": args.seed,
        "baseline": "skipped",
        "comparable": False,
        "api_key_stripped": preflight["api_key_stripped"],
        "force_unlock": bool(args.force_unlock),
        "slice": "mat-97-start",
    }
    session.ledger.write()

    if args.max_concurrency not in {"1", "auto"} and graph.width < 2:
        print(
            "orch: --max-concurrency exceeds graph width; "
            "a chain never runs two nodes at once.",
            file=sys.stderr,
        )

    code = run_session(session, adapter, only_node=args.node, seed=args.seed)
    print(
        f"orch: session {session.path}  graph {graph.id}  "
        f"stop={'reached' if code == EXIT_OK and not args.node else 'n/a'}  "
        f"exit {code}"
    )
    print(f"  state:  {session.path / 'state.json'}")
    print(f"  events: {session.path / 'events.jsonl'}")
    if args.node:
        node = session.ledger.nodes.get(args.node)
        print(f"  node {args.node}: {node.status if node else 'missing'}")
    return code


def _concurrency(flag: str, width: int) -> tuple[int, str | None]:
    if flag == "auto":
        return 1, "this slice stubs --max-concurrency auto → 1 (SPEC default auto is not wired yet)"
    try:
        value = int(flag)
    except ValueError as exc:
        raise UsageError("--max-concurrency must be auto or 1..3") from exc
    if value < 1 or value > 3:
        raise UsageError("--max-concurrency 4+ is refused, not clamped (SPEC §2)")
    if value > 1:
        return 1, (
            f"--max-concurrency {value} accepted but this slice stubs the "
            f"scheduler at 1 (width={width}; worktrees not created)"
        )
    return 1, None


if __name__ == "__main__":
    raise SystemExit(main())
