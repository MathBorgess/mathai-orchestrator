"""`orch team` — the team is code, and code gets reviewed.

The load-bearing test is `test_runtime_never_writes_the_declaration`: it hashes the
`graphs/` tree before and after a full `up`, including the path where the gate
degraded. If anyone ever implements topology mutation, this breaks and they are
forced to decide on purpose — which is the point.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orch import team as team_mod
from orch.cli import main
from orch.errors import EXIT_GRAPH, EXIT_OK
from orch.graph import load_graph
from tests.conftest import set_knobs

REPO = Path(__file__).resolve().parents[1]
V1 = REPO / "graphs" / "v1.yaml"


def _variant(repo: Path, **edits: str) -> Path:
    """A copy of v1.yaml with textual edits, still inside a repo with prompts/ and bin/."""
    path = repo / "graphs" / "v1.yaml"
    text = path.read_text(encoding="utf-8")
    for old, new in edits.items():
        assert old in text, f"anchor not found: {old!r}"
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")
    return path


# ------------------------------------------------------------------------ lint


def test_lint_accepts_v1_and_refuses_v0(capsys) -> None:
    assert main(["team", "lint", str(V1)]) == EXIT_OK
    assert "ok " in capsys.readouterr().out
    assert main(["team", "lint", str(REPO / "graphs" / "v0.yaml")]) == EXIT_GRAPH
    assert "RECUSA" in capsys.readouterr().err


def test_lint_takes_many_graphs_and_reports_the_worst(capsys) -> None:
    code = main(["team", "lint", str(V1), str(REPO / "graphs" / "v0.yaml")])
    assert code == EXIT_GRAPH  # one bad graph fails the whole hook
    captured = capsys.readouterr()
    assert "ok " in captured.out and "RECUSA" in captured.err


# ------------------------------------------------------------------------ show


def test_show_answers_what_a_reviewer_asks(capsys) -> None:
    assert main(["team", "show", str(V1)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "escreve handoff.md" in out          # who may write what
    assert "out/a.md" in out and "out/b.md" in out
    assert "timeout 600s" in out                # what it costs
    assert "largura declarada 3" in out         # declared parallelism
    assert "parada: gate ∧ contract" in out     # what ends the session
    assert "verify: non_empty · min_lines=12 · cmd" in out
    assert "owns a-b, a-c, b-c" in out
    assert "fingerprint" in out


# ------------------------------------------------------------- fingerprint


def test_fingerprint_is_invariant_to_key_order_and_comments(
    graph_repo: Path, tmp_path: Path
) -> None:
    before = team_mod.fingerprint(load_graph(graph_repo / "graphs" / "v1.yaml"))
    path = graph_repo / "graphs" / "v1.yaml"
    text = path.read_text(encoding="utf-8")
    text = "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#")
    )
    text = text.replace(
        "  - {from: scout, to: build,    on: artifact_valid, artifact: handoff.md,    handoff: structured}",
        "  - {to: build, artifact: handoff.md, from: scout, handoff: structured, on: artifact_valid}",
    )
    path.write_text(text + "\n# um comentário novo no fim\n", encoding="utf-8")
    assert team_mod.fingerprint(load_graph(path)) == before


def test_fingerprint_moves_when_behaviour_moves(graph_repo: Path) -> None:
    path = graph_repo / "graphs" / "v1.yaml"
    before = team_mod.fingerprint(load_graph(path))
    _variant(graph_repo, **{"  session_units: 6.00": "  session_units: 12.00"})
    assert team_mod.fingerprint(load_graph(path)) != before


def test_fingerprint_moves_when_a_prompt_body_is_rewritten(graph_repo: Path) -> None:
    """Same YAML, different team: a rewritten prompt is not the same agent, and two
    runs across that edit must not be aggregated in silence."""
    path = graph_repo / "graphs" / "v1.yaml"
    before = team_mod.fingerprint(load_graph(path))
    prompt = graph_repo / "prompts" / "builder.md"
    prompt.write_text(prompt.read_text() + "\nEscreva em inglês.\n", encoding="utf-8")
    assert team_mod.fingerprint(load_graph(path)) != before


def test_fingerprint_ignores_the_rationale_prose(graph_repo: Path) -> None:
    """The loader never reads `rationale`; a reworded justification is not a
    different team. `diff` still surfaces it — the fingerprint does not."""
    path = graph_repo / "graphs" / "v1.yaml"
    before = team_mod.fingerprint(load_graph(path))
    _variant(
        graph_repo,
        **{"      P1 handoff: cada instância recebe handoff.md": "      P1 handoff: reescrito, mesma decisão; cada instância recebe handoff.md"},
    )
    assert team_mod.fingerprint(load_graph(path)) == before


def test_fingerprint_report_refuses_to_aggregate_two_teams(
    graph_repo: Path, tmp_path: Path, capsys
) -> None:
    other = tmp_path / "other"
    (other / "graphs").mkdir(parents=True)
    (other / "prompts").mkdir(parents=True)
    for prompt in (graph_repo / "prompts").glob("*.md"):
        (other / "prompts" / prompt.name).write_bytes(prompt.read_bytes())
    (other / "graphs" / "v1.yaml").write_text(
        (graph_repo / "graphs" / "v1.yaml").read_text().replace(
            "  session_units: 6.00", "  session_units: 12.00"
        ),
        encoding="utf-8",
    )
    code = main(
        [
            "team",
            "fingerprint",
            str(graph_repo / "graphs" / "v1.yaml"),
            str(other / "graphs" / "v1.yaml"),
            "--require-same",
        ]
    )
    out = capsys.readouterr().out
    assert code == EXIT_GRAPH
    assert "NÃO AGREGÁVEL" in out
    assert "times distintos" in out


def test_fingerprint_report_says_same_team_when_it_is(graph_repo: Path, capsys) -> None:
    path = str(graph_repo / "graphs" / "v1.yaml")
    assert main(["team", "fingerprint", path, path, "--require-same"]) == EXIT_OK
    assert "MESMO TIME" in capsys.readouterr().out


# ------------------------------------------------------------------------ diff


def _diff(base: Path, head: Path, capsys, *extra: str) -> tuple[int, str]:
    code = main(["team", "diff", str(base), str(head), *extra])
    return code, capsys.readouterr().out


def test_diff_reads_the_four_sentences_git_diff_cannot(
    graph_repo: Path, tmp_path: Path, capsys
) -> None:
    base = graph_repo / "graphs" / "v1.yaml"
    head_repo = tmp_path / "head"
    (head_repo / "graphs").mkdir(parents=True)
    for sub in ("prompts", "bin"):
        (head_repo / sub).mkdir(parents=True)
        for item in (graph_repo / sub).iterdir():
            dst = head_repo / sub / item.name
            dst.write_bytes(item.read_bytes())
            dst.chmod(0o755)
    (head_repo / "graphs" / "v1.yaml").write_text(
        base.read_text()
        .replace('writes: ["out/a.md"]', 'writes: ["out/a.md", "src/**"]')
        .replace("  all_of: [gate, contract]", "  all_of: [gate]")
        .replace("  session_units: 6.00", "  session_units: 12.00")
        .replace("      min_lines: 20\n", ""),
        encoding="utf-8",
    )
    code, out = _diff(base, head_repo / "graphs" / "v1.yaml", capsys)
    assert code == EXIT_OK
    assert "NÃO são agregáveis" in out
    assert "ALARGA PODER" in out
    assert "build.a: contrato de escrita ganhou src/**" in out
    assert "stop: all_of perdeu contract" in out
    assert "budget: session_units 6.0 → 12.0" in out
    assert "verify.min_lines removido" in out
    assert "0 restringem" in out


def test_diff_marks_restrictions_as_restrictions(
    graph_repo: Path, tmp_path: Path, capsys
) -> None:
    base = graph_repo / "graphs" / "v1.yaml"
    head_repo = tmp_path / "head"
    (head_repo / "graphs").mkdir(parents=True)
    for sub in ("prompts", "bin"):
        (head_repo / sub).mkdir(parents=True)
        for item in (graph_repo / sub).iterdir():
            dst = head_repo / sub / item.name
            dst.write_bytes(item.read_bytes())
            dst.chmod(0o755)
    (head_repo / "graphs" / "v1.yaml").write_text(
        base.read_text()
        .replace("  session_units: 6.00", "  session_units: 3.00")
        .replace("    timeout_seconds: 600", "    timeout_seconds: 300"),
        encoding="utf-8",
    )
    code, out = _diff(base, head_repo / "graphs" / "v1.yaml", capsys)
    assert code == EXIT_OK
    assert "restringe" in out
    assert "session_units 6.0 → 3.0" in out
    assert "0 alargam poder" in out


def test_diff_same_team_says_aggregable(graph_repo: Path, capsys) -> None:
    path = graph_repo / "graphs" / "v1.yaml"
    code, out = _diff(path, path, capsys)
    assert code == EXIT_OK
    assert "mesmo time" in out
    assert "agregáveis" in out


def test_diff_on_a_refused_head_is_a_refusal_not_a_finding(
    graph_repo: Path, tmp_path: Path, capsys
) -> None:
    """A partition that stopped being disjoint is not a review finding: it is a
    compile error, and the loader names both instances and both globs."""
    base = graph_repo / "graphs" / "v1.yaml"
    head_repo = tmp_path / "head"
    (head_repo / "graphs").mkdir(parents=True)
    for sub in ("prompts", "bin"):
        (head_repo / sub).mkdir(parents=True)
        for item in (graph_repo / sub).iterdir():
            dst = head_repo / sub / item.name
            dst.write_bytes(item.read_bytes())
            dst.chmod(0o755)
    (head_repo / "graphs" / "v1.yaml").write_text(
        base.read_text().replace('writes: ["out/b.md"]', 'writes: ["out"]'),
        encoding="utf-8",
    )
    code, out = _diff(base, head_repo / "graphs" / "v1.yaml", capsys)
    assert code == EXIT_GRAPH
    assert "RECUSADO no load" in out


def test_fail_on_widening_is_a_policy_gate(
    graph_repo: Path, tmp_path: Path, capsys
) -> None:
    base = graph_repo / "graphs" / "v1.yaml"
    head_repo = tmp_path / "head"
    (head_repo / "graphs").mkdir(parents=True)
    for sub in ("prompts", "bin"):
        (head_repo / sub).mkdir(parents=True)
        for item in (graph_repo / sub).iterdir():
            dst = head_repo / sub / item.name
            dst.write_bytes(item.read_bytes())
            dst.chmod(0o755)
    (head_repo / "graphs" / "v1.yaml").write_text(
        base.read_text().replace("  session_units: 6.00", "  session_units: 12.00"),
        encoding="utf-8",
    )
    head = head_repo / "graphs" / "v1.yaml"
    assert _diff(base, head, capsys)[0] == EXIT_OK
    assert main(["team", "diff", str(base), str(head), "--fail-on-widening"]) == EXIT_GRAPH


def test_diff_classifies_tools_and_fanout_ceiling() -> None:
    """Unit-level, on the semantic models: tools.allow and the fanout ceiling are the
    two widenings that are easiest to miss in a YAML diff."""
    base = {
        "id": "v1",
        "budget": {
            "wall_seconds": 1, "session_units": 1.0, "log_bytes": 1, "max_nodes": 1,
            "iters_default": 1, "node_units_default": 1.0, "no_progress_rounds": 1,
            "tools": {"allow": ["Read"], "deny": ["Bash"]},
        },
        "nodes": {
            "build": {
                "type": "fanout", "adapter": "claude", "cwd": ".", "reads": [],
                "writes": [], "timeout_seconds": 1, "model": None, "prompt": "p.md",
                "iters": 1, "budget_units": 1.0, "max": 2,
                "tools": {"allow": ["Read"], "deny": ["Bash"]},
                "partition": [{"slot": "a", "reads": [], "writes": ["out/a.md"]}],
            }
        },
        "artifacts": {}, "edges": [], "stop": {"all_of": ["gate"], "failsafe": "budget"},
        "baseline": {
            "writes": ["out/**"], "budget_units": 1.0, "timeout_seconds": 1,
            "prompt": "b.md",
        },
        "prompts": {}, "check_binaries": {},
    }
    head = json.loads(json.dumps(base))
    head["nodes"]["build"]["max"] = 3
    head["nodes"]["build"]["tools"]["allow"] = ["Read", "Bash"]
    head["nodes"]["build"]["tools"]["deny"] = []
    head["budget"]["tools"]["deny"] = []
    changes = team_mod.diff_models(base, head)
    texts = [f"{c.severity}|{c.subject}|{c.text}" for c in changes]
    assert any("alarga|build|max 2 → 3" == t for t in texts), texts
    assert any("alarga|build|tools.allow ganhou Bash" == t for t in texts), texts
    assert any("alarga|build|tools.deny perdeu Bash" == t for t in texts), texts
    assert any("alarga|budget.tools|deny perdeu Bash" == t for t in texts), texts


# ------------------------------------------ the invariant: graphs/ is read-only


def _graphs_tree(root: Path) -> str:
    return team_mod.declaration_tree_sha256(root)


@pytest.mark.parametrize(
    "knobs, expect_degrade",
    [({}, False), ({"utilization": 0.90}, True)],
)
def test_runtime_never_writes_the_declaration(
    fake_claude: Path,
    graph_repo: Path,
    tmp_path: Path,
    double_control: Path,
    capsys,
    knobs: dict,
    expect_degrade: bool,
) -> None:
    """The invariant that keeps the declaration and the runtime from being two truths.
    Covers the degraded path too: the gate lowering concurrency is a runtime decision,
    and it is recorded as a deviation — never written back to graphs/."""
    if knobs:
        set_knobs(double_control, **knobs)
    before = _graphs_tree(graph_repo)
    session = tmp_path / "sess"
    code = main(
        [
            "up",
            str(graph_repo / "graphs" / "v1.yaml"),
            "--session-dir",
            str(session),
        ]
    )
    assert code == EXIT_OK, capsys.readouterr().out
    after = _graphs_tree(graph_repo)
    assert after == before, "the runtime wrote to graphs/"

    state = json.loads((session / "state.json").read_text())
    assert state["preflight"]["declaration_tree_sha256"] == before
    assert state["preflight"]["declaration_tree_sha256_after"] == before

    kinds = {d["kind"] for d in state["deviations"]}
    assert {"concurrency", "isolation", "launch_order"} <= kinds
    if expect_degrade:
        assert "concurrency_degraded" in kinds, state["deviations"]


def test_the_deviation_carries_declared_and_effective_side_by_side(
    fake_claude: Path, graph_repo: Path, tmp_path: Path, capsys
) -> None:
    session = tmp_path / "sess"
    assert (
        main(
            [
                "up",
                str(graph_repo / "graphs" / "v1.yaml"),
                "--session-dir",
                str(session),
                "--no-baseline",
                "--max-concurrency",
                "1",
            ]
        )
        == EXIT_OK
    ), capsys.readouterr().out
    state = json.loads((session / "state.json").read_text())
    by_kind = {d["kind"]: d for d in state["deviations"]}
    assert by_kind["concurrency"]["declared"] == "1"
    assert by_kind["concurrency"]["effective"] == 1
    assert by_kind["isolation"]["effective"] == "cwd"
    assert by_kind["baseline"]["effective"].startswith("skipped")
    assert by_kind["launch_order"]["effective"][0] == "scout"


def test_fingerprint_lands_in_state_and_verdict(
    fake_claude: Path, graph_repo: Path, tmp_path: Path, capsys
) -> None:
    session = tmp_path / "sess"
    assert (
        main(["up", str(graph_repo / "graphs" / "v1.yaml"), "--session-dir", str(session)])
        == EXIT_OK
    ), capsys.readouterr().out
    expected = team_mod.fingerprint(load_graph(graph_repo / "graphs" / "v1.yaml"))
    state = json.loads((session / "state.json").read_text())
    verdict = json.loads((session / "verdict.json").read_text())
    assert state["preflight"]["team_fingerprint"] == expected
    assert verdict["team_fingerprint"] == expected
    # and the session dir is a valid input to the aggregation report
    fp, origin = team_mod.read_fingerprint(session)
    assert fp == expected and "verdict.json" in origin
