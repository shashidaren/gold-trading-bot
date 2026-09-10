#!/usr/bin/env python3
"""
Lightweight pre-trade filter & Portfolio Risk Gatekeeper
Acts as the final gatekeeper for portfolio/state-level rules.
(Strategy-level rules like RSI, Wick, and Trend are handled in engine.py)

Timestamps: engine.py writes Entry_Time / Exit_Time in UTC.
This module also uses UTC for blackouts, cooldowns, daily limits, and skip logs.
"""

import csv
import os
from datetime import datetime, time, timedelta, timezone

TRADES_LOG = "/opt/gold/trades.csv"
SKIP_LOG   = "/opt/gold/skipped_trades.csv"
LOOKBACK   = 30

# === Settings (Risk & Volatility Controls) ===
SL_COOLDOWN_BASE_MINUTES = 30     # Base cooldown after 1 SL (30 min)
SL_COOLDOWN_ESCALATED_MINUTES = 60 # Escalated cooldown after 2 consecutive SLs (60 min)
MAX_DAILY_LOSSES         = 10     # Halt trading for the rest of the day after 10 SLs
MIN_ATR_TO_TRADE         = 1.10   # Do not trade when ATR is too low
MAX_ATR_TO_TRADE         = 4.50   # Block trades during extreme news spikes / illiquidity

# === Session Blackout Windows (UTC) ===
# High-risk session transitions, news windows, and rollover spread spikes:
BLACKOUT_WINDOWS = [
    (7, 55, 9, 0, "London Open & Early Session Kill-Zone"),
    (12, 25, 12, 45, "NY Early Pre-Market"),
    (13, 25, 15, 15, "NY Open & US High-Impact Macro Releases"),
    (21, 45, 22, 30, "Daily Market Rollover & Spread Spike"),
]


def is_in_blackout(now: datetime = None) -> tuple[bool, str]:
    if now is None:
        now = datetime.now(timezone.utc)
    t = now.time()
    for sh, sm, eh, em, label in BLACKOUT_WINDOWS:
        start = time(sh, sm)
        end = time(eh, em)
        if start <= t <= end:
            return True, f"Blackout: {label}"
    return False, ""


