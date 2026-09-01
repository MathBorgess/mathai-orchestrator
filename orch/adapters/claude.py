"""Claude Code adapter: CLI subprocess only. Never HTTP, never SDK, never --bare."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from orch.env import child_env, parent_had_api_key
from orch.errors import BareForbidden, PreflightError
from orch.graph import Node
from orch.outcome import Denial, Outcome, RateLimit, Spawn

NODE_SESSION_NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://mathai.orchestrator/session-node")
BINARY = "claude"
REQUIRED_RESULT_FIELDS = (
    "is_error", "subtype", "permission_denials", "num_turns", "total_cost_usd",
)
AUTH_LOGIN_HINT = "Claude Code is not logged in with a Pro/Max subscription. Run: claude auth login"


def node_session_id(session_id: str, node_id: str) -> str:
    return str(uuid.uuid5(NODE_SESSION_NS, f"{session_id}:{node_id}"))


def which_claude(path: str | None = None) -> str | None:
    return shutil.which(BINARY, path=path)


class ClaudeAdapter:
    name = "claude"

    def preflight(self, timeout_s: float = 5.0, env: dict[str, str] | None = None) -> dict[str, Any]:
        binary = which_claude()
        if not binary:
            raise PreflightError("claude CLI is not on PATH. Install Claude Code and log in: claude auth login")
        child, report = child_env(environ=env)
        version = _run_capture([binary, "--version"], child, timeout_s=timeout_s)
        auth = _run_capture([binary, "auth", "status"], child, timeout_s=timeout_s)
        if auth.rc != 0:
            raise PreflightError(f"{AUTH_LOGIN_HINT} (auth status exit {auth.rc})")
        probe = self.probe_schema(binary, child, timeout_s=timeout_s)
        return {
            "binary": binary,
            "version": version.stdout.strip(),
            "auth_status": "ok",
            "auth_detail": auth.stdout.strip()[:500],
            "probe": probe,
            "api_key_stripped": parent_had_api_key(env),
            "env_stripped": sorted(report.stripped),
        }

    def probe_schema(self, binary: str, env: dict[str, str], timeout_s: float = 5.0) -> dict[str, Any]:
        argv = [binary, "-p", "--output-format", "json"]
        _refuse_bare(argv)
        with tempfile.TemporaryDirectory(prefix="orch-doctor-") as sandbox:
            captured = _run_capture(argv, env, timeout_s=timeout_s, stdin=b"reply OK\n", cwd=sandbox)
        if captured.rc != 0:
            raise PreflightError(f"doctor probe failed (exit {captured.rc}). {AUTH_LOGIN_HINT}")
        payload = json.loads(captured.stdout)
        missing = [f for f in REQUIRED_RESULT_FIELDS if f not in payload]
        if missing:
            raise PreflightError("doctor probe JSON missing fields: " + ", ".join(missing))
        return {"fields": list(REQUIRED_RESULT_FIELDS), "subtype": payload.get("subtype")}

    def build(self, node: Node, *, session_id: str, session_dir: Path, preamble: str, prompt: str, cwd: Path, stdout_path: Path, stderr_path: Path, seed: int | None = None, add_dirs: tuple[Path, ...] = ()) -> Spawn:
        model = node.model or "sonnet"
        budget = node.budget_units if node.budget_units is not None else 1.0
        argv = [BINARY, "-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits", "--model", model, "--session-id", node_session_id(session_id, node.id), "--add-dir", str(session_dir), "--allowedTools", ",".join(node.tools.allow), "--disallowedTools", ",".join(node.tools.deny), "--max-budget-usd", f"{budget:.2f}", "--setting-sources", "project", "--strict-mcp-config", "--append-system-prompt", preamble]
        for extra_dir in add_dirs:
            argv.extend(["--add-dir", str(extra_dir)])
        _refuse_bare(argv)
        extra = {"ORCH_SESSION_DIR": str(session_dir), "ORCH_NODE_ID": node.id}
        if seed is not None:
            extra["ORCH_SEED"] = str(seed)
        env, _ = child_env(extra=extra)
        return Spawn(argv=argv, cwd=str(cwd), env=env, stdin_bytes=prompt.encode("utf-8"), timeout_s=int(node.timeout_seconds), stdout_path=str(stdout_path), stderr_path=str(stderr_path))

    def spawn(self, spec: Spawn, on_start: Callable[[Any], None] | None = None) -> int:
        _refuse_bare(spec.argv)
        return run_process_group(spec, on_start=on_start)

    def parse(self, rc: int, stdout_path: str | Path, stderr_path: str | Path) -> Outcome:
        result, rate, degraded = _read_stream(Path(stdout_path))
        denials = [Denial(tool_name=str(d.get("tool_name") or "unknown"), tool_input=d.get("tool_input")) for d in (result.get("permission_denials") or []) if isinstance(d, dict)]
        is_error = bool(result.get("is_error")) if result else rc != 0
        failure = _classify(rc, is_error, result.get("subtype") if result else None, denials, result)
        process_ok = rc == 0 and is_error is False and not denials and failure is None
        return Outcome(ok=process_ok, rc=rc, failure=failure, denials=denials, turns=result.get("num_turns") if result else None, cost_units=float(result.get("total_cost_usd")) if result and isinstance(result.get("total_cost_usd"), (int, float)) else None, session_ref=str(result.get("session_id")) if result and result.get("session_id") else None, rate_limit=rate, degraded=degraded, text="", is_error=is_error, subtype=str(result.get("subtype")) if result and result.get("subtype") else None, raw_result=result)


def _refuse_bare(argv: list[str]) -> None:
    if "--bare" in argv:
        raise BareForbidden()


def _classify(rc, is_error, subtype, denials, result) -> str | None:
    if denials:
        return "permission"
    if rc != 0 and not result:
        return "parse"
    if is_error:
        return "transport"
    return None


def _read_stream(path: Path):
    result = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and (obj.get("type") == "result" or "is_error" in obj):
                result = obj
    return result, None, False


class _Captured:
    def __init__(self, rc, stdout, stderr):
        self.rc, self.stdout, self.stderr = rc, stdout, stderr


def _run_capture(argv, env, timeout_s, stdin=None, cwd=None) -> _Captured:
    _refuse_bare(argv)
    proc = subprocess.run(argv, input=stdin, capture_output=True, timeout=timeout_s, env=env, cwd=cwd, start_new_session=True)
    return _Captured(proc.returncode, (proc.stdout or b"").decode(), (proc.stderr or b"").decode())


def run_process_group(spec: Spawn, on_start: Callable[[Any], None] | None = None) -> int:
    Path(spec.stdout_path).parent.mkdir(parents=True, exist_ok=True)
    with open(spec.stdout_path, "wb") as out, open(spec.stderr_path, "wb") as err:
        proc = subprocess.Popen(spec.argv, cwd=spec.cwd, env=spec.env, stdin=subprocess.PIPE, stdout=out, stderr=err, start_new_session=True)
        if on_start:
            on_start(proc)
        try:
            proc.communicate(spec.stdin_bytes, timeout=spec.timeout_s)
        except subprocess.TimeoutExpired:
            kill_process_group(proc)
            raise TimeoutError(spec.timeout_s)
        return int(proc.returncode)


def kill_process_group(proc: subprocess.Popen[bytes]) -> None:
    if proc.pid is None or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.time() + 5
    while time.time() < deadline and proc.poll() is None:
        time.sleep(0.05)
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        return
    proc.wait()
