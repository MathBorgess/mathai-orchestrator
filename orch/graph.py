"""Load and refuse a v1 graph. Invalid graph is a compile error (exit 50)."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from orch.errors import GraphError

ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
SLOT_RE = re.compile(r"^[a-z0-9]{1,8}$")
DERIVED_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}\.[a-z0-9]{1,8}$")

AGENT_DENYLIST = frozenset(
    {"claude", "cursor-agent", "codex", "opencode", "aider", "llm", "ollama"}
)
PRINT_FLAGS = frozenset({"-p", "--print"})
TEMPLATE_FORBIDDEN = frozenset({"id", "reads", "writes"})
NODE_TYPES = frozenset({"agent", "check", "fanout", "join"})
EDGE_ONS = frozenset(
    {"artifact_exists", "artifact_valid", "check_passed", "check_failed", "always"}
)
DEFAULT_TOOLS_ALLOW = ["Read", "Write", "Edit", "Glob", "Grep"]
DEFAULT_TOOLS_DENY = ["WebFetch", "WebSearch", "Task", "Bash"]


def infer_root(graph_path: Path) -> Path:
    resolved = graph_path.resolve()
    parent = resolved.parent
    if parent.name == "graphs" and (parent.parent / "prompts").is_dir():
        return parent.parent
    return Path.cwd()


@dataclass(frozen=True)
class Tools:
    allow: tuple[str, ...]
    deny: tuple[str, ...]


@dataclass(frozen=True)
class ArtifactSpec:
    path: str
    owner: str
    format: str
    sections: tuple[str, ...]
    verify: dict[str, Any]


@dataclass(frozen=True)
class Partition:
    slot: str
    reads: tuple[str, ...]
    writes: tuple[str, ...]


@dataclass
class Node:
    id: str
    type: str
    adapter: str = "claude"
    prompt: str | None = None
    cwd: str = "."
    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    iters: int | None = None
    budget_units: float | None = None
    timeout_seconds: int = 300
    tools: Tools = field(
        default_factory=lambda: Tools(tuple(DEFAULT_TOOLS_ALLOW), tuple(DEFAULT_TOOLS_DENY))
    )
    model: str | None = None
    run: tuple[str, ...] | None = None
    max: int | None = None
    rationale: str | None = None
    template: dict[str, Any] | None = None
    partition: tuple[Partition, ...] = ()
    from_fanout: str | None = None
    owns: tuple[str, ...] = ()
    fanout_id: str | None = None
    slot: str | None = None

    @property
    def runnable(self) -> bool:
        return self.type in {"agent", "check", "join", "instance"}


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    on: str
    artifact: str | None = None
    handoff: str | None = None
    check: str | None = None


@dataclass(frozen=True)
class Baseline:
    adapter: str
    prompt: str
    cwd: str
    writes: tuple[str, ...]
    budget_units: float
    timeout_seconds: int
    compare_on: tuple[str, ...]
    tools: Tools


@dataclass(frozen=True)
class Budget:
    wall_seconds: int
    session_units: float
    log_bytes: int
    iters_default: int
    node_units_default: float
    max_nodes: int
    no_progress_rounds: int
    tools: Tools


@dataclass(frozen=True)
class Stop:
    all_of: tuple[str, ...]
    failsafe: str


@dataclass
class Graph:
    id: str
    path: Path
    root: Path
    sha256: str
    raw_bytes: bytes
    baseline: Baseline
    budget: Budget
    artifacts: dict[str, ArtifactSpec]
    nodes: dict[str, Node]
    instances: dict[str, Node]
    edges: tuple[Edge, ...]
    stop: Stop
    width: int

    def runnable_nodes(self) -> dict[str, Node]:
        out = dict(self.instances)
        for node in self.nodes.values():
            if node.type in {"agent", "check", "join"}:
                out[node.id] = node
        return out

    def incoming(self, node_id: str) -> list[Edge]:
        node = self.runnable_nodes().get(node_id)
        fanout = node.fanout_id if node and node.type == "instance" else None
        found = []
        for edge in self.edges:
            if edge.target == node_id:
                found.append(edge)
            elif fanout and edge.target == fanout and edge.on != "always":
                found.append(edge)
        return found

    def declared_or_instance(self, node_id: str) -> Node | None:
        if node_id in self.nodes:
            return self.nodes[node_id]
        return self.instances.get(node_id)


def load_graph(path: str | Path, root: Path | None = None) -> Graph:
    graph_path = Path(path)
    if not graph_path.is_file():
        raise GraphError("V-file", f"graph file does not exist: {graph_path}")
    raw = graph_path.read_bytes()
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise GraphError("V-yaml", f"invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise GraphError("V-yaml", "graph root must be a mapping")
    repo_root = (root or infer_root(graph_path)).resolve()
    return _validate(data, graph_path.resolve(), repo_root, raw)


def _validate(data: dict[str, Any], graph_path: Path, root: Path, raw: bytes) -> Graph:
    graph_id = data.get("id")
    if not isinstance(graph_id, str) or not ID_RE.match(graph_id):
        raise GraphError("V-2", f"graph id {graph_id!r} is not {ID_RE.pattern}")
    stem = graph_path.stem
    if graph_id != stem:
        raise GraphError("V-1", f"graph id {graph_id!r} != file stem {stem!r}")

    budget = _budget(data.get("budget") or {})
    baseline = _baseline(data.get("baseline"), root, budget)
    nodes = _nodes(data.get("nodes"), root, budget)
    artifacts = _artifacts(data.get("artifacts") or {})
    edges = _edges(data.get("edges") or [])
    stop = _stop(data.get("stop"))

    _check_ids(nodes)
    instances = _expand_fanouts(nodes, budget)
    _check_id_collisions(nodes, instances)
    _check_prompts(nodes, baseline, root)
    _check_edges(nodes, instances, edges, artifacts, stop)
    _check_orphans_and_cycles(nodes, edges, stop)
    _check_parallelism(nodes, instances, edges)
    _check_contracts(nodes, instances, artifacts, edges, stop, root, baseline)
    _check_partition_writes(nodes)

    width = max((len(n.partition) for n in nodes.values() if n.type == "fanout"), default=1)
    return Graph(
        id=graph_id,
        path=graph_path,
        root=root,
        sha256=hashlib.sha256(raw).hexdigest(),
        raw_bytes=raw,
        baseline=baseline,
        budget=budget,
        artifacts=artifacts,
        nodes=nodes,
        instances=instances,
        edges=tuple(edges),
        stop=stop,
        width=width,
    )


def _budget(raw: dict[str, Any]) -> Budget:
    tools_raw = raw.get("tools") or {}
    return Budget(
        wall_seconds=int(raw.get("wall_seconds") or 3600),
        session_units=float(raw.get("session_units") or 6.0),
        log_bytes=int(raw.get("log_bytes") or 8_000_000),
        iters_default=int(raw.get("iters_default") or 4),
        node_units_default=float(raw.get("node_units_default") or 1.0),
        max_nodes=int(raw.get("max_nodes") or 8),
        no_progress_rounds=int(raw.get("no_progress_rounds") or 2),
        tools=_tools(tools_raw, None),
    )


def _tools(raw: Any, parent: Tools | None) -> Tools:
    parent = parent or Tools(tuple(DEFAULT_TOOLS_ALLOW), tuple(DEFAULT_TOOLS_DENY))
    if not raw:
        return parent
    allow = tuple(raw.get("allow") or parent.allow)
    deny = tuple(raw.get("deny") or parent.deny)
    extra = set(allow) - set(parent.allow)
    if extra:
        raise GraphError("V-tools", f"node tools.allow widened beyond budget: {sorted(extra)}")
    leaked = set(allow) & set(parent.deny)
    if leaked:
        raise GraphError("V-tools", f"node tools.allow includes budget.deny: {sorted(leaked)}")
    return Tools(allow=allow, deny=deny)


def _baseline(raw: Any, root: Path, budget: Budget) -> Baseline:
    if not raw:
        raise GraphError("V-19", "graph has no baseline block")
    writes = tuple(raw.get("writes") or ())
    if not writes:
        raise GraphError("V-20", "baseline.writes is empty")
    prompt = raw.get("prompt")
    if not prompt:
        raise GraphError("V-3", "baseline.prompt is missing")
    timeout = raw.get("timeout_seconds")
    if not timeout:
        raise GraphError("V-timeout", "baseline.timeout_seconds is required")
    return Baseline(
        adapter=raw.get("adapter") or "claude",
        prompt=str(prompt),
        cwd=raw.get("cwd") or ".",
        writes=writes,
        budget_units=float(raw.get("budget_units") or budget.node_units_default),
        timeout_seconds=int(timeout),
        compare_on=tuple(raw.get("compare_on") or ()),
        tools=_tools(raw.get("tools"), budget.tools),
    )


def _nodes(raw: Any, root: Path, budget: Budget) -> dict[str, Node]:
    if not isinstance(raw, list) or not raw:
        raise GraphError("V-2", "nodes must be a non-empty list")
    nodes: dict[str, Node] = {}
    for item in raw:
        if not isinstance(item, dict):
            raise GraphError("V-2", "each node must be a mapping")
        node = _one_node(item, budget)
        if node.id in nodes:
            raise GraphError("V-2", f"duplicate node id {node.id!r}")
        nodes[node.id] = node
    return nodes


def _one_node(item: dict[str, Any], budget: Budget) -> Node:
    node_id = item.get("id")
    if not isinstance(node_id, str) or not ID_RE.match(node_id):
        raise GraphError("V-2", f"node id {node_id!r} is not {ID_RE.pattern}")
    ntype = item.get("type")
    if ntype not in NODE_TYPES:
        raise GraphError("V-2", f"node {node_id!r} has unknown type {ntype!r}")

    if ntype == "check":
        if "writes" in item:
            raise GraphError("V-20", f"check {node_id!r} declared writes")
        run = item.get("run")
        if not isinstance(run, list) or not run or not all(isinstance(x, str) for x in run):
            raise GraphError("V-17", f"check {node_id!r} run must be a non-empty argv list")
        return Node(
            id=node_id,
            type="check",
            run=tuple(run),
            cwd=item.get("cwd") or ".",
            timeout_seconds=int(item.get("timeout_seconds") or 300),
            writes=(),
        )

    if ntype == "fanout":
        return _fanout_node(item, budget)

    writes = tuple(item.get("writes") or ())
    if not writes:
        raise GraphError("V-20", f"{ntype} {node_id!r} has empty writes")
    timeout = item.get("timeout_seconds")
    if not timeout:
        raise GraphError("V-timeout", f"{ntype} {node_id!r} missing timeout_seconds")
    prompt = item.get("prompt")
    if not prompt:
        raise GraphError("V-3", f"{ntype} {node_id!r} missing prompt")

    from_fanout = item.get("from") if ntype == "join" else None
    owns = tuple(item.get("owns") or ()) if ntype == "join" else ()
    if ntype == "join" and not from_fanout:
        raise GraphError("V-11", f"join {node_id!r} missing from")

    return Node(
        id=node_id,
        type=ntype,
        adapter=item.get("adapter") or "claude",
        prompt=str(prompt),
        cwd=item.get("cwd") or ".",
        reads=tuple(item.get("reads") or ()),
        writes=writes,
        iters=int(item["iters"]) if item.get("iters") is not None else budget.iters_default,
        budget_units=float(item["budget_units"])
        if item.get("budget_units") is not None
        else budget.node_units_default,
        timeout_seconds=int(timeout),
        tools=_tools(item.get("tools"), budget.tools),
        model=item.get("model"),
        from_fanout=from_fanout,
        owns=owns,
    )


def _fanout_node(item: dict[str, Any], budget: Budget) -> Node:
    node_id = item["id"]
    maximum = item.get("max")
    if not isinstance(maximum, int) or not 2 <= maximum <= 3:
        raise GraphError("V-8", f"fanout {node_id!r} max must be 2..3, got {maximum!r}")
    rationale = item.get("rationale")
    if not isinstance(rationale, str):
        raise GraphError("V-12c", f"fanout {node_id!r} missing rationale")
    nonempty = [ln for ln in rationale.splitlines() if ln.strip()]
    if len(nonempty) < 3:
        raise GraphError("V-12c", f"fanout {node_id!r} rationale has < 3 lines")
    template = item.get("template")
    if not isinstance(template, dict):
        raise GraphError("V-9", f"fanout {node_id!r} missing template")
    forbidden = TEMPLATE_FORBIDDEN & set(template)
    if forbidden:
        raise GraphError(
            "V-9", f"fanout {node_id!r} template declares {sorted(forbidden)}"
        )
    if not template.get("prompt"):
        raise GraphError("V-3", f"fanout {node_id!r} template missing prompt")
    if not template.get("timeout_seconds"):
        raise GraphError("V-timeout", f"fanout {node_id!r} template missing timeout_seconds")
    raw_part = item.get("partition")
    if not isinstance(raw_part, list):
        raise GraphError("V-8", f"fanout {node_id!r} partition must be a list")
    if not 2 <= len(raw_part) <= maximum:
        raise GraphError(
            "V-8",
            f"fanout {node_id!r} len(partition)={len(raw_part)} outside 2..{maximum}",
        )
    parts: list[Partition] = []
    seen_slots: set[str] = set()
    for entry in raw_part:
        slot = entry.get("slot")
        if not isinstance(slot, str) or not SLOT_RE.match(slot):
            raise GraphError("V-2", f"fanout {node_id!r} slot {slot!r} is not {SLOT_RE.pattern}")
        if slot in seen_slots:
            raise GraphError("V-2", f"fanout {node_id!r} duplicate slot {slot!r}")
        seen_slots.add(slot)
        writes = tuple(entry.get("writes") or ())
        if not writes:
            raise GraphError("V-20", f"fanout {node_id!r} slot {slot!r} has empty writes")
        parts.append(
            Partition(
                slot=slot,
                reads=tuple(entry.get("reads") or ()),
                writes=writes,
            )
        )
    return Node(
        id=node_id,
        type="fanout",
        max=maximum,
        rationale=rationale,
        template=template,
        partition=tuple(parts),
        adapter=template.get("adapter") or "claude",
        prompt=str(template["prompt"]),
        cwd=template.get("cwd") or ".",
        timeout_seconds=int(template["timeout_seconds"]),
        tools=_tools(template.get("tools"), budget.tools),
        model=template.get("model"),
        iters=int(template["iters"]) if template.get("iters") is not None else budget.iters_default,
        budget_units=float(template["budget_units"])
        if template.get("budget_units") is not None
        else budget.node_units_default,
    )


def _artifacts(raw: dict[str, Any]) -> dict[str, ArtifactSpec]:
    artifacts: dict[str, ArtifactSpec] = {}
    for path, spec in raw.items():
        if not isinstance(spec, dict):
            raise GraphError("V-13", f"artifact {path!r} must be a mapping")
        owner = spec.get("owner")
        if not owner:
            raise GraphError("V-13", f"artifact {path!r} has no owner")
        verify = spec.get("verify") or {}
        artifacts[path] = ArtifactSpec(
            path=path,
            owner=str(owner),
            format=str(spec.get("format") or "prose"),
            sections=tuple(spec.get("sections") or ()),
            verify=dict(verify),
        )
    return artifacts


def _edges(raw: list[Any]) -> list[Edge]:
    edges: list[Edge] = []
    for item in raw:
        if not isinstance(item, dict):
            raise GraphError("V-4", "edge must be a mapping")
        source, target = item.get("from"), item.get("to")
        # YAML 1.1: the key `on` is an implicit bool and loads as True.
        on = item.get("on")
        if on is None and True in item:
            on = item[True]
        if not source or not target or not on:
            raise GraphError("V-4", f"edge missing from/to/on: {item}")
        if on not in EDGE_ONS:
            raise GraphError("V-4", f"unknown edge predicate {on!r}")
        artifact = item.get("artifact")
        handoff = item.get("handoff")
        if handoff and not artifact:
            raise GraphError("V-15", f"edge {source}->{target} has handoff but no artifact")
        if artifact and not handoff:
            raise GraphError(
                "V-15", f"edge {source}->{target} carries artifact but no handoff"
            )
        if on in {"artifact_exists", "artifact_valid"} and not artifact:
            raise GraphError("V-15", f"edge {source}->{target} {on} needs artifact")
        if on in {"check_passed", "check_failed"} and not item.get("check"):
            raise GraphError("V-4", f"edge {source}->{target} {on} needs check")
        edges.append(
            Edge(
                source=str(source),
                target=str(target),
                on=str(on),
                artifact=str(artifact) if artifact else None,
                handoff=str(handoff) if handoff else None,
                check=str(item["check"]) if item.get("check") else None,
            )
        )
    return edges


def _stop(raw: Any) -> Stop:
    if not isinstance(raw, dict) or not raw.get("all_of"):
        raise GraphError("V-16", "stop.all_of is required")
    all_of = tuple(raw["all_of"])
    if not all_of:
        raise GraphError("V-16", "stop.all_of is empty")
    return Stop(all_of=all_of, failsafe=str(raw.get("failsafe") or "budget"))


def _check_ids(nodes: dict[str, Node]) -> None:
    for node in nodes.values():
        if node.type == "fanout":
            for part in node.partition:
                derived = f"{node.id}.{part.slot}"
                if derived in nodes:
                    raise GraphError(
                        "V-2",
                        f"declared id {derived!r} collides with fanout instance",
                    )


def _expand_fanouts(nodes: dict[str, Node], budget: Budget) -> dict[str, Node]:
    instances: dict[str, Node] = {}
    for node in nodes.values():
        if node.type != "fanout" or node.template is None:
            continue
        template = node.template
        for part in node.partition:
            inst_id = f"{node.id}.{part.slot}"
            instances[inst_id] = Node(
                id=inst_id,
                type="instance",
                adapter=template.get("adapter") or node.adapter,
                prompt=str(template.get("prompt") or node.prompt),
                cwd=template.get("cwd") or node.cwd,
                reads=part.reads,
                writes=part.writes,
                iters=node.iters,
                budget_units=node.budget_units,
                timeout_seconds=node.timeout_seconds,
                tools=node.tools,
                model=node.model,
                fanout_id=node.id,
                slot=part.slot,
            )
    return instances


def _check_id_collisions(nodes: dict[str, Node], instances: dict[str, Node]) -> None:
    for inst_id in instances:
        if inst_id in nodes:
            raise GraphError("V-2", f"instance id {inst_id!r} collides with a declared node")


def _check_prompts(nodes: dict[str, Node], baseline: Baseline, root: Path) -> None:
    missing = []
    if not (root / baseline.prompt).is_file():
        missing.append(f"baseline:{baseline.prompt}")
    for node in nodes.values():
        if node.type in {"agent", "join", "fanout"} and node.prompt:
            if not (root / node.prompt).is_file():
                missing.append(f"{node.id}:{node.prompt}")
    if missing:
        raise GraphError("V-3", f"prompt(s) not on disk: {', '.join(missing)}")


def _check_edges(
    nodes: dict[str, Node],
    instances: dict[str, Node],
    edges: list[Edge],
    artifacts: dict[str, ArtifactSpec],
    stop: Stop,
) -> None:
    for edge in edges:
        if edge.source not in nodes and edge.source not in instances:
            raise GraphError("V-4", f"edge from unknown node {edge.source!r}")
        if edge.target not in nodes and edge.target not in instances:
            raise GraphError("V-4", f"edge to unknown node {edge.target!r}")
        src = nodes.get(edge.source) or instances.get(edge.source)
        dst = nodes.get(edge.target) or instances.get(edge.target)
        assert src is not None and dst is not None
        if edge.on == "always":
            if src.type != "fanout" or dst.type != "join" or dst.from_fanout != src.id:
                raise GraphError(
                    "V-10",
                    f"always is only legal on fanout→its join, got {edge.source}->{edge.target}",
                )
        if edge.artifact:
            spec = artifacts.get(edge.artifact)
            if spec is None:
                raise GraphError("V-14", f"edge {edge.source}->{edge.target} artifact {edge.artifact!r} is not declared")
            if spec.owner != edge.source:
                raise GraphError(
                    "V-14",
                    f"edge {edge.source}->{edge.target} artifact owner {spec.owner!r} != from {edge.source!r}",
                )
            if edge.handoff == "structured":
                if spec.format != "structured" or not spec.sections:
                    raise GraphError(
                        "V-15",
                        f"structured handoff on {edge.artifact!r} needs format:structured and sections",
                    )
        if edge.on in {"check_passed", "check_failed"}:
            check_id = edge.check
            check = nodes.get(check_id or "")
            if check is None or check.type != "check":
                raise GraphError("V-16", f"edge names unknown check {check_id!r}")
        if src.type == "instance" and dst.type == "instance" and src.fanout_id == dst.fanout_id:
            raise GraphError("V-12", f"edge between instances of the same fanout: {edge.source}->{edge.target}")

    for check_id in stop.all_of:
        node = nodes.get(check_id)
        if node is None or node.type != "check":
            raise GraphError("V-16", f"stop.all_of references non-check {check_id!r}")


def _check_orphans_and_cycles(nodes: dict[str, Node], edges: list[Edge], stop: Stop) -> None:
    declared = set(nodes)
    incoming: dict[str, list[str]] = {i: [] for i in declared}
    outgoing: dict[str, list[str]] = {i: [] for i in declared}
    for edge in edges:
        if edge.source in declared and edge.target in declared:
            incoming[edge.target].append(edge.source)
            outgoing[edge.source].append(edge.target)

    sources = [i for i, preds in incoming.items() if not preds]
    if not sources:
        raise GraphError("V-5", "graph has no source node")
    if len(sources) != 1:
        extras = sorted(sources)
        raise GraphError("V-5", f"orphan sources (exactly one allowed): {extras}")

    # cycle: Kahn
    indeg = {i: len(incoming[i]) for i in declared}
    queue = [i for i, d in indeg.items() if d == 0]
    seen = 0
    while queue:
        cur = queue.pop()
        seen += 1
        for nxt in outgoing[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    if seen != len(declared):
        raise GraphError("V-6", "graph has a cycle; v1 is a strict DAG")

    source = sources[0]
    reach = set()
    stack = [source]
    while stack:
        cur = stack.pop()
        if cur in reach:
            continue
        reach.add(cur)
        stack.extend(outgoing[cur])
    missing_stop = [c for c in stop.all_of if c not in reach]
    if missing_stop:
        raise GraphError("V-7", f"stop unreachable from source {source}: {missing_stop}")
    orphans = [i for i in declared if i not in reach]
    if orphans:
        raise GraphError("V-5", f"orphan nodes: {orphans}")


def _check_parallelism(
    nodes: dict[str, Node], instances: dict[str, Node], edges: list[Edge]
) -> None:
    joins_by_fanout: dict[str, list[str]] = {}
    for node in nodes.values():
        if node.type == "join":
            if node.from_fanout not in nodes or nodes[node.from_fanout].type != "fanout":
                raise GraphError("V-11", f"join {node.id!r} from {node.from_fanout!r} is not a fanout")
            joins_by_fanout.setdefault(node.from_fanout, []).append(node.id)
            fanout = nodes[node.from_fanout]
            slots = [p.slot for p in fanout.partition]
            expected = _pair_owns(slots)
            if tuple(node.owns) != expected:
                raise GraphError(
                    "V-11",
                    f"join {node.id!r} owns {list(node.owns)} != exact pairs {list(expected)}",
                )
    for node in nodes.values():
        if node.type != "fanout":
            continue
        js = joins_by_fanout.get(node.id) or []
        if len(js) != 1:
            raise GraphError(
                "V-12b",
                f"fanout {node.id!r} must have exactly one join, has {js}",
            )

    by_fanout: dict[str, list[Node]] = {}
    for inst in instances.values():
        if inst.fanout_id:
            by_fanout.setdefault(inst.fanout_id, []).append(inst)
    for fanout_id, insts in by_fanout.items():
        for a in insts:
            for b in insts:
                if a.id == b.id:
                    continue
                for r in a.reads:
                    for w in b.writes:
                        if _globs_overlap_as_paths(r, w):
                            raise GraphError(
                                "V-12",
                                f"instance {a.id} reads {r!r} matches writes of {b.id} {w!r}",
                            )


def _pair_owns(slots: list[str]) -> tuple[str, ...]:
    ordered = sorted(slots)
    pairs = []
    for i, a in enumerate(ordered):
        for b in ordered[i + 1 :]:
            pairs.append(f"{a}-{b}")
    return tuple(pairs)


def _check_contracts(
    nodes: dict[str, Node],
    instances: dict[str, Node],
    artifacts: dict[str, ArtifactSpec],
    edges: list[Edge],
    stop: Stop,
    root: Path,
    baseline: Baseline,
) -> None:
    runnable: dict[str, Node] = {n.id: n for n in nodes.values() if n.type != "fanout"}
    runnable.update(instances)
    for spec in artifacts.values():
        if spec.owner not in runnable and spec.owner not in nodes:
            raise GraphError("V-13", f"artifact {spec.path!r} owner {spec.owner!r} is not a node")

    claimed: dict[str, str] = {}
    for node in runnable.values():
        for glob in node.writes:
            for path, spec in artifacts.items():
                if _path_matches_glob(path, glob):
                    prev = claimed.get(path)
                    if prev and prev != node.id:
                        raise GraphError(
                            "V-13",
                            f"artifact {path!r} claimed by both {prev} and {node.id}",
                        )
                    if spec.owner != node.id:
                        raise GraphError(
                            "V-13",
                            f"artifact {path!r} owner {spec.owner!r} != writer {node.id!r} via {glob}",
                        )
                    claimed[path] = node.id

    for node in nodes.values():
        if node.type != "check" or not node.run:
            continue
        exe = node.run[0]
        resolved = _resolve_exe(exe, root)
        if resolved is None or not os.access(resolved, os.X_OK):
            raise GraphError("V-17", f"check {node.id!r} run[0] {exe!r} missing or not executable")
        base = Path(exe).name
        if base in AGENT_DENYLIST:
            raise GraphError("V-18", f"check {node.id!r} run[0] basename {base!r} is an agent binary")
        if any(arg in PRINT_FLAGS for arg in node.run):
            raise GraphError("V-18", f"check {node.id!r} argv contains -p/--print")

    for spec in artifacts.values():
        cmd = spec.verify.get("cmd")
        if not cmd:
            continue
        if not isinstance(cmd, list) or not cmd:
            raise GraphError("V-17", f"artifact {spec.path!r} verify.cmd must be argv list")
        resolved = _resolve_exe(cmd[0], root)
        if resolved is None or not os.access(resolved, os.X_OK):
            raise GraphError(
                "V-17", f"artifact {spec.path!r} verify.cmd[0] {cmd[0]!r} missing or not executable"
            )
        if Path(cmd[0]).name in AGENT_DENYLIST or any(a in PRINT_FLAGS for a in cmd):
            raise GraphError("V-18", f"artifact {spec.path!r} verify.cmd looks like an agent")


def _resolve_exe(exe: str, root: Path) -> Path | None:
    path = Path(exe)
    if path.is_absolute() and path.is_file():
        return path
    cand = root / exe
    if cand.is_file():
        return cand
    return None


def _check_partition_writes(nodes: dict[str, Node]) -> None:
    for node in nodes.values():
        if node.type != "fanout":
            continue
        prefixes: list[tuple[str, str, str]] = []
        for part in node.partition:
            for glob in part.writes:
                prefix = write_glob_prefix(glob)
                if prefix is None:
                    raise GraphError(
                        "V-21",
                        f"fanout {node.id}.{part.slot} writes glob {glob!r} is not "
                        f"<prefix>, <prefix>/** or <prefix>/*.<ext>",
                    )
                prefixes.append((node.id + "." + part.slot, glob, prefix))
        for i, (ia, ga, pa) in enumerate(prefixes):
            for ib, gb, pb in prefixes[i + 1 :]:
                if ia == ib:
                    continue
                if _component_prefix(pa, pb) or _component_prefix(pb, pa):
                    raise GraphError(
                        "V-22",
                        f"overlapping writes {ia} {ga!r} and {ib} {gb!r} "
                        f"(prefixes {pa!r}, {pb!r})",
                    )


def write_glob_prefix(glob: str) -> str | None:
    if "*" not in glob and "?" not in glob and "[" not in glob:
        return glob.rstrip("/")
    if glob.endswith("/**") and "*" not in glob[:-3] and "?" not in glob[:-3]:
        return glob[:-3].rstrip("/")
    # <prefix>/*.<ext>
    parts = glob.split("/")
    if len(parts) >= 2 and parts[-1].startswith("*.") and "*" not in "/".join(parts[:-1]):
        ext = parts[-1][2:]
        if ext and "*" not in ext and "?" not in ext:
            return "/".join(parts[:-1])
    return None


def _component_prefix(a: str, b: str) -> bool:
    a_parts = Path(a).parts
    b_parts = Path(b).parts
    if not a_parts or len(a_parts) > len(b_parts):
        return False
    return b_parts[: len(a_parts)] == a_parts


def _path_matches_glob(path: str, glob: str) -> bool:
    prefix = write_glob_prefix(glob)
    if prefix is None:
        return path == glob
    if glob == prefix:
        return path == glob
    if glob.endswith("/**"):
        return path == prefix or _component_prefix(prefix, path)
    if "/*." in glob:
        ext = glob.rsplit("*.", 1)[-1]
        return Path(path).parent.as_posix() == prefix and path.endswith("." + ext)
    return path == glob or _component_prefix(prefix, path)


def _globs_overlap_as_paths(read_glob: str, write_glob: str) -> bool:
    """True when a read glob could name a file covered by a write glob."""
    wr = write_glob_prefix(write_glob)
    rd = write_glob_prefix(read_glob)
    if wr is None and rd is None:
        return read_glob == write_glob
    if wr and rd:
        return wr == rd or _component_prefix(wr, rd) or _component_prefix(rd, wr)
    if wr and read_glob == wr:
        return True
    return False


def pair_owns(slots: list[str]) -> tuple[str, ...]:
    return _pair_owns(list(slots))
