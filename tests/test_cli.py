from __future__ import annotations

import json
from pathlib import Path

from orch.cli import main
from orch.errors import EXIT_GRAPH, EXIT_OK, EXIT_USAGE

REPO = Path(__file__).resolve().parents[1]


def test_validate_only_accepts_v1() -> None:
    assert main(["up", str(REPO / "graphs" / "v1.yaml"), "--validate-only"]) == EXIT_OK


def test_validate_only_refuses_v0() -> None:
    assert main(["up", str(REPO / "graphs" / "v0.yaml"), "--validate-only"]) == EXIT_GRAPH


def test_doctor_with_fake_claude(fake_claude: Path, capsys) -> None:
    assert main(["doctor"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "orch doctor: ok" in out
    assert "is_error" in out
    assert "permission_denials" in out
    assert "--bare forbidden" in out
    assert "claude auth login" in out


def test_max_concurrency_4_is_refused_not_clamped(fake_claude: Path, tmp_path: Path) -> None:
    code = main(
        [
            "up",
            str(REPO / "graphs" / "v1.yaml"),
            "--session-dir",
            str(tmp_path / "s"),
            "--max-concurrency",
            "4",
        ]
    )
    assert code == EXIT_USAGE


def test_up_spawns_one_claude_node(fake_claude: Path, tmp_path: Path) -> None:
    session = tmp_path / "sess"
    code = main(
        [
            "up",
            str(REPO / "graphs" / "v1.yaml"),
            "--session-dir",
            str(session),
            "--no-baseline",
            "--node",
            "scout",
        ]
    )
    assert code == EXIT_OK
    state = json.loads((session / "state.json").read_text())
    assert state["nodes"]["scout"]["status"] == "done"
    assert state["preflight"]["comparable"] is False
    assert state["nodes"]["scout"]["wall_seconds"] > 0
    assert (session / "graph.yaml").read_bytes() == (REPO / "graphs" / "v1.yaml").read_bytes()
    assert (session / "handoff.md").is_file()
    argv = json.loads((session / "artifacts" / "last-argv.json").read_text())
    assert "-p" in argv
    assert "--output-format" in argv and "stream-json" in argv
    assert "--verbose" in argv
    assert "--bare" not in argv
    events = (session / "events.jsonl").read_text().strip().splitlines()
    assert any('"to": "running"' in line for line in events)
    assert any('"to": "verifying"' in line for line in events)
    assert any('"to": "done"' in line for line in events)


def test_second_up_refuses_nonempty_session(fake_claude: Path, tmp_path: Path) -> None:
    session = tmp_path / "sess2"
    args = [
        "up",
        str(REPO / "graphs" / "v1.yaml"),
        "--session-dir",
        str(session),
        "--no-baseline",
        "--node",
        "scout",
    ]
    assert main(args) == EXIT_OK
    assert main(args) == EXIT_USAGE


def test_doctor_probe_does_not_write_in_the_operator_cwd(
    fake_claude: Path, tmp_path: Path, monkeypatch
) -> None:
    """The probe must not leave files in the directory the operator is standing in,
    and must not register that project in the CLI cache just to answer `doctor`."""
    workdir = tmp_path / "someones-repo"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    assert main(["doctor"]) == EXIT_OK
    assert list(workdir.iterdir()) == []
