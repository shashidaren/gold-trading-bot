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
PRICE_LOG  = "/opt/gold/forward_test_log.csv"
LOOKBACK   = 30

# === Settings (Risk & Volatility Controls) ===
SL_COOLDOWN_BASE_MINUTES = 30     # Base cooldown after 1 SL (30 min)
SL_COOLDOWN_ESCALATED_MINUTES = 60 # Escalated cooldown after 2 consecutive SLs (60 min)
MAX_DAILY_LOSSES         = 10     # Trend-side-only mode engages after this many SLs in one
                                  # UTC day (soft breaker, 2026-09-10). Intentionally 10:
                                  # the 3->10 bump of 2026-09-10 was deliberate; older live
                                  # skip rows still show the previous limit ("11/3 SLs today").
MIN_ATR_TO_TRADE         = 1.10   # Do not trade when ATR is too low
MAX_ATR_TO_TRADE         = 4.50   # Block trades during extreme news spikes / illiquidity
MOMENTUM_LOOKBACK_MINUTES = 60    # Higher-TF momentum window for the trend-side gate

# === Session Blackout Windows (UTC) ===
# High-risk session transitions, news windows, and rollover spread spikes.
# Each entry: (start_h, start_m, end_h, end_m, label, blocked_sides)
# London kill-zone is DIRECTION-AWARE since 2026-09-10: phantom replay of
# blocked signals showed SELLs there going 5W/1L (+20 phantom) while BUYs
# whipsawed (see docs/ANALYSIS-2026-09-10-losing-trades.md). Block BUYs,
# allow SELLs. Other windows block both sides.
BLACKOUT_WINDOWS = [
    (7, 55, 9, 0, "London Open & Early Session Kill-Zone", ("BUY",)),
    (12, 25, 12, 45, "NY Early Pre-Market", ("BUY", "SELL")),
    (13, 25, 15, 15, "NY Open & US High-Impact Macro Releases", ("BUY", "SELL")),
    (21, 45, 22, 30, "Daily Market Rollover & Spread Spike", ("BUY", "SELL")),
]


def is_in_blackout(now: datetime = None, side: str = None) -> tuple[bool, str]:
    """True when `now` is inside a blackout window that blocks `side`.
    side=None keeps legacy behavior (any window blocks)."""
    if now is None:
        now = datetime.now(timezone.utc)
    t = now.time()
    for sh, sm, eh, em, label, sides in BLACKOUT_WINDOWS:
        start = time(sh, sm)
        end = time(eh, em)
        if start <= t <= end and (side is None or side in sides):
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


def get_momentum_side(now: datetime = None,
                      minutes: int = MOMENTUM_LOOKBACK_MINUTES,
                      price_log: str = None):
    """Sign of the last `minutes` of price movement, read from the 1-min log.

    Returns "BUY" (rising), "SELL" (falling), or None when the log is
    missing, stale (>15 min behind `now`), or has no data at the cutoff.
    Tail-reads the file so the cost stays flat as the log grows.
    """
    path = price_log or PRICE_LOG
    if not os.path.isfile(path):
        return None
    if now is None:
        now = datetime.now(timezone.utc)
    now_naive = now.replace(tzinfo=None)
    cutoff = now_naive - timedelta(minutes=minutes)

    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 256 * 1024))
            chunk = f.read().decode("utf-8", errors="ignore")
        lines = chunk.splitlines()
        if size > 256 * 1024 and lines:
            lines = lines[1:]  # drop the possibly-partial first line
        last_ts = None
        close_now = None
        close_then = None
        for line in lines:
            parts = line.split(",")
            if len(parts) < 5 or not parts[0] or parts[0] == "Timestamp":
                continue
            try:
                ts = datetime.strptime(parts[0], "%Y-%m-%d %H:%M:%S")
                c = float(parts[4])
            except (ValueError, IndexError):
                continue
            if ts <= cutoff:
                close_then = c
            last_ts = ts
            close_now = c
        if close_now is None or close_then is None or last_ts is None:
            return None
        if (now_naive - last_ts) > timedelta(minutes=15):
            return None  # stale feed - don't trust momentum
        if close_now > close_then:
            return "BUY"
        if close_now < close_then:
            return "SELL"
        return None
    except Exception as e:
        print(f"⚠️ momentum read failed: {e}")
        return None


def check_daily_loss_limit(trades: list, now: datetime = None, side: str = None) -> tuple[bool, str]:
    """Soft circuit breaker (2026-09-10 change).

    Phantom replay showed the hard halt was anti-productive: signals fired
    right AFTER the halt went 7W/0L (+27.71 phantom) because loss clusters
    mark trend days, and the trend then pays the *other* side (see
    docs/ANALYSIS-2026-09-10-losing-trades.md). So once the daily SL limit
    is hit, only entries aligned with 60-min momentum pass; the wrong side
    is skipped instead of halting everything.

    Without `side` (legacy callers/tests) or when momentum is unavailable,
    this falls back to the original hard halt.
    """
    daily_sls = get_daily_sl_count(trades, now)
    if daily_sls < MAX_DAILY_LOSSES:
        return False, ""
    hard_reason = f"Daily Loss Limit Reached ({daily_sls}/{MAX_DAILY_LOSSES} SLs today)"
    if side is None:
        return True, f"{hard_reason} - Trading Halted"
    mom = get_momentum_side(now)
    if mom is None:
        return True, f"{hard_reason} - Trading Halted (momentum unavailable)"
    if side == mom:
        return False, "OK"
    return True, (f"{hard_reason} - Trend-Side Only: "
                  f"{side} blocked, momentum is {mom}")


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


def should_take_trade(current_atr=None, current_price=None, ema_fast=None, ema_slow=None, now: datetime = None, side: str = None) -> tuple[bool, str]:
    """
    Final gatekeeper for portfolio/state-level rules.
    Note: RSI, Wick, Floor/Ceiling, and Trend direction are validated in engine.py.

    `side` ("BUY"/"SELL") enables the direction-aware rules:
      - London kill-zone blackout blocks BUYs only (SELL phantom edge 2026-09-10)
      - the daily-loss breaker degrades to trend-side-only instead of halting
    Legacy callers passing no side keep the old block-everything behavior.
    """

    # 1. Time blackout (direction-aware)
    in_bo, bo_reason = is_in_blackout(now, side)
    if in_bo:
        log_skip(bo_reason, current_price, current_atr)
        return False, bo_reason

    trades = load_recent_trades()

    # 2. Daily Loss Circuit Breaker (trend-side-only after limit, not a halt)
    halted, halt_reason = check_daily_loss_limit(trades, now, side)
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