def load_recent_trades(n=LOOKBACK) -> list:
    if not os.path.isfile(TRADES_LOG):
        return []
    rows = []
    try:
        with open(TRADES_LOG, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Schema-drift tripwire (2026-09-10 incident): if a row was
                # written with a Trade_Type column but the header lacks it,
                # Entry_Time parses as "BUY"/"SELL" and every later field is
                # shifted - Exit_Reason becomes a price, so SL counting,
                # cooldowns and the daily-loss breaker silently stop working.
                if (row.get("Entry_Time") or "").strip().upper() in ("BUY", "SELL"):
                    print("WARNING: trades.csv schema drift detected (Entry_Time == BUY/SELL). "
                          "Risk-gate counts are UNRELIABLE until the file is migrated - "
                          "restart the engine (it auto-migrates) or run engine.migrate_trades_csv().")
                rows.append(row)
    except Exception:
        return []
    return rows[-n:] if rows else []


def get_daily_sl_count(trades: list, now: datetime = None) -> int:
    """Counts number of Stop Loss trades that exited today in UTC."""
    if not trades:
        return 0
    if now is None:
        now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    count = 0
    for t in trades:
        ext = t.get("Exit_Time") or t.get("Entry_Time") or ""
        if ext.startswith(today_str) and (t.get("Exit_Reason") or "").strip().upper() == "SL":
            count += 1
    return count


def get_consecutive_sl_count(trades: list) -> int:
    """Counts uninterrupted trailing Stop Loss trades."""
    if not trades:
        return 0
    count = 0
    for t in reversed(trades):
        reason = (t.get("Exit_Reason") or "").strip().upper()
        if reason == "SL":
            count += 1
        elif reason == "TP":
            break
    return count


def check_daily_loss_limit(trades: list, now: datetime = None) -> tuple[bool, str]:
    """Circuit breaker: Halts trading if daily loss limit is hit."""
    daily_sls = get_daily_sl_count(trades, now)
    if daily_sls >= MAX_DAILY_LOSSES:
        return True, f"Daily Loss Limit Reached ({daily_sls}/{MAX_DAILY_LOSSES} SLs today) - Trading Halted"
    return False, ""


def check_sl_cooldown(trades: list, now: datetime = None) -> tuple[bool, str]:
    """Escalating cooldown based on consecutive losses."""
    if not trades:
        return False, ""

    last = trades[-1]
    if (last.get("Exit_Reason") or "").strip().upper() != "SL":
        return False, ""

    consecutive_sls = get_consecutive_sl_count(trades)
    cooldown_minutes = (
        SL_COOLDOWN_ESCALATED_MINUTES if consecutive_sls >= 2 else SL_COOLDOWN_BASE_MINUTES
    )

    try:
        # Exit_Time is written by engine.py in UTC
        exit_time = datetime.strptime(last["Exit_Time"], "%Y-%m-%d %H:%M:%S")
        exit_time = exit_time.replace(tzinfo=timezone.utc)
        cooldown_end = exit_time + timedelta(minutes=cooldown_minutes)
        if now is None:
            now = datetime.now(timezone.utc)

        if now < cooldown_end:
            remaining = int((cooldown_end - now).total_seconds() / 60) + 1
            streak_info = f" ({consecutive_sls} consecutive SLs -> {cooldown_minutes}m cooldown)" if consecutive_sls >= 2 else ""
            return True, f"SL Cooldown: {remaining} min remaining{streak_info}"
    except Exception:
        pass

    return False, ""


def log_skip(reason: str, price=None, atr=None):
    file_exists = os.path.isfile(SKIP_LOG)
    try:
        with open(SKIP_LOG, mode="a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "Timestamp", "Reason", "Price", "ATR"
            ])
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "Reason": reason,
                "Price": f"{price:.2f}" if price is not None else "",
                "ATR": f"{atr:.2f}" if atr is not None else "",
            })
    except Exception as e:
        print(f"⚠️ Failed to log skip: {e}")


def should_take_trade(current_atr=None, current_price=None, ema_fast=None, ema_slow=None, now: datetime = None) -> tuple[bool, str]:
    """
    Final gatekeeper for portfolio/state-level rules.
    Note: RSI, Wick, Floor/Ceiling, and Trend direction are validated in engine.py.
    """

    # 1. Time blackout
    in_bo, bo_reason = is_in_blackout(now)
    if in_bo:
        log_skip(bo_reason, current_price, current_atr)
        return False, bo_reason

    trades = load_recent_trades()

    # 2. Daily Loss Circuit Breaker
    halted, halt_reason = check_daily_loss_limit(trades, now)
    if halted:
        log_skip(halt_reason, current_price, current_atr)
        return False, halt_reason

    # 3. Escalating SL Cooldown
    skip, reason = check_sl_cooldown(trades, now)
    if skip:
        log_skip(reason, current_price, current_atr)
        return False, reason

    # 4. Minimum ATR (Volatility filter)
    if current_atr is not None and current_atr < MIN_ATR_TO_TRADE:
        reason = f"ATR too low ({current_atr:.2f} < {MIN_ATR_TO_TRADE})"
        log_skip(reason, current_price, current_atr)
        return False, reason

    # 5. Maximum ATR (Block extreme news volatility / spreads)
    if current_atr is not None and current_atr > MAX_ATR_TO_TRADE:
        reason = f"ATR too high - News volatility ({current_atr:.2f} > {MAX_ATR_TO_TRADE})"
        log_skip(reason, current_price, current_atr)
        return False, reason

    # All portfolio filters passed
    return True, "OK"


if __name__ == "__main__":
    # Test run with dummy data
    allow, reason = should_take_trade(current_atr=1.50, current_price=3400.00, ema_fast=3405.00, ema_slow=3395.00)
    print(f"Allow: {allow} | Reason: {reason}")
