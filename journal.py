#!/usr/bin/env python3
"""journal.py — the bot's self-journal: every BUY/SELL, why, and how it ended.

OWNER ASK (2026-10-23)
    "just checking if you can self journal the buy/sell and see the success rate
     as well" + "if there's any more [indicators] that we can add to further
     improve".

WHAT THIS IS
    A read-only layer that turns the ledger into a journal a human can audit:

      * one record per closed trade: side, entry/exit, geometry, exit reason,
        R multiple, hold time, MFE/MAE, the engine's logged context at entry,
        the candidate-indicator snapshot at entry, and a one-line thesis;
      * honest success rates (decisive WR = TP/(TP+SL), all-in rate, R/trade,
        payoff, profit factor, net at the assumed round-trip cost) with Wilson
        CIs — overall, per rule era, per side, per session, per day;
      * "what the journal noticed": scratches that were once ahead, stop-outs
        that were once ahead, winners that survived heat, current and longest
        stop streaks, max drawdown;
      * the open trade as an entry with no outcome yet (never counted);
      * a scoreboard of candidate indicators measured on the bot's OWN entries.

    The engine does not need to write a second file for this: every decision and
    its context is derivable from forward_test_log.csv (the bar the engine had
    just processed) plus trades.csv (what happened). Deriving it means the
    journal can never silently disagree with the ledger, and re-running it fills
    in history rather than starting from today.

WHAT THIS IS NOT
    Not a strategy input. Nothing here is imported by engine.py or
    trade_filter.py, nothing writes a file (the CLI's --write is explicit), and
    no number here is an entry condition. A candidate indicator is not "added"
    by appearing in this journal: it needs a new dated pre-registration, an
    out-of-sample confirmation and owner sign-off (docs/HANDOFF.md §11). The
    board's permutation test exists precisely to stop the journal from turning
    the best-looking bucket of twenty into a strategy.

SUCCESS DEFINITIONS (the repo's own, HANDOFF §1 "Definitions")
    decisive WR   TP/(TP+SL), excludes BE and TIME
    all-in rate   TP/all closed trades (scratches and time exits count against)
    R             Profit / actual risk, risk rebuilt from the reward leg
                  |TP − Entry| / 1.5 (never ATR — ratcheted rows lose their stop)
    net           every closed trade charged the assumed round trip (default
                  $0.40 — the quote logger has not reached its 14-day target)

Stdlib only. Read-only. `python3 tools/journal_report.py` prints it.
"""
from __future__ import annotations

import bisect
import math
from datetime import datetime, timedelta

import indicators as IND
import pressure as P

COST_USD = 0.40
BE_TRIGGER_R = P.BE_TRIGGER_R
CUTOVER = P.STRUCT_STOP_CUTOVER
MFE_HEAT_R = BE_TRIGGER_R          # "was once ahead enough to arm the ratchet"
RECENT_N = 12
INDICATOR_MIN_DECISIVE = 15        # per bucket, below this no verdict is offered
NOISE_ALPHA = 0.05                 # global permutation p-value the board accepts
MIN_LIFT_PP = 8.0                  # a "candidate" must also be a useful-sized gap


# ─────────────────────────────────────────────────────────────────────────────
# 1. the joined record
# ─────────────────────────────────────────────────────────────────────────────

def _rows(source):
    """Accept parsed rows or (path) — tests pass synthetic dicts."""
    if source is None:
        return []
    if isinstance(source, (list, tuple)):
        return list(source)
    return P.read_rows(source)


def _side(row):
    return (row.get("Trade_Type") or "").strip().upper()


def _reason(row):
    reason = (row.get("Exit_Reason") or "").strip().upper()
    return reason if reason in ("TP", "SL", "BE", "TIME") else "OTHER"


def _session(dt):
    if dt is None:
        return "unknown"
    return "Asia/rollover (23–07 UTC)" if (dt.hour >= 23 or dt.hour < 7) else "London/NY (07–23 UTC)"


def _window(series, start, end):
    """Bar indices strictly after `start` and up to `end` (entry bar excluded)."""
    ts_list = series["ts"]
    lo = bisect.bisect_right(ts_list, start)
    hi = bisect.bisect_right(ts_list, end) if end is not None else series["n"]
    return lo, max(lo, hi)


def _excursions(series, side, entry, start, end):
    """MFE/MAE in $ from the price path after the entry bar. None when no bars."""
    lo, hi = _window(series, start, end)
    if hi <= lo:
        return None, None, 0
    highs = series["high"][lo:hi]
    lows = series["low"][lo:hi]
    fav = (max(highs) - entry) if side == "BUY" else (entry - min(lows))
    adv = (entry - min(lows)) if side == "BUY" else (max(highs) - entry)
    return fav, adv, hi - lo


def _entry_context(series, k, side, entry, floor, ceiling):
    """The engine's view + candidate snapshot at bar k (the last CLOSED bar)."""
    snap = IND.at(series, k) or {}
    atr = snap.get("atr")
    ctx = {key: snap.get(key) for key in IND.CONTEXT_FIELDS}
    ctx.update({
        "atr": atr, "rsi": snap.get("rsi"),
        "ema50": snap.get("ema50"), "ema200": snap.get("ema200"),
        "ema_spread_atr": snap.get("ema_spread_atr"),
        "ts": snap.get("ts"),
    })
    if k is not None and floor is not None and ceiling is not None and atr:
        ctx["floor"] = floor
        ctx["ceiling"] = ceiling
        ctx["level_dist_atr"] = ((entry - floor) / atr) if side == "BUY" else ((ceiling - entry) / atr)
        span = ceiling - floor
        ctx["range_pos"] = ((entry - floor) / span) if span > 0 else None
    else:
        ctx["level_dist_atr"] = None
        ctx["range_pos"] = snap.get("donchian_pos")

    # EMA slope in ATR, from the same series (30 bars, mirroring the engine gate)
    ctx["ema_slope_atr"] = None
    if series and k is not None and k >= 30 and atr:
        now, then = series["ema50"][k], series["ema50"][k - 30]
        if now is not None and then is not None:
            ctx["ema_slope_atr"] = (now - then) / atr
    return ctx


