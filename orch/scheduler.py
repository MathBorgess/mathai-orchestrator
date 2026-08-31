"""The ready-set scheduler (SPEC §3.3). The parent does NOT walk a pre-computed
topological order: on every completion it recomputes

    ready_set() := { n : status(n)==pending ∧ ∀e ∈ in(n): status(e.from)==done ∧ pred(e) }

blocks on the FIRST completion (never a barrier — nodes have unequal duration and a
barrier is the implementation that makes concurrency 3 render like 1), runs
`verifying` in the parent, and only then frees the slot. Freeing the slot before the
verdict is how parallelism starts corrupting the graph.

An empty ready set with nothing running is `stop_reason: deadlock` — a named error,
never an eternal wait.
"""

from __future__ import annotations

import shutil
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orch.adapters.claude import ClaudeAdapter, kill_process_group
from orch.errors import (
    EXIT_CONTRACT,
    EXIT_GRAPH,
    EXIT_OK,
    EXIT_PERMISSION,
    EXIT_TIMEOUT,
    EXIT_VERIFY,
    OrchError,
)
from orch.gate import Gate
from orch.graph import Edge, Graph, Node
from orch.runner import Completion, preamble_text, run_agent, run_check
from orch.session import Session
from orch.verdict import ArmMetrics
from orch.verify import (
    owned_specs,
    sha256_file,
    snapshot_tree,
    verify_owned,
    write_violations,
)
from orch import worktree as wt


class StopReached(OrchError):
    exit_code = EXIT_OK


class NodeFailed(OrchError):
    def __init__(self, message: str, exit_code: int):
        super().__init__(message)
        self.exit_code = exit_code


class Deadlock(NodeFailed):
    def __init__(self, pending: list[str]):
        super().__init__(
            "stop_reason: deadlock — ready_set is empty and nothing is running or "
            f"verifying. pending={sorted(pending)}. This is a named error, never a "
            "wait that never returns.",
            EXIT_GRAPH,
        )


@dataclass
class Slot:
    node: Node
    started_epoch: float
    cwd: Path
    write_roots: list[Path]
    before: dict[Path, dict[str, tuple[str, float]]]
    overlap: set[str] = field(default_factory=set)
    worktree_path: Path | None = None
    proc: Any = None


@dataclass
class SessionResult:
    exit_code: int
    stop_reason: str
    metrics: ArmMetrics
    diagnostic: dict[str, Any]
    concurrency: dict[str, Any]
    wall_seconds: float
    failure: OrchError | None = None


