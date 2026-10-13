#!/usr/bin/env python3
"""
strategy_lab.py — costed, stateful, era-matched FULL-STRATEGY replay.

Why this exists
---------------
Every exit/gate decision in this repo so far has been made on top of the
*observed* ledger (win_rate_report §5b/§5c, pathwalk_sims, phantom_trades) or
on gate replays that do not model portfolio state. ANALYSIS-2026-10-01 §4
listed exactly what was missing before any of it could decide a change:

  1. matched-rule baseline calibration — the replay must first reproduce the
     live entry stream, or its counterfactuals mean nothing;
  2. a real execution-cost model applied to ALL exits including BE scratches
     (the 0.985 haircut in win_rate_report shrinks losses and leaves scratches
     free — that is not a cost model);
  3. production cooldown semantics (a BE scratch is *transparent* to the SL
     streak — it neither counts nor breaks it — while win_rate_report's
     cascade_replay resets the streak on BE) and wall-clock elapsed time
     instead of bar index;
  4. direction-aware gates inside the replay: the London blackout blocks BUY
     only, and the 10-SL daily breaker degrades to trend-side-only.

This tool supplies all four. It regenerates the signal funnel from the 1-min
bar log using engine.py's own indicator definitions and gate order, walks the
exits with the engine's own intra-bar ordering (arm-ratchet-before-stop,
stop-before-target, TIME last), then applies the live portfolio state machine
(occupancy, 30/60-min escalating SL cooldown, trend-side breaker, blackouts,
ATR bounds). Costs are a fixed charge per side, applied on entry AND exit.

READ-ONLY research harness: never writes a CSV, never imports engine state.
It is not an oracle — see CAVEATS at the bottom of the output and HANDOFF §8
(broker history != live feed; a replay that reproduces the ledger proves
implementation match, not future edge).

Usage
-----
    python3 tools/strategy_lab.py                  # calibrate, then variants
    python3 tools/strategy_lab.py --calib-only
    python3 tools/strategy_lab.py --cost 0.35      # override cost per side ($)
    python3 tools/strategy_lab.py --only baseline,tol0.50
    python3 tools/strategy_lab.py --era maxhold   # restrict to one era (default: 075 master)
    python3 tools/strategy_lab.py --grid level     # scan the gate tolerance
    python3 tools/strategy_lab.py --table --only baseline,structstop
                                                   # era x cost x variant grid (this is what
                                                   # docs/ANALYSIS-2026-10-05-stop-loss-geometry.md
                                                   # quotes, so the doc and the tool cannot drift)
    python3 tools/strategy_lab.py --json /tmp/lab.json
    python3 tools/strategy_lab.py --bars history_utc.csv
                                                   # LARGE-N mode: replay today's rules over broker M1
                                                   # history (docs/ACCELERATE-TESTING.md). The file must come
                                                   # from tools/history_to_log.py (UTC); the live ledger and
                                                   # the calibration are skipped; --ratchet const|era|off

Variant `baseline` (no cfg overrides) = the rules production used up to the structural-stop
deploy, which is the correct replay of every historical era. `structstop` = the rule that is
LIVE from 2026-10-06 03:00 UTC (structural stop, TP = 1.5 x actual risk; planned for 10-05
21:00 but only deployed by the 03:00 autosync, see LIVE_CUTOVER below); after the cutover
`structstop` IS production, so its recall vs the ledger is the "harness still matches the
engine" test (docs/ANALYSIS-2026-10-05-stop-loss-geometry.md 7-A3).
"""
import argparse
import csv
import json
import math
import statistics
import sys
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta

# ---------------------------------------------------------------- constants
# Mirrors of engine.py / trade_filter.py as of 2026-10-05. If a runtime param
# moves, move it here too — §1 (calibration) is the tripwire that complains
# when the replay stops reproducing the ledger.
LOOKBACK = 20
WICK_TARGET = 0.38
EMA_FAST_N, EMA_SLOW_N = 50, 200
RSI_N = ATR_N = 14
SLOPE_LOOKBACK = 30
MAX_EMA_DIST_ATR = 0.30
ATR_SL_MULT, ATR_TP_MULT = 2.0, 3.0
BE_TRIGGER_R = 0.75
MAX_HOLD_MIN = 240
MIN_ATR_ENGINE = 1.10
MIN_ATR_FILTER, MAX_ATR_FILTER = 1.10, 4.50
RSI_BUY = (30.0, 68.0)
RSI_SELL = (32.0, 70.0)            # engine mirrors 100-RSI_MAX .. 100-RSI_MIN
COOLDOWN_BASE, COOLDOWN_ESC = 30, 60
MAX_DAILY_LOSSES = 10
MOMENTUM_MINUTES = 60
FLOOR_BUFFER_PCT_LIVE = 0.0020     # engine.py: price-relative "near the level"
# (start, end, blocked sides) — London is BUY-only since 2026-09-10.
BLACKOUTS = [
    ((7, 55), (9, 0), ("BUY",)),
    ((12, 25), (12, 45), ("BUY", "SELL")),
    ((13, 25), (15, 15), ("BUY", "SELL")),
    ((21, 45), (22, 30), ("BUY", "SELL")),
]
ERA_030 = datetime(2026, 9, 10, 12, 34)          # BE ratchet + current gate stack
ERA_RATCHET_075 = datetime(2026, 9, 15, 6, 0)   # "0.75R master book"
ERA_MAXHOLD = datetime(2026, 9, 21, 6, 0)       # "max-hold era"

BARS_PATH = "forward_test_log.csv"
TRADES_PATH = "trades.csv"


# ------------------------------------------------------------------ data load
def load_bars(path=BARS_PATH):
    """(ts, o, h, l, c, tick_volume) per closed minute, deduped, sorted."""
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            try:
                rows.append((
                    datetime.strptime(r["Timestamp"], "%Y-%m-%d %H:%M:%S"),
                    float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"]),
                    float(r["Volume"]) if r.get("Volume") not in (None, "", "Calculating") else 1.0,
                ))
            except (ValueError, KeyError):
                continue
    out, seen = [], set()
    for b in rows:                       # a restart can re-log one candle
        k = b[0].replace(second=0, microsecond=0)
        if k in seen:
            continue
        seen.add(k)
        out.append(b)
    out.sort(key=lambda x: x[0])
    return out


def load_ledger(path=TRADES_PATH):
    T = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            try:
                T.append(dict(
                    num=int(r["Trade_Num"]), side=r["Trade_Type"],
                    et=datetime.strptime(r["Entry_Time"], "%Y-%m-%d %H:%M:%S"),
                    xt=datetime.strptime(r["Exit_Time"], "%Y-%m-%d %H:%M:%S"),
                    ep=float(r["Entry_Price"]), sl=float(r["Stop_Loss"]), tp=float(r["Take_Profit"]),
                    xp=float(r["Exit_Price"]), reason=r["Exit_Reason"], pnl=float(r["Profit"]),
                    rsi=float(r["RSI_At_Entry"]) if r["RSI_At_Entry"] else None,
                    atr=float(r["ATR_At_Entry"]) if r["ATR_At_Entry"] else None,
                ))
            except (ValueError, KeyError):
                continue
    return T


