#!/usr/bin/env python3
"""Hermetic tests for the 2026-10-26 LIVE-path hardening + readiness gate.

    python3 tools/test_live_readiness.py

Pins three things:
  * `engine.live_armed` fails CLOSED (unset env, wrong value, kill-switch file);
  * `engine.resolve_order_filling` reads the broker's bitmask instead of
    guessing — the captured XM spec is IOC-only, so FOK must never be sent;
  * `tools/live_readiness.py` is an honest, static, read-only scorecard: the
    checks that exist today PASS, the gaps are TODO, the three operator/evidence
    items are MANUAL, and the LIVE gate stays CLOSED.

No network, no /opt/gold, no real orders, no wall clock.
"""
import ast
import contextlib
import io
import json
import os
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

# engine.py imports optional third-party modules at import time; stub them exactly
# as tools/smoke_test.py does so this file runs in a bare checkout.
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
import live_readiness as LR  # noqa: E402


class _FakeMT5:
    ORDER_FILLING_FOK = 1
    ORDER_FILLING_IOC = 2


class _Sym:
    def __init__(self, mode, point=0.01):
        self.filling_mode = mode
        self.point = point


class TestLiveArmed(unittest.TestCase):
    def test_unset_env_is_disarmed(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(engine.live_armed(env={}, halt_path=os.path.join(d, "HALT")))

    def test_zero_or_typo_is_disarmed(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "HALT")
            for value in ("0", "yes", "true", " 1 ", ""):
                if value != " 1 ":
                    self.assertFalse(engine.live_armed(
                        env={engine.LIVE_ARM_ENV: value}, halt_path=p), value)
            self.assertTrue(engine.live_armed(
                env={engine.LIVE_ARM_ENV: " 1 "}, halt_path=p))

    def test_armed_without_halt_file(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(engine.live_armed(
                env={engine.LIVE_ARM_ENV: "1"}, halt_path=os.path.join(d, "HALT")))

    def test_kill_switch_overrides_arming(self):
        with tempfile.TemporaryDirectory() as d:
            halt = os.path.join(d, "LIVE_HALT")
            with open(halt, "w") as fh:
                fh.write("stop")
            self.assertFalse(engine.live_armed(
                env={engine.LIVE_ARM_ENV: "1"}, halt_path=halt))

    def test_no_placeholder_arm_in_this_checkout(self):
        # The repository must never ship armed-by-default.
        self.assertEqual(engine.TRADING_MODE, "FORWARD_TEST")
        self.assertIn(engine.LIVE_ARM_ENV, ("GOLD_LIVE_ARMED",))


class TestFilling(unittest.TestCase):
    def test_fok_only(self):
        self.assertEqual(engine.resolve_order_filling(_FakeMT5, _Sym(1)),
                         _FakeMT5.ORDER_FILLING_FOK)

    def test_ioc_only(self):
        self.assertEqual(engine.resolve_order_filling(_FakeMT5, _Sym(2)),
                         _FakeMT5.ORDER_FILLING_IOC)

    def test_both_prefers_fok(self):
        self.assertEqual(engine.resolve_order_filling(_FakeMT5, _Sym(3)),
                         _FakeMT5.ORDER_FILLING_FOK)

    def test_unknown_or_missing_refuses(self):
        for mode in (0, 4, None):
            self.assertIsNone(engine.resolve_order_filling(_FakeMT5, _Sym(mode)), mode)
        self.assertIsNone(engine.resolve_order_filling(_FakeMT5, None))
        self.assertIsNone(engine.resolve_order_filling(object(), _Sym(2)))

    def test_captured_xm_spec_is_ioc_only(self):
        path = os.path.join(ROOT, "xm_data", "symbol_spec.json")
        with open(path) as fh:
            spec = json.load(fh)
        self.assertEqual(spec["symbol_info"]["filling_mode"], 2)
        self.assertEqual(spec["decoded"]["filling_allowed_flags"], ["IOC"])
        self.assertEqual(engine.resolve_order_filling(_FakeMT5, _Sym(2)),
                         _FakeMT5.ORDER_FILLING_IOC)


class TestChecker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.checks = LR.all_checks(ROOT)
        cls.by_id = {c["id"]: c for c in cls.checks}

    def test_all_checks_have_the_contract(self):
        for c in self.checks:
            self.assertEqual(set(c), {"id", "area", "title", "status",
                                     "evidence", "blocking"})
            self.assertIn(c["status"], (LR.PASS, LR.TODO, LR.MANUAL))
            self.assertTrue(c["evidence"])
        self.assertTrue(len(self.checks) >= 20)

    def test_hardened_checks_pass(self):
        for cid in ("mode_paper", "arm_gate", "filling_spec", "closed_bars",
                    "bar_dedup", "spread_filter", "dst_offsets",
                    "spec_filling", "no_account_ids",
                    # B2 (2026-10-28): broker-side BE ratchet + time stop.
                    "broker_be", "broker_time_stop"):
            self.assertEqual(self.by_id[cid]["status"], LR.PASS, cid)

    def test_open_gaps_are_visible(self):
        for cid in ("position_reconcile", "deal_reconcile", "disconnect_safety",
                    "sizing_limits", "cost_guard"):
            self.assertEqual(self.by_id[cid]["status"], LR.TODO, cid)

    def test_operator_items_are_manual(self):
        for cid in ("demo_evidence", "cost_model", "edge_evidence"):
            self.assertEqual(self.by_id[cid]["status"], LR.MANUAL, cid)

    def test_gate_is_closed_and_says_so(self):
        self.assertFalse(LR.gate_open(self.checks))
        self.assertIn("LIVE GATE: CLOSED", LR.render(self.checks))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(LR.main(["--root", ROOT, "--strict"]), 1)
            self.assertEqual(LR.main(["--root", ROOT]), 0)

    def test_gate_logic_ignores_nonblocking_items(self):
        checks = [_check_stub(LR.PASS, True), _check_stub(LR.TODO, False)]
        self.assertTrue(LR.gate_open(checks))
        checks.append(_check_stub(LR.MANUAL, True))
        self.assertFalse(LR.gate_open(checks))

    def test_attribute_check_ignores_comments(self):
        src = 'def f():\n    # mt5.ORDER_FILLING_FOK is mentioned here\n    return "filling"\n'
        self.assertFalse(LR._uses_attribute(src, "ORDER_FILLING_FOK"))
        self.assertTrue(LR._uses_attribute("def f(): return mt5.ORDER_FILLING_FOK",
                                           "ORDER_FILLING_FOK"))

    def test_broker_side_checks_follow_the_call_graph(self):
        """B2: a helper the LIVE loop never calls must NOT turn a check green."""
        # The evidence must name the manager, not the docstrings.
        self.assertIn("live_manage_open_position", self.by_id["broker_be"]["evidence"])
        self.assertIn("live_manage_open_position",
                      self.by_id["broker_time_stop"]["evidence"])

        src = (
            "class GoldEngine:\n"
            "    def run_live(self):\n"
            "        self.evaluate_candle(1, 2, 0.5, 1.5, 10)\n"
            "    def evaluate_candle(self, o, h, l, c, v):\n"
            "        pass\n"
            "    def mod(self, ticket):\n"
            "        return mt5.order_send({'action': mt5.TRADE_ACTION_SLTP})\n"
            "    def close(self, p):\n"
            "        return mt5.order_send({'action': mt5.TRADE_ACTION_DEAL,\n"
            "                              'position': p.ticket})\n"
            "    def manage(self, price=None):\n"
            "        if held >= MAX_HOLD_MINUTES:\n"
            "            self.close(p)\n"
            "        self.mod(1)\n"
        )
        tree = ast.parse(src)
        fn_src = LR._callable_sources(tree, src)
        reachable = LR._reachable(fn_src)
        self.assertEqual(reachable, {"run_live", "evaluate_candle"})
        self.assertNotIn("manage", reachable)       # never called from run_live
        # ... so nothing is credited to the LIVE path, even though the code exists.
        sltp = {n for n in fn_src if LR._uses_attribute(fn_src[n], "TRADE_ACTION_SLTP")}
        self.assertTrue(sltp)                        # the construct does exist
        self.assertFalse(reachable & sltp)           # but the loop cannot reach it
        close = {n for n in fn_src if LR._uses_attribute(fn_src[n], "TRADE_ACTION_DEAL")
                 and LR._dict_has_key(fn_src[n], "position")}
        self.assertTrue(close)
        self.assertFalse(reachable & close)

    def test_docstrings_and_comments_never_satisfy_a_check(self):
        """A comment claiming a feature is not the feature (B2 lesson)."""
        doc = ('def f():\n    """Uses TRADE_ACTION_SLTP and MAX_HOLD_MINUTES, '
               'with a "position" key."""\n    return 1\n')
        self.assertFalse(LR._uses_attribute(doc, "TRADE_ACTION_SLTP"))
        self.assertFalse(LR._uses_name(doc, "MAX_HOLD_MINUTES"))
        self.assertFalse(LR._dict_has_key(doc, "position"))
        self.assertTrue(LR._uses_attribute("def f(): return mt5.TRADE_ACTION_SLTP",
                                           "TRADE_ACTION_SLTP"))
        self.assertTrue(LR._uses_name("def f(): return MAX_HOLD_MINUTES",
                                      "MAX_HOLD_MINUTES"))
        self.assertTrue(LR._dict_has_key("def f(): return {'position': 1}", "position"))

    def test_json_shape(self):
        payload = json.loads(json.dumps(dict(checks=self.checks,
                                             gate_open=LR.gate_open(self.checks))))
        self.assertFalse(payload["gate_open"])
        self.assertEqual(len(payload["checks"]), len(self.checks))


def _check_stub(status, blocking):
    return dict(id="stub", area="code", title="stub", status=status,
                evidence="synthetic", blocking=blocking)


if __name__ == "__main__":
    unittest.main(verbosity=2)
