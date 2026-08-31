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

NODE_SESSION_NS = uuid.uuid5(
    uuid.NAMESPACE_URL, "https://mathai.orchestrator/session-node"
)
BINARY = "claude"
REQUIRED_RESULT_FIELDS = (
    "is_error",
    "subtype",
    "permission_denials",
    "num_turns",
    "total_cost_usd",
)
AUTH_LOGIN_HINT = (
    "Claude Code is not logged in with a Pro/Max subscription. "
    "Run: claude auth login"
)


def node_session_id(session_id: str, node_id: str) -> str:
    return str(uuid.uuid5(NODE_SESSION_NS, f"{session_id}:{node_id}"))


def which_claude(path: str | None = None) -> str | None:
    return shutil.which(BINARY, path=path)


class ClaudeAdapter:
    name = "claude"

    def preflight(self, timeout_s: float = 5.0, env: dict[str, str] | None = None) -> dict[str, Any]:
        binary = which_claude()
        if not binary:
            raise PreflightError(
                "claude CLI is not on PATH. Install Claude Code and log in with "
                "the subscription: claude auth login"
            )
        child, report = child_env(environ=env)
        version = _run_capture([binary, "--version"], child, timeout_s=timeout_s)
        auth = _run_capture([binary, "auth", "status"], child, timeout_s=timeout_s)
        if auth.rc != 0:
            raise PreflightError(
                f"{AUTH_LOGIN_HINT} (auth status exit {auth.rc}: {auth.stderr or auth.stdout})"
            )
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

    def probe_schema(
        self, binary: str, env: dict[str, str], timeout_s: float = 5.0
    ) -> dict[str, Any]:
        argv = [binary, "-p", "--output-format", "json"]
        _refuse_bare(argv)
        # The probe runs in a throwaway directory, never in the operator's cwd: it
        # must not create files there, and it must not register the project the
        # operator happens to be standing in as a CLI project directory.
        with tempfile.TemporaryDirectory(prefix="orch-doctor-") as sandbox:
            captured = _run_capture(
                argv, env, timeout_s=timeout_s, stdin=b"reply OK\n", cwd=sandbox
            )
        if captured.rc != 0:
            raise PreflightError(
                f"doctor probe failed (exit {captured.rc}). {AUTH_LOGIN_HINT}. "
                f"stderr={captured.stderr[:300]}"
            )
        try:
            payload = json.loads(captured.stdout)
        except json.JSONDecodeError as exc:
            raise PreflightError(
                f"doctor probe did not return JSON: {exc}. stdout={captured.stdout[:200]!r}"
            ) from exc
        missing = [f for f in REQUIRED_RESULT_FIELDS if f not in payload]
        if missing:
            raise PreflightError(
                "doctor probe JSON is missing field(s) the parser reads: "
                + ", ".join(missing)
                + ". Date an amendment in SPEC.md before changing the adapter."
            )
        return {"fields": list(REQUIRED_RESULT_FIELDS), "subtype": payload.get("subtype")}

    def build(
        self,
        node: Node,
        *,
        session_id: str,
        session_dir: Path,
        preamble: str,
        prompt: str,
        cwd: Path,
        stdout_path: Path,
        stderr_path: Path,
        seed: int | None = None,
        add_dirs: tuple[Path, ...] = (),
    ) -> Spawn:
        model = node.model or "sonnet"
        budget = node.budget_units if node.budget_units is not None else 1.0
        allow = list(node.tools.allow)
        deny = list(node.tools.deny)
        argv = [
            BINARY,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "acceptEdits",
            "--model",
            model,
            "--session-id",
            node_session_id(session_id, node.id),
            "--add-dir",
            str(session_dir),
            "--allowedTools",
            ",".join(allow),
            "--disallowedTools",
            ",".join(deny),
            "--max-budget-usd",
            f"{budget:.2f}",
            "--setting-sources",
            "project",
            "--strict-mcp-config",
            "--append-system-prompt",
            preamble,
        ]
        for extra_dir in add_dirs:
            argv.extend(["--add-dir", str(extra_dir)])
        _refuse_bare(argv)
        extra = {
            "ORCH_SESSION_DIR": str(session_dir),
            "ORCH_NODE_ID": node.id,
        }
        if seed is not None:
            # The CLI exposes no seed knob; the seed labels the sample in the series
            # and reaches the child as a declared fact, not as a sampling parameter.
            extra["ORCH_SEED"] = str(seed)
        concrete = [w for w in node.writes if not any(c in w for c in "*?[")]
        if concrete:
            extra["ORCH_ARTIFACT"] = concrete[0]
        env, _ = child_env(extra=extra)
        return Spawn(
            argv=argv,
            cwd=str(cwd),
            env=env,
            stdin_bytes=prompt.encode("utf-8"),
            timeout_s=int(node.timeout_seconds),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
        )

    def spawn(self, spec: Spawn, on_start: Callable[[Any], None] | None = None) -> int:
        _refuse_bare(spec.argv)
        for key in spec.env:
            if key.startswith("ANTHROPIC_") or key.startswith("CLAUDE"):
                raise PreflightError(f"child env leaked {key}")
        return run_process_group(spec, on_start=on_start)

    def parse(self, rc: int, stdout_path: str | Path, stderr_path: str | Path) -> Outcome:
        result, rate, degraded = _read_stream(Path(stdout_path))
        denials = [
            Denial(
                tool_name=str(d.get("tool_name") or d.get("tool") or "unknown"),
                tool_input=d.get("tool_input"),
            )
            for d in (result.get("permission_denials") or [])
            if isinstance(d, dict)
        ]
        is_error = bool(result.get("is_error")) if result else rc != 0
        subtype = result.get("subtype") if result else None
        failure = _classify(rc, is_error, subtype, denials, result)
        text = ""
        if result:
            raw_text = result.get("result") or result.get("text") or ""
            text = raw_text if isinstance(raw_text, str) else json.dumps(raw_text)
        turns = result.get("num_turns") if result else None
        cost = result.get("total_cost_usd") if result else None
        session_ref = result.get("session_id") if result else None
        # ok is the three process conditions; artifact verify is applied by the parent
        process_ok = (
            rc == 0
            and is_error is False
            and not denials
            and failure is None
        )
        return Outcome(
            ok=process_ok,
            rc=rc,
            failure=failure,
            denials=denials,
            turns=int(turns) if isinstance(turns, int) else None,
            cost_units=float(cost) if isinstance(cost, (int, float)) else None,
            session_ref=str(session_ref) if session_ref else None,
            rate_limit=rate,
            degraded=degraded,
            text=text,
            is_error=is_error,
            subtype=str(subtype) if subtype else None,
            raw_result=result,
        )