def _thesis(side, ctx, wick, level_dist_atr):
    bits = [side]
    if level_dist_atr is not None:
        name = "20-bar floor" if side == "BUY" else "20-bar ceiling"
        side_txt = "+" if level_dist_atr >= 0 else "−"
        bits.append(f"{name} {side_txt}{abs(level_dist_atr):.2f} ATR")
    if wick is not None:
        bits.append(f"{'lower' if side == 'BUY' else 'upper'} wick {wick:.0f}%")
    if ctx.get("rsi") is not None:
        bits.append(f"RSI {ctx['rsi']:.1f}")
    if ctx.get("ema_spread_atr") is not None:
        bits.append(f"EMA {ctx['ema_spread_atr']:+.2f} ATR")
    if ctx.get("adx") is not None:
        strength = "strong" if ctx["adx"] >= 25 else ("weak" if ctx["adx"] < 20 else "trending")
        bits.append(f"ADX {ctx['adx']:.0f} {strength}")
    if ctx.get("er30") is not None:
        bits.append(f"ER {ctx['er30']:.2f}")
    return " · ".join(bits)


def _closed_entry(series, row, cost):
    side = _side(row)
    entry = P.parse_float(row.get("Entry_Price"))
    stop = P.parse_float(row.get("Stop_Loss"))
    tp = P.parse_float(row.get("Take_Profit"))
    profit = P.parse_float(row.get("Profit"))
    risk = P.trade_risk(row)
    et = P.parse_ts(row.get("Entry_Time"))
    xt = P.parse_ts(row.get("Exit_Time"))
    if side not in ("BUY", "SELL") or entry is None or et is None:
        return None
    reason = _reason(row)
    r = (profit / risk) if (risk and profit is not None) else None

    # the entry bar is the last bar STRICTLY before the ledger's entry minute
    k = bisect.bisect_left(series["ts"], et) - 1 if series and series["n"] else None
    floor = ceiling = None
    if k is not None and k >= 20:
        floor = min(series["low"][k - 20:k])
        ceiling = max(series["high"][k - 20:k])
    ctx = _entry_context(series, k, side, entry, floor, ceiling)
    mfe, mae, path_bars = (None, None, 0)
    if series and series["n"]:
        mfe, mae, path_bars = _excursions(series, side, entry, et, xt)

    atr = P.parse_float(row.get("ATR_At_Entry"))
    wick = P.parse_float((row.get("Wick_Ratio_At_Entry") or "").replace("%", ""))
    mfe_r = (mfe / risk) if (risk and mfe is not None) else None
    mae_r = (mae / risk) if (risk and mae is not None) else None

    return {
        "num": row.get("Trade_Num"), "side": side,
        "entry_time": et, "exit_time": xt, "hour": et.hour,
        "entry": entry, "stop": stop, "tp": tp,
        "exit": P.parse_float(row.get("Exit_Price")), "reason": reason,
        "profit": profit, "risk": risk, "r": r,
        "net": (profit - cost) if profit is not None else None,
        "hold_min": ((xt - et).total_seconds() / 60.0) if xt else None,
        "mfe_r": mfe_r, "mae_r": mae_r, "path_bars": path_bars,
        "atr": atr, "rsi": P.parse_float(row.get("RSI_At_Entry")), "wick": wick,
        "ema50": P.parse_float(row.get("EMA50_At_Entry")),
        "ema200": P.parse_float(row.get("EMA200_At_Entry")),
        "level_dist_atr": ctx.get("level_dist_atr"),
        "range_pos": ctx.get("range_pos"),
        "session": _session(et),
        "era": "struct-stop" if et >= CUTOVER else "pre-struct-stop",
        "context": ctx,
        "thesis": _thesis(side, ctx, wick, ctx.get("level_dist_atr")),
        "verdict": {"TP": "win", "SL": "loss", "BE": "scratch", "TIME": "time"}.get(reason, "other"),
        "open": False,
    }


