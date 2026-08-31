"""Invoke Claude Code Pro via CLI only. No Anthropic API, no SDK, no API key."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


class PreflightError(RuntimeError):
    """claude is missing or not logged in. Do not spawn nodes."""


LOGIN_HINT = (
    "Run `claude auth login` with your Claude Pro subscription, then retry."
)


def env_without_api_key(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    env.pop("ANTHROPIC_API_KEY", None)
    return env


def resolve_claude_bin() -> str | None:
    override = os.environ.get("CLAUDE_BIN")
    if override:
        path = Path(override)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
        return None
    return shutil.which("claude")


def preflight_claude() -> str:
    """Abort before any node spawn. Point at Pro login, never at an API key."""
    binary = resolve_claude_bin()
    if binary is None:
        raise PreflightError(f"claude CLI not found. {LOGIN_HINT}")
    try:
        result = subprocess.run(
            [binary, "auth", "status"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env_without_api_key(),
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PreflightError(f"claude auth status failed. {LOGIN_HINT}") from exc
    if result.returncode != 0:
        raise PreflightError(f"claude auth status failed. {LOGIN_HINT}")
    return binary


def build_prompt(node_id: str, session_dir: Path, artifact: str, prompt_path: Path) -> str:
    body = prompt_path.read_text(encoding="utf-8")
    preamble = (
        f"session_dir: {session_dir}\n"
        f"node_id: {node_id}\n"
        f"artifact: {artifact}\n"
        "\n"
    )
    return preamble + body


def spawn_claude(
    *,
    binary: str,
    prompt: str,
    cwd: Path,
    log_path: Path,
) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    argv = [binary, "-p", "--output-format", "text", prompt]
    with log_path.open("wb") as log:
        result = subprocess.run(
            argv,
            cwd=cwd,
            env=env_without_api_key(),
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    return result.returncode