def _refuse_bare(argv: list[str]) -> None:
    if "--bare" in argv or any(a.startswith("--bare=") for a in argv):
        raise BareForbidden()


def _classify(
    rc: int,
    is_error: bool,
    subtype: str | None,
    denials: list[Denial],
    result: dict[str, Any],
) -> str | None:
    if denials:
        return "permission"
    if subtype == "error_max_budget_usd" or result.get("terminal_reason") == "budget_exhausted":
        return "budget"
    if rc != 0 and (result.get("api_error_status") is not None or subtype == "error"):
        if result.get("api_error_status") is not None:
            return "transport"
    if rc != 0 and not result:
        return "parse"
    if is_error:
        return "transport" if result.get("api_error_status") is not None else "parse"
    return None


def _read_stream(path: Path) -> tuple[dict[str, Any], RateLimit | None, bool]:
    if not path.is_file():
        return {}, None, False
    result: dict[str, Any] = {}
    rate: RateLimit | None = None
    degraded = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        typ = obj.get("type")
        if typ == "result" or (typ is None and "is_error" in obj):
            result = obj
        if typ == "rate_limit_event" or "rate_limit_info" in obj:
            rate = _rate_limit(obj.get("rate_limit_info") or obj)
        if typ == "autocompact_state" or obj.get("subtype") == "autocompact":
            degraded = True
    if not result:
        # doctor-style single JSON object (not JSONL)
        try:
            whole = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(whole, dict):
                result = whole
        except json.JSONDecodeError:
            pass
    return result, rate, degraded


def _rate_limit(info: dict[str, Any]) -> RateLimit:
    windows = info.get("unifiedWindows") or {}
    five = windows.get("five_hour") or {}
    seven = windows.get("seven_day") or {}
    return RateLimit(
        status=info.get("status"),
        five_hour_util=_as_float(five.get("utilization")),
        seven_day_util=_as_float(seven.get("utilization")),
        resets_at=_as_float(five.get("resetsAt") or info.get("resetsAt")),
    )


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


class _Captured:
    def __init__(self, rc: int, stdout: str, stderr: str):
        self.rc = rc
        self.stdout = stdout
        self.stderr = stderr


def _run_capture(
    argv: list[str],
    env: dict[str, str],
    timeout_s: float,
    stdin: bytes | None = None,
    cwd: str | None = None,
) -> _Captured:
    _refuse_bare(argv)
    try:
        proc = subprocess.run(
            argv,
            input=stdin,
            capture_output=True,
            timeout=timeout_s,
            env=env,
            cwd=cwd,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        raise PreflightError(f"failed to exec {argv[0]}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PreflightError(
            f"{' '.join(argv[:3])} exceeded {timeout_s:.0f}s. {AUTH_LOGIN_HINT}."
        ) from exc
    return _Captured(
        rc=proc.returncode,
        stdout=(proc.stdout or b"").decode("utf-8", errors="replace"),
        stderr=(proc.stderr or b"").decode("utf-8", errors="replace"),
    )


def run_process_group(
    spec: Spawn, on_start: Callable[[Any], None] | None = None
) -> int:
    Path(spec.stdout_path).parent.mkdir(parents=True, exist_ok=True)
    Path(spec.stderr_path).parent.mkdir(parents=True, exist_ok=True)
    with open(spec.stdout_path, "wb") as out, open(spec.stderr_path, "wb") as err:
        try:
            proc = subprocess.Popen(
                spec.argv,
                cwd=spec.cwd,
                env=spec.env,
                stdin=subprocess.PIPE,
                stdout=out,
                stderr=err,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            raise PreflightError(f"failed to exec {spec.argv[0]}: {exc}") from exc
        if on_start is not None:
            on_start(proc)
        try:
            proc.communicate(spec.stdin_bytes, timeout=spec.timeout_s)
        except subprocess.TimeoutExpired:
            kill_process_group(proc)
            raise TimeoutError(spec.timeout_s)
        return int(proc.returncode)


def kill_process_group(proc: subprocess.Popen[bytes]) -> None:
    """SPEC §3.5-1: the child spawns grandchildren (the Bash tool). kill() leaves them
    holding the worktree and writing to the artifact after the node was declared dead.
    start_new_session=True, then killpg(SIGTERM) -> 5s grace -> SIGKILL."""
    if proc.pid is None:
        return
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except OSError:
        # Already reaped, or a pid the OS refuses. Never let one stuck node stop the
        # cleanup of the others: the drain has to reach every slot.
        return
    deadline = time.time() + 5
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.05)
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        return
    proc.wait()
