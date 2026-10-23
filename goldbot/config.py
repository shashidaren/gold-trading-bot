"""Configuration — one dataclass, every knob named, nothing hidden in a module global.

v1 kept its parameters as ~40 module-level constants in a 1,760-line engine.py with
the rationale in trailing comments. That made a parameter change a code edit and made
it impossible to hold two configurations side by side, which is exactly what an A/B
needs. Here a Config is a value: you can build two, replay both, and diff them.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional


# ── measured constants (see the docstrings; do not tune these casually) ────────
#: $0.55 round trip — median measured by the XM quote logger (docs/XM-LOGGER.md).
#: The repo's *registered* assumption is $0.40 (HANDOFF §1); 0.55 is the measured
#: figure. v2 defaults to the measured one because v1's whole problem is cost, and
#: costing it at the optimistic number is how that stayed invisible.
DEFAULT_COST_ROUND_TRIP = 0.55

#: Break-even decisive win rate at a 1:1.5 payoff, cost-free.
BREAKEVEN_WR_AT_1_5R = 0.40


@dataclass(frozen=True)
class Config:
    """Everything the strategy is allowed to know.

    Frozen on purpose: a replay must not be able to mutate the configuration it
    was run with, or the result cannot be reproduced from the record.
    """

    # ── timeframe ──────────────────────────────────────────────────────────────
    #: Minutes per bar. v1 ran 1. The cost/risk table in the package docstring is
    #: the reason this default is 240: at $26 of risk the round trip is 2.1% of R
    #: instead of 19.5%. This is the single most important number in the file.
    timeframe_minutes: int = 240

    # ── structure ──────────────────────────────────────────────────────────────
    #: Bars in the rolling high/low box. On H4 this is ~3.3 days of gold.
    lookback: int = 20
    #: Minimum wick, as a share of bar range, for a bar to count as a rejection.
    #: v1 used 0.38 on M1; on H4 a single bar carries far more information, so
    #: the same number is a different claim. Kept as a knob, not a truth.
    wick_ratio_min: float = 0.38

    # ── trend ──────────────────────────────────────────────────────────────────
    ema_fast: int = 20
    ema_slow: int = 50
    #: Require the fast EMA to be sloping with the trade over this many bars.
    slope_bars: int = 5
    #: Volatility/momentum periods. They are config rather than literals because
    #: `warmup_bars()` has to account for them: a replay that starts evaluating
    #: before ATR exists refuses every entry with "no ATR" and reports a clean,
    #: empty, entirely misleading result. That bug was real and the tests caught it.
    atr_period: int = 14
    rsi_period: int = 14

    # ── risk geometry ──────────────────────────────────────────────────────────
    #: The stop must clear the box edge it was placed beyond, by this many ATRs.
    #: Inherited from v1's structural stop (docs/ANALYSIS-2026-10-05), which is the
    #: one v1 rule with a clean measured justification: 63.8% of its stops sat
    #: *inside* the level the trade claimed to bounce off.
    stop_clear_atr: float = 0.5
    #: Floor on stop distance in ATRs, so a quiet tape cannot produce a stop so
    #: tight that cost dominates it. This is the explicit anti-v1 guard.
    min_stop_atr: float = 1.5
    #: Reward as a multiple of the realised risk.
    rr_target: float = 1.5
    #: Move the stop to entry once the trade is this far into profit, in R.
    #: v1 measured 0.30R as catastrophic (77% scratched) and 0.75R as tolerable.
    #: `None` disables the ratchet — and note that on v1's entries *no ratchet at
    #: all* was the better of the two measured options (-$150.97 vs -$381.77).
    breakeven_trigger_r: Optional[float] = 0.75
    #: Close at market after this many bars, whatever the P&L. On H4, 30 bars is
    #: five trading days.
    max_hold_bars: int = 30

    # ── the cost floor (the reason v2 exists) ──────────────────────────────────
    #: Round-trip cost in USD.
    cost_round_trip: float = DEFAULT_COST_ROUND_TRIP
    #: Refuse a setup whose risk is not at least this many times the round-trip
    #: cost. At 20x, cost is <=5% of R. v1's median was 7.2x (14.0% of R) and its
    #: 20-bar box entries ran at 5.1x (19.5% of R) — this is the guard that would
    #: have rejected them.
    min_risk_to_cost: float = 20.0

    # ── portfolio ──────────────────────────────────────────────────────────────
    #: One position at a time. Non-negotiable: every honest number in this repo is
    #: computed under a one-position convention, and the overlapping-events
    #: convention has already produced one vanished 10pp "edge"
    #: (docs/ANALYSIS-2026-10-21-box-chop-retest-alerts.md).
    max_open: int = 1
    #: Bars to sit out after a stop-out.
    cooldown_bars: int = 2
    #: Stop after this many stop-outs in one UTC day.
    max_daily_losses: int = 3
    #: USD of account risk per trade. Position sizing is a *separate* concern from
    #: the expectancy math and is not needed to judge a signal.
    risk_per_trade_usd: float = 10.0

    # ── bookkeeping ────────────────────────────────────────────────────────────
    #: Label written into every trade row and every report, so a result can never
    #: be quoted without the hypothesis that produced it.
    name: str = "v2-h4-pullback"

    def with_(self, **changes) -> "Config":
        """A copy with some fields replaced. Frozen dataclass, so this is the setter."""
        return replace(self, **changes)

    # ── derived quantities ─────────────────────────────────────────────────────
    @property
    def min_risk_usd(self) -> float:
        """Smallest risk (in $) this config is allowed to take a trade at."""
        return self.cost_round_trip * self.min_risk_to_cost

    @property
    def breakeven_wr(self) -> float:
        """Decisive win rate needed to break even at this payoff, cost-free.

        At reward = rr_target * risk, expectancy is zero when
        p * rr * risk == (1 - p) * risk, i.e. p == 1 / (1 + rr).
        """
        return 1.0 / (1.0 + self.rr_target)

    def breakeven_wr_after_cost(self, risk_usd: float) -> float:
        """The same, with the round trip charged. Always >= `breakeven_wr`.

        Net of a round trip c, a winner nets (rr*risk - c) and a loser nets
        -(risk + c), so expectancy is zero at

            p = (risk + c) / (risk * (1 + rr) + c)

        CHECK THIS AGAINST THE LEDGER, because it is the number the whole v2 design
        rests on: at v1's median risk $3.94 and the measured $0.55 round trip this
        returns 0.4318 — the 43.2% that v1's 37.9% decisive win rate fell short of.
        A form that charges cost against the winner's reward as well (the tempting
        `(risk + c) / (risk*(1+rr) + 2c)`, or the `(risk+c)/(2.5*risk+c)` shortcut
        that drops c from the reward) gives 0.4558 / 0.4289 and quietly moves the bar
        by 2.4pp. `goldbot/tests/test_core.py` pins 0.432.
        """
        if risk_usd <= 0:
            return 1.0
        c = self.cost_round_trip
        denom = risk_usd * (1.0 + self.rr_target) + c
        if denom <= 0:
            return 1.0
        return (risk_usd + c) / denom

    def validate(self) -> None:
        """Raise on a configuration that cannot mean what it says.

        Cheap and catches the class of bug that is otherwise invisible for weeks:
        a knob set to something that silently disables a guard.
        """
        if self.timeframe_minutes < 1:
            raise ValueError(f"timeframe_minutes must be >= 1, got {self.timeframe_minutes}")
        if self.lookback < 2:
            raise ValueError(f"lookback must be >= 2, got {self.lookback}")
        if self.ema_fast >= self.ema_slow:
            raise ValueError(f"ema_fast ({self.ema_fast}) must be < ema_slow ({self.ema_slow})")
        if not 0.0 <= self.wick_ratio_min <= 1.0:
            raise ValueError(f"wick_ratio_min must be in [0,1], got {self.wick_ratio_min}")
        if self.rr_target <= 0:
            raise ValueError(f"rr_target must be > 0, got {self.rr_target}")
        if self.min_stop_atr <= 0:
            raise ValueError(f"min_stop_atr must be > 0, got {self.min_stop_atr}")
        if self.min_risk_to_cost < 1.0:
            raise ValueError(
                f"min_risk_to_cost must be >= 1 (else cost exceeds risk), got {self.min_risk_to_cost}"
            )
        if self.cost_round_trip < 0:
            raise ValueError(f"cost_round_trip must be >= 0, got {self.cost_round_trip}")
        if self.breakeven_trigger_r is not None and self.breakeven_trigger_r <= 0:
            raise ValueError("breakeven_trigger_r must be > 0 or None")
        if self.atr_period < 1 or self.rsi_period < 1:
            raise ValueError("atr_period and rsi_period must be >= 1")
        if self.slope_bars < 1:
            raise ValueError(f"slope_bars must be >= 1, got {self.slope_bars}")
        if self.max_open < 1:
            raise ValueError(f"max_open must be >= 1, got {self.max_open}")


#: The default hypothesis. Named so that a result is never separable from it.
DEFAULT = Config()