def open_entry(series, status, cost=COST_USD, price=None):
    """The live trade as a journal row with no outcome. Never counted as closed."""
    if not status or not status.get("trade_active"):
        return None
    side = (status.get("trade_type") or "").upper()
    entry = P.parse_float(status.get("entry_price"))
    tp = P.parse_float(status.get("take_profit"))
    sl = P.parse_float(status.get("stop_loss"))
    et = P.parse_ts(status.get("entry_time"))
    if side not in ("BUY", "SELL") or entry is None or tp is None or et is None or tp == entry:
        return None
    risk = abs(tp - entry) / P.RR_TARGET
    if price is None:
        price = series["close"][-1] if series and series["n"] else None
    direction = 1.0 if side == "BUY" else -1.0
    k = bisect.bisect_left(series["ts"], et) - 1 if series and series["n"] else None
    floor = ceiling = None
    if k is not None and k >= 20:
        floor = min(series["low"][k - 20:k])
        ceiling = max(series["high"][k - 20:k])
    ctx = _entry_context(series, k, side, entry, floor, ceiling)
    # status carries the engine's own entry snapshot; prefer it where present
    for key, src in (("rsi", "entry_rsi"), ("atr", "entry_atr")):
        v = P.parse_float(status.get(src))
        if v is not None:
            ctx[key] = v
    wick_raw = P.parse_float(status.get("entry_wick_ratio"))
    wick = wick_raw * 100.0 if (wick_raw is not None and wick_raw <= 1.0) else wick_raw
    age = None
    if series and series["n"]:
        age = (series["ts"][-1] - et).total_seconds() / 60.0
    return {
        "num": status.get("current_trade_num"), "side": side,
        "entry_time": et, "exit_time": None, "hour": et.hour,
        "entry": entry, "stop": sl, "tp": tp, "exit": None, "reason": "OPEN",
        "profit": None, "risk": risk, "r": None, "net": None,
        "hold_min": age,
        "mfe_r": None, "mae_r": None, "path_bars": 0,
        "atr": P.parse_float(status.get("entry_atr")),
        "rsi": P.parse_float(status.get("entry_rsi")), "wick": wick,
        "ema50": P.parse_float(status.get("entry_ema_fast")),
        "ema200": P.parse_float(status.get("entry_ema_slow")),
        "level_dist_atr": ctx.get("level_dist_atr"),
        "range_pos": ctx.get("range_pos"),
        "session": _session(et), "era": "struct-stop" if et >= CUTOVER else "pre-struct-stop",
        "context": ctx,
        "thesis": _thesis(side, ctx, wick, ctx.get("level_dist_atr")),
        "verdict": "open", "open": True,
        "price_now": price,
        "r_now": ((price - entry) * direction / risk) if (price is not None and risk) else None,
        "cost": cost,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. success accounting
# ─────────────────────────────────────────────────────────────────────────────

def _median(values):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def _mean(values):
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def summarise(entries, cost=COST_USD, label="book"):
    """Outcome, success rate, R and cost view for a list of CLOSED entries."""
    closed = [e for e in entries if not e.get("open")]
    n = len(closed)
    out = {"label": label, "n": n, "cost": cost, "counts": {"TP": 0, "SL": 0, "BE": 0, "TIME": 0, "OTHER": 0}}
    if not n:
        out.update({"decisive": 0, "decisive_wr": None, "decisive_ci": (None, None),
                    "all_in_pct": None, "gross": 0.0, "net": 0.0, "net_per_trade": None,
                    "r_mean": None, "r_median": None, "r_sum": None, "expectancy_r": None,
                    "avg_win": None, "avg_loss": None, "payoff": None,
                    "breakeven_wr_pct": None, "profit_factor": None,
                    "max_dd_net": None, "days": 0, "trades_per_day": None,
                    "hold_median": None, "hold_mean": None, "sl_share_pct": None,
                    "scratch_pct": None, "first_entry": None, "last_exit": None,
                    "streak": {"current": None, "length": 0, "longest_sl": 0},
                    "mfe_median": None, "mae_median": None})
        return out

    for e in closed:
        out["counts"][e["reason"] if e["reason"] in out["counts"] else "OTHER"] += 1
    wins = out["counts"]["TP"]
    losses = out["counts"]["SL"]
    decisive = wins + losses
    wr = (100.0 * wins / decisive) if decisive else None
    ci = P.wilson_interval(wins, decisive) if decisive else (None, None)

    gross = sum(e["profit"] or 0.0 for e in closed)
    net = sum(e["net"] or 0.0 for e in closed)
    profits = [e["profit"] for e in closed if e["profit"] is not None]
    rs = [e["r"] for e in closed if e["r"] is not None]
    win_px = [e["profit"] for e in closed if e["reason"] == "TP" and e["profit"] is not None]
    loss_px = [abs(e["profit"]) for e in closed if e["reason"] == "SL" and e["profit"] is not None]
    avg_win = _mean(win_px)
    avg_loss = _mean(loss_px)
    payoff = (avg_win / avg_loss) if (avg_win and avg_loss) else None
    breakeven_wr = (100.0 / (1.0 + payoff)) if payoff else None
    gross_win = sum(win_px) if win_px else 0.0
    gross_loss = sum(loss_px) if loss_px else 0.0
    profit_factor = (gross_win / gross_loss) if gross_loss else None

    # drawdown on the NET cumulative curve in exit order
    by_exit = sorted([e for e in closed if e.get("exit_time")], key=lambda e: e["exit_time"])
    running = peak = dd = 0.0
    for e in by_exit:
        running += e["net"] or 0.0
        peak = max(peak, running)
        dd = max(dd, peak - running)
    # SL streak in exit order (engine semantics: BE neither counts nor breaks)
    current = None
    length = 0
    longest_sl = 0
    run_sl = 0
    for e in by_exit:
        if e["reason"] == "SL":
            run_sl += 1
            current, length = "SL", run_sl
            longest_sl = max(longest_sl, run_sl)
        elif e["reason"] == "TP":
            run_sl = 0
            current, length = "TP", 1
        elif e["reason"] == "TIME":
            current, length = "TIME", 1
        # BE: ignored, exactly like get_consecutive_sl_count()

    days = len({e["entry_time"].date() for e in closed if e.get("entry_time")})
    out.update({
        "decisive": decisive, "decisive_wr": wr, "decisive_ci": ci,
        "all_in_pct": 100.0 * wins / n, "wins": wins, "losses": losses,
        "be": out["counts"]["BE"], "time": out["counts"]["TIME"],
        "gross": gross, "net": net, "net_per_trade": net / n,
        "r_mean": _mean(rs), "r_median": _median(rs), "r_sum": sum(rs) if rs else None,
        "expectancy_r": _mean(rs),
        "avg_win": avg_win, "avg_loss": avg_loss, "payoff": payoff,
        "breakeven_wr_pct": breakeven_wr, "profit_factor": profit_factor,
        "max_dd_net": dd, "days": days, "trades_per_day": (n / days) if days else None,
        "hold_median": _median([e["hold_min"] for e in closed]),
        "hold_mean": _mean([e["hold_min"] for e in closed]),
        "sl_share_pct": 100.0 * losses / n, "scratch_pct": 100.0 * out["counts"]["BE"] / n,
        "first_entry": min((e["entry_time"] for e in closed if e.get("entry_time")), default=None),
        "last_exit": max((e["exit_time"] for e in closed if e.get("exit_time")), default=None),
        "streak": {"current": current, "length": length, "longest_sl": longest_sl},
        "mfe_median": _median([e["mfe_r"] for e in closed]),
        "mae_median": _median([e["mae_r"] for e in closed]),
        "dec_win_px": _mean(win_px), "dec_loss_px": _mean(loss_px),
        "gross_win": gross_win, "gross_loss": gross_loss,
    })
    return out


def _group(entries, key):
    buckets = {}
    for e in entries:
        if e.get("open"):
            continue
        buckets.setdefault(key(e), []).append(e)
    return {name: summarise(rows, label=name) for name, rows in sorted(buckets.items())}


def givebacks(entries):
    """The journal's self-review list — factual, not advice."""
    closed = [e for e in entries if not e.get("open")]
    gave_back = [e for e in closed if e["reason"] in ("BE", "SL", "TIME")
                 and e["mfe_r"] is not None and e["mfe_r"] >= MFE_HEAT_R]
    runners = [e for e in gave_back if e["reason"] == "BE"]
    stopped = [e for e in gave_back if e["reason"] == "SL"]
    heat = [e for e in closed if e["reason"] == "TP"
            and e["mae_r"] is not None and e["mae_r"] >= 0.5]
    left = [round(e["mfe_r"] - (e["r"] or 0.0), 2) for e in gave_back]
    return {
        "was_ahead_n": len(gave_back),
        "was_ahead_pct": (100.0 * len(gave_back) / len(closed)) if closed else None,
        "scratched_runners": len(runners),
        "stopped_after_profit": len(stopped),
        "winners_with_heat": len(heat),
        "heat_r_threshold": MFE_HEAT_R,
        "left_on_table_r_median": _median(left),
        "left_on_table_r_sum": (sum(left) if left else None),
        "worst": sorted(gave_back, key=lambda e: -(e["mfe_r"] or 0))[:3],
    }


def skips(skip_rows, now=None, hours=24):
    """What the risk layer blocked — counts only (the file logs no side)."""
    now = now or (max((P.parse_ts(r.get("Timestamp")) for r in skip_rows if P.parse_ts(r.get("Timestamp"))),
                      default=None))
    recent, reasons = [], {}
    for row in skip_rows:
        ts = P.parse_ts(row.get("Timestamp"))
        if ts is None:
            continue
        label = (row.get("Reason") or "unknown").split(":")[0].strip()
        if label.startswith("ATR too high"):
            label = "ATR too high"
        elif label.startswith("Daily Loss Limit"):
            label = "Daily loss limit"
        if now is None or (now - ts) <= timedelta(hours=hours):
            recent.append(row)
            reasons[label] = reasons.get(label, 0) + 1
    return {"n_24h": len(recent), "reasons_24h": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
            "last": (recent[-1] if recent else None), "hours": hours}


def daily(entries, last=14):
    """Per-entry-date rows (the repo's era convention groups by Entry_Time)."""
    buckets = {}
    for e in entries:
        if e.get("open"):
            continue
        buckets.setdefault(e["entry_time"].date(), []).append(e)
    rows = []
    cum = 0.0
    for day in sorted(buckets):
        rows.append(summarise(buckets[day], label=str(day)))
    for row in rows:
        cum += row["net"] or 0.0
        row["cum_net"] = cum
    return rows[-last:]


# ─────────────────────────────────────────────────────────────────────────────
# 3. candidate-indicator scoreboard — measured, permutation-guarded
# ─────────────────────────────────────────────────────────────────────────────

def _two_prop_z(p1, n1, p2, n2):
    """Two-proportion z and a normal two-sided p. Returns (z, p) or (None, None)."""
    if not n1 or not n2:
        return None, None
    pool = (p1 * n1 + p2 * n2) / (n1 + n2)
    if pool <= 0 or pool >= 1:
        return None, None
    se = math.sqrt(pool * (1 - pool) * (1.0 / n1 + 1.0 / n2))
    if se == 0:
        return None, None
    z = (p1 - p2) / se
    p = math.erfc(abs(z) / math.sqrt(2.0))
    return z, p


def _corr(xs, ys):
    pairs = []
    for x, y in zip(xs, ys):
        try:
            pairs.append((float(x), float(y)))
        except (TypeError, ValueError):
            continue
    if len(pairs) < 3:
        return None
    n = len(pairs)
    mx = sum(x for x, _ in pairs) / n
    my = sum(y for _, y in pairs) / n
    sxx = sum((x - mx) ** 2 for x, _ in pairs)
    syy = sum((y - my) ** 2 for _, y in pairs)
    if sxx <= 0 or syy <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    return sxy / math.sqrt(sxx * syy)


def _bucket_counts(rows):
    decisive = [e for e in rows if e["reason"] in ("TP", "SL")]
    wins = sum(1 for e in decisive if e["reason"] == "TP")
    rs = [e["r"] for e in rows if e["r"] is not None]
    return {"n": len(rows), "decisive": len(decisive), "wins": wins,
            "wr": (100.0 * wins / len(decisive)) if decisive else None,
            "ci": P.wilson_interval(wins, len(decisive)) if decisive else (None, None),
            "r_mean": _mean(rs), "net_per_trade": _mean([e["net"] for e in rows]),
            "be": sum(1 for e in rows if e["reason"] == "BE"),
            "time": sum(1 for e in rows if e["reason"] == "TIME")}


def _split_of(key, entries):
    """(split value, label) for a feature, using the pre-declared rule."""
    values = [e["context"].get(key) for e in entries]
    if key == "di_side":
        return None, "DI side"
    rule = IND.SPLITS.get(key)
    if rule is None:
        return IND.split_value(key, values), "median"
    return rule, "fixed"


def indicator_board(entries, permutations=200, seed=7, min_decisive=INDICATOR_MIN_DECISIVE):
    """Does a candidate indicator separate the bot's own entries' outcomes?

    One fixed split per feature (see indicators.SPLITS — declared before looking
    at outcomes). For each feature the table reports both buckets' decisive WR,
    R/trade and costed $/trade, and the lift in each direction.

    The guard is a permutation test on the MAXIMUM lift across every feature and
    both directions: shuffle the outcome labels, recompute the best-looking lift,
    repeat. If the real best lift sits inside that null distribution, the board
    says "inside noise" no matter how good the bucket looks — this is the
    multiple-comparisons answer to "but one of these twenty must work".
    """
    closed = [e for e in entries if not e.get("open")]
    decisive_total = sum(1 for e in closed if e["reason"] in ("TP", "SL"))
    rows, skipped = [], []
    for key in IND.CONTEXT_FIELDS:
        rule, rule_kind = _split_of(key, closed)
        if key == "di_side":
            hi = [e for e in closed if e["context"].get("di_side") == e["side"]]
            lo = [e for e in closed if e["context"].get("di_side") not in (None, e["side"])]
            hi_label, lo_label = "DI agrees with side", "DI against side"
        else:
            if rule is None:
                continue
            hi = [e for e in closed if e["context"].get(key) is not None and e["context"][key] >= rule]
            lo = [e for e in closed if e["context"].get(key) is not None and e["context"][key] < rule]
            hi_label, lo_label = f"≥ {rule:.3g}", f"< {rule:.3g}"
        if not hi or not lo:
            skipped.append({"key": key, "label": IND.describe(key)["label"],
                            "reason": "one side of the split has no trades"
                                      + (" (the trend gate makes DI collinear with side)"
                                         if key == "di_side" else "")})
            continue
        h, l = _bucket_counts(hi), _bucket_counts(lo)
        lift = (h["wr"] - l["wr"]) if (h["wr"] is not None and l["wr"] is not None) else None
        z, p = (None, None)
        if h["wr"] is not None and l["wr"] is not None:
            z, p = _two_prop_z(h["wr"] / 100.0, h["decisive"], l["wr"] / 100.0, l["decisive"])
        r_lift = (h["r_mean"] - l["r_mean"]) if (h["r_mean"] is not None and l["r_mean"] is not None) else None

        # split-half consistency (by entry time), same sign as the full lift
        ordered = sorted([e for e in closed if e["context"].get(key) is not None],
                         key=lambda e: e["entry_time"])
        half = len(ordered) // 2
        halves = []
        for part in (ordered[:half], ordered[half:]):
            if key == "di_side":
                ph = [e for e in part if e["context"].get("di_side") == e["side"]]
                pl = [e for e in part if e["context"].get("di_side") not in (None, e["side"])]
            else:
                ph = [e for e in part if e["context"][key] >= rule]
                pl = [e for e in part if e["context"][key] < rule]
            a, b = _bucket_counts(ph), _bucket_counts(pl)
            halves.append((a["wr"] - b["wr"]) if (a["wr"] is not None and b["wr"] is not None) else None)
        stable = (lift is not None and None not in halves
                  and all((hh > 0) == (lift > 0) for hh in halves)
                  and all(abs(hh) >= 2.0 for hh in halves))

        # redundancy against what the engine already reads
        red = {}
        if closed:
            side_num = [1.0 if e["side"] == "BUY" else 0.0 for e in closed]
            red["side"] = _corr([e["context"].get(key) for e in closed], side_num)
            red["rsi"] = _corr([e["context"].get(key) for e in closed],
                               [e["context"].get("rsi") for e in closed])
            red["atr"] = _corr([e["context"].get(key) for e in closed],
                               [e["context"].get("atr") for e in closed])
            red["ema_spread"] = _corr([e["context"].get(key) for e in closed],
                                      [e["context"].get("ema_spread_atr") for e in closed])
        worst = max(((abs(v), k) for k, v in red.items() if v is not None), default=(None, None))

        rows.append({
            "key": key, **IND.describe(key), "split_rule": rule, "rule_kind": rule_kind,
            "high": h, "low": l, "high_label": hi_label, "low_label": lo_label,
            "lift": lift, "z": z, "p": p, "r_lift": r_lift, "stable": stable,
            "halves": halves, "redundancy": red,
            "max_corr": worst[0], "max_corr_with": worst[1],
            "verdict": "too few trades",
            "n_decisive": (h["decisive"] or 0) + (l["decisive"] or 0),
        })

    # ── permutation null for the maximum WR lift and the maximum R lift ──
    usable = [e for e in rows if e["lift"] is not None]
    observed_wr = max((abs(e["lift"]) for e in usable), default=None)
    observed_r = max((abs(e["r_lift"]) for e in usable if e["r_lift"] is not None), default=None)
    null_wr, null_r = [], []
    if permutations and closed:
        import random
        rng = random.Random(seed)
        # fix bucket membership once: every feature's high/low masks
        masks = []
        for e in rows:
            if e["lift"] is None:
                continue
            key = e["key"]
            if key == "di_side":
                high_mask = [1 if x["context"].get("di_side") == x["side"] else 0 for x in closed]
                low_mask = [1 if x["context"].get("di_side") not in (None, x["side"]) else 0 for x in closed]
            else:
                rule = e["split_rule"]
                high_mask = [1 if (x["context"].get(key) is not None and x["context"][key] >= rule) else 0
                             for x in closed]
                low_mask = [1 if (x["context"].get(key) is not None and x["context"][key] < rule) else 0
                            for x in closed]
            masks.append((high_mask, low_mask))
        decisive = [1 if x["reason"] == "TP" else 0 if x["reason"] == "SL" else None for x in closed]
        r_vals = [x["r"] for x in closed]
        for _ in range(permutations):
            rng.shuffle(decisive)
            best = 0.0
            for hm, lm in masks:
                wh = [decisive[i] for i in range(len(closed)) if hm[i] and decisive[i] is not None]
                wl = [decisive[i] for i in range(len(closed)) if lm[i] and decisive[i] is not None]
                if len(wh) >= 5 and len(wl) >= 5:
                    best = max(best, abs(100.0 * sum(wh) / len(wh) - 100.0 * sum(wl) / len(wl)))
            null_wr.append(best)
            rng.shuffle(r_vals)
            best_r = 0.0
            for hm, lm in masks:
                rh = [r_vals[i] for i in range(len(closed)) if hm[i] and r_vals[i] is not None]
                rl = [r_vals[i] for i in range(len(closed)) if lm[i] and r_vals[i] is not None]
                if len(rh) >= 5 and len(rl) >= 5:
                    best_r = max(best_r, abs(sum(rh) / len(rh) - sum(rl) / len(rl)))
            null_r.append(best_r)
    null_wr.sort()
    null_r.sort()
    null_wr_95 = null_wr[int(0.95 * (len(null_wr) - 1))] if null_wr else None
    null_r_95 = null_r[int(0.95 * (len(null_r) - 1))] if null_r else None
    p_global_wr = (sum(1 for v in null_wr if v >= (observed_wr or 0)) / len(null_wr)) if null_wr else None
    p_global_r = (sum(1 for v in null_r if v >= (observed_r or 0)) / len(null_r)) if null_r else None

    for e in rows:
        if e["n_decisive"] < 2 * min_decisive:
            e["verdict"] = "too few trades"
        elif p_global_wr is not None and p_global_wr > NOISE_ALPHA:
            e["verdict"] = "inside noise (family-wise)"
        elif e["p"] is not None and e["p"] > 0.05:
            e["verdict"] = "not significant"
        elif e["lift"] is not None and abs(e["lift"]) < MIN_LIFT_PP:
            e["verdict"] = f"small effect (<{MIN_LIFT_PP:.0f} pp)"
        elif not e["stable"]:
            e["verdict"] = "unstable across halves"
        elif e["max_corr"] is not None and e["max_corr"] >= 0.70:
            e["verdict"] = f"redundant with {e['max_corr_with']}"
        else:
            e["verdict"] = "candidate — pre-register before any use"

    rows.sort(key=lambda e: -(abs(e["lift"]) if e["lift"] is not None else -1.0))
    passing = [e for e in rows if e["verdict"].startswith("candidate")]
    if not rows:
        verdict = "No joinable entries — nothing to measure."
    elif passing:
        verdict = (f"{len(passing)} of {len(rows)} candidates clear the noise floor and the "
                   f"stability/redundancy checks. That is NOT permission to trade them: "
                   f"pre-register a dated bar first.")
    else:
        verdict = (f"None of {len(rows)} candidate indicators separates the bot's own entries "
                   f"beyond what chance produces on this sample. Adding any of them to the "
                   f"engine would be decoration, not improvement.")
    return {
        "ok": bool(rows), "n_entries": len(closed), "n_decisive": decisive_total,
        "rows": rows, "skipped": skipped, "permutations": permutations,
        "observed_max_lift_pp": observed_wr, "null_max_lift_95_pp": null_wr_95,
        "p_global_wr": p_global_wr, "observed_max_r_lift": observed_r,
        "null_max_r_lift_95": null_r_95, "p_global_r": p_global_r,
        "alpha": NOISE_ALPHA, "min_decisive": min_decisive,
        "verdict": verdict,
        "note": ("Exploratory. Splits are declared in indicators.SPLITS; the permutation "
                 "shuffles outcomes, so a null 95th percentile is the best lift random labels "
                 "produce across this many looks. A candidate still needs a dated "
                 "pre-registration and out-of-sample confirmation (HANDOFF §11)."),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. the report object
# ─────────────────────────────────────────────────────────────────────────────

def build(log_rows=None, trades=None, status=None, skip_rows=None, cost=COST_USD,
          permutations=0):
    """Join the tape, the ledger and the live state into one journal report."""
    log_rows = _rows(log_rows)
    trades = _rows(trades)
    skip_rows = _rows(skip_rows)
    bars = IND.bars_from_rows(log_rows)
    series = IND.build(bars) if bars else {"n": 0, "ts": [], "close": []}
    entries = []
    skipped_rows = 0
    for row in trades:
        e = _closed_entry(series, row, cost)
        if e is None:
            skipped_rows += 1
            continue
        entries.append(e)
    entries.sort(key=lambda e: (e["exit_time"] or e["entry_time"], e["entry_time"]))
    open_trade = open_entry(series, status, cost)

    era = [e for e in entries if e["era"] == "struct-stop"]
    today = None
    if series.get("n"):
        today = series["ts"][-1].date()
    todays = [e for e in entries if today and e["entry_time"].date() == today]
    last7 = [e for e in entries if today and (today - e["entry_time"].date()).days < 7 and e["entry_time"].date() <= today]
    report = {
        "ok": bool(entries),
        "as_of": series["ts"][-1] if series.get("n") else None,
        "cost": cost, "era_label": f"entries ≥ {CUTOVER:%Y-%m-%d %H:%M} UTC",
        "cutover": CUTOVER,
        "book": summarise(entries, cost, "all closed"),
        "era": summarise(era, cost, "struct-stop era"),
        "pre_era": summarise([e for e in entries if e["era"] != "struct-stop"], cost, "pre-struct-stop"),
        "today": summarise(todays, cost, "today (entry date)"),
        "last7": summarise(last7, cost, "last 7 days (entry date)"),
        "sides": _group(entries, lambda e: e["side"]),
        "era_sides": _group(era, lambda e: e["side"]),
        "sessions": _group(entries, lambda e: e["session"]),
        "era_sessions": _group(era, lambda e: e["session"]),
        "daily": daily(entries, last=14),
        "recent": list(reversed(entries[-RECENT_N:])),
        "givebacks": givebacks(entries),
        "era_givebacks": givebacks(era),
        "skips": skips(skip_rows),
        "open": open_trade,
        "unparsed_rows": skipped_rows,
        "entries": entries,
        "series": series,
        "definitions": {
            "decisive_wr": "TP / (TP + SL) — BE scratches and TIME exits excluded",
            "all_in": "TP / every closed trade",
            "r": "Profit ÷ actual risk, risk = |TP − Entry| ÷ 1.5 (reward leg)",
            "net": f"every closed trade charged ${cost:.2f} round trip (assumed, not yet measured)",
            "mfe_mae": "best/worst price excursion after the entry bar, in R",
            "session": "entry hour in UTC; Asia/rollover 23:00–06:59, London/NY 07:00–22:59",
        },
    }
    if permutations:
        report["board"] = indicator_board(entries, permutations=permutations)
    return report


def dashboard_view(report, recent=None):
    """Trim the report to what the page needs (no full series / entries)."""
    if not report or not report.get("ok"):
        return report or {"ok": False, "reason": "no journal rows"}
    keep = ("ok", "as_of", "cost", "era_label", "book", "era", "pre_era", "today",
            "last7", "sides", "era_sides", "sessions", "era_sessions", "daily",
            "givebacks", "era_givebacks", "skips", "open", "definitions", "board")
    out = {k: report.get(k) for k in keep}
    out["recent"] = (recent if recent is not None else report.get("recent")) or []
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 5. human-readable report (the CLI's default)
# ─────────────────────────────────────────────────────────────────────────────

def _money(value, sign=True):
    if value is None:
        return "—"
    return f"${value:+,.2f}" if sign else f"${value:,.2f}"


def _pct(value, digits=1):
    return "—" if value is None else f"{value:.{digits}f}%"


def _num(value, digits=2):
    return "—" if value is None else f"{value:+.{digits}f}"


def _fmt_ts(dt):
    return "—" if dt is None else dt.strftime("%Y-%m-%d %H:%M")


def _line_summary(s):
    if not s or not s["n"]:
        return f"{s['label'] if s else '—'}: no closed trades"
    ci = s["decisive_ci"]
    ci_txt = f" [{ci[0]:.1f}–{ci[1]:.1f}]" if ci and ci[0] is not None else ""
    return (f"{s['label']}: n={s['n']} · {s['wins']}W/{s['losses']}L/{s['be']}BE/{s['time']}TIME · "
            f"decisive {_pct(s['decisive_wr'])}{ci_txt} · all-in {_pct(s['all_in_pct'])} · "
            f"R/trade {_num(s['r_mean'])} · net {_money(s['net'])} · "
            f"maxDD {_money(-s['max_dd_net']) if s['max_dd_net'] else '—'}")


def report_lines(report):
    """The journal as text, for tools/journal_report.py."""
    if not report or not report.get("ok"):
        return ["No closed trades joinable to the tape."]
    out = []
    out.append("SELF-JOURNAL — what the bot did, why, and how it ended")
    out.append(f"data through {_fmt_ts(report['as_of'])} · cost ${report['cost']:.2f} round trip "
               f"· {report['era_label']}")
    out.append("")
    out.append("1. SUCCESS RATE")
    for key in ("book", "era", "pre_era", "last7", "today"):
        out.append("   " + _line_summary(report[key]))
    b = report["book"]
    out.append(f"   payoff {b['payoff']:.2f} : 1 · breakeven WR {_pct(b['breakeven_wr_pct'])} · "
               f"profit factor {b['profit_factor']:.2f}" if b["payoff"] and b["profit_factor"] else
               "   payoff / profit factor: —")
    out.append(f"   streaks: current {b['streak']['current'] or '—'} "
               f"({b['streak']['length']}) · longest SL run {b['streak']['longest_sl']} · "
               f"median hold {b['hold_median']:.0f} min" if b["hold_median"] is not None else
               "   streaks: —")
    out.append("")
    out.append("2. BY SIDE")
    for side, s in report["sides"].items():
        out.append("   " + _line_summary(s))
    out.append("")
    out.append("3. BY SESSION (entry hour, UTC)")
    for name, s in report["sessions"].items():
        out.append("   " + _line_summary(s))
    out.append("")
    out.append("4. LAST 14 ENTRY DAYS")
    out.append("   date         n   W  L BE TIME   decWR      R/trade      net    cum net")
    for d in report["daily"]:
        out.append(f"   {d['label']}  {d['n']:>2}  {d['wins']:>2} {d['losses']:>2} {d['be']:>2} {d['time']:>2}   "
                   f"{_pct(d['decisive_wr'], 0):>5}   {_num(d['r_mean']):>7}   "
                   f"{_money(d['net']):>9}  {_money(d.get('cum_net')):>9}")
    out.append("")
    out.append("5. WHAT THE JOURNAL NOTICED")
    g = report["givebacks"]
    out.append(f"   {g['was_ahead_n']} of {b['n']} trades ({_pct(g['was_ahead_pct'])}) were at least "
               f"+{g['heat_r_threshold']:.2f}R ahead at some point and did not finish there:")
    out.append(f"     · {g['scratched_runners']} scratched on the ratchet (BE)")
    out.append(f"     · {g['stopped_after_profit']} gave the gain back and hit the stop")
    out.append(f"     · {g['winners_with_heat']} winners first ran ≥0.5R against")
    out.append(f"     · peak unrealised (median) {_num(g['left_on_table_r_median'])}R; "
               f"sum of peaks {_num(g['left_on_table_r_sum'])}R")
    if g["worst"]:
        worst = ", ".join(f"#{e['num']} {e['side']} {e['reason']} +{e['mfe_r']:.2f}R→{_num(e['r'])}R"
                          for e in g["worst"])
        out.append(f"     · largest: {worst}")
    sk = report["skips"]
    out.append(f"   risk layer blocked {sk['n_24h']} signals in the last {sk['hours']} h of skip log: "
               + (", ".join(f"{k} {v}" for k, v in sk["reasons_24h"].items()) or "none"))
    if report.get("open"):
        o = report["open"]
        out.append(f"   OPEN: #{o['num']} {o['side']} @ {o['entry']:.2f}, stop {o['stop']:.2f}, "
                   f"target {o['tp']:.2f}, {o['hold_min']:.0f} min old, "
                   f"now {_num(o['r_now'])}R at last close {o['price_now']:.2f}")
    else:
        out.append("   OPEN: none")
    out.append("")
    out.append("6. RECENT ENTRIES (newest first)")
    for e in report["recent"]:
        out.append(f"   #{e['num']:<4} {e['entry_time']:%m-%d %H:%M} {e['side']:<4} "
                   f"{e['reason']:<4} {_num(e['r'])}R  MFE {_num(e['mfe_r'])}R  "
                   f"{e['thesis']}")
    board = report.get("board")
    if board:
        out.append("")
        out.append("7. CANDIDATE INDICATORS — measured on these entries")
        out.append(f"   n={board['n_entries']} closed, {board['n_decisive']} decisive; "
                   f"{board['permutations']} permutations; family-wise alpha {board['alpha']}")
        out.append("   feature                    split      bucket WR (n dec)      lift    verdict")
        for row in board["rows"]:
            hi, lo = row["high"], row["low"]
            out.append(f"   {row['label'][:26]:<26} {row['high_label'][:10]:<10} "
                       f"{_pct(hi['wr'], 0):>5} ({hi['decisive']:>3}) vs {_pct(lo['wr'], 0):>5} "
                       f"({lo['decisive']:>3})  {_num(row['lift'], 0):>6} pp  {row['verdict']}")
        out.append(f"   best-lift {_num(board['observed_max_lift_pp'], 1)} pp vs random-label "
                   f"95th pct {_num(board['null_max_lift_95_pp'], 1)} pp "
                   f"(global p={board['p_global_wr']:.3f})" if board["p_global_wr"] is not None else
                   "   permutation guard not run (--permutations 0)")
        out.append(f"   VERDICT: {board['verdict']}")
    out.append("")
    out.append("Definitions: " + " · ".join(f"{k}={v}" for k, v in report["definitions"].items()))
    return out


def entries_csv(entries):
    """A flat, spreadsheet-friendly export (one row per closed trade)."""
    cols = ["Trade_Num", "Entry_Time", "Exit_Time", "Side", "Entry", "Stop", "Target",
            "Exit", "Reason", "Profit", "Risk", "R", "Net_at_cost", "Hold_min",
            "MFE_R", "MAE_R", "RSI", "ATR", "Wick_pct", "EMA_spread_ATR",
            "Level_dist_ATR", "Range_pos", "ADX", "MACD_hist", "BB_pctB", "Stoch_K",
            "Stoch_D", "Keltner_pos", "Donchian_pos", "ER30", "ATR_pct", "RVOL",
            "RSI_slope", "Body_ATR", "Close_loc", "Gap_ATR", "Session", "Era", "Thesis"]
    lines = [",".join(cols)]
    def q(v):
        if v is None:
            return ""
        if isinstance(v, float):
            return f"{v:.4f}"
        text = str(v).replace('"', "'").replace(",", ";")
        return f'"{text}"'
    for e in entries:
        c = e["context"]
        row = [e["num"], e["entry_time"], e.get("exit_time"), e["side"], e["entry"], e["stop"],
               e["tp"], e.get("exit"), e["reason"], e.get("profit"), e["risk"], e["r"],
               e.get("net"), e.get("hold_min"), e["mfe_r"], e["mae_r"], e["rsi"], e["atr"],
               e["wick"], c.get("ema_spread_atr"), e["level_dist_atr"], e["range_pos"],
               c.get("adx"), c.get("macd_hist"), c.get("bb_pct_b"), c.get("stoch_k"),
               c.get("stoch_d"), c.get("keltner_pos"), c.get("donchian_pos"), c.get("er30"),
               c.get("atr_pct"), c.get("rvol"), c.get("rsi_slope"), c.get("body_atr"),
               c.get("close_loc"), c.get("gap_atr"), e["session"], e["era"], e["thesis"]]
        lines.append(",".join(q(v) for v in row))
    return "\n".join(lines) + "\n"
