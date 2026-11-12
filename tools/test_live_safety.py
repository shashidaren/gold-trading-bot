#!/usr/bin/env python3
"""Hermetic tests for the LIVE pre-order safety guards (plan step B4, 2026-11-12).

    python3 tools/test_live_safety.py

B4 closes the last three code TODO items on the LIVE gate:

  * **disconnect_safety** - `terminal_info()` must report `connected` AND
    `trade_allowed` before a real order is sent; every failure mode (exception,
    None, missing flag) refuses the trade rather than guessing.
  * **sizing_limits** - the lot size must sit on the BROKER's own
    volume_min/volume_step/volume_max grid, and SL/TP must clear its
    stops/freeze distance. `volume_max` was never consulted before this change.
  * **cost_guard** - the measured live round-trip spread must be under
    `LIVE_COST_MAX_PCT_OF_R` of the trade's 1R. The flat $0.60 cap it replaces
    let the measured $0.55 median spread through at up to 25% of the smallest R.

Every test is pure: no network, no broker, no /opt/gold, no wall clock, and the
paper path is never entered. The order path itself is driven end-to-end against
a fake broker in `tools/smoke_test.py` Scenario AD.

Evidence + the measured threshold: docs/ANALYSIS-2026-11-12-b4-live-order-safety.md
"""
import os
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

# engine.py imports optional third-party modules at import time; stub them so the
# suite runs in a bare checkout (same trick as test_live_readiness.py).
for _name in ("requests", "dotenv", "twelvedata"):
    if _name not in sys.modules:
        _m = types.ModuleType(_name)
        if _name == "requests":
            _m.post = lambda *a, **k: None
            _m.get = lambda *a, **k: None
        if _name == "dotenv":
            _m.load_dotenv = lambda *a, **k: None
        if _name == "twelvedata":
            _m.TDClient = object
        sys.modules[_name] = _m

import engine  # noqa: E402


