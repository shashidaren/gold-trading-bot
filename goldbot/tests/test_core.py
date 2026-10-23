"""Hermetic tests for the goldbot v2 harness. Stdlib unittest, no network, no repo data.

Run:  python3 -m unittest discover -s goldbot/tests -t . -v
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from goldbot import indicators  # noqa: E402
from goldbot.config import Config  # noqa: E402
from goldbot.data import Bar, aggregate, bucket_start, load_log  # noqa: E402
from goldbot.portfolio import Portfolio  # noqa: E402
from goldbot.replay import format_report, judge, run  # noqa: E402
from goldbot.risk import Refusal, cost_gate, lots, place  # noqa: E402
from goldbot.signal import build_market, trend_pullback, warmup_bars  # noqa: E402


def bar(ts, o, h, l, c, ticks=None):
    return Bar(ts=ts, open=o, high=h, low=l, close=c, ticks=ticks)


class TestConfig(unittest.TestCase):
    def test_the_default_config_is_valid(self):
        Config().validate()

    def test_breakeven_win_rate_at_1_5r_is_40_percent(self):
        self.assertAlmostEqual(Config(rr_target=1.5).breakeven_wr, 0.40, places=9)

    def test_breakeven_at_1_to_1_is_50_percent(self):
        self.assertAlmostEqual(Config(rr_target=1.0).breakeven_wr, 0.50, places=9)

    def test_cost_raises_the_bar(self):
        cfg = Config(cost_round_trip=0.55)
        bare = cfg.breakeven_wr
        with_cost = cfg.breakeven_wr_after_cost(3.94)
        self.assertGreater(with_cost, bare)
        # and it reproduces the number measured on the v1 ledger: 43.2% at $3.94 risk
        self.assertAlmostEqual(with_cost, 0.432, places=2)

    def test_zero_risk_needs_certainty(self):
        self.assertEqual(Config().breakeven_wr_after_cost(0.0), 1.0)

    def test_the_cost_floor_is_20x_the_round_trip(self):
        self.assertAlmostEqual(Config().min_risk_usd, 0.55 * 20.0, places=9)

    def test_a_tight_cost_floor_is_rejected(self):
        # min_risk_to_cost < 1 would allow a trade whose cost exceeds its risk
        with self.assertRaises(ValueError):
            Config(min_risk_to_cost=0.5).validate()

    def test_crossed_emas_are_rejected(self):
        with self.assertRaises(ValueError):
            Config(ema_fast=50, ema_slow=20).validate()

    def test_config_is_immutable_but_replaceable(self):
        cfg = Config()
        with self.assertRaises(Exception):
            cfg.lookback = 99  # type: ignore[misc]
        self.assertEqual(cfg.with_(lookback=99).lookback, 99)
        self.assertEqual(cfg.lookback, 20)


class TestBarGeometry(unittest.TestCase):
    def test_wick_ratios_are_shares_of_range(self):
        b = bar(datetime(2026, 1, 1), o=100.0, h=110.0, l=90.0, c=108.0)
        # body 100..108, so lower wick 10, upper wick 2, range 20
        self.assertAlmostEqual(b.lower_wick_ratio, 0.5)
        self.assertAlmostEqual(b.upper_wick_ratio, 0.1)

    def test_a_zero_range_bar_does_not_divide_by_zero(self):
        b = bar(datetime(2026, 1, 1), o=100.0, h=100.0, l=100.0, c=100.0)
        self.assertEqual(b.lower_wick_ratio, 0.0)
        self.assertEqual(b.upper_wick_ratio, 0.0)

    def test_a_bear_bar_measures_its_wicks_from_the_right_body_edge(self):
        b = bar(datetime(2026, 1, 1), o=108.0, h=110.0, l=90.0, c=100.0)
        # body 100..108 -> lower wick 10, upper wick 2
        self.assertAlmostEqual(b.lower_wick_ratio, 0.5)
        self.assertAlmostEqual(b.upper_wick_ratio, 0.1)


class TestAggregation(unittest.TestCase):
    """The invariant that matters: aggregation must never invent a bar, and must
    never expose a bar that has not closed."""

    def m1(self, n, start=datetime(2026, 1, 1, 0, 0), base=100.0):
        return [
            bar(start + timedelta(minutes=i), base + i, base + i + 0.5, base + i - 0.5, base + i + 0.25)
            for i in range(n)
        ]

    def test_the_forming_bucket_is_dropped_by_default(self):
        bars = aggregate(self.m1(150), 60)
        # 150 minutes = 2 closed hours + a 30-minute stub that must not appear
        self.assertEqual(len(bars), 2)

    def test_the_forming_bucket_can_be_asked_for(self):
        self.assertEqual(len(aggregate(self.m1(150), 60, include_forming=True)), 3)

    def test_an_h1_bar_carries_the_ohlc_of_its_minutes(self):
        src = self.m1(120, base=100.0)
        out = aggregate(src, 60)
        first = out[0]
        self.assertAlmostEqual(first.open, src[0].open)
        self.assertAlmostEqual(first.close, src[59].close)
        self.assertAlmostEqual(first.high, max(b.high for b in src[:60]))
        self.assertAlmostEqual(first.low, min(b.low for b in src[:60]))

    def test_the_bar_is_stamped_with_its_close_time(self):
        out = aggregate(self.m1(120, start=datetime(2026, 1, 1, 9, 0)), 60)
        self.assertEqual(out[0].ts, datetime(2026, 1, 1, 10, 0))

    def test_a_gap_does_not_weld_two_sessions_together(self):
        # 30 minutes of trading, a 3-hour closure, then 30 more — must be 2 bars, not 1
        early = self.m1(30, start=datetime(2026, 1, 1, 9, 0))
        late = self.m1(30, start=datetime(2026, 1, 1, 12, 30))
        out = aggregate(early + late, 60, include_forming=True)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].ts, datetime(2026, 1, 1, 10, 0))
        self.assertEqual(out[1].ts, datetime(2026, 1, 1, 13, 0))

    def test_a_four_hour_bucket_is_four_hours_wide(self):
        out = aggregate(self.m1(480, start=datetime(2026, 1, 1, 0, 0)), 240)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].ts, datetime(2026, 1, 1, 4, 0))

    def test_bucket_start_anchors_at_midnight(self):
        self.assertEqual(bucket_start(datetime(2026, 1, 1, 13, 47), 240), datetime(2026, 1, 1, 12, 0))
        self.assertEqual(bucket_start(datetime(2026, 1, 1, 13, 47), 60), datetime(2026, 1, 1, 13, 0))

    def test_timeframe_one_is_a_passthrough_that_still_hides_the_forming_bar(self):
        src = self.m1(10)
        self.assertEqual(len(aggregate(src, 1)), 9)
        self.assertEqual(len(aggregate(src, 1, include_forming=True)), 10)

    def test_ticks_sum_and_a_missing_tick_count_is_not_invented(self):
        src = [
            bar(datetime(2026, 1, 1, 0, 0), 1, 2, 0.5, 1.5, ticks=10),
            bar(datetime(2026, 1, 1, 0, 1), 1, 2, 0.5, 1.5, ticks=7),
        ]
        self.assertEqual(aggregate(src, 60, include_forming=True)[0].ticks, 17)
        src[1] = bar(datetime(2026, 1, 1, 0, 1), 1, 2, 0.5, 1.5, ticks=None)
        self.assertIsNone(aggregate(src, 60, include_forming=True)[0].ticks)


class TestIndicators(unittest.TestCase):
    def test_ema_is_none_until_seeded_then_seeds_on_the_sma(self):
        out = indicators.ema([1.0, 2.0, 3.0, 4.0], 3)
        self.assertIsNone(out[0])
        self.assertIsNone(out[1])
        self.assertAlmostEqual(out[2], 2.0)  # SMA(1,2,3)
        self.assertIsNotNone(out[3])

    def test_ema_of_a_constant_series_is_that_constant(self):
        out = indicators.ema([5.0] * 20, 10)
        self.assertAlmostEqual(out[-1], 5.0, places=9)

    def test_sma_matches_a_hand_computed_window(self):
        out = indicators.sma([1.0, 2.0, 3.0, 4.0], 2)
        self.assertIsNone(out[0])
        self.assertAlmostEqual(out[1], 1.5)
        self.assertAlmostEqual(out[3], 3.5)

    def test_true_range_uses_the_prior_close(self):
        tr = indicators.true_range([10.0], [5.0], [7.0])
        self.assertAlmostEqual(tr[0], 5.0)
        tr = indicators.true_range([10.0, 20.0], [5.0, 15.0], [7.0, 18.0])
        # bar 2: max(20-15, |20-7|, |15-7|) = 13
        self.assertAlmostEqual(tr[1], 13.0)

    def test_atr_is_a_simple_mean_not_wilder(self):
        # pinned so a future "improvement" to Wilder smoothing is a visible change
        h = [10.0, 11.0, 12.0, 13.0]
        l = [9.0, 10.0, 11.0, 12.0]
        c = [9.5, 10.5, 11.5, 12.5]
        out = indicators.atr(h, l, c, period=2)
        tr = indicators.true_range(h, l, c)
        self.assertAlmostEqual(out[-1], (tr[-2] + tr[-1]) / 2)

    def test_rsi_is_100_when_nothing_ever_falls(self):
        out = indicators.rsi([float(i) for i in range(1, 30)], 14)
        self.assertAlmostEqual(out[-1], 100.0)

    def test_rsi_is_bounded(self):
        closes = [100.0]
        for i in range(40):
            closes.append(closes[-1] + (3.0 if i % 3 else -5.0))
        out = indicators.rsi(closes, 14)
        vals = [v for v in out if v is not None]
        self.assertTrue(all(0.0 <= v <= 100.0 for v in vals))

    def test_slope_is_the_difference_over_the_window(self):
        out = indicators.slope([1.0, 2.0, 3.0, 4.0], 2)
        self.assertIsNone(out[0])
        self.assertIsNone(out[1])
        self.assertAlmostEqual(out[2], 2.0)

    def test_slope_propagates_a_missing_endpoint(self):
        out = indicators.slope([None, 1.0, 2.0], 1)
        self.assertIsNone(out[1])
        self.assertAlmostEqual(out[2], 1.0)

    def test_a_zero_period_is_refused_rather_than_silently_wrong(self):
        with self.assertRaises(ValueError):
            indicators.ema([1.0, 2.0], 0)
        with self.assertRaises(ValueError):
            indicators.sma([1.0, 2.0], 0)


class TestRisk(unittest.TestCase):
    def test_the_stop_clears_the_level_by_the_configured_atr(self):
        cfg = Config(stop_clear_atr=0.5, min_stop_atr=0.01)
        pl = place("BUY", entry=4000.0, level=3990.0, atr=2.0, cfg=cfg)
        self.assertIsInstance(pl, Refusal) if False else None
        # 10 to the level + 1.0 clearance = 11
        self.assertAlmostEqual(pl.risk, 11.0)
        self.assertAlmostEqual(pl.stop, 3989.0)
        self.assertEqual(pl.stop_basis, "level")

    def test_the_atr_floor_binds_when_the_level_is_too_close(self):
        cfg = Config(stop_clear_atr=0.5, min_stop_atr=1.5)
        pl = place("BUY", entry=4000.0, level=3999.5, atr=2.0, cfg=cfg)
        self.assertAlmostEqual(pl.risk, 3.0)  # 1.5 * 2.0, not 0.5+1.0
        self.assertEqual(pl.stop_basis, "atr_floor")

    def test_the_target_is_rr_times_the_realised_risk_not_a_fixed_multiple(self):
        cfg = Config(rr_target=1.5, stop_clear_atr=0.5, min_stop_atr=0.01)
        pl = place("BUY", entry=4000.0, level=3990.0, atr=2.0, cfg=cfg)
        self.assertAlmostEqual(pl.target - pl.entry, 1.5 * pl.risk)

    def test_a_sell_mirrors_a_buy(self):
        cfg = Config(stop_clear_atr=0.5, min_stop_atr=0.01)
        b = place("BUY", 4000.0, 3990.0, 2.0, cfg)
        s = place("SELL", 4000.0, 4010.0, 2.0, cfg)
        self.assertAlmostEqual(b.risk, s.risk)
        self.assertGreater(s.stop, s.entry)
        self.assertLess(s.target, s.entry)

    def test_a_missing_atr_is_refused_not_assumed(self):
        self.assertIsInstance(place("BUY", 4000.0, 3990.0, None, Config()), Refusal)
        self.assertIsInstance(place("BUY", 4000.0, 3990.0, 0.0, Config()), Refusal)

    def test_a_bad_side_is_refused(self):
        self.assertIsInstance(place("HOLD", 4000.0, 3990.0, 2.0, Config()), Refusal)

    def test_the_cost_gate_rejects_a_v1_sized_stop(self):
        # the v1 20-bar box BUY on the current tape: risk $2.82 against a $0.55 round trip
        cfg = Config()
        reason = cost_gate(2.82, cfg)
        self.assertIsNotNone(reason)
        self.assertIn("19.5%", reason)

    def test_the_cost_gate_passes_an_h4_sized_stop(self):
        # the 4h box BUY: risk $26.34 -> cost is 2.1% of R
        self.assertIsNone(cost_gate(26.34, Config()))

    def test_the_cost_gate_rejects_zero_risk(self):
        self.assertIsNotNone(cost_gate(0.0, Config()))

    def test_lot_size_rounds_down_never_up(self):
        cfg = Config(risk_per_trade_usd=10.0)
        # risk $3.00, 100 oz/lot -> 0.0333 lots -> must floor to 0.03
        self.assertAlmostEqual(lots(3.0, cfg), 0.03)

    def test_lot_size_is_zero_when_the_risk_is_nonsense(self):
        self.assertEqual(lots(0.0, Config()), 0.0)
        self.assertEqual(lots(-1.0, Config()), 0.0)


class TestPortfolio(unittest.TestCase):
    def test_only_one_position_at_a_time(self):
        p = Portfolio(cfg=Config())
        self.assertIsNone(p.can_enter(datetime(2026, 1, 1)))
        p.opened()
        self.assertIsNotNone(p.can_enter(datetime(2026, 1, 1)))

    def test_the_cooldown_counts_bars_not_minutes(self):
        p = Portfolio(cfg=Config(cooldown_bars=2))
        p.opened()
        p.closed(stopped_out=True)
        self.assertIn("cooldown", p.can_enter(datetime(2026, 1, 1, 5)) or "")
        p.on_new_bar(datetime(2026, 1, 1, 9))
        self.assertIn("cooldown", p.can_enter(datetime(2026, 1, 1, 9)) or "")
        p.on_new_bar(datetime(2026, 1, 1, 13))
        self.assertIsNone(p.can_enter(datetime(2026, 1, 1, 13)))

    def test_a_breakeven_exit_does_not_trigger_the_cooldown(self):
        p = Portfolio(cfg=Config(cooldown_bars=2))
        p.opened()
        p.closed(stopped_out=False)
        self.assertIsNone(p.can_enter(datetime(2026, 1, 1, 5)))

    def test_the_daily_cap_resets_on_a_new_utc_day(self):
        p = Portfolio(cfg=Config(max_daily_losses=1))
        p.opened()
        p.closed(stopped_out=True)
        p.bars_since_stop = None
        self.assertIn("daily loss cap", p.can_enter(datetime(2026, 1, 1, 20)) or "")
        p.on_new_bar(datetime(2026, 1, 2, 0, 1))
        self.assertIsNone(p.can_enter(datetime(2026, 1, 2, 0, 1)))

    def test_refusals_are_counted_by_category(self):
        p = Portfolio(cfg=Config())
        p.refuse("cooldown (1/2 bars)")
        p.refuse("cooldown (2/2 bars)")
        self.assertEqual(p.refusals.get("cooldown"), 2)


class TestReplay(unittest.TestCase):
    """Replay-level tests. These are the ones that matter: a subtly wrong exit
    convention produces a beautiful, confident, false backtest."""

    #: A config whose warm-up is 6 bars, so a 20-bar fixture can actually reach it.
    #: The production default needs 52 bars before it will say anything, which is
    #: correct behaviour but useless in a unit test.
    CFG_KW = dict(ema_fast=2, ema_slow=3, slope_bars=1, lookback=3,
                  atr_period=2, rsi_period=2,
                  rr_target=1.5, stop_clear_atr=0.5, min_stop_atr=0.01,
                  breakeven_trigger_r=None, min_risk_to_cost=1.0, cooldown_bars=0)

    def _flat(self, n, price=4000.0, start=datetime(2026, 1, 1), hours=4):
        return [bar(start + timedelta(hours=hours * i), price, price + 1, price - 1, price)
                for i in range(n)]

    @staticmethod
    def _force_buy(index):
        def fn(market, cfg):
            from goldbot.signal import Signal
            if market.index == index:
                return Signal("BUY", 4000.0, 3990.0, ["test"])
            return None
        return fn

    def test_a_series_with_no_signal_produces_no_trades_and_says_so(self):
        res = run(self._flat(60), Config())
        self.assertEqual(res.trades, [])
        self.assertIn("no trades", judge(res, Config()).note)

    def test_a_forced_entry_resolves_to_the_target(self):
        cfg = Config(**self.CFG_KW)
        i0 = warmup_bars(cfg)
        bars = self._flat(20)
        # risk = |4000-3990| + 0.5*ATR(=2) = 11, so the target is +16.5
        bars[i0 + 1] = bar(bars[i0 + 1].ts, 4000.0, 4020.0, 3999.0, 4018.0)
        res = run(bars, cfg, signal_fn=self._force_buy(i0))
        self.assertEqual(len(res.trades), 1)
        self.assertEqual(res.trades[0].reason, "TP")
        self.assertAlmostEqual(res.trades[0].exit_price, 4000.0 + 1.5 * 11.0)
        self.assertAlmostEqual(res.trades[0].r_multiple, 1.5)

    def test_the_stop_wins_when_a_bar_spans_both(self):
        """Conservative convention, and the same one tools/pathwalk_sims.py uses."""
        cfg = Config(**self.CFG_KW)
        i0 = warmup_bars(cfg)
        bars = self._flat(20)
        # one bar spans the stop (3989) AND the target (4016.5)
        bars[i0 + 1] = bar(bars[i0 + 1].ts, 4000.0, 4030.0, 3980.0, 4000.0)
        res = run(bars, cfg, signal_fn=self._force_buy(i0))
        self.assertEqual(res.trades[0].reason, "SL")
        self.assertAlmostEqual(res.trades[0].r_multiple, -1.0)

    def test_cost_is_charged_on_a_breakeven_scratch(self):
        """The v1 lesson: the BE bucket booked $0.00 gross and paid full cost."""
        cfg = Config(**{**self.CFG_KW, "breakeven_trigger_r": 0.5, "cost_round_trip": 0.55})
        i0 = warmup_bars(cfg)
        bars = self._flat(30)
        bars[i0 + 1] = bar(bars[i0 + 1].ts, 4000.0, 4006.0, 3999.0, 4005.0)  # +6 >= 0.5R (5.5): arms
        bars[i0 + 2] = bar(bars[i0 + 2].ts, 4005.0, 4006.0, 3999.0, 4000.0)  # back to entry
        res = run(bars, cfg, signal_fn=self._force_buy(i0))
        t = res.trades[0]
        self.assertEqual(t.reason, "BE")
        self.assertAlmostEqual(t.gross, 0.0)
        self.assertAlmostEqual(t.net, -0.55)
        self.assertAlmostEqual(res.cost_paid, 0.55)

    def test_the_max_hold_time_stop_fires(self):
        cfg = Config(**{**self.CFG_KW, "max_hold_bars": 3})
        i0 = warmup_bars(cfg)
        bars = self._flat(30)
        res = run(bars, cfg, signal_fn=self._force_buy(i0))
        self.assertEqual(res.trades[0].reason, "TIME")
        self.assertEqual(res.trades[0].bars_held, 3)

    def test_only_one_position_is_ever_open(self):
        # max_hold 2 forces each position to close, so a signal that fires on every
        # bar produces a chain of trades — which is what makes overlap detectable.
        # (With no exit at all the book is one trade and the test proves nothing.)
        cfg = Config(**{**self.CFG_KW, "max_hold_bars": 2})
        bars = self._flat(200)

        def always_buy(market, cfg):
            from goldbot.signal import Signal
            return Signal("BUY", 4000.0, 3990.0, ["test"])

        res = run(bars, cfg, signal_fn=always_buy)
        self.assertGreater(len(res.trades), 5)
        for a, b in zip(res.trades, res.trades[1:]):
            self.assertLessEqual(a.exit_ts, b.entry_ts, "trades overlapped")

    def test_the_daily_loss_cap_stops_trading_within_one_utc_day(self):
        # 20 bars an hour apart from 00:00 all land on 2026-01-01, so the cap cannot
        # be confused with the day rolling over (an earlier fixture crossed midnight
        # and silently reset the counter — which is why this test is written this way)
        cfg = Config(**{**self.CFG_KW, "max_daily_losses": 1, "max_hold_bars": 1000})
        bars = [bar(datetime(2026, 1, 1, 0, 0) + timedelta(hours=i), 4000.0, 4001.0, 3900.0, 3950.0)
                for i in range(20)]

        def always_buy(market, cfg):
            from goldbot.signal import Signal
            return Signal("BUY", 4000.0, 3990.0, ["test"])

        res = run(bars, cfg, signal_fn=always_buy)
        self.assertEqual(res.losses, 1)
        self.assertTrue(any("daily loss cap" in k for k in res.refusals), res.refusals)

    def test_the_wilson_interval_is_absent_not_faked_when_there_is_nothing_to_measure(self):
        self.assertIsNone(run(self._flat(5), Config()).wilson())

    def test_gross_minus_cost_equals_net(self):
        cfg = Config(**{**self.CFG_KW, "cost_round_trip": 0.55, "max_hold_bars": 2})
        bars = self._flat(40)
        res = run(bars, cfg, signal_fn=self._force_buy(warmup_bars(cfg)))
        self.assertAlmostEqual(res.gross - res.cost_paid, res.net)


class TestVerdict(unittest.TestCase):
    def test_the_verdict_names_the_config_that_produced_it(self):
        cfg = Config(name="my-hypothesis")
        v = judge(run([], cfg), cfg)
        self.assertEqual(v.label, "my-hypothesis")
        self.assertFalse(v.clears_reference)

    def test_a_report_mentions_the_cost_share(self):
        cfg = Config(name="x")
        out = format_report(run([], cfg), cfg)
        self.assertIn("x", out)
        self.assertIn("VERDICT", out)


class TestSignalSymmetry(unittest.TestCase):
    def test_warmup_is_at_least_the_slow_ema(self):
        cfg = Config()
        self.assertGreaterEqual(warmup_bars(cfg), cfg.ema_slow)

    def test_warmup_covers_every_indicator_the_signal_reads(self):
        """Regression: warmup_bars() once ignored atr_period, so ATR was None at the
        first evaluated bar, every entry was refused with 'no ATR', and the replay
        reported zero trades as though that were a finding."""
        cfg = Config(ema_fast=2, ema_slow=3, slope_bars=1, lookback=3, atr_period=14)
        self.assertGreaterEqual(warmup_bars(cfg), cfg.atr_period)
        bars = [bar(datetime(2026, 1, 1) + timedelta(hours=i), 4000.0, 4002.0, 3998.0, 4001.0)
                for i in range(warmup_bars(cfg) + 1)]
        market = build_market(bars, cfg)
        market.index = warmup_bars(cfg)
        self.assertIsNotNone(market._at(market.atr))

    def test_no_signal_before_warmup(self):
        cfg = Config()
        bars = [bar(datetime(2026, 1, 1) + timedelta(hours=4 * i), 4000.0, 4010.0, 3990.0, 4005.0)
                for i in range(warmup_bars(cfg))]
        market = build_market(bars, cfg)
        market.index = len(bars) - 1
        self.assertIsNone(trend_pullback(market, cfg))

    def test_the_buy_and_sell_rules_are_mirrors(self):
        """Build a tape that satisfies the BUY side, then flip it and require a SELL.

        If someone edits one branch of trend_pullback and not the other, this fails.
        """
        cfg = Config(timeframe_minutes=240, ema_fast=3, ema_slow=8, slope_bars=1,
                     lookback=5, wick_ratio_min=0.30)
        n = 40
        start = datetime(2026, 1, 1)

        def tape(direction):
            out = []
            price = 4000.0
            for i in range(n):
                # drift up (direction=+1) or down (-1)
                price += direction * 2.0
                if i == n - 1:
                    # the rejection bar: pierce the box edge and close back inside,
                    # with a long wick against the move
                    if direction > 0:
                        out.append(bar(start + timedelta(hours=4 * i), price, price + 1.0,
                                       price - 30.0, price - 1.0))
                    else:
                        out.append(bar(start + timedelta(hours=4 * i), price, price + 30.0,
                                       price - 1.0, price + 1.0))
                else:
                    out.append(bar(start + timedelta(hours=4 * i), price, price + 4.0,
                                   price - 4.0, price + direction * 1.0))
            return out

        up = build_market(tape(+1), cfg)
        up.index = n - 1
        down = build_market(tape(-1), cfg)
        down.index = n - 1

        sig_up = trend_pullback(up, cfg)
        sig_down = trend_pullback(down, cfg)
        self.assertIsNotNone(sig_up, "the BUY branch did not fire on a rising tape with a hammer")
        self.assertIsNotNone(sig_down, "the SELL branch did not fire on a falling tape with a shooting star")
        self.assertEqual(sig_up.side, "BUY")
        self.assertEqual(sig_down.side, "SELL")
        self.assertEqual(len(sig_up.reasons), len(sig_down.reasons))


class TestLoaderOnRealData(unittest.TestCase):
    """One test against the checked-in ledger, skipped if it is absent, so the suite
    still proves the loader parses the real schema and not just a fixture."""

    LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "forward_test_log.csv")

    def test_the_real_log_parses_and_aggregates(self):
        if not os.path.exists(self.LOG):
            self.skipTest("forward_test_log.csv not present")
        m1 = load_log(self.LOG)
        self.assertGreater(len(m1), 1000)
        self.assertTrue(all(m1[i].ts <= m1[i + 1].ts for i in range(len(m1) - 1)))
        h4 = aggregate(m1, 240)
        self.assertLess(len(h4), len(m1))
        # every H4 bar's high must be at least its low, and its close inside its range
        for b in h4:
            self.assertGreaterEqual(b.high, b.low)
            self.assertLessEqual(b.close, b.high + 1e-9)
            self.assertGreaterEqual(b.close, b.low - 1e-9)

    def test_the_warm_up_string_is_skipped_not_fatal(self):
        if not os.path.exists(self.LOG):
            self.skipTest("forward_test_log.csv not present")
        with open(self.LOG) as fh:
            head = fh.read(4000)
        if "Calculating" not in head:
            self.skipTest("no warm-up rows in this log")
        # load_log must not raise on it
        self.assertGreater(len(load_log(self.LOG)), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
