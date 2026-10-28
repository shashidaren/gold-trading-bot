#!/usr/bin/env python3
"""Hermetic fake-MT5 tests for LIVE broker-side management (plan step B2, 2026-10-28).

    python3 tools/test_live_manage.py

The paper engine manages exits itself. In LIVE the broker holds the stop and the
target, so the two ENGINE-side rules -- the +0.75R BE ratchet and the 240-minute
time stop -- would silently stop existing unless they are mirrored at the broker.
These tests pin that mirror, and every way it could lie:

  * the modify/close REQUEST shapes (action, ticket as `position`, opposite side);
  * a rejection never books an outcome (no arm, no ledger row, no P&L);
  * one retry on a market-moved reject, none on a logic reject;
  * the stop only ever tightens, arming happens once, and only after DONE;
  * a broker-closed position ("gone") books NOTHING and blocks new entries;
  * state (ticket, sizing risk) survives a restart through status.json;
  * management keeps working while the process is DISARMED (risk-reducing only);
  * the paper mode is completely inert.

No network, no /opt/gold, no real broker, no wall clock beyond "now" for hold time.
Decision record: docs/DECISION-2026-10-28-b2-broker-be-and-time-stop.md.
"""
import json
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone

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


class _Result:
    def __init__(self, retcode, comment="", order=0, price=0.0):
        self.retcode = retcode
        self.comment = comment
        self.order = order
        self.price = price


class _Pos:
    def __init__(self, ticket=555, type=0, volume=0.01, sl=0.0, tp=0.0):
        self.ticket = ticket
        self.type = type
        self.volume = volume
        self.sl = sl
        self.tp = tp


class _Tick:
    def __init__(self, bid, ask):
        self.bid = bid
        self.ask = ask


class _Info:
    def __init__(self, filling_mode=2, point=0.01):
        self.filling_mode = filling_mode
        self.point = point


class _Account:
    def __init__(self, balance=500.0):
        self.balance = balance


class _FakeMT5:
    """Just enough MetaTrader5 to exercise the LIVE management path."""

    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_SLTP = 6
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_REQUOTE = 10004
    TRADE_RETCODE_PRICE_CHANGED = 10020
    TRADE_RETCODE_INVALID_STOPS = 10016
    ORDER_FILLING_FOK = 1
    ORDER_FILLING_IOC = 2
    ORDER_TIME_GTC = 0
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1

    def __init__(self, positions=None, script=None, bid=4000.0, ask=4000.2,
                 filling_mode=2):
        self.positions = list(positions or [])
        self.script = list(script or [])
        self.sent = []
        self.bid = bid
        self.ask = ask
        self.filling_mode = filling_mode

    # --- broker surface used by the engine ---
    def positions_get(self, ticket=None, symbol=None, magic=None):
        return [p for p in self.positions if ticket is None or p.ticket == ticket]

    def order_send(self, request):
        self.sent.append(dict(request))
        if self.script:
            return self.script.pop(0)
        return _Result(self.TRADE_RETCODE_DONE, "done",
                       order=request.get("position") or 777,
                       price=float(request.get("price", 0.0)))

    def symbol_info(self, symbol):
        return _Info(self.filling_mode)

    def symbol_info_tick(self, symbol):
        return _Tick(self.bid, self.ask)

    def account_info(self):
        return _Account(500.0)


