from __future__ import annotations

from pathlib import Path

import pytest

from orch.adapters.claude import ClaudeAdapter, node_session_id
from orch.errors import BareForbidden
from orch.graph import Node, Tools


def _node() -> Node:
    return Node(
        id="scout",
        type="agent",
        prompt="prompts/scout.md",
        writes=("handoff.md",),
        timeout_seconds=30,
        budget_units=0.5,
        tools=Tools(("Read", "Write"), ("Bash", "WebFetch")),
    )


def test_build_matches_spec_contract(tmp_path: Path) -> None:
    adapter = ClaudeAdapter()
    session = tmp_path / "s"
    session.mkdir()
    spec = adapter.build(
        _node(),
        session_id="t1",
        session_dir=session,
        preamble="preamble\n",
        prompt="write handoff\n",
        cwd=session,
        stdout_path=session / "logs" / "scout.jsonl",
        stderr_path=session / "logs" / "scout.err",
    )
    argv = spec.argv
    assert argv[0] == "claude"
    assert argv[1] == "-p"
    assert "--bare" not in argv
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in argv
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
    assert argv[argv.index("--session-id") + 1] == node_session_id("t1", "scout")
    assert argv[argv.index("--add-dir") + 1] == str(session)
    assert argv[argv.index("--setting-sources") + 1] == "project"
    assert "--strict-mcp-config" in argv
    assert spec.stdin_bytes == b"write handoff\n"
    assert spec.env["TERM"] == "dumb"
    assert "ANTHROPIC_API_KEY" not in spec.env
    assert spec.env["ORCH_NODE_ID"] == "scout"


def test_build_refuses_bare_if_injected() -> None:
    from orch.adapters import claude as mod

    with pytest.raises(BareForbidden):
        mod._refuse_bare(["claude", "-p", "--bare"])


def test_parse_stream_json_and_denials(tmp_path: Path) -> None:
    adapter = ClaudeAdapter()
    out = tmp_path / "n.jsonl"
    out.write_text(
        '{"type":"system"}\n'
        '{"type":"result","subtype":"success","is_error":false,'
        '"permission_denials":[{"tool_name":"Write"}],'
        '"num_turns":2,"total_cost_usd":0.2,"result":"nope"}\n'
    )
    outcome = adapter.parse(0, out, tmp_path / "n.err")
    assert outcome.ok is False
    assert outcome.failure == "permission"
    assert outcome.denials[0].tool_name == "Write"


def test_parse_does_not_trust_rc_alone(tmp_path: Path) -> None:
    adapter = ClaudeAdapter()
    out = tmp_path / "n.jsonl"
    out.write_text(
        '{"type":"result","subtype":"success","is_error":false,'
        '"permission_denials":[],"num_turns":1,"total_cost_usd":0.0}\n'
    )
    outcome = adapter.parse(0, out, tmp_path / "n.err")
    assert outcome.ok is True
    assert outcome.failure is None
