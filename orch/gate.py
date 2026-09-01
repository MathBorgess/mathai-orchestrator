"""Budget and window gate (SPEC §4.6). With k nodes this is not a precaution:
it is the mechanism that stops the session from killing itself.

Three axes, all read off the same `Outcome`:

  cost per node     `--max-budget-usd` (the adapter's job)
  cost per session  accumulated `total_cost_usd`; the next node does not go up if
                    accumulated + its cap would cross the session cap. Checked
                    BEFORE the spawn, because checking after is discovering the
                    overrun with the money already spent.
  window            rate_limit_event.unifiedWindows.{five_hour,seven_day}

      util >= 0.85          effective concurrency degrades to 1
      util >= 0.95          sleep until resetsAt (pause, not failure)
      status != "allowed"   stop the session, exit 30

Never a blind retry on 429: that is the traffic pattern the platform measures.
`total_cost_usd` comes with costBasis "list" — it is a budget unit, never money.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from orch.errors import EXIT_BUDGET, EXIT_RATE_LIMIT, EXIT_WALL, OrchError
from orch.outcome import Outcome, RateLimit

DEGRADE_AT = 0.85
SLEEP_AT = 0.95


class RateLimitAbort(OrchError):
    exit_code = EXIT_RATE_LIMIT


class SessionBudgetExhausted(OrchError):
    exit_code = EXIT_BUDGET


class WallFailsafe(OrchError):
    exit_code = EXIT_WALL


@dataclass
class Gate:
    session_units: float
    wall_seconds: int
    started_at: float = field(default_factory=time.time)
    now: Callable[[], float] = time.time
    sleep: Callable[[float], None] = time.sleep
    printer: Callable[[str], None] = print

    spent_units: float = 0.0
    sample: RateLimit | None = None
    slept_seconds: float = 0.0
    sleeps: int = 0
    last_utilization: float | None = None

    # -- observation -------------------------------------------------------

    def observe(self, outcome: Outcome) -> None:
        if outcome.rate_limit is not None:
            self.sample = outcome.rate_limit
            util = self.utilization
            if util is not None:
                self.last_utilization = util
        if outcome.cost_units:
            self.spent_units += float(outcome.cost_units)

    @property
    def utilization(self) -> float | None:
        if self.sample is None:
            return None
        seen = [
            u
            for u in (self.sample.five_hour_util, self.sample.seven_day_util)
            if u is not None
        ]
        return max(seen) if seen else None

    # -- the three axes ----------------------------------------------------

    def check_wall(self) -> None:
        elapsed = self.now() - self.started_at
        if self.wall_seconds and elapsed > self.wall_seconds:
            raise WallFailsafe(
                f"budget.wall_seconds failsafe: {elapsed:.0f}s > {self.wall_seconds}s. "
                "The failsafe is unconditional and not ablatable (SPEC §6.1)."
            )

    def admits(self, node_cap: float) -> bool:
        if not self.session_units:
            return True
        return self.spent_units + float(node_cap) <= self.session_units

    def refuse_spawn(self, node_id: str, node_cap: float) -> SessionBudgetExhausted:
        return SessionBudgetExhausted(
            f"session budget cap reached before {node_id}: "
            f"spent {self.spent_units:.2f} + node cap {node_cap:.2f} > "
            f"{self.session_units:.2f} budget units. The check runs before the spawn. "
            "(budget units are list price, never what the subscription charged.)"
        )

    def ceiling(self) -> int:
        """Concurrency ceiling from the window alone. 0 means 'sleep first'."""
        util = self.utilization
        if util is None:
            return 3
        if util >= SLEEP_AT:
            return 0
        if util >= DEGRADE_AT:
            return 1
        return 3

    def enforce(self) -> str | None:
        """Applied before filling each slot. Returns a stop_reason fragment if it slept."""
        self.check_wall()
        status = self.sample.status if self.sample else None
        if status is not None and status != "allowed":
            raise RateLimitAbort(
                f'rate limit status is {status!r}, not "allowed". Stopping the session '
                "instead of retrying: a blind retry on 429 is the traffic pattern the "
                "platform measures."
            )
        if self.ceiling() != 0:
            return None
        return self._sleep_until_reset()

    def _sleep_until_reset(self) -> str:
        util = self.utilization or 0.0
        resets_at = self.sample.resets_at if self.sample else None
        now = self.now()
        if not resets_at or resets_at <= now:
            self.printer(
                f"orch: window utilization {util:.0%} >= {SLEEP_AT:.0%} but resetsAt is "
                "missing or in the past; degrading to concurrency 1 instead of sleeping "
                "blind, and waiting for a fresh rate_limit_event."
            )
            self.sample = None
            return "window_stale"
        remaining = resets_at - now
        self.printer(
            f"orch: window utilization {util:.0%} >= {SLEEP_AT:.0%}. Sleeping "
            f"{remaining / 60:.0f} min until "
            f"{time.strftime('%H:%M:%S', time.localtime(resets_at))} "
            "(pause, not failure; artifacts and worktrees stay valid)."
        )
        while True:
            self.check_wall()
            now = self.now()
            if now >= resets_at:
                break
            step = min(5.0, resets_at - now)
            self.sleep(step)
            self.slept_seconds += step
        self.sleeps += 1
        # The sample has been honoured; the next node's stream brings a fresh one.
        self.sample = None
        return "window_sleep"