def run_session(
    session: Session,
    adapter: ClaudeAdapter,
    *,
    gate: Gate,
    concurrency: int = 1,
    isolate: bool = False,
    seed: int = 1,
    only_node: str | None = None,
) -> SessionResult:
    graph = session.graph
    runnable = graph.runnable_nodes()
    started = time.time()
    stop_reason = ""
    window_events: list[str] = []
    inflight: dict[str, Slot] = {}
    futures: dict[Future[Completion], str] = {}
    launch_order: list[str] = []
    degraded_at: set[int] = set()
    max_workers = max(1, concurrency)

    if only_node is not None and only_node not in runnable:
        raise NodeFailed(f"unknown --node {only_node!r}", EXIT_GRAPH)

    executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="orch")
    failure: NodeFailed | OrchError | None = None
    try:
        while True:
            if only_node is None and _stop_reached(session, graph):
                stop_reason = "stop_reached"
                break
            if only_node is not None and session.ledger.nodes[only_node].status != "pending":
                if not inflight:
                    stop_reason = "single_node"
                    break

            reason = gate.enforce()
            if reason:
                window_events.append(reason)

            ceiling = gate.ceiling() or 1
            effective = max(1, min(concurrency, graph.width, ceiling))
            if ceiling < min(concurrency, graph.width) and ceiling not in degraded_at:
                degraded_at.add(ceiling)
                session.ledger.add_deviation(
                    "concurrency_degraded",
                    declared=min(concurrency, graph.width),
                    effective=effective,
                    why=f"window utilization {gate.utilization}: the gate degrades, "
                    "the declaration does not change",
                )
            if only_node is not None:
                effective = 1
                ready = (
                    [only_node]
                    if session.ledger.nodes[only_node].status == "pending"
                    else []
                )
            else:
                ready = ready_set(session, graph)

            while ready and len(inflight) < effective:
                node = runnable[ready.pop(0)]
                cap = _node_cap(graph, node)
                if not gate.admits(cap):
                    raise gate.refuse_spawn(node.id, cap)
                slot = _launch(session, adapter, node, seed=seed, isolate=isolate)
                for other in inflight.values():
                    other.overlap.update(node.writes)
                    slot.overlap.update(other.node.writes)
                inflight[node.id] = slot
                launch_order.append(node.id)
                futures[
                    executor.submit(_worker, session, adapter, slot, seed)
                ] = node.id

            if not inflight:
                if not ready:
                    pending = [
                        n
                        for n, st in session.ledger.nodes.items()
                        if st.status == "pending"
                    ]
                    raise Deadlock(pending)
                continue

            done, _ = wait(list(futures), return_when=FIRST_COMPLETED, timeout=1.0)
            gate.check_wall()
            for future in done:
                node_id = futures.pop(future)
                slot = inflight.pop(node_id)
                completion = future.result()
                # verifying runs in the parent, with the slot still held (SPEC §3.2).
                _finish(session, adapter, slot, completion, gate)
                state = session.ledger.nodes[node_id]
                if state.status == "failed":
                    failure = NodeFailed(
                        f"node {node_id} failed: {state.failure}",
                        _failure_exit(state.failure),
                    )
                    break
            if failure is not None:
                stop_reason = f"failed:{session.ledger.nodes[node_id].failure}"
                break
    except OrchError as exc:
        failure = exc
        stop_reason = _abort_reason(exc)
    finally:
        _drain(session, inflight, futures, reason="stop_reached" if failure is None else "aborted")
        executor.shutdown(wait=True, cancel_futures=True)
        _remove_worktrees(session, inflight)

    session.ledger.add_deviation(
        "launch_order",
        declared="ready-set; the declaration fixes no order",
        effective=launch_order,
        why="the order is a runtime decision recomputed on every completion",
    )
    wall = time.time() - started
    if window_events:
        stop_reason = f"{stop_reason} · {' · '.join(sorted(set(window_events)))}"
    metrics = collect_metrics(session, wall)
    result = SessionResult(
        exit_code=EXIT_OK if failure is None else failure.exit_code,
        stop_reason=stop_reason or "unknown",
        metrics=metrics,
        diagnostic=collect_diagnostic(session, graph, metrics),
        concurrency={
            "requested": concurrency,
            "graph_width": graph.width,
            "effective_cap": max(1, min(concurrency, graph.width)),
            "isolated_worktrees": isolate,
            "window_sleeps": gate.sleeps,
            "slept_seconds": round(gate.slept_seconds, 1),
            "last_utilization": gate.last_utilization,
        },
        wall_seconds=wall,
        failure=failure,
    )
    return result


# ---------------------------------------------------------------- ready set


def ready_set(session: Session, graph: Graph) -> list[str]:
    runnable = graph.runnable_nodes()
    ready: list[str] = []
    for node_id, node in runnable.items():
        st = session.ledger.nodes[node_id]
        if st.status != "pending":
            continue
        edges = _effective_incoming(graph, node)
        if edges and not all(_edge_satisfied(session, graph, edge, node) for edge in edges):
            continue
        ready.append(node_id)

    def sort_key(nid: str) -> tuple[int, str]:
        node = runnable[nid]
        if node.type == "instance" and node.fanout_id and node.slot:
            fanout = graph.nodes[node.fanout_id]
            slots = [p.slot for p in fanout.partition]
            return (1, f"{node.fanout_id}.{slots.index(node.slot):02d}")
        return (0, nid)

    ready.sort(key=sort_key)
    return ready


def _effective_incoming(graph: Graph, node: Node) -> list[Edge]:
    if node.type == "instance" and node.fanout_id:
        return [e for e in graph.edges if e.target == node.fanout_id and e.on != "always"]
    return [e for e in graph.edges if e.target == node.id]


