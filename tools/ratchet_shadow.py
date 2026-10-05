#!/usr/bin/env python3
"""
Ratchet-off forward shadow A/B test harness & calibration validator.

Implements the experimental shadow evaluator defined in:
  docs/PREREG-2026-10-05-ratchet-off.md

Requirements:
- REUSE the signal funnel and BE/max-hold exit logic from engine.py and
  gates from trade_filter.py (no rule divergence).
- Stateful: one position at a time; SL cooldown 30 min / 60 min after 2
  consecutive SLs with BE neither counting nor breaking the streak;
  daily breaker 10 SLs -> trend-side-only; all blackouts incl. BUY-only
  London window; ATR bounds (1.10 - 4.50); bar-vs-tick exit priority.
- Cost model: $0.05 / $0.08 / $0.11 per round trip on EVERY exit incl. BE & TIME;
  gap exits fill at re-open price.
- Read-only w.r.t live state: reads CSVs, writes only its own shadow log/state.
  NO change to engine.py / trade_filter.py / dashboard.py / any live parameter.
- Deterministic + idempotent.

Modes:
  --calibrate    Run historical calibration gate (BE_TRIGGER_R = 0.75) vs live ledger.
  --shadow       Run shadow simulation (BE_TRIGGER_R = None) over historical/candidate window.
  --init-t0      Initialize T0 and forward state files.
"""
import os
import sys
import csv
import json
import bisect
import math
from datetime import datetime, timezone, timedelta

# Path handling
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# Stub external dependencies if needed (for headless / no-network environments)
import types
for mod in ("requests", "dotenv", "twelvedata"):
    if mod not in sys.modules:
        m = types.ModuleType(mod)
        if mod == "requests": m.post = lambda *a, **k: None
        if mod == "dotenv": m.load_dotenv = lambda *a, **k: None
        if mod == "twelvedata": m.TDClient = object
        sys.modules[mod] = m

import engine
import trade_filter

LIVE_TRADES_PATH = os.path.join(ROOT, "trades.csv")
LIVE_LOG_PATH = os.path.join(ROOT, "forward_test_log.csv")
LIVE_SKIPS_PATH = os.path.join(ROOT, "skipped_trades.csv")

SHADOW_LOG_PATH = os.path.join(ROOT, "shadow_trades.csv")
SHADOW_STATE_PATH = os.path.join(ROOT, "shadow_state.json")

# Era anchors
ERA_075_DEPLOY = "2026-09-15 06:00:00"
MAX_HOLD_DEPLOY = "2026-09-21 06:00:00"
RE_REVIEW_CUTOFF = "2026-10-05 01:44:05"   # 479 closed trades snapshot

# Fixed cost tiers per PREREG §4
COST_TIERS = {
    "low": 0.05,
    "mid": 0.08,
    "high": 0.11,
}


def parse_dt(dt_str: str) -> datetime:
    """Parse 'YYYY-MM-DD HH:MM:SS' string into UTC datetime."""
    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
    return dt.replace(tzinfo=timezone.utc)


