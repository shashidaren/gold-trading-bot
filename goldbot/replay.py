"""Replay — the honest, costed, stateful backtest. This is the research harness.

WHY ANOTHER REPLAY, WHEN tools/strategy_lab.py EXISTS
-----------------------------------------------------
strategy_lab.py is canonical for the v1 rules and stays so; it replays v1's funnel,
v1's exits and v1's gates, and it is what a v1 rule change must be judged with. It
cannot replay a v2 signal at a different timeframe, because v1's funnel is wired into
it. This module replays a `Config` + a signal function over any bar series, which is
the thing v2 needs in order to be testable at all.

THE CONVENTIONS, STATED SO A NUMBER CAN BE TRUSTED
--------------------------------------------------
* CLOSED BARS ONLY. A signal is evaluated on a bar that has closed, and the entry is
  that bar's close. No bar is ever read before it finishes.
* ONE POSITION. See portfolio.py.
* STOP BEFORE TARGET WITHIN A BAR. When a single bar spans both the stop and the
  target, the stop is assumed to hit first. This is conservative, and it is the same
  convention tools/pathwalk_sims.py uses, so the two are comparable.
* COST ON EVERY CLOSED TRADE, including scratches at breakeven. On v1's ledger the
  breakeven bucket booked $0.00 gross and paid $29.15 of cost for the privilege; a
  replay that nets cost against winners only would have hidden that.
* AGAINST A DRIFTLESS REFERENCE. A win rate means nothing next to nothing. The
  break-even decisive rate at this payoff is 1/(1+rr), and after cost it is higher;
  both are printed with every result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional, Sequence

from .config import Config
from .data import Bar, aggregate, load_log
from .portfolio import Portfolio
from .risk import Placement, Refusal, cost_gate, place
from .signal import Market, Signal, build_market, trend_pullback

SignalFn = Callable[[Market, Config], Optional[Signal]]


@dataclass(frozen=True)
class Trade:
    """One closed trade."""

    side: str
    entry_ts: datetime
    entry: float
    stop: float
    target: float
    exit_ts: datetime
    exit_price: float
    reason: str  # TP | SL | BE | TIME
    risk: float
    r_multiple: float
    gross: float  # in price units ($/oz), before cost
    net: float  # after the round trip
    stop_basis: str
    reasons: List[str]
    bars_held: int


@dataclass
class Result:
    """Everything needed to judge a hypothesis without re-running it."""

    config_name: str
    timeframe_minutes: int
    bars: int
    cost_round_trip: float = 0.0
    trades: List[Trade] = field(default_factory=list)
    refusals: Dict[str, int] = field(default_factory=dict)
    first_ts: Optional[datetime] = None
    last_ts: Optional[datetime] = None

    # ── counts ────────────────────────────────────────────────────────────────
    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.reason == "TP")

    @property
    def losses(self) -> int:
        return sum(1 for t in self.trades if t.reason == "SL")

    @property
    def scratches(self) -> int:
        return sum(1 for t in self.trades if t.reason in ("BE", "TIME"))

    @property
    def decisive(self) -> int:
        """TP+SL. Breakeven and time exits are neutral — the v1 convention, and the
        right one: a scratch is not a loss, it is a trade that did not happen."""
        return self.wins + self.losses

    # ── rates ─────────────────────────────────────────────────────────────────
    @property
    def win_rate(self) -> Optional[float]:
        return self.wins / self.decisive if self.decisive else None

    def wilson(self, z: float = 1.96):
        """Wilson score interval on the decisive win rate. (lower, upper) or None.

        Printed with every number in this repo because a 63.6% win rate on n=16 is
        not a finding — the journal has a bucket exactly like it.
        """
        n = self.decisive
        if n == 0:
            return None
        p = self.wins / n
        denom = 1.0 + z * z / n
        centre = (p + z * z / (2 * n)) / denom
        half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
        return (max(0.0, centre - half), min(1.0, centre + half))

    # ── money ─────────────────────────────────────────────────────────────────
    @property
    def gross(self) -> float:
        return sum(t.gross for t in self.trades)

    @property
    def cost_paid(self) -> float:
        """Total round trips paid, as a POSITIVE number.

        Charged on every closed trade, scratches included — the v1 lesson, where the
        breakeven bucket booked $0.00 gross and still paid $29.15.
        """
        return self.cost_round_trip * len(self.trades)

    @property
    def net(self) -> float:
        return sum(t.net for t in self.trades)

    def per_trade(self, value: float) -> float:
        return value / len(self.trades) if self.trades else 0.0

    @property
    def avg_r(self) -> float:
        return sum(t.r_multiple for t in self.trades) / len(self.trades) if self.trades else 0.0

    @property
    def median_risk(self) -> float:
        if not self.trades:
            return 0.0
        xs = sorted(t.risk for t in self.trades)
        mid = len(xs) // 2
        return xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2


@dataclass(frozen=True)
class Verdict:
    """The four lines a hypothesis is judged on. Nothing else is a verdict."""

    label: str
    n_trades: int
    decisive: int
    win_rate: Optional[float]
    wilson_low: Optional[float]
    breakeven_wr: float
    breakeven_wr_after_cost: float
    net: float
    net_per_trade: float
    avg_r: float
    median_risk: float
    cost_share_of_risk: Optional[float]
    clears_reference: bool
    note: str


def judge(res: Result, cfg: Config) -> Verdict:
    """Reduce a replay to the question that was actually pre-registered.

    "Clears the reference" means the Wilson LOWER bound on the decisive win rate is
    above the break-even rate *after cost*. That is a deliberately hard bar and it is
    the bar this repo already uses (docs/ANALYSIS-2026-10-20 §1): clearing the
    reference while losing money is not an edge, it is a good ratio.
    """
    wr = res.win_rate
    wil = res.wilson()
    med = res.median_risk
    be = cfg.breakeven_wr
    be_cost = cfg.breakeven_wr_after_cost(med) if med else be
    share = (cfg.cost_round_trip / med) if med else None
    clears = bool(wr is not None and wil is not None and wil[0] > be_cost)

    if not res.trades:
        note = "no trades — the signal never fired or every setup was refused"
    elif res.decisive < 30:
        note = f"only {res.decisive} decisive trades; too few to judge anything"
    elif clears:
        note = "Wilson lower bound clears the costed break-even — worth pre-registering"
    elif wr is not None and wr < be_cost:
        note = f"below the {100 * be_cost:.1f}% costed break-even"
    else:
        note = "inside noise: the interval straddles the costed break-even"

    return Verdict(
        label=cfg.name,
        n_trades=len(res.trades),
        decisive=res.decisive,
        win_rate=wr,
        wilson_low=None if wil is None else wil[0],
        breakeven_wr=be,
        breakeven_wr_after_cost=be_cost,
        net=res.net,
        net_per_trade=res.per_trade(res.net),
        avg_r=res.avg_r,
        median_risk=med,
        cost_share_of_risk=share,
        clears_reference=clears,
        note=note,
    )


def _resolve(bar: Bar, side: str, pl: Placement, be_armed: bool):
    """Which exit a bar produced, stop-first on ambiguity. Returns (reason, price)."""
    stop = pl.entry if be_armed else pl.stop
    if side == "BUY":
        hit_stop = bar.low <= stop
        hit_target = bar.high >= pl.target
    else:
        hit_stop = bar.high >= stop
        hit_target = bar.low <= pl.target
    if hit_stop:
        return ("BE" if be_armed else "SL"), stop
    if hit_target:
        return "TP", pl.target
    return None, None


def run(
    bars: Sequence[Bar],
    cfg: Config,
    signal_fn: SignalFn = trend_pullback,
) -> Result:
    """Replay `cfg` + `signal_fn` over a CLOSED-bar series. Pure: writes nothing."""
    cfg.validate()
    market = build_market(bars, cfg)
    book = Portfolio(cfg=cfg)
    res = Result(config_name=cfg.name, timeframe_minutes=cfg.timeframe_minutes, bars=len(bars),
                 cost_round_trip=cfg.cost_round_trip)
    if bars:
        res.first_ts, res.last_ts = bars[0].ts, bars[-1].ts

    open_trade: Optional[dict] = None

    for i, bar in enumerate(bars):
        market.index = i
        book.on_new_bar(bar.ts)

        # ── manage an open position first ──────────────────────────────────────
        if open_trade is not None:
            t = open_trade
            pl: Placement = t["placement"]
            be_armed = t["be_armed"]
            cfg_be = cfg.breakeven_trigger_r

            # arm the ratchet on this bar's favourable extreme
            if not be_armed and cfg_be is not None:
                fav = (bar.high - pl.entry) if t["side"] == "BUY" else (pl.entry - bar.low)
                if fav >= cfg_be * pl.risk:
                    be_armed = True
                    t["be_armed"] = True

            reason, price = _resolve(bar, t["side"], pl, be_armed)
            held = i - t["index"]
            if reason is None and held >= cfg.max_hold_bars:
                reason, price = "TIME", bar.close

            if reason is not None:
                gross = (price - pl.entry) if t["side"] == "BUY" else (pl.entry - price)
                res.trades.append(
                    Trade(
                        side=t["side"],
                        entry_ts=t["entry_ts"],
                        entry=pl.entry,
                        stop=pl.stop,
                        target=pl.target,
                        exit_ts=bar.ts,
                        exit_price=price,
                        reason=reason,
                        risk=pl.risk,
                        r_multiple=gross / pl.risk if pl.risk else 0.0,
                        gross=gross,
                        net=gross - cfg.cost_round_trip,
                        stop_basis=pl.stop_basis,
                        reasons=t["reasons"],
                        bars_held=held,
                    )
                )
                book.closed(stopped_out=reason == "SL")
                open_trade = None

        # ── then look for a new entry ──────────────────────────────────────────
        if open_trade is not None:
            continue
        sig = signal_fn(market, cfg)
        if sig is None:
            continue

        why = book.can_enter(bar.ts)
        if why is not None:
            book.refuse(why)
            continue

        atr_now = market._at(market.atr)
        outcome = place(sig.side, sig.price, sig.level, atr_now, cfg)
        if isinstance(outcome, Refusal):
            book.refuse(outcome.reason)
            continue

        gate = cost_gate(outcome.risk, cfg)
        if gate is not None:
            book.refuse(gate)
            continue

        book.opened()
        open_trade = {
            "side": sig.side,
            "placement": outcome,
            "entry_ts": bar.ts,
            "index": i,
            "be_armed": False,
            "reasons": list(sig.reasons),
        }

    res.refusals = dict(book.refusals)
    return res


def run_file(path: str, cfg: Config, signal_fn: SignalFn = trend_pullback) -> Result:
    """Load a forward_test_log.csv-schema file, aggregate to cfg's timeframe, replay."""
    m1 = load_log(path)
    bars = aggregate(m1, cfg.timeframe_minutes)
    return run(bars, cfg, signal_fn)


