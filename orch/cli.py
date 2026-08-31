"""v0 CLI: python -m orch up graphs/v0.yaml --session-dir .sessions/<id>"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from orch.claude import PreflightError
from orch.graph import GraphError, load_graph
from orch.runner import SessionError, run_session


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m orch")
    sub = parser.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("up", help="start one session of one graph")
    up.add_argument("graph", help="path to graphs/v0.yaml")
    up.add_argument("--session-dir", required=True, help=".sessions/<id>")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd != "up":
        parser.error("v0 only implements `up`")
    try:
        graph = load_graph(Path(args.graph))
        return run_session(graph, Path(args.session_dir))
    except (GraphError, PreflightError, SessionError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
