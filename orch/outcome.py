"""Outcome is defined before adapters and is the only coupling between them."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Denial:
    tool_name: str
    tool_input: Any = None


@dataclass(frozen=True)
class RateLimit:
    status: str | None
    five_hour_util: float | None
    seven_day_util: float | None
    resets_at: float | None


@dataclass
class Outcome:
    ok: bool
    rc: int
    failure: str | None = None
    denials: list[Denial] = field(default_factory=list)
    turns: int | None = None
    cost_units: float | None = None
    session_ref: str | None = None
    rate_limit: RateLimit | None = None
    degraded: bool = False
    text: str = ""
    is_error: bool | None = None
    subtype: str | None = None
    raw_result: dict[str, Any] = field(default_factory=dict)

    def session_exit_code(self) -> int:
        from orch.errors import (
            EXIT_BUDGET,
            EXIT_BUG,
            EXIT_OK,
            EXIT_PERMISSION,
            EXIT_TIMEOUT,
            EXIT_VERIFY,
        )

        if self.ok:
            return EXIT_OK
        return {
            "permission": EXIT_PERMISSION,
            "budget": EXIT_BUDGET,
            "timeout": EXIT_TIMEOUT,
            "verify": EXIT_VERIFY,
            "semantic": EXIT_VERIFY,
            "parse": EXIT_BUG,
        }.get(self.failure or "", EXIT_BUG)


@dataclass
class Spawn:
    argv: list[str]
    cwd: str
    env: dict[str, str]
    stdin_bytes: bytes
    timeout_s: int
    stdout_path: str
    stderr_path: str