def _edge_satisfied(session: Session, graph: Graph, edge: Edge, node: Node) -> bool:
    if edge.on == "always":
        fanout = graph.nodes[edge.source]
        inst_ids = [f"{fanout.id}.{p.slot}" for p in fanout.partition]
        return all(session.ledger.nodes[i].status == "done" for i in inst_ids)

    src_status = _source_status(session, graph, edge.source)
    if edge.on in {"artifact_exists", "artifact_valid", "check_passed"}:
        if src_status != "done":
            return False
    if edge.on == "check_failed":
        src = session.ledger.nodes.get(edge.check or edge.source)
        return bool(src and src.status == "failed")
    if edge.on == "check_passed":
        return src_status == "done"
    if edge.on == "artifact_exists":
        return (session.path / (edge.artifact or "")).is_file()
    if edge.on == "artifact_valid":
        spec = graph.artifacts.get(edge.artifact or "")
        if spec is None:
            return False
        rec = session.ledger.artifacts.get(spec.path)
        return bool(rec and rec.valid)
    return False


def _source_status(session: Session, graph: Graph, source_id: str) -> str | None:
    node = graph.nodes.get(source_id)
    if node and node.type == "fanout":
        insts = [f"{node.id}.{p.slot}" for p in node.partition]
        statuses = [session.ledger.nodes[i].status for i in insts]
        if all(s == "done" for s in statuses):
            return "done"
        if any(s == "failed" for s in statuses):
            return "failed"
        return "pending"
    st = session.ledger.nodes.get(source_id)
    return st.status if st else None


def _stop_reached(session: Session, graph: Graph) -> bool:
    return all(session.ledger.nodes[n].status == "done" for n in graph.stop.all_of)


# ---------------------------------------------------------------- launch / worker


def _launch(
    session: Session,
    adapter: ClaudeAdapter,
    node: Node,
    *,
    seed: int,
    isolate: bool,
) -> Slot:
    ledger = session.ledger
    ledger.set_status(node.id, "ready")
    worktree_path: Path | None = None
    cwd = (session.path / node.cwd).resolve()

    if isolate and node.type == "instance":
        worktree_path = (session.path / "wt" / node.id).resolve()
        wt.add(
            session.graph.root,
            worktree_path,
            wt.branch_name(session.id, node.id),
        )
        cwd = worktree_path

    cwd.mkdir(parents=True, exist_ok=True)
    roots = [session.path]
    if worktree_path is not None:
        roots.append(worktree_path)
    before = {root: snapshot_tree(root) for root in roots}
    ledger.set_status(
        node.id,
        "running",
        extra={"cwd": str(cwd), "worktree": str(worktree_path) if worktree_path else None},
    )
    return Slot(
        node=node,
        started_epoch=time.time(),
        cwd=cwd,
        write_roots=roots,
        before=before,
        worktree_path=worktree_path,
    )


def _worker(
    session: Session, adapter: ClaudeAdapter, slot: Slot, seed: int
) -> Completion:
    """Runs in the pool thread. Spawns the process and waits. It writes no ledger
    state: `state.json` stays single-writer, and the writer is the parent."""
    node = slot.node
    logs = session.path / "logs"

    def register(proc: Any) -> None:
        slot.proc = proc

    if node.type == "check":
        return run_check(
            node,
            cwd=slot.cwd,
            root=session.graph.root,
            log_dir=logs,
            on_start=register,
        )

    owned = owned_specs(session.graph.artifacts, node)
    write_root = slot.worktree_path or session.path
    incoming: list[tuple[str, tuple[str, ...]]] = []
    for edge in session.graph.edges:
        if (
            edge.target in {node.id, node.fanout_id}
            and edge.handoff == "structured"
            and edge.artifact
        ):
            spec = session.graph.artifacts.get(edge.artifact)
            if spec and spec.sections:
                incoming.append((edge.artifact, spec.sections))
    preamble = preamble_text(
        session_dir=session.path,
        node=node,
        write_root=write_root,
        owned=owned,
        incoming_sections=incoming,
        seed=seed,
    )
    prompt = (session.graph.root / (node.prompt or "")).read_text(encoding="utf-8")
    return run_agent(
        adapter,
        node,
        session_id=session.id,
        session_dir=session.path,
        cwd=slot.cwd,
        preamble=preamble,
        prompt=prompt,
        prompt_dir=session.path / "prompts",
        log_dir=logs,
        seed=seed,
        add_dirs=(slot.cwd,) if slot.worktree_path else (),
        on_start=register,
    )


