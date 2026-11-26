#!/usr/bin/env python3
"""manual_plan.py — the read-only "would this manual trade be worth taking?" layer.

WHY THIS EXISTS
    The bot's numbers answer questions about *the bot*: R/trade, decisive WR, era
    verdicts. A human trading by hand on the same feed needs four different numbers,
    and none of them was available anywhere:

      1. "Where does my stop go, and what does that make 1R worth?"   -> plan()
      2. "How many lots is that for the money I am willing to lose?" -> sizing_rows()
      3. "Is the spread a sane share of that risk, right now?"        -> plan()["cost"]
      4. "How many minutes until the daily break makes my stop
          unenforceable?"                                             -> session_clock()

    Between them they cover the single most expensive mistake in manual gold
    scalping — a tight stop that pays 20-40% of its own risk to the spread — and the
    second most expensive one, a position that rides the broker's daily closure with
    no way to be stopped out.

WHAT THIS IS NOT
    Not a signal, not a forecast, not an entry condition, and not a strategy input.
    Nothing here is imported by engine.py or trade_filter.py, nothing writes a file
    (the optional journal is CLI-only, host-local and refuses to write inside the
    repo), and no number here may become a gate without a pre-registered bar
    (docs/HANDOFF.md §11). The measured base rates travel with every verdict:
    no edge has been demonstrated for any of these geometries.

    The one deliberate duplication is the daily-break read (`observed_closure`): the
    engine's own `derive_daily_closure` lives in engine.py, which this module must
    not import. The mirror is simpler — it reports the modal break of the last
    `CLOSURE_SAMPLES` observed holes and does not re-implement the engine's ±60 min
    DST adaptation — so it is labelled "observed" and tools/smoke_test.py Scenario U
    pins it to the engine's value on the live log. When they disagree, the engine is
    right and this panel is the one to distrust.

Stdlib only (plus the repo's own display modules, which are stdlib only as well).
Pure functions of the rows they are handed, so they are testable without a clock.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta

import chart as C
import pressure as P

# ─────────────────────────────────────────────────────────────────────────────
# Contract + cost constants. The CONTRACT facts are the broker's, read from the
# logger's spec file at run time; these are the documented fallbacks (the same
# numbers engine.py carries) used when no spec has been captured yet.
# ─────────────────────────────────────────────────────────────────────────────
CONTRACT_SIZE = 100.0        # XM GOLD Standard: 100 oz per 1.00 lot (engine.CONTRACT_SIZE)
VOLUME_MIN = 0.01            # engine.VOLUME_MIN
VOLUME_STEP = 0.01           # engine.VOLUME_STEP
VOLUME_MAX = 50.0            # captured spec 2026-11-22
POINT = 0.01                 # captured spec: digits 2
LEVERAGE = 1000.0            # captured spec: 1:1000
SPEC_FILE = "symbol_spec.json"

COST_ROUND_TRIP = C.COST_USD_MEASURED        # $0.55 — the quote logger's measured median
COST_REGISTERED = C.COST_USD_REGISTERED      # $0.40 — the registered assumption (still binding)
COST_SHARE_OK_PCT = C.COST_MAX_SHARE_PCT     # 10% of 1R: geometry is not the problem
COST_SHARE_MAX_PCT = 20.0                    # engine.LIVE_COST_MAX_PCT_OF_R — the live veto

# Display-only advice thresholds. None of these is a gate, and none is registered:
# they exist so the panel can say "this is the part that will hurt" in words.
MIN_STOP_ATR = 3.0            # docs/PROPOSAL-2026-10-23-manual-chart-tab.md: R >= 10 x cost
SPREAD_WARN_MULT = 1.3        # live spread this far above the measured median = caution
GUARD_CUTOFF_MIN = 30         # engine.GUARD_CUTOFF_MIN — the bot's own pre-close block
CLOSURE_SAMPLES = 5           # modal break over this many observed holes (display only)
CLOSURE_MIN_MIN = 30.0        # engine.GUARD_MIN_BREAK_MIN
CLOSURE_MAX_MIN = 180.0       # engine.GUARD_MAX_BREAK_MIN

DEFAULT_RISK_BUDGETS = (5.0, 10.0, 20.0, 50.0)   # $ per trade — account-agnostic presets

# docs/EXECUTION-PLAN.md §7 — the private manual observation record. The CLI journal
# writes exactly these fields, in this order, and nothing else.
JOURNAL_FIELDS = (
    "timestamp_utc", "bot_trade_id", "side", "bot_entry", "bot_sl", "bot_tp",
    "manual_entry", "manual_exit", "pressure_source", "pressure_metric",
    "pressure_timeframe", "pressure_value_at_entry", "pressure_value_at_stop_touch",
    "last_closed_bar_utc", "contemporaneous_action", "reason_code",
    "max_hold_or_exit_rule", "post_stop_markout_horizons", "mfe", "mae",
    "hypothetical_exit", "estimated_cost", "notes_without_account_identifiers",
)
JOURNAL_REQUIRED = ("timestamp_utc", "side", "manual_entry",
                    "reason_code", "contemporaneous_action")
JOURNAL_SIDES = ("BUY", "SELL", "NONE")
# A journal row must never carry a broker login, server name or account number:
# the record is meant to stay private, and anything written has to be safe even if
# it is pasted into an issue by mistake. Matching is on the FIELD NAME.
_FORBIDDEN_FIELD_PARTS = ("login", "password", "account", "server", "token", "chat_id")


def _f(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


# ─────────────────────────────────────────────────────────────────────────────
# 1. the broker's contract facts, from the logger's captured spec
# ─────────────────────────────────────────────────────────────────────────────

def load_spec(qdir):
    """Contract facts from xm_data/symbol_spec.json, or the documented defaults.

    Returns a dict that always has every key, plus `source` ("captured" / "default")
    and `captured_utc`, so the panel can say whether it is quoting the broker or a
    constant. Never raises: a missing spec is a reason to distrust the numbers, not
    a reason for the page to break.
    """
    out = {"source": "default", "captured_utc": None, "account_kind": None,
           "contract_size": CONTRACT_SIZE, "volume_min": VOLUME_MIN,
           "volume_step": VOLUME_STEP, "volume_max": VOLUME_MAX, "point": POINT,
           "leverage": LEVERAGE, "stops_level_points": 0.0, "freeze_level_points": 0.0,
           "swap_long": None, "swap_short": None, "path": None}
    try:
        with open(os.path.join(qdir, SPEC_FILE), encoding="utf-8") as fh:
            spec = json.load(fh)
    except (OSError, ValueError, TypeError):
        return out
    if not isinstance(spec, dict):
        return out
    info = spec.get("symbol_info") or {}
    account = spec.get("account") or {}
    def take(key, cast=float, default=None):
        value = info.get(key)
        if value is None:
            return default
        try:
            return cast(value)
        except (TypeError, ValueError):
            return default
    out["source"] = "captured"
    out["captured_utc"] = spec.get("captured_utc")
    out["account_kind"] = (spec.get("decoded") or {}).get("account_kind")
    out["contract_size"] = take("trade_contract_size", default=CONTRACT_SIZE) or CONTRACT_SIZE
    out["volume_min"] = take("volume_min", default=VOLUME_MIN) or VOLUME_MIN
    out["volume_step"] = take("volume_step", default=VOLUME_STEP) or VOLUME_STEP
    out["volume_max"] = take("volume_max", default=VOLUME_MAX) or VOLUME_MAX
    out["point"] = take("point", default=POINT) or POINT
    out["leverage"] = float(account.get("leverage") or LEVERAGE) or LEVERAGE
    out["stops_level_points"] = take("trade_stops_level", default=0.0) or 0.0
    out["freeze_level_points"] = take("trade_freeze_level", default=0.0) or 0.0
    out["swap_long"] = take("swap_long")
    out["swap_short"] = take("swap_short")
    out["path"] = info.get("path")
    return out


def round_lots(lots, spec):
    """Snap a lot size DOWN onto the broker's own grid. Returns (lots, note).

    Rounding down is deliberate: rounding up would silently risk more than the
    trader asked for. A size below volume_min is refused rather than raised,
    because raising it is the same silent over-risk in the other direction.
    """
    spec = spec or {}
    step = _f(spec.get("volume_step")) or VOLUME_STEP
    vmin = _f(spec.get("volume_min")) or VOLUME_MIN
    vmax = _f(spec.get("volume_max")) or VOLUME_MAX
    raw = _f(lots)
    if raw is None or raw <= 0:
        return 0.0, "no size — the risk budget is zero at this stop distance"
    snapped = math.floor(raw / step + 1e-9) * step
    snapped = round(snapped, 8)
    if snapped >= vmin - 1e-9:
        if snapped <= vmax + 1e-9:
            return snapped, None
        return vmax, f"capped at the broker's maximum {vmax:g} lots"
    return 0.0, (f"below the broker's minimum lot ({vmin:g}): a {raw:.4f} lot size is not "
                 f"tradeable, so this stop is too wide for that risk budget")


# ─────────────────────────────────────────────────────────────────────────────
# 2. the daily break, observed (display mirror; the engine is authoritative)
# ─────────────────────────────────────────────────────────────────────────────

def observed_closure(rows, samples=CLOSURE_SAMPLES, min_min=CLOSURE_MIN_MIN,
                     max_min=CLOSURE_MAX_MIN):
    """The broker's recent daily-break signature, from the price log's own holes.

    A daily break is a hole of `min_min`..`max_min` minutes. The signature is the
    MODE of the last `samples` holes' close and reopen minute-of-day, which is how
    the engine converges too (engine.derive_daily_closure). Differences on purpose:
    this mirror does not re-implement the engine's ±60 min DST adaptation, ignores
    holes longer than `max_min` (weekends are not the daily break), and reports
    `source="observed"` so no page can present it as the deployed guard.
    """
    stamps = []
    for row in rows or []:
        ts = P.parse_ts(row.get("Timestamp"))
        if ts is not None:
            stamps.append(ts)
    stamps.sort()
    holes = []
    for a, b in zip(stamps, stamps[1:]):
        minutes = (b - a).total_seconds() / 60.0
        if min_min <= minutes <= max_min:
            holes.append((a, (a.hour, a.minute), (b.hour, b.minute)))
    recent = holes[-samples:] if samples else holes
    out = {"ok": False, "source": "observed", "samples": len(recent),
           "holes_seen": len(holes), "close_tod": None, "reopen_tod": None,
           "last_break": None, "detail": ""}
    if not recent:
        out["detail"] = (f"no {min_min:.0f}-{max_min:.0f} min daily break in the log "
                         f"yet — the break time is unknown, so assume the broker can "
                         f"close at any time near 21:00-23:00 UTC")
        return out
    close_tod = _mode([c for _, c, _ in recent])
    reopen_tod = _mode([r for _, _, r in recent])
    last = recent[-1]
    out.update({"ok": True, "close_tod": close_tod, "reopen_tod": reopen_tod,
                "last_break": {"at": last[0], "close": last[1], "reopen": last[2]},
                "detail": (f"last {len(recent)} break(s): closes "
                           f"{close_tod[0]:02d}:{close_tod[1]:02d} UTC, opens "
                           f"{reopen_tod[0]:02d}:{reopen_tod[1]:02d} UTC")})
    return out


def _mode(samples):
    """Most common minute-of-day, ties broken by the median (engine's rule)."""
    counts = {}
    for s in samples:
        counts[s] = counts.get(s, 0) + 1
    best = max(counts.values())
    winners = sorted(k for k, v in counts.items() if v == best)
    if len(winners) == 1:
        return winners[0]
    mins = sorted(h * 60 + m for h, m in winners)
    mid = mins[len(mins) // 2]
    return (mid // 60, mid % 60)


def _wrap(minutes):
    return minutes % (24 * 60)


def session_clock(now, closure, cutoff_min=GUARD_CUTOFF_MIN):
    """Where the clock is relative to the daily break — the manual trader's gap risk.

    The engine refuses NEW entries in `[close - cutoff, reopen)`; a manual trader
    has no such guard, and test #815 shows what that costs: a ratcheted scratch
    position rode the 2026-11-04 break and reopened $2.77 through its stop.
    `state` is one of "open" (clear), "guard" (inside the bot's pre-close block),
    "closed" (inside the break itself) and "unknown" (no signature observed).
    """
    out = {"state": "unknown", "minutes_to_close": None, "minutes_to_reopen": None,
           "cutoff_min": cutoff_min, "detail": "", "closure": closure}
    if not closure or not closure.get("ok"):
        out["detail"] = (closure or {}).get("detail") or "no daily break observed yet"
        return out
    close_tod, reopen_tod = closure["close_tod"], closure["reopen_tod"]
    close_min = _wrap(close_tod[0] * 60 + close_tod[1])
    reopen_min = _wrap(reopen_tod[0] * 60 + reopen_tod[1])
    now_min = now.hour * 60 + now.minute
    to_close = (close_min - now_min) % (24 * 60)
    to_reopen = (reopen_min - now_min) % (24 * 60)
    # inside the break itself?
    inside = ((now_min >= close_min or now_min < reopen_min)
              if close_min > reopen_min else (close_min <= now_min < reopen_min))
    out["minutes_to_close"] = int(to_close)
    out["minutes_to_reopen"] = int(to_reopen)
    if inside:
        out.update({"state": "closed",
                    "detail": (f"the broker's daily break is in progress "
                               f"({close_tod[0]:02d}:{close_tod[1]:02d} -> "
                               f"{reopen_tod[0]:02d}:{reopen_tod[1]:02d} UTC); it reopens "
                               f"in {to_reopen} min — nothing can be closed until then")})
    elif to_close <= cutoff_min:
        out.update({"state": "guard",
                    "detail": (f"{to_close} min to the daily close — the bot stops taking "
                               f"entries now; a manual stop here cannot be enforced "
                               f"across the break")})
    else:
        out.update({"state": "open",
                    "detail": (f"{to_close} min to the daily close, {to_reopen} min to the "
                               f"reopen; a position taken now still needs the break to be "
                               f"survived")})
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 3. the trade plan: stop, target, R, and what the spread takes
# ─────────────────────────────────────────────────────────────────────────────

def structural_stop(side, level, atr, clear_atr=None, sl_mult=None):
    """The stop the bot's own rule would place against `level` (engine's formula).

    risk = max(ATR_SL_MULT·ATR, |entry − level| + SL_CLEAR_ATR·ATR). Here the entry
    is not known to this helper, so the distance is expressed from the LEVEL: the
    caller passes the entry and gets `entry ∓ distance`. Kept separate so the plan
    can show the same number the bot would use.
    """
    clear = P.SL_CLEAR_ATR if clear_atr is None else clear_atr
    mult = P.ATR_SL_MULT if sl_mult is None else sl_mult
    if atr is None or atr <= 0:
        return None
    return {"distance_atr_floor": mult, "clear_atr": clear}


def cost_view(entry, stop, target, spread_rt=COST_ROUND_TRIP,
              spread_now=None, measured=COST_ROUND_TRIP, registered=COST_REGISTERED):
    """Cost as a share of 1R, and the decisive win rate the geometry needs.

    The share is `spread / risk` — invariant to lot size, which is the whole point:
    a bigger size changes the dollars, not the ratio. `breakeven_wr` is the decisive
    (TP/(TP+SL)) win rate at which this geometry is exactly flat after cost, so the
    trader can compare it with the measured 33-37% base rate instead of guessing.
    """
    risk = abs(entry - stop) if entry is not None and stop is not None else None
    reward = abs(target - entry) if entry is not None and target is not None else None
    out = {"ok": False, "risk_usd_per_oz": risk, "reward_usd_per_oz": reward,
           "spread_rt": spread_rt, "spread_now": spread_now, "measured": measured,
           "registered": registered, "share_pct": None, "share_now_pct": None,
           "gross_rr": None, "net_rr": None, "breakeven_wr_pct": None,
           "min_risk_for_ok": None, "zone": "unknown"}
    if not risk or risk <= 0 or not reward:
        return out
    out["ok"] = True
    out["gross_rr"] = reward / risk
    out["net_rr"] = (reward - spread_rt) / (risk + spread_rt)
    out["share_pct"] = 100.0 * spread_rt / risk
    if spread_now is not None:
        out["share_now_pct"] = 100.0 * spread_now / risk
    out["breakeven_wr_pct"] = 100.0 / (1.0 + out["net_rr"]) if out["net_rr"] > -1 else None
    out["min_risk_for_ok"] = spread_rt / (COST_SHARE_OK_PCT / 100.0)
    share = out["share_now_pct"] if out["share_now_pct"] is not None else out["share_pct"]
    out["zone"] = ("red" if share > COST_SHARE_MAX_PCT else
                   "amber" if share > COST_SHARE_OK_PCT else "green")
    return out


def sizing_rows(risk_per_oz, budgets=DEFAULT_RISK_BUDGETS, spec=None,
                entry=None, cost_rt=COST_ROUND_TRIP):
    """Lot size, dollars at risk, margin and cost share for each risk budget.

    `risk_per_oz` is |entry − stop| in $ per ounce — the same number as the $ risk of
    one 0.01 lot (1 oz at a 100 oz contract). Every row is the same trade at a
    different size, so the cost SHARE of 1R is identical across rows and only the
    dollars move; that is the lesson the table exists to teach.
    """
    spec = spec or load_spec("")
    risk_per_oz = _f(risk_per_oz)
    rows = []
    if not risk_per_oz or risk_per_oz <= 0:
        return rows
    contract = _f(spec.get("contract_size")) or CONTRACT_SIZE
    leverage = _f(spec.get("leverage")) or LEVERAGE
    for budget in budgets or ():
        budget = _f(budget)
        if not budget or budget <= 0:
            continue
        raw = budget / (contract * risk_per_oz)
        lots, note = round_lots(raw, spec)
        effective = lots * contract * risk_per_oz
        margin = (lots * contract * (entry or 0.0) / leverage) if entry else None
        rows.append({
            "budget_usd": budget,
            "lots": lots,
            "lots_raw": raw,
            "risk_usd": effective,
            "risk_pct_over": (100.0 * (effective - budget) / budget) if budget else None,
            "margin_usd": margin,
            "cost_usd": lots * contract * cost_rt,
            "cost_share_pct": 100.0 * cost_rt / risk_per_oz,
            "ok": lots > 0,
            "note": note,
        })
    return rows


def plan(side, entry, atr, level=None, target=None, spread_now=None,
         spread_rt=COST_ROUND_TRIP, spec=None, closure=None, now=None,
         risk_budgets=DEFAULT_RISK_BUDGETS, box=None, checks=None, stop=None):
    """One side's manual plan: stop, target, R, cost share, size rows, blockers.

    The stop is the stricter of the bot's structural rule against `level` and the
    box's far edge (`box` = a pressure.box_geometry() box dict), so the plan never
    proposes a stop inside the range the entry was built on. The target defaults to
    1.5 × risk — the bot's own RR_TARGET — because that is the only payoff the
    ledger has measured anything at.

    `verdict` is "no trade" / "watch" / "geometry ok"; it is NEVER "take", and the
    measured base rate is attached to every answer. Display-only.

    `stop` lets the caller judge ITS OWN stop instead of the proposed one. It is the
    only supported way to do that: the risk, the cost share, the size table and every
    warning are then derived from that stop in one pass, so no number on the panel can
    be left over from a different geometry. A stop on the winning side is refused as a
    typo rather than silently inverted.
    """
    side = (side or "").upper()
    out = {"ok": False, "side": side, "entry": entry, "atr": atr, "stop": None,
           "target": None, "risk": None, "level": level, "box": box,
           "cost": None, "sizing": [], "warnings": [], "reasons": [],
           "verdict": "no trade", "verdict_text": "NO TRADE", "clock": None,
           "spec": spec or load_spec(""), "measured": _measured_text()}
    if side not in ("BUY", "SELL"):
        out["reasons"].append("side must be BUY or SELL")
        return out
    entry = _f(entry)
    atr = _f(atr)
    if not entry or not atr or atr <= 0:
        out["reasons"].append("no usable price/ATR on the last closed bar yet")
        return out
    sign = 1 if side == "BUY" else -1
    spec = out["spec"]

    # --- stop: the structural rule on the tested level, widened to the box's far edge
    candidate = atr * P.ATR_SL_MULT
    level = _f(level)
    if level is not None and level > 0:
        candidate = max(candidate, abs(entry - level) + P.SL_CLEAR_ATR * atr)
    if box:
        far = box.get("low") if side == "BUY" else box.get("high")
        far = _f(far)
        if far is not None and sign * (entry - far) > 0:
            candidate = max(candidate, abs(entry - far) + P.SL_CLEAR_ATR * atr)
    override = _f(stop)
    if override is not None and sign * (entry - override) > 0:
        candidate = abs(entry - override)
    stop = entry - sign * candidate
    risk = abs(entry - stop)

    # --- target: explicit, else the bot's 1.5R on the ACTUAL risk
    tp = _f(target)
    if tp is None:
        tp = entry + sign * P.RR_TARGET * risk
    else:
        # an explicit target must sit on the winning side, or it is a typo
        if sign * (tp - entry) <= 0:
            out["reasons"].append("the target you typed is on the wrong side of the entry")
            tp = entry + sign * P.RR_TARGET * risk
    out.update({"stop": stop, "target": tp, "risk": risk, "ok": True})

    # --- cost + size
    cost = cost_view(entry, stop, tp, spread_rt=spread_rt, spread_now=spread_now)
    out["cost"] = cost
    out["sizing"] = sizing_rows(risk, budgets=risk_budgets, spec=spec,
                               entry=entry, cost_rt=spread_rt)
    out["clock"] = session_clock(now, closure) if now is not None else None

    # --- warnings (soft) and reasons (hard)
    if cost["share_pct"] is not None:
        if cost["share_pct"] > COST_SHARE_MAX_PCT:
            out["reasons"].append(
                f"the round trip is {cost['share_pct']:.0f}% of 1R (${spread_rt:.2f} vs "
                f"${risk:.2f} risk) — over the {COST_SHARE_MAX_PCT:.0f}% the live path "
                f"vetoes; widen the stop or skip it")
        elif cost["share_pct"] > COST_SHARE_OK_PCT:
            out["warnings"].append(
                f"the round trip is {cost['share_pct']:.0f}% of 1R — above the "
                f"{COST_SHARE_OK_PCT:.0f}% comfort line; the geometry is carrying the cost")
    if risk < MIN_STOP_ATR * atr:
        out["warnings"].append(
            f"the stop is only {risk / atr:.1f} ATR away — under the {MIN_STOP_ATR:.0f} ATR "
            f"the repo's own placement rule asks for on this tape")
    if cost["ok"] and cost["net_rr"] is not None and cost["net_rr"] < 1.0:
        out["warnings"].append(
            f"net reward/risk is {cost['net_rr']:.2f}:1 — you are risking more than you can win")
    if level is not None and level > 0 and sign * (entry - level) > 0:
        # The tested level only matters when it sits on the LOSING side of the entry
        # (the floor under a BUY, the ceiling above a SELL). Then the stop must clear
        # it by SL_CLEAR_ATR, which is exactly what the engine's rule enforces — a
        # stop inside the level is the defect the 2026-10-05 analysis found on 64% of
        # the old book. A level on the winning side is not a stop constraint.
        clear = P.SL_CLEAR_ATR * atr
        passes = (stop <= level - clear + 1e-9) if side == "BUY" else (stop >= level + clear - 1e-9)
        if not passes:
            out["reasons"].append(
                f"the stop (${stop:,.2f}) does not clear the tested level (${level:,.2f}) by "
                f"{P.SL_CLEAR_ATR:.1f} ATR — that is the defect the 2026-10-05 analysis fixed")
    if spread_now is not None and spread_now > SPREAD_WARN_MULT * COST_ROUND_TRIP:
        out["warnings"].append(
            f"the live spread (${spread_now:.2f}) is {spread_now / COST_ROUND_TRIP:.1f}× the "
            f"measured median — rollover or news; wait if you can")
    clock = out["clock"]
    if clock:
        if clock["state"] == "closed":
            out["reasons"].append(clock["detail"])
        elif clock["state"] == "guard":
            out["reasons"].append(clock["detail"])
    if not any(row["ok"] for row in out["sizing"]):
        notes = {row["note"] for row in out["sizing"] if row["note"]}
        out["reasons"].append("; ".join(sorted(notes)) or
                             "no risk budget produces a tradeable lot size at this stop")
    for item in checks or ():
        if item.get("state") in ("fail", "warn"):
            text = f"{item.get('label')}: {item.get('detail')}"
            if item.get("state") == "fail":
                out["reasons"].append(text)
            else:
                out["warnings"].append(text)

    out["verdict"] = "no trade" if out["reasons"] else ("watch" if out["warnings"] else "geometry ok")
    out["verdict_text"] = {"no trade": "NO TRADE", "watch": "SIZE DOWN / WATCH",
                           "geometry ok": "GEOMETRY OK"}[out["verdict"]]
    return out


def attach_bot_view(plan_out, setup, side):
    """Attach the engine's own verdict on this side, as CONTEXT (never a veto).

    The manual trader and the bot look at the same bar and can reach different
    answers: the bot requires all eight of its entry gates, and a human is free to
    take a geometry the bot would skip. That difference is worth seeing, not
    silently resolving — so it rides along as `bot_view` with its own sentence, and
    it never changes `verdict`.
    """
    side_read = (setup or {}).get(side) or {}
    gates = side_read.get("gates")
    total = len(gates) if gates else (side_read.get("total") or 0)
    passed = side_read.get("passed")
    if not (setup or {}).get("ok") or passed is None:
        plan_out["bot_view"] = {"ok": False, "text": "the engine's gate read is unavailable",
                                "passed": None, "total": total}
        return
    missing = [g.get("name") for g in (gates or []) if not g.get("ok") and not g.get("inactive")]
    ready = bool(side_read.get("ready"))
    if ready:
        text = (f"the bot also reads {passed}/{total} on this side — it would take the "
                f"setup on the next bar if its risk gates allow")
    else:
        shown = ", ".join(missing[:3]) + (" …" if len(missing) > 3 else "")
        text = (f"the bot reads {passed}/{total} on this side and would NOT enter "
                f"(missing: {shown}). You may still take it — that is a decision, not a signal")
    plan_out["bot_view"] = {"ok": True, "passed": passed, "total": total,
                            "ready": ready, "missing": missing, "text": text}


def _measured_text():
    """The honest footer every plan carries: what the ledger says about these setups."""
    return {
        "box_cells": P.BOX_MEASURED.get("cells"),
        "box_cleared": P.BOX_MEASURED.get("cleared"),
        "false_break_pct_20": P.BOX_MEASURED.get("false_break_pct_20"),
        "line": ("No edge has been measured for any of these geometries: "
                 f"{P.BOX_MEASURED.get('cleared')} of {P.BOX_MEASURED.get('cells')} box "
                 f"geometries cleared the no-edge reference, ~"
                 f"{P.BOX_MEASURED.get('false_break_pct_20', 0):.0f}% of breaks close back "
                 f"inside within 15 min, and the paper book is negative at $0.00 cost. "
                 f"This panel checks geometry and cost, not direction."),
    }


def cost_row_presets(atr, spec=None, spread_rt=COST_ROUND_TRIP):
    """The 'how wide must my stop be' table, in ATR — arithmetic, not opinion."""
    return C.cost_ruler(atr, costs=(COST_REGISTERED, spread_rt))


# ─────────────────────────────────────────────────────────────────────────────
# 4. the private manual journal (CLI only; never written by the dashboard)
# ─────────────────────────────────────────────────────────────────────────────

def journal_row(fields):
    """Validate + order one manual observation row. Returns (row, problems).

    Field names are checked against docs/EXECUTION-PLAN.md §7, the five required
    ones must be present and non-empty, and any field whose NAME looks like a
    credential or an account identifier is refused outright — the journal is private
    and must stay safe to paste.
    """
    fields = dict(fields or {})
    problems = []
    for key in fields:
        # The §7 schema itself is allow-listed by name; the scan exists to catch an
        # EXTRA field someone adds to carry a broker login or an account number.
        if key in JOURNAL_FIELDS:
            continue
        lowered = key.lower()
        if any(part in lowered for part in _FORBIDDEN_FIELD_PARTS):
            problems.append(f"field {key!r} looks like an account identifier or a secret")
    unknown = [k for k in fields if k not in JOURNAL_FIELDS]
    if unknown:
        problems.append("unknown field(s): " + ", ".join(sorted(unknown)))
    for key in JOURNAL_REQUIRED:
        if not str(fields.get(key) or "").strip():
            problems.append(f"missing required field: {key}")
    side = str(fields.get("side") or "").upper()
    if side and side not in JOURNAL_SIDES:
        problems.append("side must be BUY, SELL or NONE")
    if side:
        fields["side"] = side
    # Deliberately NO auto-timestamp: a row stamped by the tool when the trader
    # forgot is a row whose "before the outcome" claim cannot be checked. The CLI
    # supplies the timestamp (defaulting to now UTC) so the omission is visible.
    row = {key: fields.get(key) for key in JOURNAL_FIELDS}
    return row, problems


def inside_repo(path, repo_root):
    """True when `path` would land inside the checkout (so it must not be written)."""
    try:
        target = os.path.abspath(path)
        root = os.path.abspath(repo_root)
        return os.path.commonpath([target, root]) == root
    except (ValueError, TypeError):
        return True


def append_journal(path, row, repo_root=None):
    """Append ONE JSON line to a host-local journal. Returns (ok, detail).

    Refuses to write inside the repository: docs/EXECUTION-PLAN.md §7 says the filled
    rows stay private, and a journal that can be committed is a journal that will be
    committed by an autosync run. The default path lives in the data directory,
    which .gitignore already excludes for this exact file.
    """
    repo_root = repo_root or os.path.dirname(os.path.abspath(__file__))
    if inside_repo(path, repo_root):
        return False, (f"refusing to write the manual journal inside the repo ({path}); "
                       f"keep it in the data directory — filled rows are private")
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=False) + "\n")
        return True, f"appended one row to {path}"
    except OSError as exc:
        return False, f"could not write {path}: {exc}"


# ─────────────────────────────────────────────────────────────────────────────
# 5. one call for the dashboard
# ─────────────────────────────────────────────────────────────────────────────

def read(log_rows=None, quotes=None, spec=None, now=None, spread_rt=COST_ROUND_TRIP,
         risk_budgets=DEFAULT_RISK_BUDGETS, box_status=None, boxes=None):
    """The whole manual panel: both sides' plans + clock + cost ruler + spec source.

    `log_rows` is the tail of forward_test_log.csv, `quotes` the tail of today's
    quote CSVs (for the live spread), `box_status` an optional pressure.box_status()
    read whose failing checks ride along as soft warnings. Everything is optional so
    the panel degrades one card at a time instead of failing whole.
    """
    now = now or datetime.now().replace(microsecond=0)
    spec = spec or load_spec("")
    log_rows = log_rows or []
    closure = observed_closure(log_rows)
    setup = P.setup_read(log_rows)
    level = None
    atr = None
    entry = None
    if log_rows:
        floor, ceiling, _logged = P.levels(log_rows)
        last = log_rows[-1]
        entry = P.parse_float(last.get("Close"))
        atr = P.parse_float(last.get("ATR"))
        level = {"BUY": floor, "SELL": ceiling}
    spread_now = None
    for quote in reversed(quotes or []):
        value = P.parse_float(quote.get("spread"))
        if (value is not None and math.isfinite(value) and value >= 0
                and (P.parse_float(quote.get("n_ok")) or 0) > 0 and not quote.get("flags")):
            spread_now = value
            break
    checks = (box_status or {}).get("checks") or []
    plans = {}
    for side in ("BUY", "SELL"):
        plans[side] = plan(side, entry, atr, level=(level or {}).get(side),
                           spread_now=spread_now, spread_rt=spread_rt, spec=spec,
                           closure=closure, now=now, risk_budgets=risk_budgets,
                           checks=checks)
        attach_bot_view(plans[side], setup, side)
    return {
        "ok": bool(entry and atr),
        "as_of": log_rows[-1].get("Timestamp") if log_rows else None,
        "entry": entry,
        "atr": atr,
        "spread_now": spread_now,
        "spread_rt": spread_rt,
        "spec": spec,
        "closure": closure,
        "clock": session_clock(now, closure),
        "setup": setup,
        "plans": plans,
        "cost_ruler": cost_row_presets(atr) if atr else None,
        "risk_budgets": list(risk_budgets or ()),
        "journal": {"fields": list(JOURNAL_FIELDS), "required": list(JOURNAL_REQUIRED),
                    "command": "python3 tools/manual_trade.py --log-decision --side BUY "
                               "--entry 3580.63 --stop 3571.89 --reason-code level_retest"},
        "measured": _measured_text(),
        "notes": [
            "Display-only: this panel places no order, writes no file and changes no gate.",
            f"Cost is the measured median ${spread_rt:.2f} round trip; the registered "
            f"assumption is ${COST_REGISTERED:.2f}.",
            "1R is |entry − stop|. At 0.01 lot (1 oz) a $1 move is $1.00, so dollars and "
            "price distance are the same number per ounce.",
        ],
    }
