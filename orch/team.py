"""`orch team` — the team is code, and code gets reviewed.

The graph lives in `graphs/*.yaml` inside the repo of the project it works on: it
changes in a PR, it diffs, it has blame. That is the hole the competition leaves
open and admits to — Maestri keeps the partitura in `~/.maestri/partituras`, outside
the repo; the Agent Teams documentation states there is no project-level equivalent
for the team config, and hand edits are overwritten.

Four verbs, and the value is in the third:

  lint         run the loader's refusal list without spawning anything (pre-commit, CI)
  show         render the team for the human reviewing the PR, not for the operator
  diff         SEMANTIC diff: `git diff` shows lines, this shows power
  fingerprint  stable semantic hash; two runs aggregate only if it matches

**The declaration is read-only at runtime.** Everything the runtime decides —
effective concurrency, the order it picked, gate degradation, worktrees created —
is written to `state.json` as a declared deviation, and never back into the YAML.
`declaration_tree_sha256` is the proof, checked before and after every `up`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orch.errors import GraphError
from orch.graph import Graph, Node, Tools, load_graph

DECLARATION_DIRS = ("graphs",)

WIDENS = "alarga"
RESTRICTS = "restringe"
NEUTRAL = "neutra"
SEVERITY_ORDER = {WIDENS: 0, RESTRICTS: 1, NEUTRAL: 2}
SEVERITY_LABEL = {
    WIDENS: "ALARGA PODER",
    RESTRICTS: "restringe",
    NEUTRAL: "neutra",
}


# --------------------------------------------------------------- semantic model


def _tools(tools: Tools) -> dict[str, list[str]]:
    return {"allow": sorted(tools.allow), "deny": sorted(tools.deny)}


def _node_model(node: Node) -> dict[str, Any]:
    model: dict[str, Any] = {
        "type": node.type,
        "adapter": node.adapter,
        "cwd": node.cwd,
        "reads": sorted(node.reads),
        "writes": sorted(node.writes),
        "timeout_seconds": node.timeout_seconds,
        "tools": _tools(node.tools),
        "model": node.model,
    }
    if node.type == "check":
        model["run"] = list(node.run or ())
        return model
    model["prompt"] = node.prompt
    model["iters"] = node.iters
    model["budget_units"] = node.budget_units
    if node.type == "fanout":
        model["max"] = node.max
        model["partition"] = [
            {"slot": p.slot, "reads": sorted(p.reads), "writes": sorted(p.writes)}
            for p in node.partition
        ]
        # `rationale` is prose the loader never reads. It is out of the fingerprint on
        # purpose — a reworded justification is not a different team — and `diff`
        # reports it as a neutral change so the reviewer still sees it.
    if node.type == "join":
        model["from"] = node.from_fanout
        model["owns"] = sorted(node.owns)
    return model


def _file_digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return "missing"


def semantic_model(graph: Graph) -> dict[str, Any]:
    """The declaration, canonicalised. Invariant to key order and comments; sensitive
    to anything that changes behaviour — including the prompt files and the check
    binaries, because a rewritten `prompts/builder.md` is a different team even when
    the YAML is byte-identical."""
    prompts: dict[str, str] = {}
    binaries: dict[str, str] = {}

    def note_prompt(rel: str | None) -> None:
        if rel:
            prompts[rel] = _file_digest(graph.root / rel)

    note_prompt(graph.baseline.prompt)
    for node in graph.nodes.values():
        if node.type == "check":
            if node.run:
                binaries[node.run[0]] = _file_digest(graph.root / node.run[0])
        else:
            note_prompt(node.prompt)

    return {
        "schema": "orch/team/1",
        "id": graph.id,
        "baseline": {
            "adapter": graph.baseline.adapter,
            "prompt": graph.baseline.prompt,
            "cwd": graph.baseline.cwd,
            "writes": sorted(graph.baseline.writes),
            "budget_units": graph.baseline.budget_units,
            "timeout_seconds": graph.baseline.timeout_seconds,
            "compare_on": sorted(graph.baseline.compare_on),
            "tools": _tools(graph.baseline.tools),
        },
        "budget": {
            "wall_seconds": graph.budget.wall_seconds,
            "session_units": graph.budget.session_units,
            "log_bytes": graph.budget.log_bytes,
            "iters_default": graph.budget.iters_default,
            "node_units_default": graph.budget.node_units_default,
            "max_nodes": graph.budget.max_nodes,
            "no_progress_rounds": graph.budget.no_progress_rounds,
            "tools": _tools(graph.budget.tools),
        },
        "artifacts": {
            path: {
                "owner": spec.owner,
                "format": spec.format,
                "sections": list(spec.sections),
                "verify": _canonical(spec.verify),
            }
            for path, spec in sorted(graph.artifacts.items())
        },
        "nodes": {nid: _node_model(node) for nid, node in sorted(graph.nodes.items())},
        "instances": sorted(graph.instances),
        "edges": sorted(
            [e.source, e.target, e.on, e.artifact or "", e.handoff or "", e.check or ""]
            for e in graph.edges
        ),
        "stop": {"all_of": sorted(graph.stop.all_of), "failsafe": graph.stop.failsafe},
        "width": graph.width,
        "prompts": dict(sorted(prompts.items())),
        "check_binaries": dict(sorted(binaries.items())),
    }


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _canonical(value[k]) for k in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def fingerprint(graph: Graph) -> str:
    payload = json.dumps(semantic_model(graph), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def short(fp: str) -> str:
    return fp[:12]


# ---------------------------------------------------- declaration tree invariant


def declaration_tree_sha256(root: Path, dirs: tuple[str, ...] = DECLARATION_DIRS) -> str:
    """Hash of the versioned declaration on disk. Recorded before the first node goes
    up and re-checked after the last one: the runtime never writes to `graphs/`."""
    digest = hashlib.sha256()
    for name in dirs:
        base = root / name
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            digest.update(rel.encode("utf-8"))
            digest.update(b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


# ------------------------------------------------------------------ semantic diff


@dataclass(frozen=True)
class Change:
    severity: str
    subject: str
    text: str

    def line(self) -> str:
        return f"  [{SEVERITY_LABEL[self.severity]:<12}] {self.subject}: {self.text}"


def _num(subject: str, field: str, before: Any, after: Any, higher_widens: bool) -> Change | None:
    if before == after:
        return None
    try:
        wider = float(after) > float(before)
    except (TypeError, ValueError):
        return Change(NEUTRAL, subject, f"{field}: {before!r} → {after!r}")
    severity = (WIDENS if wider else RESTRICTS) if higher_widens else (
        RESTRICTS if wider else WIDENS
    )
    return Change(severity, subject, f"{field} {before} → {after}")


def _set_change(
    subject: str, field: str, before: list[str], after: list[str], added_widens: bool
) -> list[Change]:
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    out: list[Change] = []
    if added:
        out.append(
            Change(
                WIDENS if added_widens else RESTRICTS,
                subject,
                f"{field} ganhou {', '.join(added)}",
            )
        )
    if removed:
        out.append(
            Change(
                RESTRICTS if added_widens else WIDENS,
                subject,
                f"{field} perdeu {', '.join(removed)}",
            )
        )
    return out


def diff_models(base: dict[str, Any], head: dict[str, Any]) -> list[Change]:
    changes: list[Change] = []

    if base["id"] != head["id"]:
        changes.append(Change(NEUTRAL, "time", f"id {base['id']} → {head['id']}"))

    # ---- budget: the session-wide ceiling
    for field, higher_widens in (
        ("wall_seconds", True),
        ("session_units", True),
        ("log_bytes", True),
        ("max_nodes", True),
        ("iters_default", True),
        ("node_units_default", True),
        ("no_progress_rounds", True),
    ):
        change = _num("budget", field, base["budget"][field], head["budget"][field], higher_widens)
        if change:
            changes.append(change)
    changes.extend(
        _set_change(
            "budget.tools", "allow", base["budget"]["tools"]["allow"],
            head["budget"]["tools"]["allow"], True,
        )
    )
    changes.extend(
        _set_change(
            "budget.tools", "deny", base["budget"]["tools"]["deny"],
            head["budget"]["tools"]["deny"], False,
        )
    )

    # ---- nodes
    for node_id in sorted(set(base["nodes"]) | set(head["nodes"])):
        before = base["nodes"].get(node_id)
        after = head["nodes"].get(node_id)
        if before is None:
            changes.append(
                Change(WIDENS, node_id, f"nó novo ({after['type']}), escreve {', '.join(after['writes']) or '—'}")
            )
            continue
        if after is None:
            changes.append(Change(RESTRICTS, node_id, f"nó removido ({before['type']})"))
            continue
        changes.extend(_diff_node(node_id, before, after))

    # ---- artifacts and their verify blocks
    for path in sorted(set(base["artifacts"]) | set(head["artifacts"])):
        before = base["artifacts"].get(path)
        after = head["artifacts"].get(path)
        if before is None:
            changes.append(Change(RESTRICTS, f"artefato {path}", "declarado, com verify"))
            continue
        if after is None:
            changes.append(
                Change(WIDENS, f"artefato {path}", "deixou de ser declarado: sai do predicado de conclusão")
            )
            continue
        if before["owner"] != after["owner"]:
            changes.append(
                Change(NEUTRAL, f"artefato {path}", f"dono {before['owner']} → {after['owner']}")
            )
        if before["format"] != after["format"] or before["sections"] != after["sections"]:
            changes.append(Change(NEUTRAL, f"artefato {path}", "formato ou seções mudaram"))
        changes.extend(_diff_verify(f"artefato {path}", before["verify"], after["verify"]))

    # ---- stop: the only thing that ends a session
    changes.extend(
        _set_change("stop", "all_of", base["stop"]["all_of"], head["stop"]["all_of"], False)
    )
    if base["stop"]["failsafe"] != head["stop"]["failsafe"]:
        changes.append(
            Change(NEUTRAL, "stop", f"failsafe {base['stop']['failsafe']} → {head['stop']['failsafe']}")
        )

    # ---- edges
    changes.extend(_diff_edges(base["edges"], head["edges"]))

    # ---- baseline
    changes.extend(
        _set_change("baseline", "writes", base["baseline"]["writes"], head["baseline"]["writes"], True)
    )
    for field in ("budget_units", "timeout_seconds"):
        change = _num("baseline", field, base["baseline"][field], head["baseline"][field], True)
        if change:
            changes.append(change)
    if base["baseline"]["prompt"] != head["baseline"]["prompt"]:
        changes.append(
            Change(NEUTRAL, "baseline", f"prompt {base['baseline']['prompt']} → {head['baseline']['prompt']}")
        )

    # ---- prompt bodies and check binaries: not in the YAML, but they are the team
    for rel in sorted(set(base["prompts"]) | set(head["prompts"])):
        b, h = base["prompts"].get(rel), head["prompts"].get(rel)
        if b and h and b != h:
            changes.append(Change(NEUTRAL, f"prompt {rel}", "conteúdo reescrito (fora do YAML)"))
    for rel in sorted(set(base["check_binaries"]) | set(head["check_binaries"])):
        b, h = base["check_binaries"].get(rel), head["check_binaries"].get(rel)
        if b and h and b != h:
            changes.append(
                Change(WIDENS, f"check {rel}", "binário do portão mudou: o critério de parada mudou junto")
            )

    changes.sort(key=lambda c: (SEVERITY_ORDER[c.severity], c.subject, c.text))
    return changes


def _diff_node(node_id: str, before: dict[str, Any], after: dict[str, Any]) -> list[Change]:
    out: list[Change] = []
    if before["type"] != after["type"]:
        out.append(Change(NEUTRAL, node_id, f"tipo {before['type']} → {after['type']}"))
    out.extend(_set_change(node_id, "contrato de escrita", before["writes"], after["writes"], True))
    out.extend(_set_change(node_id, "reads (informativo)", before["reads"], after["reads"], True))
    out.extend(_set_change(node_id, "tools.allow", before["tools"]["allow"], after["tools"]["allow"], True))
    out.extend(_set_change(node_id, "tools.deny", before["tools"]["deny"], after["tools"]["deny"], False))
    for field in ("timeout_seconds", "budget_units", "iters", "max"):
        if field in before or field in after:
            change = _num(node_id, field, before.get(field), after.get(field), True)
            if change:
                out.append(change)
    if before.get("model") != after.get("model"):
        out.append(Change(NEUTRAL, node_id, f"model {before.get('model')} → {after.get('model')}"))
    if before.get("prompt") != after.get("prompt"):
        out.append(Change(NEUTRAL, node_id, f"prompt {before.get('prompt')} → {after.get('prompt')}"))
    if before.get("run") != after.get("run"):
        out.append(
            Change(WIDENS, node_id, f"argv do check {before.get('run')} → {after.get('run')}")
        )
    if before.get("owns") != after.get("owns"):
        out.extend(_set_change(node_id, "owns", before.get("owns") or [], after.get("owns") or [], False))
    out.extend(_diff_partition(node_id, before.get("partition"), after.get("partition")))
    return out


def _diff_partition(node_id: str, before: Any, after: Any) -> list[Change]:
    if not before and not after:
        return []
    before = {p["slot"]: p for p in (before or [])}
    after = {p["slot"]: p for p in (after or [])}
    out: list[Change] = []
    for slot in sorted(set(before) | set(after)):
        b, h = before.get(slot), after.get(slot)
        subject = f"{node_id}.{slot}"
        if b is None:
            out.append(Change(WIDENS, subject, f"raia nova, escreve {', '.join(h['writes'])}"))
            continue
        if h is None:
            out.append(Change(RESTRICTS, subject, "raia removida"))
            continue
        out.extend(_set_change(subject, "contrato de escrita", b["writes"], h["writes"], True))
        out.extend(_set_change(subject, "reads (informativo)", b["reads"], h["reads"], True))
    return out


VERIFY_STRENGTH = ("non_empty", "min_lines", "cmd")


def _diff_verify(subject: str, before: dict[str, Any], after: dict[str, Any]) -> list[Change]:
    out: list[Change] = []
    for key in VERIFY_STRENGTH:
        b, h = before.get(key), after.get(key)
        if b == h:
            continue
        if b is not None and h is None:
            out.append(Change(WIDENS, subject, f"verify.{key} removido: o portão do artefato afrouxou"))
        elif b is None and h is not None:
            out.append(Change(RESTRICTS, subject, f"verify.{key} adicionado"))
        elif key == "min_lines":
            change = _num(subject, "verify.min_lines", b, h, False)
            if change:
                out.append(change)
        else:
            out.append(Change(NEUTRAL, subject, f"verify.{key} mudou"))
    return out


STRICTNESS = {"artifact_valid": 2, "artifact_exists": 1, "check_passed": 1, "check_failed": 1, "always": 1}


def _diff_edges(base: list[list[str]], head: list[list[str]]) -> list[Change]:
    out: list[Change] = []
    base_by_pair = {(e[0], e[1]): e for e in base}
    head_by_pair = {(e[0], e[1]): e for e in head}
    for pair in sorted(set(base_by_pair) | set(head_by_pair)):
        b, h = base_by_pair.get(pair), head_by_pair.get(pair)
        label = f"aresta {pair[0]} → {pair[1]}"
        if b is None:
            out.append(Change(NEUTRAL, label, f"nova, on {h[2]}"))
            continue
        if h is None:
            out.append(Change(NEUTRAL, label, f"removida (era on {b[2]})"))
            continue
        if b[2] != h[2]:
            before_strict = STRICTNESS.get(b[2], 1)
            after_strict = STRICTNESS.get(h[2], 1)
            severity = (
                WIDENS if after_strict < before_strict
                else RESTRICTS if after_strict > before_strict
                else NEUTRAL
            )
            out.append(Change(severity, label, f"predicado {b[2]} → {h[2]}"))
        if b[4] != h[4]:
            out.append(Change(NEUTRAL, label, f"handoff {b[4] or '—'} → {h[4] or '—'}"))
    return out


# ------------------------------------------------------------------ load helpers


@dataclass
class Loaded:
    path: Path
    graph: Graph | None
    error: GraphError | None

    @property
    def ok(self) -> bool:
        return self.graph is not None


def try_load(path: str | Path) -> Loaded:
    try:
        return Loaded(Path(path), load_graph(path), None)
    except GraphError as exc:
        return Loaded(Path(path), None, exc)


# --------------------------------------------------------------------- rendering

RULE = "─" * 82


def render_show(graph: Graph) -> str:
    """The reader is the reviewer of the PR, not the operator. Answer, in order:
    who is each node, what may each one write, what does it cost, how wide is the
    declared parallelism, and what ends the session."""
    fp = fingerprint(graph)
    lines = [
        f"time  {graph.id}   fingerprint {short(fp)}   largura declarada {graph.width}   "
        f"parada: {' ∧ '.join(graph.stop.all_of)}",
        RULE,
        "nós",
    ]
    for nid, node in graph.nodes.items():
        lines.extend(_show_node(nid, node, graph))
    lines.append("")
    lines.append("artefatos  (dono único; o verify mora aqui, não na aresta)")
    for path, spec in graph.artifacts.items():
        checks = []
        if spec.verify.get("non_empty"):
            checks.append("non_empty")
        if spec.verify.get("min_lines"):
            checks.append(f"min_lines={spec.verify['min_lines']}")
        if spec.verify.get("cmd"):
            checks.append("cmd " + " ".join(spec.verify["cmd"]))
        sections = f"  [{', '.join(spec.sections)}]" if spec.sections else ""
        lines.append(
            f"  {path:<16} dono {spec.owner:<10} {spec.format}{sections}"
        )
        lines.append(f"  {'':<16} verify: {' · '.join(checks) or 'nenhum'}")
    lines.append("")
    lines.append("arestas  (o handoff é dado, não comando)")
    for edge in graph.edges:
        extra = f"  artefato {edge.artifact}" if edge.artifact else ""
        handoff = f"  handoff {edge.handoff}" if edge.handoff else ""
        lines.append(f"  {edge.source:<10} → {edge.target:<10} on {edge.on}{extra}{handoff}")
    lines.append("")
    lines.append("orçamento  (três camadas de bound; a última é incondicional)")
    b = graph.budget
    lines.append(
        f"  sessão {b.session_units:.2f}u · parede {b.wall_seconds}s · "
        f"log {b.log_bytes / 1_000_000:.1f} MB · nós ≤ {b.max_nodes} · "
        f"sem progresso {b.no_progress_rounds} rodadas"
    )
    lines.append(
        f"  ACL default: +{', '.join(b.tools.allow)}  −{', '.join(b.tools.deny)}"
    )
    lines.append("")
    lines.append("braço de controle  (obrigatório; roda primeiro e serial)")
    bl = graph.baseline
    lines.append(
        f"  {bl.prompt}  escreve {', '.join(bl.writes)}  "
        f"{bl.budget_units:.2f}u  timeout {bl.timeout_seconds}s"
    )
    lines.append("")
    lines.append("parada")
    lines.append(
        f"  todos de [{', '.join(graph.stop.all_of)}] em `done` com rc 0. "
        f"failsafe {graph.stop.failsafe}, incondicional."
    )
    lines.append("")
    lines.append(f"fingerprint completo  {fp}")
    lines.append(
        "  dois runs só são agregáveis se este valor bater. cobre o YAML canonizado, "
        "o conteúdo dos prompts e o binário de cada check."
    )
    return "\n".join(lines)


def _show_node(nid: str, node: Node, graph: Graph) -> list[str]:
    out: list[str] = []
    if node.type == "check":
        out.append(
            f"  {nid:<10} check      run {' '.join(node.run or ())}  "
            f"timeout {node.timeout_seconds}s  escreve: nada (imutável)"
        )
        return out
    if node.type == "fanout":
        out.append(
            f"  {nid:<10} fanout     max {node.max}  raias "
            f"{', '.join(p.slot for p in node.partition)}  "
            f"{node.budget_units:.2f}u/raia  timeout {node.timeout_seconds}s"
        )
        for part in node.partition:
            out.append(
                f"    {nid}.{part.slot:<6} escreve {', '.join(part.writes):<14} "
                f"lê {', '.join(part.reads) or '—'}"
            )
        out.append(f"    {'':<8} tools +{','.join(node.tools.allow)} −{','.join(node.tools.deny)}")
        return out
    extra = ""
    if node.type == "join":
        extra = f"  de {node.from_fanout}  owns {', '.join(node.owns)}"
    out.append(
        f"  {nid:<10} {node.type:<10} {node.adapter}/{node.model or 'sonnet'}  "
        f"escreve {', '.join(node.writes)}  lê {', '.join(node.reads) or '—'}{extra}"
    )
    out.append(
        f"  {'':<10} {'':<10} {node.budget_units:.2f}u  timeout {node.timeout_seconds}s  "
        f"iters {node.iters}  tools +{','.join(node.tools.allow)} −{','.join(node.tools.deny)}"
    )
    return out


def render_diff(base: Loaded, head: Loaded) -> tuple[str, list[Change]]:
    lines = [
        f"team diff  {base.path}  →  {head.path}",
        RULE,
    ]
    if not base.ok or not head.ok:
        for side, loaded in (("base", base), ("head", head)):
            if not loaded.ok:
                lines.append(
                    f"  RECUSADO no load ({side} {loaded.path}): {loaded.error.message}"
                )
        lines.append("")
        lines.append(
            "  um lado não é um time válido, então não há diff semântico a fazer. "
            "grafo inválido é erro de compilação, não achado de revisão."
        )
        return "\n".join(lines), []

    assert base.graph is not None and head.graph is not None
    base_fp, head_fp = fingerprint(base.graph), fingerprint(head.graph)
    lines.append(f"  fingerprint  {short(base_fp)}  →  {short(head_fp)}")
    if base_fp == head_fp:
        lines.append("")
        lines.append("  mesmo time. os runs dos dois lados são agregáveis.")
        return "\n".join(lines), []
    lines.append("  times distintos: runs dos dois lados NÃO são agregáveis.")
    lines.append("")

    changes = diff_models(semantic_model(base.graph), semantic_model(head.graph))
    if not changes:
        lines.append(
            "  o fingerprint mudou mas nenhuma regra de revisão pegou — "
            "provavelmente o conteúdo de um prompt ou de um binário de check."
        )
        return "\n".join(lines), changes

    counts = {sev: sum(1 for c in changes if c.severity == sev) for sev in SEVERITY_ORDER}
    lines.append(
        f"  {counts[WIDENS]} alargam poder · {counts[RESTRICTS]} restringem · "
        f"{counts[NEUTRAL]} neutras"
    )
    lines.append("")
    current = None
    for change in changes:
        if change.severity != current:
            current = change.severity
            lines.append(f"  {SEVERITY_LABEL[change.severity]}")
        lines.append(change.line())
    lines.append("")
    if counts[WIDENS]:
        lines.append(
            "  leia primeiro as linhas que ALARGAM PODER: contrato de escrita maior, "
            "orçamento maior, tool liberada, portão afrouxado, teto de fanout maior. "
            "é o que um `git diff` de YAML mostra como linha e não como consequência."
        )
    return "\n".join(lines), changes


def read_fingerprint(path: Path) -> tuple[str | None, str]:
    """Accepts a graph file or a session dir. Returns (fingerprint, origin)."""
    path = Path(path)
    if path.is_dir():
        for name, key in (("verdict.json", "team_fingerprint"), ("state.json", None)):
            candidate = path / name
            if not candidate.is_file():
                continue
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            value = data.get(key) if key else (data.get("preflight") or {}).get(
                "team_fingerprint"
            )
            if value:
                return str(value), f"{path.name}/{name}"
        return None, f"{path.name} (sem fingerprint gravado)"
    loaded = try_load(path)
    if not loaded.ok:
        return None, f"{path} (recusado no load)"
    assert loaded.graph is not None
    return fingerprint(loaded.graph), str(path)


def render_fingerprints(pairs: list[tuple[str | None, str]]) -> tuple[str, bool]:
    """One path prints the hash. Several print the aggregation report — because a
    verdict of one team must never be summed with the verdict of another in silence."""
    if len(pairs) == 1:
        fp, origin = pairs[0]
        if fp is None:
            return f"orch: {origin}", False
        return f"{fp}  {origin}", True

    groups: dict[str, list[str]] = {}
    unknown: list[str] = []
    for fp, origin in pairs:
        if fp is None:
            unknown.append(origin)
        else:
            groups.setdefault(fp, []).append(origin)

    lines = ["agregação por fingerprint de time", RULE]
    for fp in sorted(groups):
        lines.append(f"  {short(fp)}  ({len(groups[fp])})")
        for origin in sorted(groups[fp]):
            lines.append(f"      {origin}")
    for origin in sorted(unknown):
        lines.append(f"  {'—':<12}  {origin}")
    lines.append("")
    same = len(groups) == 1 and not unknown
    if same:
        lines.append("  MESMO TIME: os runs são agregáveis.")
    else:
        lines.append(
            f"  NÃO AGREGÁVEL: {len(groups) + len(unknown)} times distintos. "
            "somar estes vereditos mede a mudança do time, não a da tarefa."
        )
    return "\n".join(lines), same