def format_report(res: Result, cfg: Config) -> str:
    """A printable verdict. Kept in the library so a CLI and a test share one truth."""
    v = judge(res, cfg)
    lines = [
        f"── {v.label} ──  ({res.bars} bars"
        f"{'' if res.first_ts is None else f', {res.first_ts:%Y-%m-%d} → {res.last_ts:%Y-%m-%d}'})",
        f"  trades {v.n_trades}   decisive {v.decisive}   "
        f"({res.wins}W/{res.losses}L/{res.scratches} scratch)",
    ]
    if v.win_rate is not None:
        wil = res.wilson()
        lines.append(
            f"  decisive WR {100 * v.win_rate:.1f}%  [95% {100 * wil[0]:.1f}–{100 * wil[1]:.1f}]"
            f"   needs {100 * v.breakeven_wr:.1f}% cost-free, {100 * v.breakeven_wr_after_cost:.1f}% after cost"
        )
    if v.median_risk:
        lines.append(
            f"  median risk ${v.median_risk:.2f}   round trip ${cfg.cost_round_trip:.2f} "
            f"= {100 * v.cost_share_of_risk:.1f}% of R"
            f"   (v1's median was 14.0%; its 20-bar box entries 19.5%)"
        )
    lines.append(
        f"  gross {res.gross:+.2f}   cost -{res.cost_paid:.2f}   net {res.net:+.2f}   "
        f"({v.net_per_trade:+.2f}/trade, avg {v.avg_r:+.3f}R)"
    )
    basis = {}
    for t in res.trades:
        basis[t.stop_basis] = basis.get(t.stop_basis, 0) + 1
    if basis:
        lines.append("  stop basis: " + "  ".join(f"{k}={n}" for k, n in sorted(basis.items())))
    if res.refusals:
        top = sorted(res.refusals.items(), key=lambda kv: -kv[1])[:5]
        lines.append("  refusals: " + "  ".join(f"{k} ({n})" for k, n in top))
    lines.append(f"  VERDICT: {'CLEARS' if v.clears_reference else 'does not clear'} the costed reference — {v.note}")
    return "\n".join(lines)