class LiveManageCase(unittest.TestCase):
    """Builds a real GoldEngine against temp data files and a fake broker."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self._saved = {
            "LOG_FILE_PATH": engine.LOG_FILE_PATH,
            "STATUS_FILE_PATH": engine.STATUS_FILE_PATH,
            "TRADES_LOG_PATH": engine.TRADES_LOG_PATH,
            "TRADING_MODE": engine.TRADING_MODE,
            "live_armed": engine.live_armed,
            "LIVE_MGMT_BACKOFF_S": engine.LIVE_MGMT_BACKOFF_S,
        }
        engine.LOG_FILE_PATH = os.path.join(d, "forward_test_log.csv")
        engine.STATUS_FILE_PATH = os.path.join(d, "status.json")
        engine.TRADES_LOG_PATH = os.path.join(d, "trades.csv")
        engine.LIVE_MGMT_BACKOFF_S = 0  # no sleeping in tests

        # Constructed in PAPER mode on purpose: the LIVE branch initialises the
        # terminal, which a hermetic test must never touch.
        self.eng = engine.GoldEngine()
        engine.TRADING_MODE = "LIVE"
        self.telegrams = []
        self.eng.send_telegram = lambda text, kind="trade": self.telegrams.append((kind, text))
        self._had_mt5 = hasattr(engine, "mt5")
        self._saved_mt5 = getattr(engine, "mt5", None)

    def tearDown(self):
        engine.LOG_FILE_PATH = self._saved["LOG_FILE_PATH"]
        engine.STATUS_FILE_PATH = self._saved["STATUS_FILE_PATH"]
        engine.TRADES_LOG_PATH = self._saved["TRADES_LOG_PATH"]
        engine.TRADING_MODE = self._saved["TRADING_MODE"]
        engine.live_armed = self._saved["live_armed"]
        engine.LIVE_MGMT_BACKOFF_S = self._saved["LIVE_MGMT_BACKOFF_S"]
        if self._had_mt5:
            engine.mt5 = self._saved_mt5
        elif hasattr(engine, "mt5"):
            delattr(engine, "mt5")
        self.tmp.cleanup()

    # --- helpers -----------------------------------------------------------
    def broker(self, **kw):
        fake = _FakeMT5(**kw)
        engine.mt5 = fake
        return fake

    def open_trade(self, direction="BUY", entry=4000.0, risk=5.0, ticket=555,
                   age_min=0.0, broker_sl=None, tp=None):
        e = self.eng
        e.trade_active = True
        e.trade_type = direction
        e.entry_price = entry
        e.live_risk = risk
        e.live_ticket = ticket
        e.current_trade_num = 42
        e.next_trade_num = 43
        e.be_armed = False
        e.pnl_scale = e.trade_lots * engine.CONTRACT_SIZE
        e.stop_loss = (entry - risk) if direction == "BUY" else (entry + risk)
        e.take_profit = tp if tp is not None else (
            entry + 1.5 * risk if direction == "BUY" else entry - 1.5 * risk)
        e.entry_time = (datetime.now(timezone.utc) - timedelta(minutes=age_min)
                        ).strftime("%Y-%m-%d %H:%M:%S")
        sl = broker_sl if broker_sl is not None else e.stop_loss
        pos = _Pos(ticket=ticket, type=(0 if direction == "BUY" else 1),
                   volume=0.01, sl=sl, tp=e.take_profit)
        return pos

    def trades(self):
        path = engine.TRADES_LOG_PATH
        if not os.path.isfile(path):
            return []
        with open(path, newline="") as fh:
            rows = [line for line in fh.read().splitlines() if line.strip()]
        return rows

    def status(self):
        with open(engine.STATUS_FILE_PATH) as fh:
            return json.load(fh)

    # --- request shapes ----------------------------------------------------
    def test_sltp_request_shape(self):
        fake = self.broker()
        req = engine.live_sltp_request(fake, 555, 4000.0, 4007.5)
        self.assertEqual(req["action"], fake.TRADE_ACTION_SLTP)
        self.assertEqual(req["position"], 555)          # ticket, not an order
        self.assertEqual(req["sl"], 4000.0)
        self.assertEqual(req["tp"], 4007.5)
        self.assertEqual(req["magic"], engine.MAGIC_NUMBER)
        self.assertNotIn("volume", req)                 # never resizes a position

    def test_close_request_is_the_opposite_side(self):
        fake = self.broker()
        long_req = engine.live_close_request(fake, _Pos(ticket=7, type=0, volume=0.02),
                                             4000.0, fake.ORDER_FILLING_IOC)
        self.assertEqual(long_req["action"], fake.TRADE_ACTION_DEAL)
        self.assertEqual(long_req["type"], fake.ORDER_TYPE_SELL)
        self.assertEqual(long_req["position"], 7)
        self.assertEqual(long_req["volume"], 0.02)      # broker volume, not local state
        self.assertEqual(long_req["type_filling"], fake.ORDER_FILLING_IOC)
        short_req = engine.live_close_request(fake, _Pos(ticket=8, type=1, volume=0.01),
                                              4000.0, fake.ORDER_FILLING_IOC)
        self.assertEqual(short_req["type"], fake.ORDER_TYPE_BUY)

    def test_retcode_helpers(self):
        fake = self.broker()
        self.assertTrue(engine.live_retcode_done(fake, _Result(10009)))
        self.assertFalse(engine.live_retcode_done(fake, _Result(10016)))
        self.assertFalse(engine.live_retcode_done(fake, None))
        self.assertTrue(engine.live_retcode_retryable(fake, 10004))   # requote
        self.assertTrue(engine.live_retcode_retryable(fake, 10020))   # price changed
        self.assertFalse(engine.live_retcode_retryable(fake, 10016))  # invalid stops
        self.assertFalse(engine.live_retcode_retryable(fake, None))

    def test_live_position_absent_or_unknown_is_none(self):
        fake = self.broker(positions=[])
        self.assertIsNone(engine.live_position(fake, 555))
        self.assertIsNone(engine.live_position(fake, None))
        fake.positions = [_Pos(ticket=555)]
        self.assertEqual(engine.live_position(fake, 555).ticket, 555)

    def test_a_failed_query_is_not_a_closed_position(self):
        """A dead terminal must not be mistaken for "the broker closed it".

        Reading the two the same would set live_reconcile_pending from one
        transient error and block new exposure until an operator intervened.
        """
        pos = self.open_trade(entry=4000.0, risk=5.0)

        class _Broken(_FakeMT5):
            def positions_get(self, ticket=None, symbol=None, magic=None):
                raise ConnectionError("terminal not connected")

        broken = _Broken(positions=[pos])
        engine.mt5 = broken
        self.assertEqual(self.eng.live_manage_open_position(price=4000.0), "unknown")
        self.assertFalse(self.eng.live_reconcile_pending)
        self.assertEqual(broken.sent, [])
        self.assertIs(engine.live_position(broken, 555), engine.LIVE_POSITION_UNKNOWN)

    # --- BE ratchet --------------------------------------------------------
    def test_be_arms_only_at_the_registered_trigger(self):
        pos = self.open_trade(entry=4000.0, risk=5.0)      # trigger at +3.75
        fake = self.broker(positions=[pos])
        self.assertEqual(self.eng.live_manage_open_position(price=4003.0), "held")
        self.assertEqual(fake.sent, [])
        self.assertFalse(self.eng.be_armed)

        self.assertEqual(self.eng.live_manage_open_position(price=4003.75), "be-sent")
        self.assertEqual(len(fake.sent), 1)
        self.assertEqual(fake.sent[0]["action"], fake.TRADE_ACTION_SLTP)
        self.assertEqual(fake.sent[0]["position"], 555)
        self.assertEqual(fake.sent[0]["sl"], 4000.0)      # exactly entry
        self.assertTrue(self.eng.be_armed)
        self.assertEqual(self.eng.stop_loss, 4000.0)
        self.assertTrue(self.status()["be_armed"])

    def test_be_never_widens_and_never_repeats(self):
        pos = self.open_trade(direction="SELL", entry=4000.0, risk=5.0,
                              broker_sl=4005.0)
        fake = self.broker(positions=[pos], bid=3996.0, ask=3996.2)
        # SELL gain = entry - price = 4.0 >= 0.75*5 -> tighten from 4005 to 4000.
        self.assertEqual(self.eng.live_manage_open_position(), "be-sent")
        self.assertEqual(fake.sent[0]["sl"], 4000.0)
        self.assertLess(fake.sent[0]["sl"], 4005.0)       # tighter, never wider
        # Already armed: a much better price sends nothing.
        fake.bid = 3900.0
        self.assertEqual(self.eng.live_manage_open_position(), "held")
        self.assertEqual(len(fake.sent), 1)

    def test_be_adopts_a_broker_stop_that_already_landed(self):
        # A restart cleared be_armed but the modify did reach the broker.
        pos = self.open_trade(entry=4000.0, risk=5.0, broker_sl=4000.0)
        fake = self.broker(positions=[pos])
        self.assertEqual(self.eng.live_manage_open_position(price=4005.0), "be-sent")
        self.assertEqual(fake.sent, [])                   # no duplicate modify
        self.assertTrue(self.eng.be_armed)

    # --- rejection / retry -------------------------------------------------
    def test_a_requote_is_retried_once_then_believed(self):
        pos = self.open_trade(entry=4000.0, risk=5.0)
        fake = self.broker(positions=[pos], script=[
            _Result(10004, "requote"),
            _Result(10009, "done"),
        ])
        self.assertEqual(self.eng.live_manage_open_position(price=4004.0), "be-sent")
        self.assertEqual(len(fake.sent), 2)
        self.assertTrue(self.eng.be_armed)
        self.assertEqual(self.eng._live_mgmt_fail_count, 0)

    def test_a_logic_reject_never_arms_and_never_books(self):
        pos = self.open_trade(entry=4000.0, risk=5.0)
        fake = self.broker(positions=[pos], script=[_Result(10016, "invalid stops")])
        self.assertEqual(self.eng.live_manage_open_position(price=4004.0), "be-failed")
        self.assertEqual(len(fake.sent), 1)               # no retry: logic, not market
        self.assertFalse(self.eng.be_armed)
        self.assertEqual(self.eng.stop_loss, 3995.0)      # unchanged
        self.assertEqual(self.telegrams[-1][0], "risk")
        self.assertIn("LIVE BE FAILED", self.telegrams[-1][1])

    def test_reject_alerts_are_rate_limited(self):
        pos = self.open_trade(entry=4000.0, risk=5.0)
        fake = self.broker(positions=[pos],
                           script=[_Result(10016, "invalid stops")] * 100)
        for _ in range(engine.LIVE_MGMT_ALERT_EVERY + 1):
            self.assertEqual(self.eng.live_manage_open_position(price=4004.0),
                             "be-failed")
        self.assertEqual(len(self.telegrams), 2)          # first + every Nth

    # --- time stop ---------------------------------------------------------
    def test_time_stop_closes_then_books_one_time_row(self):
        pos = self.open_trade(entry=4000.0, risk=5.0, age_min=engine.MAX_HOLD_MINUTES + 5)
        fake = self.broker(positions=[pos], bid=4001.0, ask=4001.2)
        self.assertEqual(self.eng.live_manage_open_position(), "time-closed")
        self.assertEqual(len(fake.sent), 1)
        req = fake.sent[0]
        self.assertEqual(req["action"], fake.TRADE_ACTION_DEAL)
        self.assertEqual(req["position"], 555)
        self.assertEqual(req["type"], fake.ORDER_TYPE_SELL)   # closing a BUY
        self.assertFalse(self.eng.trade_active)
        self.assertIsNone(self.eng.live_ticket)
        self.assertEqual(self.eng.time_exits, 1)

        rows = self.trades()
        self.assertEqual(len(rows), 2)                        # header + one trade
        header, row = rows[0].split(","), rows[1].split(",")
        rec = dict(zip(header, row))
        self.assertEqual(rec["Trade_Num"], "42")
        self.assertEqual(rec["Exit_Reason"], "TIME")
        self.assertEqual(rec["Trade_Type"], "BUY")
        self.assertFalse(self.status()["trade_active"])
        self.assertIsNone(self.status()["live_ticket"])

    def test_a_rejected_close_books_nothing(self):
        pos = self.open_trade(entry=4000.0, risk=5.0, age_min=engine.MAX_HOLD_MINUTES + 5)
        fake = self.broker(positions=[pos], script=[_Result(10016, "invalid stops")])
        self.assertEqual(self.eng.live_manage_open_position(), "time-failed")
        self.assertTrue(self.eng.trade_active)
        self.assertEqual(self.eng.live_ticket, 555)
        self.assertEqual(self.eng.time_exits, 0)
        self.assertEqual(self.trades(), [])                   # no phantom ledger row

    def test_no_close_before_the_hold_limit(self):
        pos = self.open_trade(entry=4000.0, risk=5.0, age_min=engine.MAX_HOLD_MINUTES - 10)
        fake = self.broker(positions=[pos], bid=4000.0, ask=4000.2)
        self.assertEqual(self.eng.live_manage_open_position(), "held")
        self.assertEqual(fake.sent, [])
        self.assertTrue(self.eng.trade_active)

    # --- safety ------------------------------------------------------------
    def test_the_paper_engine_is_inert(self):
        pos = self.open_trade(entry=4000.0, risk=5.0, age_min=999)
        fake = self.broker(positions=[pos])
        engine.TRADING_MODE = "FORWARD_TEST"
        self.assertEqual(self.eng.live_manage_open_position(price=4005.0), "paper")
        self.assertEqual(fake.sent, [])
        self.assertTrue(self.eng.trade_active)

    def test_management_still_runs_while_disarmed(self):
        """Risk-reducing actions must not be blocked by the kill switch."""
        pos = self.open_trade(entry=4000.0, risk=5.0)
        fake = self.broker(positions=[pos])
        engine.live_armed = lambda env=None, halt_path=None: False
        self.assertEqual(self.eng.live_manage_open_position(price=4004.0), "be-sent")
        self.assertEqual(len(fake.sent), 1)

    def test_a_position_the_broker_closed_books_nothing_and_blocks_entries(self):
        self.open_trade(entry=4000.0, risk=5.0)
        fake = self.broker(positions=[])                  # SL/TP fired while away
        self.assertEqual(self.eng.live_manage_open_position(price=4000.0), "gone")
        self.assertTrue(self.eng.live_reconcile_pending)
        self.assertEqual(self.trades(), [])               # no invented exit price
        self.assertTrue(any("RECONCILE" in t for _, t in self.telegrams))
        # The alert is raised once, not on every 5-second pass.
        n = len(self.telegrams)
        self.assertEqual(self.eng.live_manage_open_position(price=4000.0), "gone")
        self.assertEqual(len(self.telegrams), n)

        # New exposure stays blocked while the ledger row is missing. Arm the
        # process so the block under test is the reconcile gate, not the arm gate.
        engine.live_armed = lambda env=None, halt_path=None: True
        e = self.eng
        e.trade_active, e.trade_type, e.atr, e.rsi = False, "BUY", 2.0, 50.0
        e.entry_guard_reason = lambda now=None: None
        e.execute_live_trade("BUY", 4000.0, 0.5, "2026-10-28 19:00:00")
        self.assertEqual(fake.sent, [])
        self.assertTrue(any("ENTRY BLOCKED" in t for _, t in self.telegrams))

    def test_ticket_and_risk_survive_a_restart(self):
        self.open_trade(entry=4000.0, risk=5.0)
        self.eng.save_status()
        self.assertEqual(self.status()["live_ticket"], 555)
        self.assertEqual(self.status()["live_risk"], 5.0)

        engine.TRADING_MODE = "FORWARD_TEST"             # construct without a terminal
        restarted = engine.GoldEngine()                   # reads the same status.json
        engine.TRADING_MODE = "LIVE"
        self.assertTrue(restarted.trade_active)
        self.assertEqual(restarted.live_ticket, 555)
        self.assertEqual(restarted.live_risk, 5.0)
        self.assertEqual(restarted.current_trade_num, 42)

    def test_a_confirmed_fill_records_everything_management_needs(self):
        fake = self.broker(positions=[], bid=3999.8, ask=4000.2)
        engine.live_armed = lambda env=None, halt_path=None: True
        self.eng.atr = 2.0
        self.eng.rsi = 50.0
        self.eng.entry_guard_reason = lambda now=None: None
        self.eng.execute_live_trade("BUY", 4000.0, 0.5, "2026-10-28 19:00:00")

        self.assertEqual(len(fake.sent), 1)
        order = fake.sent[0]
        self.assertEqual(order["action"], fake.TRADE_ACTION_DEAL)
        self.assertEqual(order["type"], fake.ORDER_TYPE_BUY)
        self.assertGreater(order["sl"], 0)
        self.assertGreater(order["tp"], order["price"])

        e = self.eng
        self.assertTrue(e.trade_active)                   # <- the B2 fix
        self.assertEqual(e.live_ticket, 777)              # fake returns the ticket
        self.assertAlmostEqual(e.live_risk, 2.0 * e.atr, places=6)
        self.assertAlmostEqual(e.entry_price, order["price"], places=6)
        self.assertEqual(e.stop_loss, order["sl"])
        self.assertEqual(e.take_profit, order["tp"])
        st = self.status()
        self.assertTrue(st["trade_active"])
        self.assertEqual(st["live_ticket"], 777)
        self.assertAlmostEqual(st["live_risk"], 4.0, places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
