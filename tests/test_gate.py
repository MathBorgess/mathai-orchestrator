from __future__ import annotations

import pytest

from orch.gate import (
    DEGRADE_AT,
    SLEEP_AT,
    Gate,
    RateLimitAbort,
    SessionBudgetExhausted,
    WallFailsafe,
)
from orch.outcome import Outcome, RateLimit


def _outcome(status: str = "allowed", five: float = 0.1, resets: float | None = None):
    return Outcome(
        ok=True,
        rc=0,
        cost_units=0.5,
        rate_limit=RateLimit(
            status=status, five_hour_util=five, seven_day_util=0.2, resets_at=resets
        ),
    )


def _gate(**kwargs) -> Gate:
    clock = {"t": 1000.0}
    kwargs.setdefault("session_units", 6.0)
    kwargs.setdefault("wall_seconds", 3600)
    gate = Gate(
        started_at=1000.0,
        now=lambda: clock["t"],
        sleep=lambda s: clock.__setitem__("t", clock["t"] + s),
        printer=lambda *_: None,
        **kwargs,
    )
    gate.clock = clock  # type: ignore[attr-defined]
    return gate


def test_ceiling_is_3_below_the_degrade_threshold() -> None:
    gate = _gate()
    gate.observe(_outcome(five=DEGRADE_AT - 0.01))
    assert gate.ceiling() == 3
    assert gate.enforce() is None


def test_ceiling_degrades_to_1_at_085() -> None:
    gate = _gate()
    gate.observe(_outcome(five=DEGRADE_AT))
    assert gate.ceiling() == 1
    assert gate.enforce() is None


def test_095_sleeps_until_resets_at_and_clears_the_sample() -> None:
    gate = _gate()
    gate.observe(_outcome(five=SLEEP_AT, resets=1000.0 + 120))
    assert gate.ceiling() == 0
    assert gate.enforce() == "window_sleep"
    assert gate.clock["t"] >= 1120.0  # type: ignore[attr-defined]
    assert gate.sleeps == 1
    # honoured: the next node's stream brings a fresh sample
    assert gate.sample is None
    assert gate.ceiling() == 3


def test_095_without_resets_at_degrades_instead_of_sleeping_blind() -> None:
    gate = _gate()
    gate.observe(_outcome(five=0.99, resets=None))
    assert gate.enforce() == "window_stale"
    assert gate.clock["t"] == 1000.0  # type: ignore[attr-defined]


def test_status_not_allowed_aborts_and_never_retries() -> None:
    gate = _gate()
    gate.observe(_outcome(status="throttled"))
    with pytest.raises(RateLimitAbort) as exc:
        gate.enforce()
    assert exc.value.exit_code == 30
    assert "blind retry" in exc.value.message


def test_session_cap_is_checked_before_the_spawn() -> None:
    gate = _gate(session_units=1.0)
    assert gate.admits(0.5)
    gate.observe(_outcome())  # spends 0.5
    assert gate.admits(0.5)
    assert not gate.admits(0.6)
    err = gate.refuse_spawn("merge", 0.6)
    assert isinstance(err, SessionBudgetExhausted)
    assert err.exit_code == 12
    assert "before the spawn" in err.message


def test_wall_failsafe_is_unconditional() -> None:
    gate = _gate(wall_seconds=10)
    gate.check_wall()
    gate.clock["t"] = 1011.0  # type: ignore[attr-defined]
    with pytest.raises(WallFailsafe) as exc:
        gate.check_wall()
    assert exc.value.exit_code == 21


def test_utilization_takes_the_worst_of_the_two_windows() -> None:
    gate = _gate()
    gate.observe(
        Outcome(
            ok=True,
            rc=0,
            rate_limit=RateLimit(
                status="allowed", five_hour_util=0.10, seven_day_util=0.97, resets_at=None
            ),
        )
    )
    assert gate.utilization == pytest.approx(0.97)
    assert gate.ceiling() == 0
