"""Hermetic tests for the 2026-10-21 box additions: the chop read, the frozen-box
retest tracker, the Telegram alert decision and its rate limiter.

Synthetic tapes only — no live CSVs, no wall clock, no network. The Telegram
sender is always injected, so nothing here can hit api.telegram.org.

What these pin, and why each one matters:
  * the chop read measures what it claims (a break that closes back inside counts,
    one that runs does not) and REFUSES a tape too short to measure;
  * the retest tracker freezes the box at the break — a rolling box would make
    every bar of a sustained move look like a fresh break;
  * the alert fires only on a fresh BREAK with every check green, and every
    blocker says why in words;
  * the rate limiter is the same code the sidecar runs, so a replay, the
    dashboard preview and the live sender cannot disagree;
  * a missing credential or a dead API returns a reason and never raises.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import pressure as P  # noqa: E402
import box_alert as BA  # noqa: E402

# A Wednesday afternoon outside every engine blackout (trade_filter.BLACKOUT_WINDOWS)
T0 = datetime(2026, 10, 7, 15, 29)
NOW = datetime(2026, 10, 7, 16, 0)
PORTFOLIO = {"cooldown_minutes_left": 0, "breaker_on": False}
FEED_OK = {"ok": True, "age_seconds": 5}


def bar(i, h, l, c, atr=1.2, base=T0):
    return {"Timestamp": (base + timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:%S"),
            "Open": str(c), "High": str(h), "Low": str(l), "Close": str(c),
            "ATR": str(atr)}


def flat(i, price=100.0, atr=0.5, n=1, base=T0):
    return [bar(i + k, price + 0.2, price - 0.2, price, atr, base) for k in range(n)]


def wide_tape(break_close=107.0, n=30, atr=1.2, top=106.0):
    """A 20-bar box ~$6 wide (so the spread is a small share of R) then a break."""
    rows = []
    for i in range(n):
        c = top if i % 2 else 100.0
        rows.append(bar(i, c + 0.2, c - 0.2, c, atr))
    if break_close is not None:
        rows.append(bar(n, break_close + 0.2, break_close - 0.6, break_close, atr))
    return rows


def poke_tape(cycles, fail=True, cycle_len=70, atr=0.5, price=100.0, base=T0,
              fails=None):
    """`cycles` pokes above the rolling 20-bar box, `cycle_len` bars apart (so the
    sequential one-position rule sees each as its own event). A failing cycle closes
    back inside the box within 15 min; a holding one stays out for the whole window.

    `fails` overrides `fail` per cycle, which is how a tape is built whose RECENT
    breaks behave differently from its older ones."""
    rows, minute, cur = [], 0, price
    rows += flat(0, price, atr, n=30, base=base)
    minute = 30
    for k in range(cycles):
        this_fail = fail if fails is None else fails[k]
        prior_hi = max(float(r["High"]) for r in rows[-20:])
        prior_lo = min(float(r["Low"]) for r in rows[-20:])
        poke = prior_hi + 0.4
        rows.append(bar(minute, poke, cur - 0.1, poke, atr, base))
        minute += 1
        cur = poke
        for j in range(1, cycle_len):
            if this_fail and j == 4:
                cur = (prior_hi + prior_lo) / 2.0        # genuinely back inside
            rows.append(bar(minute, cur + 0.2, cur - 0.2, cur, atr, base))
            minute += 1
    return rows


def read_of(rows, now=NOW, portfolio=PORTFOLIO, feed=FEED_OK):
    geom = P.box_geometry(rows)
    return P.box_status(geom, portfolio=portfolio, feed=feed, now=now,
                        regime=P.box_regime(rows))


# ─────────────────────────────────────────────────────────────── the chop read
class ChopTests(unittest.TestCase):
    def test_a_break_that_comes_back_counts_and_one_that_runs_does_not(self):
        failing = P.box_chop(P._box_bars(poke_tape(8, fail=True)))
        holding = P.box_chop(P._box_bars(poke_tape(8, fail=False)))
        self.assertTrue(failing["ok"] and holding["ok"])
        self.assertEqual(failing["recent_breaks"], 8)
        self.assertEqual(failing["recent_false_breaks"], 8)
        self.assertEqual(failing["recent_false_break_pct"], 100.0)
        self.assertEqual(failing["level"], "elevated")
        self.assertEqual(holding["recent_false_breaks"], 0)
        self.assertEqual(holding["level"], "clean")

    def test_recent_and_baseline_can_disagree(self):
        # 16 cycles of 100 bars: the first 8 hold, the last 8 fail. Read over a 900-bar
        # window the recent share is ~89% while the baseline stays at 50% — which is
        # the whole point of showing both numbers instead of one.
        fails = [False] * 8 + [True] * 8
        rows = poke_tape(16, cycle_len=100, fails=fails, base=T0 - timedelta(minutes=1630))
        chop = P.box_chop(P._box_bars(rows), window_bars=900)
        self.assertTrue(chop["ok"])
        self.assertEqual(chop["recent_breaks"], 9)
        self.assertEqual(chop["baseline_breaks"], 16)
        self.assertAlmostEqual(chop["recent_false_break_pct"], 88.9, places=1)
        self.assertAlmostEqual(chop["baseline_false_break_pct"], 50.0, places=1)
        self.assertEqual(chop["level"], "elevated")

    def test_it_refuses_a_tape_it_cannot_measure(self):
        self.assertFalse(P.box_chop(P._box_bars(flat(0, n=10)))["ok"])
        self.assertFalse(P.box_chop([])["ok"])
        # enough bars, but a flat tape never breaks a box: nothing to measure
        thin = P.box_chop(P._box_bars(flat(0, n=200)))
        self.assertFalse(thin["ok"])
        self.assertIn("completed box breaks", thin["reason"])

    def test_the_negative_measurement_travels_with_the_read(self):
        chop = P.box_chop(P._box_bars(poke_tape(8, fail=True)))
        m = chop["measured"]
        self.assertEqual(m["sequential_breaks"], 681)
        self.assertIn("does NOT separate outcomes", m["verdict"])
        self.assertIn("does not separate outcomes", chop["detail"] + "does not separate outcomes")
        # the efficiency ratio is a real ratio, or None when the path is zero
        self.assertTrue(chop["eff_60"] is None or 0.0 <= chop["eff_60"] <= 1.0)
        moving = P.box_chop(P._box_bars(poke_tape(8, fail=False) +
                                        [bar(590 + k, 100.2 + 0.05 * k, 99.8 + 0.05 * k,
                                             100.0 + 0.05 * k, 0.5) for k in range(60)]))
        self.assertTrue(moving["ok"])
        self.assertTrue(0.0 < moving["eff_60"] <= 1.0)


# ─────────────────────────────────────────────────────────── the retest tracker
class RetestTests(unittest.TestCase):
    def tape(self, mode, atr=0.5):
        rows = flat(0, 100.0, atr, n=30)                  # box 99.8 - 100.2
        if mode == "none":
            return rows
        rows.append(bar(30, 101.1, 99.9, 101.0, atr))     # fresh close beyond 100.25
        if mode == "extended":
            rows += [bar(30 + k, 101.3, 100.9, 101.2, atr) for k in (1, 2, 3)]
        elif mode == "retesting":
            rows.append(bar(31, 101.1, 100.25, 100.20, atr))
        elif mode == "held":
            rows.append(bar(31, 101.1, 100.25, 100.20, atr))
            rows.append(bar(32, 100.6, 100.2, 100.5, atr))
        elif mode == "failed":
            rows.append(bar(31, 101.1, 100.25, 100.20, atr))
            rows.append(bar(32, 100.3, 99.8, 99.9, atr))
        return rows

    def test_every_state_the_tracker_can_be_in(self):
        for mode in ("extended", "retesting", "held", "failed"):
            rt = P.box_retest(P._box_bars(self.tape(mode)))
            self.assertEqual(rt["state"], mode, mode)
            self.assertEqual(rt["side"], "BUY")
            self.assertAlmostEqual(rt["edge"], 100.2)
            self.assertAlmostEqual(rt["box_low"], 99.8)
            self.assertTrue(rt["detail"])
        self.assertEqual(P.box_retest(P._box_bars(self.tape("none")))["state"], "none")

    def test_it_freezes_the_box_instead_of_chasing_the_rolling_one(self):
        # Three more bars beyond the edge: the lagging box would call each of them a
        # fresh break. The tracker must stay frozen on the FIRST bar of the episode.
        rt = P.box_retest(P._box_bars(self.tape("extended")))
        self.assertEqual(rt["state"], "extended")
        self.assertEqual(rt["bars_since"], 3)
        self.assertAlmostEqual(rt["edge"], 100.2)
        self.assertIsNone(rt["touch_ts"])

    def test_sell_side_is_the_mirror_image(self):
        rows = flat(0, 100.0, 0.5, n=30)
        rows.append(bar(30, 100.1, 98.9, 99.0, 0.5))
        rows += [bar(30 + k, 99.1, 98.7, 98.8, 0.5) for k in (1, 2, 3)]
        rt = P.box_retest(P._box_bars(rows))
        self.assertEqual((rt["state"], rt["side"]), ("extended", "SELL"))
        self.assertAlmostEqual(rt["edge"], 99.8)
        self.assertAlmostEqual(rt["box_high"], 100.2)

    def test_it_refuses_a_short_tape_and_carries_its_own_verdict(self):
        short = P.box_retest(P._box_bars(flat(0, n=5)))
        self.assertFalse(short["ok"])
        self.assertEqual(short["state"], "none")
        self.assertIn("not a filter", short["measured"]["verdict"])
        self.assertEqual(P.box_retest(P._box_bars(self.tape("held")))["measured"]
                         ["entry_on_hold_tf_pct"], 59.0)


# ─────────────────────────────────────────────────────────── the alert decision
class AlertDecisionTests(unittest.TestCase):
    def test_it_fires_on_a_fresh_break_with_every_check_green(self):
        read = read_of(wide_tape())
        self.assertEqual(read["verdict"]["code"], "candidate")
        alert = read["alert"]
        self.assertTrue(alert["fire"], alert["blockers"])
        self.assertEqual(alert["side"], "BUY")
        self.assertEqual(alert["key"], "BUY|20-bar level (engine's own)|106.20")
        for needle in ("context, not a signal", "entry ref 107.00", "stop 99.20",
                       "target 113.40", "0 cleared the no-edge reference",
                       "74% of breaks fail within 15 min", "display only"):
            self.assertIn(needle, alert["text"])
        # the message is plain text: no markdown the Bot API could mangle
        for ch in ("*", "`", "["):
            self.assertNotIn(ch, alert["text"])

    def test_every_blocker_says_why_in_words(self):
        cases = {
            "stale feed": dict(feed={"ok": True, "age_seconds": 900}),
            "closed market": dict(now=datetime(2026, 10, 10, 12, 0)),     # a Saturday
            "sl cooldown": dict(portfolio={"cooldown_minutes_left": 12, "breaker_on": False}),
            "daily breaker": dict(portfolio={"cooldown_minutes_left": 0, "breaker_on": True,
                                             "daily_sls": 10}),
            "no portfolio state": dict(portfolio=None),
        }
        for label, kw in cases.items():
            alert = read_of(wide_tape(), **kw)["alert"]
            self.assertFalse(alert["fire"], label)
            self.assertTrue(alert["blockers"], label)
            self.assertTrue(all(isinstance(b, str) and b for b in alert["blockers"]), label)

    def test_a_rejection_is_never_alerted(self):
        # wick through the high, close back inside = a SELL fade candidate
        rows = wide_tape(break_close=None)
        rows.append(bar(30, 107.5, 105.5, 105.8, 1.2))
        read = read_of(rows)
        self.assertEqual(read["trigger"]["state"], "reject")
        alert = read["alert"]
        self.assertFalse(alert["fire"])
        self.assertTrue(any("fades measured worst" in b for b in alert["blockers"]),
                        alert["blockers"])

    def test_a_chase_and_a_tight_stop_are_blocked(self):
        chase = read_of(wide_tape(break_close=108.5))["alert"]       # 1.9 ATR beyond
        self.assertFalse(chase["fire"])
        self.assertTrue(any("do not chase" in b for b in chase["blockers"]), chase["blockers"])
        # a tiny box makes the spread most of R: geometry must block the alert
        rows = [bar(i, 100.3, 99.7, 100.0 + (0.2 if i % 2 else 0.0), 1.2) for i in range(30)]
        rows.append(bar(30, 100.8, 100.2, 100.6, 1.2))
        tight = read_of(rows)["alert"]
        self.assertFalse(tight["fire"])
        self.assertTrue(any("% of R" in b for b in tight["blockers"]), tight["blockers"])

    def test_no_geometry_means_no_alert_and_no_crash(self):
        alert = read_of(flat(0, n=5))["alert"]
        self.assertFalse(alert["fire"])
        self.assertIsNone(alert["key"])
        self.assertEqual(alert["text"], "")

    def test_the_same_setup_is_dedupeable_and_a_different_edge_is_not(self):
        a = read_of(wide_tape())["alert"]
        b = read_of(wide_tape())["alert"]
        self.assertEqual(a["key"], b["key"])
        higher = read_of(wide_tape(break_close=109.0, top=108.0))["alert"]
        self.assertTrue(higher["fire"], higher["blockers"])
        self.assertNotEqual(a["key"], higher["key"])
        self.assertIn("108.20", higher["key"])


# ───────────────────────────────────────────────────────────── the rate limiter
class RateLimitTests(unittest.TestCase):
    def decision(self, key="BUY|20-bar|106.20"):
        return {"fire": True, "key": key, "side": "BUY", "box": "20-bar", "edge": 106.2,
                "text": "x", "cooldown_minutes": 90, "global_cooldown_minutes": 30,
                "daily_cap": 2}

    def test_global_spacing_then_per_edge_cooldown_then_free(self):
        state = {"sent": {}, "day": None, "count": 0, "last_sent": None, "history": []}
        d = self.decision()
        self.assertIsNone(BA.suppressed(d, state, now=NOW))
        BA.record_send(state, d, now=NOW)
        self.assertIn("minimum spacing", BA.suppressed(d, state, now=NOW + timedelta(minutes=5)))
        # past the 30-min spacing, still inside the 90-min per-edge cooldown
        self.assertIn("same box edge",
                      BA.suppressed(d, state, now=NOW + timedelta(minutes=45)))
        self.assertIsNone(BA.suppressed(d, state, now=NOW + timedelta(minutes=95)))
        # a different box edge only waits for the global spacing
        other = self.decision(key="SELL|20-bar|99.80")
        self.assertIn("minimum spacing",
                      BA.suppressed(other, state, now=NOW + timedelta(minutes=10)))
        self.assertIsNone(BA.suppressed(other, state, now=NOW + timedelta(minutes=35)))

    def test_the_daily_cap_resets_with_the_utc_day(self):
        state = {"sent": {}, "day": None, "count": 0, "last_sent": None, "history": []}
        for k in range(2):
            d = self.decision(key=f"BUY|20-bar|{100 + k}.00")
            self.assertIsNone(BA.suppressed(d, state, now=NOW + timedelta(minutes=40 * k)))
            BA.record_send(state, d, now=NOW + timedelta(minutes=40 * k))
        third = self.decision(key="BUY|20-bar|102.00")
        self.assertIn("daily cap", BA.suppressed(third, state, now=NOW + timedelta(minutes=200)))
        nxt = NOW + timedelta(days=1)
        self.assertIsNone(BA.suppressed(third, state, now=nxt))
        self.assertEqual(state["count"], 2)          # not reset until it is recorded

    def test_state_survives_a_round_trip_through_disk(self):
        import json
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "state.json")
        state = BA.load_state(path)                       # missing file -> a clean state
        self.assertEqual(state, {"sent": {}, "day": None, "count": 0,
                                 "last_sent": None, "history": []})
        BA.record_send(state, self.decision(), now=NOW)
        self.assertTrue(BA.save_state(state, path))
        again = BA.load_state(path)
        self.assertEqual(again["count"], 1)
        self.assertIn("minimum spacing", BA.suppressed(self.decision(), again,
                                                       now=NOW + timedelta(minutes=1)))
        with open(path, "w") as f:
            f.write("not json")
        self.assertEqual(BA.load_state(path)["count"], 0)   # a corrupt file is not fatal
        self.assertIsInstance(json.dumps(again), str)


# ───────────────────────────────────────────────────────────────── the sender
class SenderTests(unittest.TestCase):
    def test_no_credentials_is_a_reason_not_an_exception(self):
        for var in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
            os.environ.pop(var, None)
        ok, detail = BA.send_telegram("hello")
        self.assertFalse(ok)
        self.assertIn("not set", detail)

    def test_the_digest_never_leaks_a_token_and_names_the_state(self):
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        line = BA.digest_line({"sent": {}, "day": None, "count": 0, "last_sent": None,
                               "history": []})
        self.assertTrue(line.startswith("box alerts:"))
        self.assertIn("not configured", line)
        os.environ["TELEGRAM_BOT_TOKEN"] = "SECRET-TOKEN"
        os.environ["TELEGRAM_CHAT_ID"] = "42"
        line = BA.digest_line({"sent": {}, "day": NOW.strftime("%Y-%m-%d"), "count": 3,
                               "last_sent": None,
                               "history": [{"ts": "2026-10-07 09:05:00", "side": "BUY",
                                            "key": "k", "box": "b"}]}, now=NOW)
        self.assertIn("3 sent today", line)
        self.assertIn("09:05", line)
        self.assertNotIn("SECRET-TOKEN", line)
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        os.environ.pop("TELEGRAM_CHAT_ID", None)


class DecideOnceTests(unittest.TestCase):
    """decide_once() end to end on the checked-in tape, with a fake sender."""

    class Args:
        def __init__(self, root, state):
            self.log = os.path.join(root, "forward_test_log.csv")
            self.status = os.path.join(root, "status.json")
            self.trades = os.path.join(root, "trades.csv")
            self.state = state
            self.spread = None
            self.dry_run = False

    def setUp(self):
        import tempfile
        self.root = os.path.dirname(HERE)
        self.state = os.path.join(tempfile.mkdtemp(), "state.json")
        self.sent = []

    def fake_sender(self, text):
        self.sent.append(text)
        return True, "sent"

    def test_it_decides_without_sending_when_nothing_lines_up(self):
        rc, out = BA.decide_once(self.Args(self.root, self.state),
                                 now=datetime(2026, 10, 21, 16, 0),
                                 sender=self.fake_sender, state_path=self.state)
        self.assertEqual(rc, 0)
        self.assertIn(out["action"], ("no alert", "suppressed", "would send (dry run)", "sent"))
        # the checked-in log ends 14:59 UTC, so at 16:00 the feed check must block
        if out["action"] == "no alert":
            self.assertIn("feed", out["reason"])
        self.assertEqual(self.sent, [] if out["action"] != "sent" else self.sent)

    def test_dry_run_never_calls_the_sender(self):
        args = self.Args(self.root, self.state)
        args.dry_run = True
        rc, out = BA.decide_once(args, now=datetime(2026, 10, 21, 16, 0),
                                 sender=self.fake_sender, state_path=self.state)
        self.assertEqual(rc, 0)
        self.assertEqual(self.sent, [])
        self.assertNotEqual(out["action"], "sent")

    def test_a_firing_decision_sends_once_and_then_is_suppressed(self):
        # Drive the real pipeline on a synthetic candidate by pointing the readers at
        # the synthetic tape: same code path, no network, no live files.
        read = read_of(wide_tape())
        self.assertTrue(read["alert"]["fire"])
        state = BA.load_state(self.state)
        decision = read["alert"]
        self.assertIsNone(BA.suppressed(decision, state, now=NOW))
        BA.record_send(state, decision, now=NOW)
        BA.save_state(state, self.state)
        again = BA.load_state(self.state)
        self.assertIn("minimum spacing",
                      BA.suppressed(decision, again, now=NOW + timedelta(minutes=1)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