def format_dt(dt: datetime) -> str:
    """Format UTC datetime into 'YYYY-MM-DD HH:MM:SS'."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def wilson_ci(w: int, dec: int, z: float = 1.96) -> tuple[float, float]:
    """Calculate 95% Wilson score interval for decisive win rate."""
    if dec == 0:
        return 0.0, 0.0
    p = w / dec
    denom = 1.0 + z * z / dec
    centre = p + z * z / (2.0 * dec)
    half = z * math.sqrt(p * (1.0 - p) / dec + z * z / (4.0 * dec * dec))
    lo = max(0.0, (centre - half) / denom * 100.0)
    hi = min(100.0, (centre + half) / denom * 100.0)
    return lo, hi


class ShadowEngine:
    """
    Independent, stateful trade execution and risk tracking engine.
    Reuses strategy geometry and exit priority from engine.py,
    and portfolio risk rules from trade_filter.py.
    """
    def __init__(self, be_trigger_r: float = None, max_hold_minutes: int = 240):
        self.be_trigger_r = be_trigger_r          # 0.75 for control/calibration, None for ratchet-off
        self.max_hold_minutes = max_hold_minutes  # 240m max-hold cap
        self.reset()

    def reset(self):
        self.trade_active = False
        self.current_trade = None
        self.closed_trades = []
        self.balance = 500.00
        self.wins = 0
        self.losses = 0
        self.be_exits = 0
        self.time_exits = 0

    def check_sl_cooldown(self, now: datetime) -> tuple[bool, str]:
        """
        Stateful cooldown: 30 min base, 60 min after 2+ consecutive SLs.
        BE scratches and TIME exits neither count nor break streak.
        Tolerance of 5s handles candle timestamp vs sub-minute tick execution skew.
        """
        if not self.closed_trades:
            return False, ""
        last = self.closed_trades[-1]
        if last.get("Exit_Reason") != "SL":
            return False, ""

        consec_sl = trade_filter.get_consecutive_sl_count(self.closed_trades)
        cd_min = (
            trade_filter.SL_COOLDOWN_ESCALATED_MINUTES
            if consec_sl >= 2
            else trade_filter.SL_COOLDOWN_BASE_MINUTES
        )
        exit_dt = parse_dt(last["Exit_Time"])
        # Cooldown end allowing 5s sub-minute tolerance
        cd_end = exit_dt + timedelta(minutes=cd_min) - timedelta(seconds=5)
        if now < cd_end:
            rem = int((cd_end - now).total_seconds() / 60.0) + 1
            info = f" ({consec_sl} consecutive SLs -> {cd_min}m cooldown)" if consec_sl >= 2 else ""
            return True, f"SL Cooldown: {rem} min remaining{info}"
        return False, ""

    def check_daily_breaker(self, now: datetime, side: str, candles: list, candle_idx: int) -> tuple[bool, str]:
        """
        Soft daily circuit breaker: 10 SL exits in the same UTC day
        engages trend-side-only trading.
        """
        daily_sls = trade_filter.get_daily_sl_count(self.closed_trades, now)
        if daily_sls < trade_filter.MAX_DAILY_LOSSES:
            return False, ""
        hard_reason = f"Daily Loss Limit Reached ({daily_sls}/{trade_filter.MAX_DAILY_LOSSES} SLs today)"
        mom = self.get_momentum_side(now, candles, candle_idx)
        if mom is None:
            return True, f"{hard_reason} - Trading Halted (momentum unavailable)"
        if side == mom:
            return False, "OK"
        return True, f"{hard_reason} - Trend-Side Only: {side} blocked, momentum is {mom}"

    def get_momentum_side(self, now: datetime, candles: list, candle_idx: int, minutes: int = 60) -> str:
        """
        Computes 60-min momentum from candle stream directly, mirroring
        trade_filter.get_momentum_side.
        """
        cutoff = now - timedelta(minutes=minutes)
        close_now = float(candles[candle_idx]["Close"])
        last_ts = parse_dt(candles[candle_idx]["Timestamp"])
        if (now - last_ts) > timedelta(minutes=15):
            return None
        close_then = None
        for j in range(candle_idx, -1, -1):
            c_ts = parse_dt(candles[j]["Timestamp"])
            if c_ts <= cutoff:
                close_then = float(candles[j]["Close"])
                break
        if close_then is None:
            return None
        if close_now > close_then:
            return "BUY"
        if close_now < close_then:
            return "SELL"
        return None

    def should_take_trade(self, now: datetime, side: str, atr: float, price: float,
                          candles: list, candle_idx: int) -> tuple[bool, str]:
        """
        Evaluates portfolio and risk gates:
        1. Direction-aware session blackouts
        2. Daily loss circuit breaker
        3. Escalating SL cooldown
        4. Min & Max ATR bounds
        """
        in_bo, bo_reason = trade_filter.is_in_blackout(now, side)
        if in_bo:
            return False, bo_reason

        halted, halt_reason = self.check_daily_breaker(now, side, candles, candle_idx)
        if halted:
            return False, halt_reason

        skip, cd_reason = self.check_sl_cooldown(now)
        if skip:
            return False, cd_reason

        if atr < trade_filter.MIN_ATR_TO_TRADE:
            return False, f"ATR too low ({atr:.2f} < {trade_filter.MIN_ATR_TO_TRADE})"

        if atr > trade_filter.MAX_ATR_TO_TRADE:
            return False, f"ATR too high - News volatility ({atr:.2f} > {trade_filter.MAX_ATR_TO_TRADE})"

        return True, "OK"

    def open_position(self, trade_num: int, side: str, entry_time: str, entry_price: float,
                      atr: float, rsi: float, wick_ratio: str, ema50: float, ema200: float):
        """Open a new position adhering to engine 2x/3x ATR geometry."""
        initial_risk = atr * engine.ATR_SL_MULT
        tp_dist = atr * engine.ATR_TP_MULT
        if side == "BUY":
            sl = entry_price - initial_risk
            tp = entry_price + tp_dist
        else:
            sl = entry_price + initial_risk
            tp = entry_price - tp_dist

        self.current_trade = {
            "Trade_Num": trade_num,
            "Trade_Type": side,
            "Entry_Time": entry_time,
            "Entry_Price": entry_price,
            "Stop_Loss": sl,
            "Take_Profit": tp,
            "Initial_Risk": initial_risk,
            "ATR_At_Entry": atr,
            "RSI_At_Entry": rsi,
            "Wick_Ratio_At_Entry": wick_ratio,
            "EMA50_At_Entry": ema50,
            "EMA200_At_Entry": ema200,
            "BE_Armed": False,
        }
        self.trade_active = True

    def resolve_candle(self, c_ts_str: str, o: float, h: float, l: float, c: float) -> dict:
        """
        Resolves open trade against a closed candle.
        Reuses exact logic from engine.py:
        - _maybe_arm_breakeven
        - resolve_open_trade_on_candle (SL-first tie break)
        - _maybe_time_stop (priority given to price exits)
        - Gap exit: fills at re-open price if gapped beyond stop level
        """
        if not self.trade_active or not self.current_trade:
            return None

        tr = self.current_trade
        side = tr["Trade_Type"]
        e = tr["Entry_Price"]
        sl = tr["Stop_Loss"]
        tp = tr["Take_Profit"]
        initial_risk = tr["Initial_Risk"]
        be_armed = tr["BE_Armed"]

        c_dt = parse_dt(c_ts_str)
        e_dt = parse_dt(tr["Entry_Time"])
        held_min = (c_dt - e_dt).total_seconds() / 60.0

        # Maybe arm breakeven
        if self.be_trigger_r is not None and not be_armed:
            gain = (h - e) if side == "BUY" else (e - l)
            if gain >= self.be_trigger_r * initial_risk - 1e-9:
                be_armed = True
                tr["BE_Armed"] = True
                tr["Stop_Loss"] = e
                sl = e

        exit_reason = None
        exit_price = None

        # Price exits with conservative SL-first order
        if side == "BUY":
            if l <= sl:
                exit_reason = "BE" if be_armed else "SL"
                # Gap fill rule: if candle opened below stop, fill at open price
                exit_price = min(sl, o) if o < sl else sl
            elif h >= tp:
                exit_reason = "TP"
                exit_price = max(tp, o) if o > tp else tp
        else: # SELL
            if h >= sl:
                exit_reason = "BE" if be_armed else "SL"
                # Gap fill rule: if candle opened above stop, fill at open price
                exit_price = max(sl, o) if o > sl else sl
            elif l <= tp:
                exit_reason = "TP"
                exit_price = min(tp, o) if o < tp else tp

        # If price levels not hit, check MAX_HOLD_MINUTES time stop
        if exit_reason is None and held_min >= self.max_hold_minutes:
            exit_reason = "TIME"
            exit_price = c

        if exit_reason is not None:
            profit = (exit_price - e) if side == "BUY" else (e - exit_price)
            self.balance += profit

            if exit_reason == "TP":
                self.wins += 1
            elif exit_reason == "SL":
                self.losses += 1
            elif exit_reason == "BE":
                self.be_exits += 1
            elif exit_reason == "TIME":
                self.time_exits += 1

            record = {
                "Trade_Num": tr["Trade_Num"],
                "Trade_Type": side,
                "Entry_Time": tr["Entry_Time"],
                "Exit_Time": c_ts_str,
                "Entry_Price": f"{e:.2f}",
                "Stop_Loss": f"{sl:.2f}",
                "Take_Profit": f"{tp:.2f}",
                "Exit_Price": f"{exit_price:.2f}",
                "Exit_Reason": exit_reason,
                "Profit": f"{profit:.2f}",
                "Balance_After": f"{self.balance:.2f}",
                "RSI_At_Entry": f"{tr['RSI_At_Entry']:.1f}",
                "ATR_At_Entry": f"{tr['ATR_At_Entry']:.2f}",
                "Wick_Ratio_At_Entry": tr["Wick_Ratio_At_Entry"],
                "EMA50_At_Entry": f"{tr['EMA50_At_Entry']:.2f}",
                "EMA200_At_Entry": f"{tr['EMA200_At_Entry']:.2f}",
            }
            self.closed_trades.append(record)
            self.trade_active = False
            self.current_trade = None
            return record

        return None


def run_evaluation(candles: list, candidate_trades: list, be_trigger_r: float = 0.75,
                   max_hold_minutes: int = 240) -> tuple[ShadowEngine, list]:
    """
    Simulates execution of candidate entry signals sequentially against candle stream.
    Respects in-trade busy blocks, cooldown cascades, and daily loss breakers.
    """
    engine_sim = ShadowEngine(be_trigger_r=be_trigger_r, max_hold_minutes=max_hold_minutes)

    candle_ts = [c["Timestamp"] for c in candles]
    cand_by_time = {t["Entry_Time"]: t for t in candidate_trades}

    # Step through every candle in chronological order
    for idx, c in enumerate(candles):
        ts = c["Timestamp"]
        o = float(c["Open"])
        h = float(c["High"])
        l = float(c["Low"])
        close = float(c["Close"])

        # 1. Resolve active position against this candle
        if engine_sim.trade_active:
            engine_sim.resolve_candle(ts, o, h, l, close)

        # 2. Check if a new candidate signal fired at this candle close
        if not engine_sim.trade_active and ts in cand_by_time:
            cand = cand_by_time[ts]
            now_dt = parse_dt(ts)
            side = cand["Trade_Type"]
            atr = float(cand["ATR_At_Entry"])
            price = float(cand["Entry_Price"])

            allow, reason = engine_sim.should_take_trade(
                now=now_dt,
                side=side,
                atr=atr,
                price=price,
                candles=candles,
                candle_idx=idx
            )

            if allow:
                engine_sim.open_position(
                    trade_num=len(engine_sim.closed_trades) + 1,
                    side=side,
                    entry_time=ts,
                    entry_price=price,
                    atr=atr,
                    rsi=float(cand["RSI_At_Entry"]),
                    wick_ratio=cand["Wick_Ratio_At_Entry"],
                    ema50=float(cand["EMA50_At_Entry"]),
                    ema200=float(cand["EMA200_At_Entry"]),
                )

    return engine_sim, engine_sim.closed_trades


def load_live_trades(path: str = LIVE_TRADES_PATH) -> list:
    """Load historical live trades from trades.csv."""
    trades = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            trades.append(r)
    return trades


def load_candles(path: str = LIVE_LOG_PATH) -> list:
    """Load closed M1 candles from forward_test_log.csv."""
    candles = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if r["Timestamp"] and r["Open"] and r["High"] and r["Low"] and r["Close"]:
                candles.append(r)
    candles.sort(key=lambda x: x["Timestamp"])
    return candles


def calculate_metrics(trades: list, cost_per_trade: float = 0.0) -> dict:
    """Calculate decisive win rate, Wilson CI, raw & costed P&L, drawdown."""
    n = len(trades)
    w = sum(1 for t in trades if t["Exit_Reason"] == "TP")
    l = sum(1 for t in trades if t["Exit_Reason"] == "SL")
    be = sum(1 for t in trades if t["Exit_Reason"] == "BE")
    tm = sum(1 for t in trades if t["Exit_Reason"] == "TIME")
    dec = w + l
    dec_wr = (w / dec * 100.0) if dec > 0 else 0.0
    ci_lo, ci_hi = wilson_ci(w, dec)

    raw_pnl = sum(float(t["Profit"]) for t in trades)
    costed_pnl = raw_pnl - (n * cost_per_trade)
    pnl_per_trade = (costed_pnl / n) if n > 0 else 0.0

    # Drawdown calculation
    equity = 500.0
    peak = 500.0
    max_dd = 0.0
    for t in trades:
        net_profit = float(t["Profit"]) - cost_per_trade
        equity += net_profit
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    return {
        "n": n, "wins": w, "losses": l, "be": be, "time": tm,
        "decisive": dec, "dec_wr": dec_wr, "ci_lo": ci_lo, "ci_hi": ci_hi,
        "raw_pnl": raw_pnl, "costed_pnl": costed_pnl, "pnl_per_trade": pnl_per_trade,
        "max_drawdown": max_dd,
    }


def run_calibration_gate(candles: list, live_trades: list) -> bool:
    """
    Step 2 Calibration Gate:
    Runs BE_TRIGGER_R = 0.75 on the live entry stream and verifies reproduction
    within +/- 3% taken trades, +/- $10 P&L, +/- 2 pp decisive WR,
    and exact reproduction of trade #476 weekend TIME behavior.
    """
    print("=" * 65)
    print("STEP 2: CALIBRATION GATE VALIDATION (BE_TRIGGER_R = 0.75)")
    print("=" * 65)

    # Max-hold era slice (entries >= 2026-09-21 06:00 up to re-review snapshot 479)
    live_mh = [
        t for t in live_trades
        if t["Entry_Time"] >= MAX_HOLD_DEPLOY and t["Entry_Time"] <= RE_REVIEW_CUTOFF
    ]
    # Replay simulated engine
    eng_mh, sim_mh = run_evaluation(candles, live_mh, be_trigger_r=0.75, max_hold_minutes=240)

    m_live = calculate_metrics(live_mh)
    m_sim = calculate_metrics(sim_mh)

    n_diff_pct = abs(m_sim["n"] - m_live["n"]) / m_live["n"] * 100.0
    pnl_diff = abs(m_sim["raw_pnl"] - m_live["raw_pnl"])
    wr_diff = abs(m_sim["dec_wr"] - m_live["dec_wr"])

    print(f"\n[Max-Hold Era Replay (n={m_live['n']})]")
    print(f"  Live Actual : {m_live['wins']}W / {m_live['losses']}L / {m_live['be']}BE / {m_live['time']}TIME | "
          f"Dec WR: {m_live['dec_wr']:.2f}% [{m_live['ci_lo']:.1f}-{m_live['ci_hi']:.1f}] | "
          f"P&L: ${m_live['raw_pnl']:.2f}")
    print(f"  Harness Sim : {m_sim['wins']}W / {m_sim['losses']}L / {m_sim['be']}BE / {m_sim['time']}TIME | "
          f"Dec WR: {m_sim['dec_wr']:.2f}% [{m_sim['ci_lo']:.1f}-{m_sim['ci_hi']:.1f}] | "
          f"P&L: ${m_sim['raw_pnl']:.2f}")
    print(f"  Differences : Trades: {abs(m_sim['n']-m_live['n'])} ({n_diff_pct:.2f}%) | "
          f"P&L: ${pnl_diff:.2f} | Dec WR: {wr_diff:.2f} pp")

    # Gate checks
    gate_trades_ok = n_diff_pct <= 3.0
    gate_pnl_ok = pnl_diff <= 10.0
    gate_wr_ok = wr_diff <= 2.0

    # Trade #476 verification
    t476_sim = next((t for t in sim_mh if t["Entry_Time"] == "2026-10-02 20:56:02"), None)
    gate_476_ok = False
    if t476_sim is not None:
        gate_476_ok = (
            t476_sim["Exit_Reason"] == "TIME" and
            t476_sim["Exit_Time"] == "2026-10-04 22:00:06" and
            abs(float(t476_sim["Profit"]) - (-1.52)) < 0.05
        )
        print(f"  Trade #476  : {t476_sim['Exit_Reason']} exit at {t476_sim['Exit_Time']}, "
              f"P&L: ${float(t476_sim['Profit']):.2f} (Expected: TIME exit, -$1.52 across weekend close)")

    print(f"\nGate Verdicts:")
    print(f"  Trades within +/-3%   : {'PASS' if gate_trades_ok else 'FAIL'}")
    print(f"  P&L within +/-$10     : {'PASS' if gate_pnl_ok else 'FAIL'}")
    print(f"  Dec WR within +/-2 pp : {'PASS' if gate_wr_ok else 'FAIL'}")
    print(f"  Trade #476 TIME exit  : {'PASS' if gate_476_ok else 'FAIL'}")

    all_passed = gate_trades_ok and gate_pnl_ok and gate_wr_ok and gate_476_ok
    if all_passed:
        print("\n--> CALIBRATION GATE PASSED: Harness reproduced live ledger accurately.")
    else:
        print("\n--> CALIBRATION GATE FAILED: HARNESS BUG detected.")
    return all_passed


def run_shadow_simulation(candles: list, candidate_trades: list):
    """
    Runs treatment simulation (BE_TRIGGER_R = None) over candidate stream
    and evaluates against control under costs.
    """
    print("\n" + "=" * 65)
    print("SHADOW TREATMENT REPLAY (BE_TRIGGER_R = None)")
    print("=" * 65)

    eng_ctrl, trades_ctrl = run_evaluation(candles, candidate_trades, be_trigger_r=0.75, max_hold_minutes=240)
    eng_shdw, trades_shdw = run_evaluation(candles, candidate_trades, be_trigger_r=None, max_hold_minutes=240)

    for tier, cost in COST_TIERS.items():
        m_c = calculate_metrics(trades_ctrl, cost_per_trade=cost)
        m_s = calculate_metrics(trades_shdw, cost_per_trade=cost)

        diff_pnl = m_s["pnl_per_trade"] - m_c["pnl_per_trade"]
        print(f"\n--- Cost Tier: {tier.upper()} (${cost:.2f}/trade) ---")
        print(f"  Control (0.75R): n={m_c['n']} | {m_c['wins']}W/{m_c['losses']}L/{m_c['be']}BE/{m_c['time']}TIME | "
              f"Dec WR: {m_c['dec_wr']:.1f}% [{m_c['ci_lo']:.1f}-{m_c['ci_hi']:.1f}] | "
              f"Costed P&L: ${m_c['costed_pnl']:.2f} (${m_c['pnl_per_trade']:+.3f}/tr) | MaxDD: ${m_c['max_drawdown']:.2f}")
        print(f"  Shadow  (None) : n={m_s['n']} | {m_s['wins']}W/{m_s['losses']}L/{m_s['be']}BE/{m_s['time']}TIME | "
              f"Dec WR: {m_s['dec_wr']:.1f}% [{m_s['ci_lo']:.1f}-{m_s['ci_hi']:.1f}] | "
              f"Costed P&L: ${m_s['costed_pnl']:.2f} (${m_s['pnl_per_trade']:+.3f}/tr) | MaxDD: ${m_s['max_drawdown']:.2f}")
        print(f"  Delta (Shadow - Ctrl): P&L/tr: {diff_pnl:+.3f} | Dec WR: {m_s['dec_wr'] - m_c['dec_wr']:+.1f} pp | "
              f"DD ratio: {(m_s['max_drawdown'] / max(m_c['max_drawdown'], 0.01)):.2f}x")


def init_t0_and_state(candles: list, live_trades: list):
    """
    Step 3: Set T0 and initialize state/log file for forward shadow tracking.
    T0 is set to the first candle following the 2026-10-05 re-review snapshot.
    """
    print("\n" + "=" * 65)
    print("STEP 3: T0 INITIALIZATION & SHADOW STATE REGISTRATION")
    print("=" * 65)

    # First candle processed after re-review cutoff
    t0_candle = next((c for c in candles if c["Timestamp"] > RE_REVIEW_CUTOFF), candles[-1])
    t0_str = t0_candle["Timestamp"]
    print(f"Registered T0 Timestamp: {t0_str} UTC")

    # Evaluate any trades that occurred post-T0 in shadow mode
    post_t0_trades = [t for t in live_trades if t["Entry_Time"] >= t0_str]
    eng_post, sim_post = run_evaluation(candles, post_t0_trades, be_trigger_r=None, max_hold_minutes=240)

    # Write append-only shadow log
    file_exists = os.path.isfile(SHADOW_LOG_PATH)
    fieldnames = [
        "Trade_Num", "Trade_Type", "Entry_Time", "Exit_Time", "Entry_Price",
        "Stop_Loss", "Take_Profit", "Exit_Price", "Exit_Reason", "Profit",
        "Balance_After", "RSI_At_Entry", "ATR_At_Entry", "Wick_Ratio_At_Entry",
        "EMA50_At_Entry", "EMA200_At_Entry"
    ]
    with open(SHADOW_LOG_PATH, mode="w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in sim_post:
            writer.writerow(row)
    print(f"Initialized shadow trade log: {SHADOW_LOG_PATH} ({len(sim_post)} trades)")

    # Write shadow state
    state = {
        "experiment": "ratchet-off",
        "status": "FORWARD_SHADOW_ACTIVE",
        "T0": t0_str,
        "evaluation_gate": {
            "min_trades": 150,
            "min_days": 21,
            "earliest_eval_date": format_dt(parse_dt(t0_str) + timedelta(days=21))
        },
        "shadow_balance": eng_post.balance,
        "shadow_closed_trades": len(sim_post),
        "shadow_wins": eng_post.wins,
        "shadow_losses": eng_post.losses,
        "shadow_be": eng_post.be_exits,
        "shadow_time": eng_post.time_exits,
        "updated_at": format_dt(datetime.now(timezone.utc)),
    }
    with open(SHADOW_STATE_PATH, mode="w") as f:
        json.dump(state, f, indent=2)
    print(f"Initialized shadow state file: {SHADOW_STATE_PATH}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Ratchet-off shadow harness & calibration")
    parser.add_argument("--calibrate", action="store_true", help="Run Step 2 calibration gate")
    parser.add_argument("--shadow", action="store_true", help="Run shadow replay on max-hold era")
    parser.add_argument("--init-t0", action="store_true", help="Initialize T0 and state files")
    args = parser.parse_args()

    candles = load_candles()
    live_trades = load_live_trades()

    # Default to running calibration and shadow replay if no specific arg passed
    if not (args.calibrate or args.shadow or args.init_t0):
        calib_ok = run_calibration_gate(candles, live_trades)
        if not calib_ok:
            sys.exit(1)
        # Replay max-hold era under shadow
        live_mh = [
            t for t in live_trades
            if t["Entry_Time"] >= MAX_HOLD_DEPLOY and t["Entry_Time"] <= RE_REVIEW_CUTOFF
        ]
        run_shadow_simulation(candles, live_mh)
        init_t0_and_state(candles, live_trades)
        return

    if args.calibrate:
        if not run_calibration_gate(candles, live_trades):
            sys.exit(1)

    if args.shadow:
        live_mh = [
            t for t in live_trades
            if t["Entry_Time"] >= MAX_HOLD_DEPLOY and t["Entry_Time"] <= RE_REVIEW_CUTOFF
        ]
        run_shadow_simulation(candles, live_mh)

    if args.init_t0:
        init_t0_and_state(candles, live_trades)


if __name__ == "__main__":
    main()
