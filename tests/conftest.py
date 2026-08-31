from __future__ import annotations

import os
import stat
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo_root() -> Path:
    return REPO


@pytest.fixture
def fake_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A claude stand-in that honors the adapter contract and never talks to Anthropic."""
    script = tmp_path / "claude"
    script.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json, os, sys
            from pathlib import Path

            session = os.environ.get("ORCH_SESSION_DIR")
            if session:
                stamp = Path(session) / "artifacts" / "last-argv.json"
                stamp.parent.mkdir(parents=True, exist_ok=True)
                stamp.write_text(json.dumps(sys.argv))
            if "--bare" in sys.argv:
                print("bare is forbidden", file=sys.stderr)
                sys.exit(2)
            if len(sys.argv) >= 2 and sys.argv[1] == "--version":
                print("2.1.251 (test-double)")
                sys.exit(0)
            if len(sys.argv) >= 3 and sys.argv[1:3] == ["auth", "status"]:
                print("logged in via subscription (test-double)")
                sys.exit(0)

            stdin = sys.stdin.read()
            stream = "stream-json" in sys.argv
            artifact = os.environ.get("ORCH_ARTIFACT")
            if session and artifact:
                dest = Path(session) / artifact
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(
                    "OBJETIVO\\nscout brief\\nPARTICAO\\na b c\\nACEITE\\nfiles exist\\n"
                    "FORA_DE_ESCOPO\\nno api\\n" + ("line\\n" * 12)
                )

            result = {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "permission_denials": [],
                "num_turns": 1,
                "total_cost_usd": 0.01,
                "session_id": "00000000-0000-0000-0000-000000000001",
                "result": "OK",
            }
            if os.environ.get("ORCH_FAKE_DENY"):
                result["permission_denials"] = [{"tool_name": "Write"}]
            if stream:
                print(json.dumps({"type": "system", "subtype": "init"}))
                print(json.dumps({"type": "rate_limit_event", "rate_limit_info": {
                    "status": "allowed",
                    "unifiedWindows": {
                        "five_hour": {"utilization": 0.1, "resetsAt": 0},
                        "seven_day": {"utilization": 0.2, "resetsAt": 0},
                    },
                }}))
                print(json.dumps(result))
            else:
                print(json.dumps(result))
            sys.exit(0)
            """
        ),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ.get('PATH', '')}")
    return script