# ------------------------------------------------- engine-faithful simulation
class Lab:
    """Indicator recomputation + funnel + exit machine + portfolio state."""

    def __init__(self, bars):
        self.bars = bars
        self.ts = [b[0] for b in bars]
        n = len(bars)
        self.ema_f = [None] * n
        self.ema_s = [None] * n
        self.atr = [None] * n
        self.rsi = [None] * n
        self.floor = [None] * n
        self.ceil = [None] * n
        ef = es = prev = None
        gains, losses, trs = [], [], []
        lows, highs = [], []
        for i, (t, o, h, l, c, v) in enumerate(bars):
            # engine seeds the EMA from the SMA once enough closes exist, then
            # recurses; RSI/ATR are simple (not Wilder) 14-period means.
            if ef is None:
                if i + 1 >= EMA_FAST_N:
                    ef = sum(b[4] for b in bars[i + 1 - EMA_FAST_N:i + 1]) / EMA_FAST_N
            else:
                k = 2 / (EMA_FAST_N + 1)
                ef = c * k + ef * (1 - k)
            if es is None:
                if i + 1 >= EMA_SLOW_N:
                    es = sum(b[4] for b in bars[i + 1 - EMA_SLOW_N:i + 1]) / EMA_SLOW_N
            else:
                k = 2 / (EMA_SLOW_N + 1)
                es = c * k + es * (1 - k)
            if prev is not None:
                ch = c - prev
                gains.append(max(ch, 0.0)); losses.append(max(-ch, 0.0))
                trs.append(max(h - l, abs(h - prev), abs(l - prev)))
                if len(gains) > RSI_N:
                    gains.pop(0); losses.pop(0)
                if len(trs) > ATR_N:
                    trs.pop(0)
                if len(gains) == RSI_N:
                    ag, al = sum(gains) / RSI_N, sum(losses) / RSI_N
                    self.rsi[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
                if len(trs) == ATR_N:
                    self.atr[i] = sum(trs) / ATR_N
            prev = c
            self.ema_f[i], self.ema_s[i] = ef, es
            # engine.evaluate_candle: floor/ceiling = min/max of the last LOOKBACK_PERIOD (20)
            # PRIOR bars - list(self.lows)[-20:] is taken BEFORE the current bar is appended.
            # This window therefore holds LOOKBACK bars *excluding* bar i. (Until 2026-10-13 it
            # kept LOOKBACK bars including bar i and sliced [:-1], i.e. 19 prior bars: that matched
            # the engine's logged Dynamic_Floor on only 86.0% of bars vs 99.96% for 20, and made
            # every replayed structural stop up to ~1.6 $ tighter than the live one.)
            if i >= LOOKBACK:
                self.floor[i] = min(lows)
                self.ceil[i] = max(highs)
            lows.append(l); highs.append(h)
            if len(lows) > LOOKBACK:
                lows.pop(0); highs.pop(0)
        self.ready = [i for i in range(n)
                      if self.atr[i] is not None and self.ema_s[i] is not None
                      and self.floor[i] is not None]

    # --------------------------------------------------------------- signals
    def signal(self, i, cfg):
        """'BUY'/'SELL'/None at the close of bar i, under gate config cfg.

        cfg keys:
          level_tol_atr   — how far the bar extreme may sit from the structural
                            level and still count as a test. None keeps the
                            LIVE price-relative buffer (0.2% of price).
          stop_beyond_level — force the initial stop at least this many ATR
                            past the level (structural stop), in addition to
                            the ATR multiple.
          sl_mult / tp_mult / be_trigger / max_hold — overrides.
          rsi_buy / rsi_sell — (lo, hi) overrides.
          min_gap_minutes — throttle: ignore a signal this soon after the last
                            exit (portfolio-level "trade less").
        """
        if self.atr[i] is None or self.ema_s[i] is None or self.floor[i] is None:
            return None
        if i < SLOPE_LOOKBACK:
            return None
        t, o, h, l, c, v = self.bars[i]
        atr, rsi = self.atr[i], self.rsi[i]
        rng = h - l
        if rng <= 0 or rsi is None:
            return None
        buf = cfg.get("level_tol_atr")
        floor, ceil = self.floor[i], self.ceil[i]
        tol_floor = (buf * atr) if buf is not None else (floor * FLOOR_BUFFER_PCT_LIVE)
        tol_ceil = (buf * atr) if buf is not None else (ceil * FLOOR_BUFFER_PCT_LIVE)
        wick_lo = (min(o, c) - l) / rng
        wick_hi = (h - max(o, c)) / rng
        ema_prev30 = self.ema_f[i - SLOPE_LOOKBACK]
        if ema_prev30 is None:
            return None
        slope_up = self.ema_f[i] > ema_prev30
        slope_dn = self.ema_f[i] < ema_prev30
        atr_lo, atr_hi = cfg.get("atr_band", (MIN_ATR_FILTER, MAX_ATR_FILTER))
        if not (atr > MIN_ATR_ENGINE and atr_lo <= atr <= atr_hi):
            return None
        rb = cfg.get("rsi_buy", RSI_BUY)
        if (l <= floor + tol_floor and c > floor and wick_lo >= WICK_TARGET
                and self.ema_f[i] > self.ema_s[i] and slope_up
                and c >= self.ema_f[i] - MAX_EMA_DIST_ATR * atr and rb[0] < rsi < rb[1]):
            return "BUY"
        rs = cfg.get("rsi_sell", RSI_SELL)
        if (h >= ceil - tol_ceil and c < ceil and wick_hi >= WICK_TARGET
                and self.ema_f[i] < self.ema_s[i] and slope_dn
                and c <= self.ema_f[i] + MAX_EMA_DIST_ATR * atr and rs[0] < rsi < rs[1]):
            return "SELL"
        return None

    def momentum_side(self, i, minutes=MOMENTUM_MINUTES):
        j = bisect_left(self.ts, self.ts[i] - timedelta(minutes=minutes))
        if j >= i:
            return None
        a, b = self.bars[j][4], self.bars[i][4]
        return "BUY" if b > a else ("SELL" if b < a else None)

    @staticmethod
    def in_blackout(t, side, windows=BLACKOUTS):
        mins = t.hour * 60 + t.minute
        for (sh, sm), (eh, em), sides in windows:
            s, e = sh * 60 + sm, eh * 60 + em
            inside = (s <= mins <= e) if s <= e else (mins >= s or mins <= e)
            if inside and side in sides:
                return True
        return False

    # ------------------------------------------------------------ exit walk
    def resolve(self, start, side, entry, sl, tp, cfg, trig):
        """Bars AFTER entry. Returns (reason, exit_price, exit_idx, mfe, mae).

        Engine order inside one bar: arm the ratchet on the bar extreme, then
        the (possibly ratcheted) stop, then the target, then the time stop at
        the close. Both levels inside one bar => the stop wins (pessimistic).
        """
        risk = abs(entry - sl)
        arm_at = None if trig is None else \
            (entry + trig * risk if side == "BUY" else entry - trig * risk)
        armed = False
        hold = cfg.get("max_hold", MAX_HOLD_MIN)
        mfe = mae = 0.0
        n = len(self.bars)
        for k in range(start + 1, n):
            t, o, h, l, c, v = self.bars[k]
            if side == "BUY":
                mfe = max(mfe, h - entry); mae = max(mae, entry - l)
            else:
                mfe = max(mfe, entry - l); mae = max(mae, h - entry)
            if arm_at is not None and not armed:
                if (side == "BUY" and h >= arm_at - 1e-9) or (side == "SELL" and l <= arm_at + 1e-9):
                    armed = True
            if armed and ((side == "BUY" and l <= entry + 1e-9) or (side == "SELL" and h >= entry - 1e-9)):
                return "BE", entry, k, mfe, mae
            if not armed and ((side == "BUY" and l <= sl + 1e-9) or (side == "SELL" and h >= sl - 1e-9)):
                return "SL", sl, k, mfe, mae
            if (side == "BUY" and h >= tp - 1e-9) or (side == "SELL" and l <= tp + 1e-9):
                return "TP", tp, k, mfe, mae
            if hold is not None and (t - self.ts[start]).total_seconds() / 60.0 >= hold:
                return "TIME", c, k, mfe, mae
        return "OPEN", self.bars[n - 1][4], n - 1, mfe, mae     # ran out of data

    # --------------------------------------------------------- portfolio run
    # Ratchet schedule actually live on the host, by entry time (HANDOFF §4):
    #   before 2026-09-10 12:34  -> no ratchet at all
    #   09-10 12:34 -> 09-15 06:00 -> +0.30R
    #   09-15 06:00 onward        -> +0.75R
    RATCHET_SCHEDULE = [
        (datetime(2026, 9, 10, 12, 34), datetime(2026, 9, 15, 6, 0), 0.30),
        (datetime(2026, 9, 15, 6, 0), None, BE_TRIGGER_R),
    ]

    def be_trigger(self, t, override="era"):
        if override == "off":
            return None
        if isinstance(override, (int, float)):
            return override
        for start, end, trig in self.RATCHET_SCHEDULE:
            if t >= start and (end is None or t < end):
                return trig
        return None

    def run(self, cfg, cost_per_side=0.0, first_i=0, last_i=None, ratchet="era", window=None):
        last_i = last_i or len(self.bars)
        win_from, win_to = window if window else (None, None)
        trades, blocked = [], defaultdict(int)
        free_at = None
        last_exit_at = None
        last_exit_reason = None
        streak = 0
        daily_sl = defaultdict(int)
        i = first_i
        while i < last_i:
            t = self.ts[i]
            if win_from is not None and t < win_from:
                i += 1; continue
            if win_to is not None and t >= win_to:
                break
            if free_at is not None and t < free_at:
                i += 1
                continue
            sig = self.signal(i, cfg)
            if sig is None:
                i += 1
                continue
            atr, entry = self.atr[i], self.bars[i][4]
            if self.in_blackout(t, sig, cfg.get("blackouts", BLACKOUTS)):
                blocked["blackout"] += 1; i += 1; continue
            band = cfg.get("band")
            if band == "asia" and not (t.hour >= 23 or t.hour < 7):
                blocked["session band"] += 1; i += 1; continue
            if band == "ldnny" and (t.hour >= 23 or t.hour < 7):
                blocked["session band"] += 1; i += 1; continue
            if daily_sl.get(self.ts[j].date() if False else t.date(), 0) >= MAX_DAILY_LOSSES \
                    and self.momentum_side(i) != sig:
                blocked["daily breaker"] += 1; i += 1; continue
            # PRODUCTION semantics (trade_filter.check_sl_cooldown): the cooldown
            # exists only while the LAST closed trade is an SL. A BE scratch (or
            # a TIME exit) sits in front of the streak and switches the cooldown
            # OFF — which is the known "instant re-entry into the same dying
            # setup" leak (HANDOFF §4). The *escalation* still counts SLs through
            # scratches (get_consecutive_sl_count ignores BE/TIME, breaks on TP).
            if last_exit_reason == "SL":
                cd = COOLDOWN_ESC if streak >= 2 else COOLDOWN_BASE
                if last_exit_at and t < last_exit_at + timedelta(minutes=cd):
                    blocked["cooldown"] += 1; i += 1; continue
            gap = cfg.get("min_gap_minutes")
            if gap and last_exit_at and t < last_exit_at + timedelta(minutes=gap):
                blocked["throttle"] += 1; i += 1; continue
            if cfg.get("skip_after_be_minutes") and last_exit_at and last_exit_reason == "BE" \
                    and t < last_exit_at + timedelta(minutes=cfg["skip_after_be_minutes"]):
                blocked["post-BE pause"] += 1; i += 1; continue
            risk = cfg.get("sl_mult", ATR_SL_MULT) * atr
            beyond = cfg.get("stop_beyond_level")
            if beyond is not None:
                lvl = self.floor[i] if sig == "BUY" else self.ceil[i]
                risk = max(risk, abs(entry - lvl) + beyond * atr)
            risk = max(risk, cfg.get("min_stop_atr", 0.0) * atr)
            tpm = cfg.get("tp_mult", ATR_TP_MULT)
            tpd = cfg.get("rr", 1.5) * risk if tpm is None else tpm * atr
            sl = entry - risk if sig == "BUY" else entry + risk
            tp = entry + tpd if sig == "BUY" else entry - tpd
            if "be_trigger" in cfg:
                trig = cfg["be_trigger"]
            elif ratchet == "era":
                trig = self.be_trigger(t, "era")
            elif ratchet == "off":
                trig = None
            else:
                trig = BE_TRIGGER_R
            reason, xp, j, mfe, mae = self.resolve(i, sig, entry, sl, tp, cfg, trig)
            gross = (xp - entry) if sig == "BUY" else (entry - xp)
            if reason == "OPEN":
                break                                   # unfinished tail: not a closed trade
            trades.append(dict(
                entry_i=i, exit_i=j, ts=t, exit_ts=self.ts[j], side=sig, entry=entry,
                sl=sl, tp=tp, xp=xp, reason=reason, gross=gross, risk=risk, atr=atr,
                mfe=mfe, mae=mae, hold_min=(self.ts[j] - t).total_seconds() / 60.0,
            ))
            last_exit_at = self.ts[j]
            last_exit_reason = reason
            free_at = self.ts[j]                  # same-bar re-entry is allowed
            streak = streak + 1 if reason == "SL" else (0 if reason == "TP" else streak)
            if reason == "SL":
                daily_sl[self.ts[j].date()] += 1   # production counts by Exit_Time day
            i = j if j > i else i + 1
        for tr in trades:
            rc = 2 * cost_per_side
            tr["net"] = tr["gross"] - rc
            tr["R"] = tr["gross"] / tr["risk"] if tr["risk"] else 0.0
            tr["Rnet"] = tr["net"] / tr["risk"] if tr["risk"] else 0.0
        return trades, dict(blocked)



# ----------------------------------------------------------------- statistics
def wilson(w, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = w / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return 100 * (c - h), 100 * (c + h)


def summarize(trades, label, width=14):
    n = len(trades)
    if n == 0:
        return f"{label:{width}s} n=   0  --"
    W = sum(1 for t in trades if t["reason"] == "TP")
    L = sum(1 for t in trades if t["reason"] == "SL")
    BE = sum(1 for t in trades if t["reason"] == "BE")
    TI = sum(1 for t in trades if t["reason"] == "TIME")
    dec = W + L
    wr = 100 * W / dec if dec else float("nan")
    lo, hi = wilson(W, dec)
    net = statistics.mean(t["net"] for t in trades)
    Rn = statistics.mean(t["Rnet"] for t in trades)
    med = statistics.median(t["hold_min"] for t in trades)
    return (f"{label:{width}s} n={n:4d} {W:3d}W/{L:3d}L/{BE:3d}BE/{TI:2d}T "
            f"{wr:5.1f}%dec[{lo:4.1f},{hi:4.1f}] SL {100*L/n:4.1f}% "
            f"${net:+7.3f}/t {Rn:+6.3f}R/t hold {med:5.1f}m")


def fisher(ra, rb):
    """Two-sided Fisher exact on decisive outcomes (TP vs SL)."""
    a = sum(1 for t in ra if t["reason"] == "TP"); b = sum(1 for t in ra if t["reason"] == "SL")
    c = sum(1 for t in rb if t["reason"] == "TP"); d = sum(1 for t in rb if t["reason"] == "SL")
    n = a + b + c + d
    if min(a + b, c + d, a + c, b + d) == 0:
        return float("nan")
    tot = math.comb(n, a + c)
    p_obs = math.comb(a + b, a) * math.comb(c + d, c) / tot
    p = 0.0
    for x in range(max(0, (a + b) - (b + d)), min(a + b, a + c) + 1):
        px = math.comb(a + b, x) * math.comb(c + d, (a + c) - x) / tot
        if px <= p_obs * (1 + 1e-12):
            p += px
    return min(1.0, 2 * p)


# engine.py 2026-10-05: risk = max(ATR_SL_MULT*ATR, |entry-level| + SL_CLEAR_ATR*ATR),
# TP = RR_TARGET * risk. Before this cutover production was the legacy geometry, so
# `baseline` (= {}) is the correct replay of every historical era; `structstop` is the
# rule that is live from the cutover on, i.e. post-cutover the two only differ if the
# level bound the stop, and a recall check on NEW data must use structstop.
#
# CUTOVER = the moment the ENGINE ON THE HOST loaded the new code - not the day it was
# written, not the planned time, not the PR merge. The 2026-10-05 session planned 21:00 UTC
# ("next autosync") but PR #28 merged 2026-10-06 00:31:53Z, and autosync (cron 00/03/06/...
# UTC) only deployed it with the `autosync: merge upstream` commit 2f4f4c6 at 03:00:04Z.
# The ledger agrees: #495 / #497 / #498 (entered 10-06 00:11-02:39) carry EXACTLY 2.00 ATR
# of risk although the level was 2.3-2.7 ATR away (old rule), and #499 (03:33:05) is the
# first trade on the new geometry. Re-derive it any time with
# `python3 tools/check_structural_stop.py` (it prints the evidence bracket and warns if this
# constant falls outside it). Rule for the next deploy: set the cutover from the host's
# `autosync: merge upstream` commit time, then let that check confirm it.
PLANNED_CUTOVER = datetime(2026, 10, 5, 21, 0)   # what the docs promised (kept for the record)
LIVE_CUTOVER = datetime(2026, 10, 6, 3, 0)       # what actually happened (autosync 03:00:04Z)
SL_CLEAR_ATR, RR_TARGET = 0.5, 1.5

VARIANTS = {
    "baseline":      ("live rules as coded (0.2% price buffer on the level test)", {}),
    "structstop":    ("SHIPPED 2026-10-05: stop clears the level by 0.5 ATR, TP = 1.5x risk",
                      {"stop_beyond_level": SL_CLEAR_ATR, "tp_mult": None, "rr": RR_TARGET}),
    "structstop0.25":("same but only 0.25 ATR of clearance",
                      {"stop_beyond_level": 0.25, "tp_mult": None, "rr": RR_TARGET}),
    "structstop1.0": ("same but 1.0 ATR of clearance",
                      {"stop_beyond_level": 1.0, "tp_mult": None, "rr": RR_TARGET}),
    "structstop+tol0.25": ("shipped stop + 0.25 ATR level test (next isolation slot)",
                      {"stop_beyond_level": SL_CLEAR_ATR, "tp_mult": None, "rr": RR_TARGET,
                       "level_tol_atr": 0.25}),
    "structstop+nord": ("shipped stop + ratchet off (needs its own slot)",
                      {"stop_beyond_level": SL_CLEAR_ATR, "tp_mult": None, "rr": RR_TARGET,
                       "be_trigger": None}),
    "tol0.25":       ("real structural test: within 0.25 ATR of the level", {"level_tol_atr": 0.25}),
    "tol0.50":       ("within 0.50 ATR of the level", {"level_tol_atr": 0.50}),
    "tol1.00":       ("within 1.00 ATR of the level", {"level_tol_atr": 1.00}),
    "sweep":         ("bar must PIERCE the level (0.00 ATR tolerance)", {"level_tol_atr": 0.0}),
    "sweep+stop":    ("pierce the level + stop 0.5 ATR beyond it", {"level_tol_atr": 0.0, "stop_beyond_level": 0.5}),
    "tol0.50+stop":  ("0.50 ATR test + stop 0.5 ATR beyond the level", {"level_tol_atr": 0.50, "stop_beyond_level": 0.5}),
    "stopbeyond":    ("stop 0.5 ATR beyond the level, entries unchanged", {"stop_beyond_level": 0.5}),
    "mindist2.5":    ("min stop 2.5 ATR, entries unchanged", {"min_stop_atr": 2.5}),
    "nordatchet":    ("ratchet off, entries unchanged", {"be_trigger": None}),
    "tol0.50+nord":  ("0.50 ATR test, ratchet off", {"level_tol_atr": 0.50, "be_trigger": None}),
    "tol0.50+pause": ("0.50 ATR test + 15-min post-BE pause", {"level_tol_atr": 0.50, "skip_after_be_minutes": 15}),
    "tol0.50+tp4.5": ("0.50 ATR test, TP 4.5 ATR (1:1.8)", {"level_tol_atr": 0.50, "tp_mult": 4.5}),
    "tol0.50+rsi":   ("0.50 ATR test, RSI 35-62 / mirrored", {"level_tol_atr": 0.50, "rsi_buy": (35.0, 62.0), "rsi_sell": (38.0, 65.0)}),
    "tol0.15":       ("within 0.15 ATR of the level", {"level_tol_atr": 0.15}),
    "band_asia":     ("entries only 23:00-06:59 UTC (session-band candidate)", {"band": "asia"}),
    "tol0.25+band":  ("0.25 ATR test + Asia-band only", {"level_tol_atr": 0.25, "band": "asia"}),
    "tol0.25+LDN/NY":("0.25 ATR test + London/NY only (independence check)", {"level_tol_atr": 0.25, "band": "ldnny"}),
}


# --------------------------------------------------------- large-N history mode
# Everything the live rules were tuned on is at or after the first live trade (2026-09-04); history before
# it is genuinely out-of-sample for them. (The gate stack itself settled on 2026-09-10; the structural stop is
# live from LIVE_CUTOVER.) `baseline`/`structstop` are today's rules, so replaying them backwards is the
# honest out-of-sample test - with the broker-history caveats printed below.
TUNING_START = datetime(2026, 9, 4)
HISTORY_COSTS = (0.0, 0.15, 0.20, 0.35)


def _month_windows(first, last):
    out, cur = [], datetime(first.year, first.month, 1)
    while cur <= last:
        nxt = datetime(cur.year + (cur.month == 12), 1 if cur.month == 12 else cur.month + 1, 1)
        out.append((cur.strftime("%Y-%m"), cur, nxt))
        cur = nxt
    return out


def _hist_line(label, name, trs, width=22):
    """One replay row: the lab's own summary plus $/day, trades/day and the equity drawdown."""
    if not trs:
        return f"  {label:{width}s}{name:12s} (no trades)"
    days = len({t["ts"].date() for t in trs}) or 1
    eq = pk = dd = 0.0
    for t in sorted(trs, key=lambda x: x["ts"]):
        eq += t["net"]
        pk = max(pk, eq)
        dd = max(dd, pk - eq)
    return (f"  {label:{width}s}{summarize(trs, name, width=12)} "
            f"${statistics.mean(t['net'] for t in trs) * len(trs) / days:+7.2f}/day {len(trs) / days:4.1f}/day dd ${dd:6.1f}")


def history_report(args):
    """`--bars PATH`: replay today's rules over a UTC-normalised broker-history file. Read-only; no ledger."""
    path = args.bars
    try:
        with open(path, newline="") as fh:
            head = [h.strip() for h in (fh.readline().strip().split(","))]
    except OSError as e:
        sys.exit(f"--bars: cannot read {path}: {e}")
    if "TickVolume" in head or "Spread" in head:
        sys.exit(f"--bars: {path} looks like RAW mt5_history_dump output (TickVolume/Spread columns). Its timestamps are "
                 f"BROKER SERVER time labelled UTC (+3 h in summer), so every UTC rule here - blackout windows, the "
                 f"Asia/London/NY bands, the daily-loss day - would be hours off. Convert it first:\n"
                 f"  python3 tools/history_to_log.py {path} --out history_utc.csv")
    if not {"Timestamp", "Open", "High", "Low", "Close"} <= set(head):
        sys.exit(f"--bars: {path} needs the columns Timestamp,Open,High,Low,Close (got {','.join(head[:8])})")
    bars = load_bars(path)
    if len(bars) < 1000:
        sys.exit(f"--bars: only {len(bars)} usable bars in {path}; the EMA200/ATR warm-up alone needs ~200 and a replay "
                 f"is meaningless below ~1000")
    lab = Lab(bars)
    if not lab.ready:
        sys.exit("--bars: the file is too short for the indicators to warm up")
    first = lab.ready[0]
    names = [x.strip() for x in (args.only.split(",") if args.only else []) if x.strip()] or ["baseline", "structstop"]
    unknown = [x for x in names if x not in VARIANTS]
    if unknown:
        sys.exit(f"unknown variant(s): {unknown}\nknown: {', '.join(VARIANTS)}")
    ratchet = args.ratchet or "const"
    rat_txt = {"const": f"constant {BE_TRIGGER_R:.2f}R (today's rule) on every bar",
               "era": "the live-era schedule (none before 2026-09-10 12:34, so history before it runs WITHOUT a ratchet)",
               "off": "OFF"}[ratchet]
    t0, t1 = bars[0][0], bars[-1][0]
    sessions = len({b[0].date() for b in bars})
    print(f"strategy_lab HISTORY — {len(bars)} bars {t0} -> {t1} ({(t1 - t0).days + 1} calendar days, {sessions} dates with "
          f"data) | first ready bar {lab.ts[first]}")
    print(f"file: {path}\n"
          f"mode: replay of TODAY's rules over broker M1 history. The live ledger and the calibration are skipped "
          f"(--bars implies no ledger).\n"
          f"cost ${args.cost:.2f}/side = ${2 * args.cost:.2f}/round trip | BE ratchet: {rat_txt}\n")
    # ------------------------------------------------------------------ H1 data quality
    gaps = defaultdict(int)
    for a, b in zip(bars, bars[1:]):
        m = (b[0] - a[0]).total_seconds() / 60.0
        if m >= 30:
            if m > 24 * 60:
                gaps["weekend/holiday (> 24 h)"] += 1
            elif 20 * 60 + 30 <= a[0].hour * 60 + a[0].minute <= 23 * 60 + 30 and m <= 150:
                gaps["daily break (starts 20:30-23:30 UTC)"] += 1
            else:
                gaps["UNSCHEDULED hole (30 min .. 24 h)"] += 1
    print("== H1. DATA ==")
    print("    gaps >= 30 min: " + (", ".join(f"{v} x {k}" for k, v in sorted(gaps.items())) or "none"))
    hl = [t for t in (b[0] for b in bars) if t < TUNING_START]
    print(f"    {len(hl)} bars ({100 * len(hl) / len(bars):.0f}%) lie BEFORE {TUNING_START:%Y-%m-%d}, the first live trade: those are "
          f"out-of-sample for the rules; later bars overlap the data they were tuned on."
          if hl else f"    NO bar lies before {TUNING_START:%Y-%m-%d} (the first live trade): nothing here is out-of-sample "
                     f"for the rules - this file only adds replay volume on the tuning period.")
    # ------------------------------------------------------------------ H2 windows x variants
    wins = [("ALL", None, None)]
    if hl:
        wins.append((f"OOS (< {TUNING_START:%m-%d})", None, TUNING_START))
        if t1 >= TUNING_START:
            wins.append((f"IN-SAMPLE (>= {TUNING_START:%m-%d})", TUNING_START, None))
    print("\n== H2. REPLAY BY WINDOW (each row is a full independent cascade restarted at the window start) ==")
    delta = {}
    for label, frm, to in wins:
        for nm in names:
            trs, _ = lab.run(dict(VARIANTS[nm][1]), first_i=first, cost_per_side=args.cost, ratchet=ratchet, window=(frm, to))
            print(_hist_line(label, nm, trs))
            delta[(label, nm)] = trs
        if "baseline" in names and "structstop" in names:
            a_, b_ = delta[(label, "baseline")], delta[(label, "structstop")]
            if a_ and b_:
                print(f"  {'':22s}structstop - baseline: {statistics.mean(t['Rnet'] for t in b_) - statistics.mean(t['Rnet'] for t in a_):+.3f} R/trade, "
                      f"{statistics.mean(t['net'] for t in b_) - statistics.mean(t['net'] for t in a_):+.3f} $/trade")
    # ------------------------------------------------------------------ H3 by month
    print("\n== H3. BY CALENDAR MONTH (each month is an independent cascade restarted at the month start) ==")
    for label, frm, to in _month_windows(t0, t1):
        for nm in names:
            trs, _ = lab.run(dict(VARIANTS[nm][1]), first_i=first, cost_per_side=args.cost, ratchet=ratchet, window=(frm, to))
            print(_hist_line(label + ("  (partial)" if (frm < t0 or to > t1 + timedelta(days=1)) else ""), nm, trs))
    # ------------------------------------------------------------------ H4 cost sensitivity
    print("\n== H4. COST SENSITIVITY on the ALL window (R/trade and $/trade, net) ==")
    print(f"    {'cost/side':>10} " + " ".join(f"{nm:>26s}" for nm in names))
    for c in HISTORY_COSTS:
        cells = []
        for nm in names:
            trs, _ = lab.run(dict(VARIANTS[nm][1]), first_i=first, cost_per_side=c, ratchet=ratchet)
            cells.append(f"n={len(trs):5d} {statistics.mean(t['Rnet'] for t in trs):+7.3f}R {statistics.mean(t['net'] for t in trs):+7.3f}$"
                         if trs else "no trades")
        print(f"    ${c:8.2f} " + " ".join(f"{x:>26s}" for x in cells))
    print("""
READ THIS BEFORE QUOTING ANYTHING ABOVE
 - This is broker M1 HISTORY, replayed. The engine consumes the same terminal's closed M1 bars (tools/history_to_log.py
   proves it bar-for-bar on the overlap with the live log), but spreads, gaps and the exact cascade are not the live
   ones: the live ledger and forward test stay the authority (HANDOFF section 8).
 - OOS rows are out-of-sample for the RULES (tuned on live data from 2026-09-04) but not for the idea: a result found here
   is a hypothesis to PRE-REGISTER and forward-test, never a reason to change a parameter inside an open test window.
 - Costs are the flat per-side charge. Real spreads widen in Asia/rollover and at news (tools/xm_quote_report.py measures
   them); compare ROW-TO-ROW deltas, not absolute dollars.
 - Intra-bar ordering is unknowable from OHLC (engine convention: arm-before-stop, stop-before-target), so every row
   shares the same bias; a looser stop or ratchet always looks better under it.
 - Months are independent cascades; a partial first/last month is small-n. Do not read a monthly row on its own.""")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cost", type=float, default=0.20, help="cost per side, $ (0 disables)")
    ap.add_argument("--calib-only", action="store_true")
    ap.add_argument("--only", default=None, help="comma list of variant names")
    ap.add_argument("--grid", choices=["level"], help="scan the level tolerance")
    ap.add_argument("--table", action="store_true",
                    help="era x cost grid for the selected variants - every cell is a full "
                         "independent cascade restarted at the era boundary. This is the table "
                         "docs/ANALYSIS-2026-10-05-stop-loss-geometry.md quotes.")
    ap.add_argument("--era", choices=["all", "075", "maxhold"], default="075",
                    help="run the variant pass on entries from this era only "
                         "(default 075 = the book where today's whole rule stack was live)")
    ap.add_argument("--json", default=None)
    ap.add_argument("--bars", default=None, metavar="PATH",
                    help="LARGE-N mode: replay today's rules over a UTC bar file made by tools/history_to_log.py "
                         "(broker M1 history). Skips the live ledger and the calibration.")
    ap.add_argument("--ratchet", choices=["const", "era", "off"], default=None,
                    help="with --bars only: BE ratchet for the whole history - const = 0.75R everywhere (default), "
                         "era = the live schedule (none before 09-10), off")
    args = ap.parse_args(argv)
    if args.ratchet and not args.bars:
        sys.exit("--ratchet only applies with --bars (the live-era replay always uses the era schedule)")
    if args.bars:
        for flag, bad in (("--table", args.table), ("--grid", args.grid), ("--calib-only", args.calib_only),
                          ("--json", args.json), ("--era", args.era != "075")):
            if bad:
                sys.exit(f"{flag} is for the live-era replay and does not combine with --bars")
        return history_report(args)

    bars = load_bars()
    ledger = load_ledger()
    lab = Lab(bars)
    first = lab.ready[0] if lab.ready else 0
    print(f"strategy_lab — {len(bars)} bars {bars[0][0]} -> {bars[-1][0]} | first ready bar {lab.ts[first]}")
    post = [t for t in ledger if t["et"] >= LIVE_CUTOVER]
    legacy = [t for t in ledger if t["et"] < LIVE_CUTOVER]
    print(f"ledger: {len(ledger)} closed trades ({len(legacy)} pre-{LIVE_CUTOVER:%Y-%m-%d %H:%M}-cutover -> replay with "
          f"`baseline`; {len(post)} under the structural stop -> replay with `--only structstop`)\n"
          f"        cost model ${args.cost:.2f}/side = ${2*args.cost:.2f}/round trip (BE included)\n")

    base, blocked = lab.run({}, first_i=first, cost_per_side=args.cost)

    # ------------------------------------------- --table: era x cost x variant
    if args.table:
        eras = [("pre-ratchet", datetime(2026, 9, 1), ERA_030),
                ("0.30R", ERA_030, ERA_RATCHET_075),
                ("075R pre-mh", ERA_RATCHET_075, ERA_MAXHOLD),
                ("max-hold", ERA_MAXHOLD, None),
                ("075R MASTER", ERA_RATCHET_075, None),
                ("post-cutover", LIVE_CUTOVER, None)]
        names = [x.strip() for x in (args.only.split(",") if args.only else []) if x.strip()]
        unknown = [x for x in names if x not in VARIANTS]
        if unknown:
            sys.exit(f"unknown variant(s): {unknown}\nknown: {', '.join(VARIANTS)}")
        names = names or ["baseline", "structstop"]
        for cost in (0.0, 0.15, 0.20, 0.35):
            print(f"\n== TABLE cost/side ${cost:.2f} (round trip ${2 * cost:.2f}) ==")
            print(f"  {'era':13s}{'variant':16s}{'n':>4}{'decWR':>7}{'SL%':>6}{'BE%':>5}{'T':>3}"
                  f"{'R/t':>8}{'$/t':>8}{'$/day':>8}{'n/day':>6}{'hold':>7}{'maxDD':>7}"
                  f"{'avgSL$':>8}{'avgTP$':>8}{'payoff':>7}{'medR$':>7}{'medRATR':>8}")
            for en, frm, to in eras:
                for nm in names:
                    trs, _ = lab.run(dict(VARIANTS[nm][1]), first_i=first,
                                     cost_per_side=cost, window=(frm, to))
                    if not trs:
                        print(f"  {en:13s}{nm:16s}  (no trades yet in this window)")
                        continue
                    W = [t for t in trs if t["reason"] == "TP"]
                    L = [t for t in trs if t["reason"] == "SL"]
                    BE = [t for t in trs if t["reason"] == "BE"]
                    TI = [t for t in trs if t["reason"] == "TIME"]
                    days = len({t["ts"].date() for t in trs}) or 1
                    eq = pk = 500.0
                    dd = 0.0
                    for t in sorted(trs, key=lambda x: x["ts"]):
                        eq += t["net"]
                        pk = max(pk, eq)
                        dd = max(dd, pk - eq)
                    avgW = statistics.mean([t["net"] for t in W]) if W else 0.0
                    avgL = statistics.mean([t["net"] for t in L]) if L else 0.0
                    print(f"  {en:13s}{nm:16s}{len(trs):4d}"
                          f"{(100 * len(W) / (len(W) + len(L))) if (W or L) else 0:6.1f}%"
                          f"{100 * len(L) / len(trs):5.1f}%{100 * len(BE) / len(trs):4.0f}%{len(TI):3d}"
                          f"{statistics.mean(t['Rnet'] for t in trs):+8.3f}"
                          f"{statistics.mean(t['net'] for t in trs):+8.3f}"
                          f"{statistics.mean(t['net'] for t in trs) * len(trs) / days:+8.2f}"
                          f"{len(trs) / days:6.1f}{statistics.median(t['hold_min'] for t in trs):6.1f}m"
                          f"{dd:7.1f}{avgL:8.2f}{avgW:8.2f}"
                          f"{(avgW / -avgL) if (W and L and avgL) else 0:7.2f}"
                          f"{statistics.median(t['risk'] for t in trs):7.2f}"
                          f"{statistics.median(t['risk'] / t['atr'] for t in trs):8.2f}")
        print(f"\n  `baseline` = the geometry production used until {LIVE_CUTOVER:%Y-%m-%d %H:%M} UTC (risk = 2xATR,")
        print("  TP = 3xATR). `structstop` = what is live from the cutover. Pre-cutover eras are")
        print("  counterfactuals; the post-cutover row is the real measurement once data exists.")
        return

    # ------------------------------------------------------------- 1. calib
    print("== 1. CALIBRATION — funnel match vs the live ledger (era-by-era) ==")
    print("    The replay must reproduce the live ENTRY stream before any of its")
    print("    counterfactuals mean anything (ANALYSIS-2026-10-01 §4 item 1).\n")
    raw = []
    for i in range(first, len(bars)):
        s_ = lab.signal(i, {})
        if s_:
            raw.append((i, bars[i][0], s_, bars[i][4]))
    for label, frm, to in (("pre-gates", datetime(2026, 9, 1), ERA_030),
                           ("0.30R era", ERA_030, ERA_RATCHET_075),
                           ("0.75R master", ERA_RATCHET_075, None),
                           ("max-hold", ERA_MAXHOLD, None)):
        sset = defaultdict(list)
        for i, t, sg, c in raw:
            if frm <= t < (to or datetime(2100, 1, 1)):
                sset[t.replace(second=0, microsecond=0)].append((sg, c))
        L = [x for x in ledger if x["et"] >= frm and (to is None or x["et"] < to)]
        hit = side = 0
        for x in L:
            k = x["et"].replace(second=0, microsecond=0)
            cand = [c for d in (0, 1, -1, 2) for c in sset.get(k + timedelta(minutes=d), [])]
            if cand:
                hit += 1
                if any(c[0] == x["side"] for c in cand):
                    side += 1
        n_sig = sum(len(v) for v in sset.values())
        print(f"    {label:12s} ledger {len(L):3d} entries | {n_sig:4d} raw signals | "
              f"entry-stream recall {100*hit/max(1,len(L)):5.1f}% | side+price ok {100*side/max(1,len(L)):5.1f}%")
    print("    (pre-09-10 recall is low on purpose: the gate stack itself changed on")
    print("     09-10 12:34 — blackouts/ATR bounds here reflect today's rules.)\n")

    base, blocked = lab.run({}, first_i=first, cost_per_side=args.cost)
    led = defaultdict(list)
    for t in ledger:
        led[t["et"].replace(second=0, microsecond=0)].append(t)
    matched = side_ok = 0
    for tr in base:
        k = tr["ts"].replace(second=0, microsecond=0)
        cand = [c for d in (0, 1, -1, 2) for c in led.get(k + timedelta(minutes=d), [])]
        if cand:
            matched += 1
            if any(c["side"] == tr["side"] for c in cand):
                side_ok += 1
    print(f"    taken-set overlap: replay {len(base)} vs ledger {len(ledger)}; {matched} replay trades have a")
    print(f"    ledger entry in the same minute ({100*matched/max(1,len(base)):.0f}%). The gap is cascade, not funnel: a")
    print(f"    simulated exit that lands a bar differently shifts the 30/60-min cooldown.")
    print(f"    replay gate blocks: {blocked}")
    print("    " + summarize(base, "REPLAY", width=8) + "   (net of costs)")
    led_R = [(t["pnl"] - 2 * args.cost) / (2 * t["atr"]) for t in ledger if t["atr"]]
    W = sum(1 for t in ledger if t["reason"] == "TP"); L = sum(1 for t in ledger if t["reason"] == "SL")
    print(f"    {'LEDGER':8s} n={len(ledger):4d} {W:3d}W/{L:3d}L  {100*W/(W+L):5.1f}%dec "
          f"${statistics.mean([t['pnl']-2*args.cost for t in ledger]):+7.3f}/t "
          f"{statistics.mean(led_R):+6.3f}R/t  (same cost model applied)\n")
    if args.calib_only:
        return

    # ------------------------------------------------------------ 2. variants
    if args.grid == "level":
        print("\n== 2. LEVEL-TOLERANCE GRID (how tight must the structural test be?) ==")
        print(f"    {'tol (ATR)':>9} {'taken':>6} {'W':>4} {'L':>4} {'BE':>4} {'dec WR':>7} {'$/trade':>8} {'R/trade':>8} {'SL rate':>7}")
        for tol in (None, 2.0, 1.5, 1.0, 0.75, 0.5, 0.35, 0.25, 0.15, 0.0):
            trs, _ = lab.run({} if tol is None else {"level_tol_atr": tol}, first_i=first, cost_per_side=args.cost)
            w = sum(1 for t in trs if t["reason"] == "TP"); l = sum(1 for t in trs if t["reason"] == "SL")
            be = sum(1 for t in trs if t["reason"] == "BE")
            if not trs:
                print(f"    {'live 0.2%' if tol is None else tol:>9} {'0':>6}"); continue
            print(f"    {('live 0.2%' if tol is None else f'{tol:.2f}'):>9} {len(trs):6d} {w:4d} {l:4d} {be:4d} "
                  f"{100*w/(w+l) if w+l else 0:6.1f}% {statistics.mean(t['net'] for t in trs):+8.3f} "
                  f"{statistics.mean(t['Rnet'] for t in trs):+8.3f} {100*l/len(trs):6.1f}%")
        return

    names = list(VARIANTS) if not args.only else [x.strip() for x in args.only.split(",") if x.strip() in VARIANTS]
    win = {"all": (None, None), "075": (ERA_RATCHET_075, None),
           "maxhold": (ERA_MAXHOLD, None)}[args.era]
    era_lbl = {"all": "ALL DATA", "075": "0.75R MASTER (entries >= 09-15 06:00)",
               "maxhold": "MAX-HOLD ERA (entries >= 09-21 06:00)"}[args.era]
    print(f"\n== 2. VARIANTS — stateful replay restricted to {era_lbl} ==")
    print("    Each variant restarts the cascade at the era boundary, so every row\n"
          "    (including BASELINE) is a full independent portfolio, not a haircut of the ledger.\n")
    bwin, bblk = lab.run({}, first_i=first, cost_per_side=args.cost, window=win)
    bR = statistics.mean(t["Rnet"] for t in bwin) if bwin else 0.0
    bD = statistics.mean(t["net"] for t in bwin) if bwin else 0.0
    bW = sum(1 for t in bwin if t["reason"] == "TP"); bL = sum(1 for t in bwin if t["reason"] == "SL")
    print("    " + summarize(bwin, "BASELINE", width=14) + f"   [dec {100*bW/(bW+bL) if bW+bL else 0:.1f}%]")
    days = len({t["ts"].date() for t in bwin}) or 1
    print(f"    baseline trades/day {len(bwin)/days:.1f} over {days} sessions, blocks {bblk}\n")
    results = {}
    for name in names:
        desc, cfg = VARIANTS[name]
        trs, blk = lab.run(cfg, first_i=first, cost_per_side=args.cost, window=win)
        mast = trs if args.era == "075" else [t for t in trs if t["ts"] >= ERA_RATCHET_075]
        mh = trs if args.era == "maxhold" else [t for t in trs if t["ts"] >= ERA_MAXHOLD]
        print(f"\n  [{name}] {desc}")
        print("   " + summarize(trs, "all", width=9))
        print("   " + summarize(mast, "0.75R", width=9))
        print("   " + summarize(mh, "maxhold", width=9))
        buy = [t for t in trs if t["side"] == "BUY"]; sell = [t for t in trs if t["side"] == "SELL"]
        print("   " + summarize(buy, "BUY", width=9))
        print("   " + summarize(sell, "SELL", width=9))
        if buy and sell:
            print(f"    side gap {statistics.mean(t['Rnet'] for t in sell)-statistics.mean(t['Rnet'] for t in buy):+.3f}R/trade "
                  f"Fisher p={fisher(buy, sell):.4f} | blocks {blk}")
        asia = [t for t in trs if t["ts"].hour >= 23 or t["ts"].hour < 7]
        if trs:
            Ra = statistics.mean(t["Rnet"] for t in asia) if asia else float("nan")
            Ro = statistics.mean(t["Rnet"] for t in trs if t not in asia) if len(asia) < len(trs) else float("nan")
            print(f"    band: Asia/rollover {len(asia):3d}/{len(trs)} entries "
                  f"({100*len(asia)/len(trs):4.0f}%)  {Ra:+.3f}R/t vs London/NY {Ro:+.3f}R/t")
        step = max(1, len(mast) // 4)
        cells = []
        for k in range(0, len(mast), step):
            ch = mast[k:k + step]
            w = sum(1 for t in ch if t["reason"] == "TP"); l = sum(1 for t in ch if t["reason"] == "SL")
            cells.append(f"{100*w/(w+l) if w+l else 0:.0f}%")
        print(f"    master chunk WR: {' '.join(cells)}")
        results[name] = dict(desc=desc, cfg={k: str(v) for k, v in cfg.items()}, n=len(trs), n_master=len(mast),
                             wr_master=round(100 * sum(1 for t in mast if t["reason"] == "TP") /
                                             max(1, sum(1 for t in mast if t["reason"] in ("TP", "SL"))), 1),
                             net_trade=round(statistics.mean(t["net"] for t in trs), 4) if trs else None,
                             R_trade=round(statistics.mean(t["Rnet"] for t in trs), 4) if trs else None,
                             R_master=round(statistics.mean(t["Rnet"] for t in mast), 4) if mast else None,
                             sl_rate=round(100 * sum(1 for t in trs if t["reason"] == "SL") / max(1, len(trs)), 1),
                             asia_share=round(100 * len(asia) / max(1, len(trs)), 1),
                             tp=sum(1 for t in trs if t["reason"] == "TP"),
                             sl=sum(1 for t in trs if t["reason"] == "SL"),
                             be=sum(1 for t in trs if t["reason"] == "BE"),
                             med_hold=round(statistics.median(t["hold_min"] for t in trs), 1) if trs else None,
                             blocks=blk)
    print(f"\n== 3. VS IN-WINDOW BASELINE ({bD:+.3f}$/t, {bR:+.3f}R/t, n={len(bwin)}) ==")
    for name in names:
        r = results[name]
        if r["R_trade"] is None:
            continue
        print(f"    {name:16s} {r['R_trade']-bR:+.3f}R/trade  {r['net_trade']-bD:+.3f}$/trade  "
              f"n={r['n']:4d} ({r['n']/max(1,len(bwin)):.2f}x volume)  SL-rate {r['sl_rate']:4.1f}%  "
              f"master {r['R_master']:+.3f}R")
    if args.json:
        with open(args.json, "w") as f:
            json.dump(results, f, indent=1)
        print(f"\n  wrote {args.json}")

    print("""
CAVEATS — read before quoting any number above
 - One position at a time (the engine can only hold one), so the cascade is
   real here, but a different entry stream re-shuffles which setups get
   consumed: compare ROW-TO-ROW deltas, not absolute dollars.
 - Intra-bar ordering is unknowable from OHLC. This uses the engine's own
   convention (arm-before-stop, stop-before-target), so every row shares the
   same bias — again, deltas over levels. A looser stop/ratchet always looks
   better under a fixed convention: the walk cannot see a wick that touched
   the target and then the stop.
 - Costs are a flat per-side charge. Real GOLD spreads widen in the Asia/
   rollover hours and at scheduled news, so a variant that wins by trading
   MORE must survive a volatility-scaled spread, not a constant one.
 - A replay result is a reason to run an isolated forward test with a
   pre-registered bar. It is never a reason to size up or go live.""")


if __name__ == "__main__":
    main()