class _TempData(unittest.TestCase):
    """Construct GoldEngine against a temp dir so a test never touches /opt/gold."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = self._tmp.name
        self._saved = (engine.LOG_FILE_PATH, engine.STATUS_FILE_PATH,
                       engine.TRADES_LOG_PATH, getattr(engine, "mt5", None),
                       hasattr(engine, "mt5"))
        engine.LOG_FILE_PATH = os.path.join(d, "forward_test_log.csv")
        engine.STATUS_FILE_PATH = os.path.join(d, "status.json")
        engine.TRADES_LOG_PATH = os.path.join(d, "trades.csv")

    def tearDown(self):
        engine.LOG_FILE_PATH, engine.STATUS_FILE_PATH, engine.TRADES_LOG_PATH = self._saved[:3]
        if self._saved[4]:
            engine.mt5 = self._saved[3]
        elif hasattr(engine, "mt5"):
            delattr(engine, "mt5")
        self._tmp.cleanup()

    def engine_with(self, fake):
        engine.mt5 = fake
        return engine.GoldEngine()


class _Terminal:
    def __init__(self, connected=True, trade_allowed=True):
        self.connected = connected
        self.trade_allowed = trade_allowed


class _Spec:
    """The captured XM GOLD spec, as `symbol_info()` reports it."""

    def __init__(self, volume_min=0.01, volume_max=50.0, volume_step=0.01,
                 stops=0, freeze=0, point=0.01, filling_mode=2):
        self.volume_min = volume_min
        self.volume_max = volume_max
        self.volume_step = volume_step
        self.trade_stops_level = stops
        self.trade_freeze_level = freeze
        self.point = point
        self.filling_mode = filling_mode


class _Tick:
    def __init__(self, bid, ask):
        self.bid = bid
        self.ask = ask


class _Acct:
    def __init__(self, balance=500.0, margin_free=None):
        self.balance = balance
        self.margin_free = margin_free


_UNSET = object()   # "this broker call returns nothing" - distinct from "use the default"


class _Fake:
    """`_UNSET` keeps its default; passing None/Exception means the call yields that."""

    leverage = 1000   # the captured XM spec; order_calc_margin uses it

    def order_calc_margin(self, order_type, symbol, volume, price):
        if self._margin is not _UNSET:
            if isinstance(self._margin, Exception):
                raise self._margin
            return self._margin
        return volume * 100.0 * price / self.leverage

    def __init__(self, term=_UNSET, spec=_UNSET, tick=_UNSET, margin=_UNSET):
        self._term = _Terminal() if term is _UNSET else term
        self._spec = _Spec() if spec is _UNSET else spec
        self._tick = _Tick(4000.00, 4000.55) if tick is _UNSET else tick
        self._margin = margin

    def terminal_info(self):
        if isinstance(self._term, Exception):
            raise self._term
        return self._term

    def symbol_info(self, symbol):
        if isinstance(self._spec, Exception):
            raise self._spec
        return self._spec

    def symbol_info_tick(self, symbol):
        if isinstance(self._tick, Exception):
            raise self._tick
        return self._tick


class TestConnectionGuard(unittest.TestCase):
    def test_connected_and_trade_allowed_passes(self):
        for term, spec, tick in (
            (_Terminal(True, True), _Spec(), _Tick(4000.0, 4000.55)),
            (_Terminal(True, True), _Spec(), _Tick(4000.0, 4000.1)),
        ):
            self.assertIsNone(engine.live_connection_problem(_Fake(term=term, spec=spec, tick=tick)))

    def test_every_failure_mode_refuses(self):
        cases = {
            "no module": None,
            "terminal_info None": _Fake(term=None),
            "exception": _Fake(term=ConnectionError("terminal not connected")),
            "disconnected": _Fake(term=_Terminal(connected=False)),
            "autotrading off": _Fake(term=_Terminal(True, trade_allowed=False)),
        }
        for label, fake in cases.items():
            with self.subTest(label):
                self.assertIsNotNone(engine.live_connection_problem(fake), label)

    def test_missing_fields_are_not_assumed_true(self):
        """An object without `connected` must fail CLOSED, not default to True."""

        class _Bare:
            pass

        self.assertIsNotNone(engine.live_connection_problem(_Fake(term=_Bare())))


class TestSymbolLimits(unittest.TestCase):
    def test_captured_spec_reads_cleanly(self):
        limits, reason = engine.live_symbol_limits(_Fake(spec=_Spec()), "GOLD")
        self.assertIsNone(reason)
        self.assertEqual(limits["volume_min"], 0.01)
        self.assertEqual(limits["volume_max"], 50.0)
        self.assertEqual(limits["volume_step"], 0.01)
        self.assertEqual(limits["stops_level"], 0.0)

    def test_unreadable_spec_refuses(self):
        for spec in (None, ValueError("bad spec"), _Spec(volume_max=0.0),
                     _Spec(volume_step=0.0)):
            with self.subTest(spec=spec):
                limits, reason = engine.live_symbol_limits(_Fake(spec=spec), "GOLD")
                self.assertIsNone(limits)
                self.assertTrue(reason)


class TestSizingGuard(unittest.TestCase):
    def limits(self, **kw):
        return engine.live_symbol_limits(_Fake(spec=_Spec(**kw)), "GOLD")[0]

    def test_on_grid_sizes_pass(self):
        lim = self.limits()
        for lots in (0.01, 0.02, 0.10, 1.00, 50.0):
            self.assertIsNone(engine.live_sizing_problem(lots, lim), lots)

    def test_off_grid_and_out_of_range_refuse(self):
        lim = self.limits()
        cases = {
            "below min": 0.001,
            "above max": 51.0,
            "off step": 0.015,
            "zero": 0.0,
            "negative": -0.01,
            "none": None,
        }
        for label, lots in cases.items():
            with self.subTest(label):
                self.assertIsNotNone(engine.live_sizing_problem(lots, lim), label)

    def test_a_tightened_broker_max_is_respected(self):
        """The whole point: volume_max was never consulted before B4."""
        lim = self.limits(volume_max=0.5)
        self.assertIsNone(engine.live_sizing_problem(0.5, lim))
        self.assertIn("volume_max", engine.live_sizing_problem(0.51, lim))

    def test_missing_limits_never_pass(self):
        self.assertIsNotNone(engine.live_sizing_problem(0.01, None))


class TestStopDistanceGuard(unittest.TestCase):
    def test_zero_stops_level_is_inert(self):
        lim = engine.live_symbol_limits(_Fake(spec=_Spec(stops=0)), "GOLD")[0]
        self.assertIsNone(engine.live_stop_distance_problem("BUY", 4000.0, 3990.0, 4015.0, lim))
        self.assertIsNone(engine.live_stop_distance_problem("SELL", 4000.0, 4010.0, 3985.0, lim))

    def test_a_raised_stops_level_rejects_too_close_geometry(self):
        # 500 points x 0.01 = $5.00 minimum distance.
        lim = engine.live_symbol_limits(_Fake(spec=_Spec(stops=500)), "GOLD")[0]
        self.assertIsNone(engine.live_stop_distance_problem("BUY", 4000.0, 3995.0, 4007.5, lim))
        self.assertIn("SL", engine.live_stop_distance_problem("BUY", 4000.0, 3997.0, 4007.5, lim))
        self.assertIn("TP", engine.live_stop_distance_problem("BUY", 4000.0, 3994.0, 4003.0, lim))

    def test_inverted_geometry_refuses_even_with_zero_stops(self):
        lim = engine.live_symbol_limits(_Fake(spec=_Spec(stops=0)), "GOLD")[0]
        self.assertIsNotNone(engine.live_stop_distance_problem("BUY", 4000.0, 4005.0, 4015.0, lim))
        self.assertIsNotNone(engine.live_stop_distance_problem("SELL", 4000.0, 3990.0, 4015.0, lim))
        self.assertIsNotNone(engine.live_stop_distance_problem("HOLD", 4000.0, 3990.0, 4015.0, lim))


class TestCostGuard(unittest.TestCase):
    def test_the_measured_median_is_inside_the_limit(self):
        ok, reason, pct = engine.live_cost_guard(0.55, 5.88)
        self.assertTrue(ok)
        self.assertAlmostEqual(pct, 9.35, places=2)
        self.assertIn("9.4% of 1R", reason)

    def test_the_measured_worst_decile_is_vetoed(self):
        """$0.55 against a $2.25 structural risk is 24.4% of R, over the 20% bar."""
        ok, reason, pct = engine.live_cost_guard(0.55, 2.25)
        self.assertFalse(ok)
        self.assertAlmostEqual(pct, 24.44, places=2)
        self.assertIn("20% limit", reason)

    def test_boundary_is_inclusive(self):
        self.assertTrue(engine.live_cost_guard(2.0, 10.0)[0])       # exactly 20%
        self.assertFalse(engine.live_cost_guard(2.01, 10.0)[0])

    def test_unmeasurable_inputs_fail_closed(self):
        for cost, risk in ((None, 5.0), (0.55, None), (0.55, 0.0), (0.55, -1.0),
                           (float("nan"), 5.0), (-0.1, 5.0), ("x", 5.0)):
            with self.subTest(cost=cost, risk=risk):
                self.assertFalse(engine.live_cost_guard(cost, risk)[0])

    def test_threshold_matches_the_registered_constant(self):
        self.assertEqual(engine.LIVE_COST_MAX_PCT_OF_R, 20.0)


class TestMeasuredCost(_TempData):
    """`live_cost_measure` must MEASURE, never fall back to the $0.40 assumption."""

    def test_round_trip_is_twice_the_live_spread(self):
        eng = self.engine_with(_Fake(tick=_Tick(4000.00, 4000.55)))
        cost, source, why = eng.live_cost_measure()
        self.assertIsNone(why)
        self.assertEqual(source, "live_spread")
        self.assertAlmostEqual(cost, 1.10)
        ok, reason, pct = eng.live_cost_check(5.88)
        self.assertTrue(ok, reason)
        self.assertAlmostEqual(pct, 18.71, places=1)

    def test_no_tick_means_no_cost_and_the_trade_is_refused(self):
        eng = self.engine_with(_Fake(tick=None))
        self.assertIsNone(eng.live_cost_measure()[0])
        ok, reason, pct = eng.live_cost_check(5.88)
        self.assertFalse(ok)
        self.assertIsNone(pct)
        self.assertIn("could not be measured", reason)

    def test_a_broken_or_inverted_quote_is_not_a_cheap_quote(self):
        """A zero/inverted quote cannot PROVE a small cost, so it must refuse.

        This is the fail-open the first cut had: spread 0 made the measured cost
        0.0, which passes every percentage limit. Gold never trades at zero
        spread on this broker (measured median $0.55), so a zero read is a data
        fault - and a fault is not a cheap trade.
        """
        for tick in (_Tick(4000.0, 4000.0), _Tick(4000.5, 4000.0), _Tick(0, 0)):
            with self.subTest(tick=tick.__dict__):
                eng = self.engine_with(_Fake(tick=tick))
                self.assertIsNone(eng.live_cost_measure()[0])
                self.assertFalse(eng.live_cost_check(5.88)[0])

    def test_an_unresponsive_terminal_refuses_rather_than_guessing(self):
        eng = self.engine_with(_Fake(tick=ConnectionError("terminal dropped")))
        self.assertIsNone(eng.live_cost_measure()[0])
        self.assertFalse(eng.live_cost_check(5.88)[0])


class TestMarginGuard(_TempData):
    """Margin comes from the broker's own order_calc_margin(), so leverage is right.

    The captured XM spec is 1:1000: 0.01 lot of GOLD is ~$4 of margin on a
    ~$4,000 notional. Pricing the notional directly (the first cut of this guard)
    overstates the requirement 1000x and would refuse every sound order, so this
    class pins that the BROKER's answer is what is used.
    """

    def test_leveraged_small_order_passes(self):
        eng = self.engine_with(_Fake())
        # 0.01 lot x 100 x $4000 / 1000 leverage = $4.00 of $10,000 free = 0.04%.
        self.assertIsNone(eng.live_free_margin_problem(_Acct(margin_free=10000.0),
                                                      0.01, 4000.0))

    def test_unreported_free_margin_refuses(self):
        eng = self.engine_with(_Fake())
        self.assertIn("margin_free", eng.live_free_margin_problem(_Acct(margin_free=None),
                                                                 0.01, 4000.0))

    def test_an_order_that_eats_the_account_refuses(self):
        eng = self.engine_with(_Fake())
        # 1.0 lot needs 1.0 x 100 x $4000 / 1000 = $400.00 of $500.00 free = 80%.
        self.assertIn("limit is 70%",
                      eng.live_free_margin_problem(_Acct(margin_free=500.0), 1.0, 4000.0))
        # The same order on a funded account is fine (0.4% of $100,000).
        self.assertIsNone(eng.live_free_margin_problem(_Acct(margin_free=100000.0),
                                                      1.0, 4000.0))

    def test_an_unanswerable_broker_refuses(self):
        """No answer (None) or an exception must refuse - never estimate."""
        for fake, label in ((_Fake(margin=None), "returns nothing"),
                            (_Fake(margin=ValueError("no such symbol")), "raises")):
            with self.subTest(label):
                eng = self.engine_with(fake)
                self.assertIsNotNone(eng.live_free_margin_problem(
                    _Acct(margin_free=10000.0), 0.01, 4000.0), label)

    def test_non_positive_margin_or_price_refuses(self):
        eng = self.engine_with(_Fake())
        for free, price in ((0.0, 4000.0), (-5.0, 4000.0), (10000.0, 0.0)):
            with self.subTest(free=free, price=price):
                self.assertIsNotNone(eng.live_free_margin_problem(
                    _Acct(margin_free=free), 0.01, price))


class TestPaperPathUntouched(unittest.TestCase):
    def test_the_guards_are_never_reached_in_paper_mode(self):
        with open(os.path.join(ROOT, "engine.py"), encoding="utf-8") as fh:
            src = fh.read()
        execute_sim = src.split("def execute_simulated_trade", 1)[1].split("\n    def ", 1)[0]
        for name in ("live_connection_problem", "live_symbol_limits", "live_sizing_problem",
                     "live_cost_check", "live_cost_guard", "live_free_margin_problem",
                     "live_stop_distance_problem"):
            self.assertNotIn(name, execute_sim, f"{name} leaked into the paper path")

    def test_no_strategy_parameter_moved(self):
        self.assertEqual(engine.SL_CLEAR_ATR, 0.5)
        self.assertEqual(engine.BE_TRIGGER_R, 0.75)
        self.assertEqual(engine.MAX_HOLD_MINUTES, 240)
        self.assertEqual(engine.RR_TARGET, 1.5)
        self.assertEqual(engine.TRADING_MODE, "FORWARD_TEST")


if __name__ == "__main__":
    unittest.main(verbosity=2)
