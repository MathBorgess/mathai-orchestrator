"""Child env is an allowlist. ANTHROPIC_API_KEY is stripped, never required."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

PASS_EXACT = frozenset(
    {"HOME", "PATH", "USER", "SHELL", "LANG", "TZ", "TMPDIR", "SSH_AUTH_SOCK"}
)
PASS_PREFIX = ("LC_",)
FORCE = {"TERM": "dumb"}

BLOCK_EXACT = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "CLAUDECODE",
    }
)
BLOCK_PREFIX = ("CLAUDE_CODE_", "CLAUDE_", "CURSOR_", "ANTHROPIC_")

ORCH_KEYS = ("ORCH_SESSION_DIR", "ORCH_NODE_ID", "ORCH_ARTIFACT", "ORCH_SEED")


@dataclass
class EnvReport:
    stripped: list[str] = field(default_factory=list)
    passed: list[str] = field(default_factory=list)


def _blocked(key: str) -> bool:
    if key in BLOCK_EXACT:
        return True
    return any(key.startswith(p) for p in BLOCK_PREFIX)


def parent_had_api_key(environ: dict[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    return bool(env.get("ANTHROPIC_API_KEY"))


def child_env(
    extra: dict[str, str] | None = None,
    environ: dict[str, str] | None = None,
    allow_ssh_auth: bool = False,
) -> tuple[dict[str, str], EnvReport]:
    src = environ if environ is not None else os.environ
    out: dict[str, str] = {}
    report = EnvReport()

    for key, value in src.items():
        if _blocked(key):
            report.stripped.append(key)
            continue
        if key in PASS_EXACT:
            if key == "SSH_AUTH_SOCK" and not allow_ssh_auth:
                continue
            out[key] = value
            report.passed.append(key)
            continue
        if key.startswith(PASS_PREFIX):
            out[key] = value
            report.passed.append(key)

    out.update(FORCE)
    if extra:
        for key, value in extra.items():
            if key not in ORCH_KEYS and _blocked(key):
                raise ValueError(f"refused to pass blocked env var {key}")
            out[key] = value
            report.passed.append(key)

    for key in list(out):
        if _blocked(key) and key not in ORCH_KEYS:
            raise ValueError(f"blocked env var leaked into child env: {key}")
    return out, report