# ---------------------------------------------------------------- verifying


def _finish(
    session: Session,
    adapter: ClaudeAdapter,
    slot: Slot,
    completion: Completion,
    gate: Gate,
) -> None:
    ledger = session.ledger
    node = slot.node
    state = ledger.nodes[node.id]
    state.wall_seconds = completion.elapsed
    state.rc = completion.rc
    if completion.stdout_path.is_file():
        size = completion.stdout_path.stat().st_size
        state.log_bytes = size
        ledger.budget["log_bytes"] = int(ledger.budget["log_bytes"]) + size
    ledger.set_status(node.id, "verifying")

    if completion.error is not None:
        _fail(session, slot, "spawn", detail=str(completion.error))
        return
    if completion.timed_out:
        _fail(
            session,
            slot,
            "timeout",
            detail=f"exceeded timeout_seconds={node.timeout_seconds}; "
            "the process group was killed (SIGTERM, 5s grace, SIGKILL)",
        )
        return

    bad = _violations(slot)
    for path in bad:
        ledger.add_violation(node.id, path, "orphan_write" if node.type != "check" else "check_wrote")
    if bad:
        _fail(session, slot, "contract", detail=", ".join(bad[:5]))
        return

    if node.type == "check":
        if completion.rc != 0:
            _fail(session, slot, "verify", detail=f"check exited {completion.rc}")
            return
        _cleanup_worktree(session, slot)
        ledger.set_status(node.id, "done", extra={"rc": completion.rc})
        return

    outcome = adapter.parse(completion.rc or 0, completion.stdout_path, completion.stderr_path)
    gate.observe(outcome)
    if outcome.cost_units:
        state.cost_units = float(outcome.cost_units)
        ledger.budget["cost_units"] = float(ledger.budget["cost_units"]) + outcome.cost_units
    if outcome.turns:
        state.iters_used = outcome.turns
        ledger.budget["iters_used"] = int(ledger.budget["iters_used"]) + outcome.turns
    ledger.budget["utilization"] = gate.utilization

    if outcome.failure == "permission":
        names = ", ".join(d.tool_name for d in outcome.denials) or "unknown"
        _fail(
            session,
            slot,
            "permission",
            detail=f"denied tools: {names}. rc=0 with permission_denials is the "
            "verified way exit 0 lies; add the tool to the node's tools.allow "
            "(--allowedTools) if it is legitimate.",
            extra={"denied_tools": names},
        )
        return
    if outcome.failure in {"budget", "transport", "parse"}:
        _fail(session, slot, outcome.failure, detail=f"subtype={outcome.subtype}")
        return
    if not outcome.ok:
        _fail(session, slot, outcome.failure or "verify", detail=f"rc={outcome.rc}")
        return

    write_root = slot.worktree_path or session.path
    specs = owned_specs(session.graph.artifacts, node)
    ok, reason = verify_owned(write_root, specs, slot.started_epoch, session.graph.root)
    if ok and slot.worktree_path is not None:
        _copy_back(slot.worktree_path, session.path, specs)
    for spec in specs:
        landed = session.path / spec.path
        if landed.is_file():
            ledger.record_artifact(
                spec.path, sha256_file(landed), node.id, landed.stat().st_mtime, ok
            )
    if not ok:
        _fail(session, slot, "verify", detail=reason)
        return

    _cleanup_worktree(session, slot)
    ledger.set_status(
        node.id,
        "done",
        session_ref=outcome.session_ref,
        extra={
            "rc": outcome.rc,
            "turns": outcome.turns,
            "cost_units": outcome.cost_units,
            "degraded": outcome.degraded,
        },
    )


def _violations(slot: Slot) -> list[str]:
    node = slot.node
    ignore = tuple(sorted(slot.overlap))
    bad: list[str] = []
    for root in slot.write_roots:
        after = snapshot_tree(root)
        scoped_ignore = ignore if root == slot.write_roots[0] else ()
        bad.extend(write_violations(slot.before[root], after, node.writes, scoped_ignore))
    return sorted(set(bad))


