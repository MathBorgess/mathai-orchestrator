from __future__ import annotations

import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# The CLI double. It honours the adapter contract, never talks to Anthropic, and
# writes relative to its own cwd — which is exactly the node's write root: the
# session dir for a graph node, `baseline/` for the control arm, the worktree for
# an isolated fanout instance.
#
# Its behaviour is steered by a JSON control file whose path is baked in at fixture
# time, NOT by environment variables: the child env is an allowlist (SPEC §4.2), so
# an ORCH_FAKE_* variable would be stripped before the double ever saw it — which is
# exactly the property the allowlist is there to have.
FAKE_CLAUDE = '''\
#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path

CONTROL = Path("__CONTROL__")
try:
    knobs = json.loads(CONTROL.read_text())
except Exception:
    knobs = {}

session = os.environ.get("ORCH_SESSION_DIR")
node = os.environ.get("ORCH_NODE_ID", "unknown")
if session:
    stamp = Path(session) / "artifacts"
    stamp.mkdir(parents=True, exist_ok=True)
    (stamp / "last-argv.json").write_text(json.dumps(sys.argv))
    (stamp / (node + "-argv.json")).write_text(json.dumps(sys.argv))
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

HANDOFF = (
    "OBJETIVO\\nscout brief\\nPARTICAO\\na b c\\nACEITE\\nfiles exist\\n"
    "FORA_DE_ESCOPO\\nno api\\n" + ("line\\n" * 12)
)
REPORT = (
    "FEITO\\nwork\\nNAO_FEITO\\nnothing\\nFRONTEIRAS\\na-b a-c b-c\\nRISCOS\\nnone\\n"
    + ("line\\n" * 24)
)

target = os.environ.get("ORCH_ARTIFACT") or "out/REPORT.md"
body = REPORT if target.endswith("REPORT.md") else (
    HANDOFF if target.endswith("handoff.md") else ("prose\\n" * 10)
)
# `session` is unset for the doctor probe: only a real node spawn writes.
if session and not knobs.get("nowrite"):
    dest = Path(target)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body)

if knobs.get("sleep"):
    time.sleep(float(knobs["sleep"]))

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
if knobs.get("deny") and node in (knobs.get("deny_nodes") or [node]):
    result["permission_denials"] = [{"tool_name": "Write"}]
util = float(knobs.get("utilization", 0.1))
status = knobs.get("rl_status", "allowed")
if stream:
    print(json.dumps({"type": "system", "subtype": "init"}))
    print(json.dumps({"type": "rate_limit_event", "rate_limit_info": {
        "status": status,
        "unifiedWindows": {
            "five_hour": {"utilization": util, "resetsAt": time.time() + 3600},
            "seven_day": {"utilization": 0.2, "resetsAt": time.time() + 86400},
        },
    }}))
    print(json.dumps(result))
else:
    print(json.dumps(result))
sys.exit(0)
'''


@pytest.fixture(autouse=True)
def no_real_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may reach the real CLI. Burning subscription window from a unit test
    is how a measuring instrument stops being cheap to run. `fake_claude` prepends
    its own directory ahead of this one."""
    guard = tmp_path / "bin-guard"
    guard.mkdir(parents=True, exist_ok=True)
    stub = guard / "claude"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "print('the test suite must not reach the real claude CLI', file=sys.stderr)\n"
        "sys.exit(97)\n",
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{guard}:{os.environ.get('PATH', '')}")


@pytest.fixture
def repo_root() -> Path:
    return REPO


@pytest.fixture
def double_control(tmp_path: Path) -> Path:
    control = tmp_path / "double.json"
    control.write_text("{}", encoding="utf-8")
    return control


@pytest.fixture
def fake_claude(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, double_control: Path
) -> Path:
    script = tmp_path / "bin-double" / "claude"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        textwrap.dedent(FAKE_CLAUDE).replace("__CONTROL__", str(double_control)),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{script.parent}:{os.environ.get('PATH', '')}")
    return script


def set_knobs(control: Path, **kwargs: object) -> None:
    data = json.loads(control.read_text())
    data.update(kwargs)
    control.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def graph_repo(tmp_path: Path) -> Path:
    """A throwaway git repo carrying graphs/, prompts/ and bin/ — so worktree tests
    never touch the developer's own checkout."""
    root = tmp_path / "repo"
    (root / "graphs").mkdir(parents=True)
    (root / "prompts").mkdir(parents=True)
    (root / "bin").mkdir(parents=True)
    for name in ("v1.yaml",):
        (root / "graphs" / name).write_bytes((REPO / "graphs" / name).read_bytes())
    for prompt in (REPO / "prompts").glob("*.md"):
        (root / "prompts" / prompt.name).write_bytes(prompt.read_bytes())
    for tool in (REPO / "bin").iterdir():
        dst = root / "bin" / tool.name
        dst.write_bytes(tool.read_bytes())
        dst.chmod(0o755)
    (root / ".gitignore").write_text(".sessions/\n")
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "orch@test.local"], check=True
    )
    subprocess.run(["git", "-C", str(root), "config", "user.name", "orch"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-qm", "fixture"],
        check=True,
        capture_output=True,
    )
    return root