def _copy_back(worktree: Path, session_path: Path, specs: list[Any]) -> None:
    """The node ran in its own checkout; its artifacts have to land in the session
    namespace where the downstream nodes read them (SPEC §3.6: copy, then remove)."""
    for spec in specs:
        src = worktree / spec.path
        if not src.is_file():
            continue
        dst = session_path / spec.path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _cleanup_worktree(session: Session, slot: Slot) -> None:
    if slot.worktree_path is None:
        return
    err = wt.remove(session.graph.root, slot.worktree_path)
    slot.worktree_path = None
    if err:
        session.ledger.append_event(
            {
                "ts": _now(),
                "node": slot.node.id,
                "from": "verifying",
                "to": "verifying",
                "worktree_remove_failed": err,
            }
        )


def _fail(
    session: Session,
    slot: Slot,
    failure: str,
    *,
    detail: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    _cleanup_worktree(session, slot)
    payload = {"detail": detail} if detail else {}
    payload.update(extra or {})
    session.ledger.set_status(slot.node.id, "failed", failure=failure, extra=payload)


def _drain(
    session: Session,
    inflight: dict[str, Slot],
    futures: dict[Future[Completion], str],
    *,
    reason: str,
) -> None:
    """SPEC §6.1-2: at the instant of the stop, the nodes still running are killed —
    killpg, 5s grace, SIGKILL — marked skipped:stop_reached, and their worktrees
    removed. A branch still burning budget after the stop is the bill nobody asked for."""
    for node_id, slot in list(inflight.items()):
        if slot.proc is not None:
            kill_process_group(slot.proc)
        _cleanup_worktree(session, slot)
        session.ledger.set_status(
            node_id, "skipped", failure=reason, extra={"killed": True}
        )
    for future in list(futures):
        future.cancel()


def _remove_worktrees(session: Session, inflight: dict[str, Slot]) -> None:
    for slot in inflight.values():
        _cleanup_worktree(session, slot)


# ---------------------------------------------------------------- metrics


def collect_metrics(session: Session, wall_seconds: float) -> ArmMetrics:
    ledger = session.ledger
    graph = session.graph
    sum_node_wall = sum(st.wall_seconds for st in ledger.nodes.values())
    log_bytes = sum(
        p.stat().st_size for p in (session.path / "logs").glob("*.jsonl") if p.is_file()
    )
    gate_total = len(graph.stop.all_of)
    gate_passed = sum(
        1
        for n in graph.stop.all_of
        if ledger.nodes[n].status == "done" and ledger.nodes[n].attempts <= 1
    )
    return ArmMetrics(
        wall_seconds=wall_seconds,
        sum_node_wall=sum_node_wall,
        log_bytes=log_bytes,
        gate_passed=gate_passed,
        gate_total=gate_total,
        cost_units=float(ledger.budget["cost_units"]),
    )


def expanded_edges(graph: Graph) -> list[tuple[str, str]]:
    def expand(node_id: str) -> list[str]:
        node = graph.nodes.get(node_id)
        if node is not None and node.type == "fanout":
            return [f"{node.id}.{p.slot}" for p in node.partition]
        return [node_id]

    out: list[tuple[str, str]] = []
    for edge in graph.edges:
        for src in expand(edge.source):
            for dst in expand(edge.target):
                out.append((src, dst))
    return out


def critical_path(graph: Graph, wall: dict[str, float]) -> tuple[list[str], float]:
    """Longest path by node wall time. `speedup_max` is Σ ÷ critical path: the ceiling
    the DAG allows, whatever the scheduler does."""
    nodes = list(graph.runnable_nodes())
    edges = expanded_edges(graph)
    preds: dict[str, list[str]] = {n: [] for n in nodes}
    indeg: dict[str, int] = {n: 0 for n in nodes}
    for src, dst in edges:
        if src in preds and dst in preds:
            preds[dst].append(src)
            indeg[dst] += 1
    order: list[str] = [n for n in nodes if indeg[n] == 0]
    queue = list(order)
    seen = set(order)
    while queue:
        current = queue.pop(0)
        for src, dst in edges:
            if src != current or dst not in indeg:
                continue
            indeg[dst] -= 1
            if indeg[dst] == 0 and dst not in seen:
                seen.add(dst)
                order.append(dst)
                queue.append(dst)
    dist: dict[str, float] = {}
    parent: dict[str, str | None] = {}
    for node_id in order:
        best, best_src = 0.0, None
        for src in preds.get(node_id, []):
            if dist.get(src, 0.0) > best:
                best, best_src = dist[src], src
        dist[node_id] = best + wall.get(node_id, 0.0)
        parent[node_id] = best_src
    if not dist:
        return [], 0.0
    end = max(dist, key=lambda n: dist[n])
    path = [end]
    while parent.get(path[-1]):
        path.append(parent[path[-1]])  # type: ignore[arg-type]
    return list(reversed(path)), dist[end]


def collect_diagnostic(
    session: Session, graph: Graph, metrics: ArmMetrics
) -> dict[str, Any]:
    ledger = session.ledger
    wall = {n: st.wall_seconds for n, st in ledger.nodes.items()}
    path, cp = critical_path(graph, wall)
    instances = list(graph.instances)
    joins = [n.id for n in graph.nodes.values() if n.type == "join"]

    # An artifact is consumed when a node declares it in `reads` OR when a
    # deterministic check names it in its argv — the gate reading out/REPORT.md is a
    # reader, and counting it as orphaned would make the diagnostic lie about the one
    # artifact the stop is built on.
    reads: set[str] = set()
    for node in list(graph.nodes.values()) + list(graph.instances.values()):
        reads.update(node.reads)
        if node.type == "check" and node.run:
            reads.update(node.run[1:])
    orphan = sorted(
        path_key
        for path_key in ledger.artifacts
        if not any(_covered(path_key, glob) for glob in reads)
    )

    null_writes = 0
    rework = 0
    for rec in ledger.artifacts.values():
        history = rec.hashes
        for i in range(1, len(history)):
            if history[i] == history[i - 1]:
                null_writes += 1
            else:
                rework += 1

    return {
        "branches": len(instances),
        "speedup_max": round(metrics.sum_node_wall / cp, 4) if cp else None,
        "critical_path": path,
        "critical_path_seconds": round(cp, 3),
        "critical_path_share": round(cp / metrics.wall_seconds, 4)
        if metrics.wall_seconds
        else None,
        "join_wall": round(sum(wall.get(j, 0.0) for j in joins), 3),
        "branch_wall": {i: round(wall.get(i, 0.0), 3) for i in instances},
        "orphan_writes": len(orphan),
        "orphan_write_paths": orphan,
        "null_writes": null_writes,
        "rework": rework,
        "write_violations": len(ledger.violations),
        "handoff_uptake": None,
        "node_status": {n: st.status for n, st in ledger.nodes.items()},
        "fanout_rationale": {
            n.id: (n.rationale or "").strip().splitlines()[0] if n.rationale else ""
            for n in graph.nodes.values()
            if n.type == "fanout"
        },
    }


def _covered(path: str, glob: str) -> bool:
    from orch.verify import _matches_write

    return _matches_write(path, glob)


def _abort_reason(exc: OrchError) -> str:
    from orch.gate import RateLimitAbort, SessionBudgetExhausted, WallFailsafe

    if isinstance(exc, Deadlock):
        return "deadlock"
    if isinstance(exc, RateLimitAbort):
        return "window_limit"
    if isinstance(exc, SessionBudgetExhausted):
        return "session_budget"
    if isinstance(exc, WallFailsafe):
        return "wall_failsafe"
    return "aborted"


def _now() -> str:
    from orch.state import utc_now

    return utc_now()


def _node_cap(graph: Graph, node: Node) -> float:
    if node.type == "check":
        return 0.0
    if node.budget_units is not None:
        return float(node.budget_units)
    return float(graph.budget.node_units_default)


def _failure_exit(failure: str | None) -> int:
    return {
        "contract": EXIT_CONTRACT,
        "permission": EXIT_PERMISSION,
        "timeout": EXIT_TIMEOUT,
        "verify": EXIT_VERIFY,
        "semantic": EXIT_VERIFY,
        "budget": 12,
    }.get(failure or "", EXIT_VERIFY)


__all__ = [
    "Deadlock",
    "NodeFailed",
    "SessionResult",
    "StopReached",
    "collect_diagnostic",
    "collect_metrics",
    "critical_path",
    "ready_set",
    "run_session",
]