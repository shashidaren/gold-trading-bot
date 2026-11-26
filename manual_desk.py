#!/usr/bin/env python3
"""manual_desk — display-only companion for the owner's MANUAL gold trading.

Like pressure.py / chart.py / readiness.py this module is stdlib-only, read-only,
never imports engine.py and never writes a file. It changes no gate, no parameter,
no cost assumption, no ledger row and places no order (paper or real).

Why it exists (docs/EXECUTION-PLAN.md §7 / Track A step A8): alongside the paper
forward test the owner trades manually. The repo already measures that boxes,
signals and the pressure composite have no directional edge; what it *can* offer
honestly is placement and risk context, in one screen:

  * the bot's OPEN PAPER position (entry / stop / target / ratchet / time stop),
    so a manual trade does not unknowingly stack on the same stop cluster;
  * a pre-trade CHECKLIST read back from the engine's own gates (feed, ATR band,
    blackouts, cooldown, daily breaker, closed market, spread as a share of R);
  * the COST + break-even arithmetic, with the registered $0.40 clearly bound to
    the current window and the measured $0.57 deferred to the NEXT one;
  * a PRIVATE observation-row template with the §7 fields and the rules that
    keep a manual log honest. Filled rows are never committed and never read by
    a bot process — this module writes nothing and provides no journal writer.

The verdict is deliberately only about CONDITIONS. It never says buy or sell,
never scores a setup, and never becomes an entry gate. The owner's manual
pressure/hold RULE is still undefined (A8's blocker): this tool implements no
rule, and no output here may be used as one without a new dated pre-registration.

CLI (read-only): python3 tools/manual_desk_report.py [--root DIR] [--json] [--template].
Docs: docs/ANALYSIS-2026-11-26-manual-desk.md.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

# ─────────────────────────────────────────────────────────────────────────────
# Mirrors of the engine / trade_filter constants, by value on purpose: the
# dashboard must not import the engine. tools/test_manual_desk.py pins every one
# of them to pressure.py, which smoke Scenario U pins to the source of truth.
# ─────────────────────────────────────────────────────────────────────────────
RR_TARGET = 1.5
MAX_HOLD_MINUTES = 240
MIN_ATR = 1.10
MAX_ATR = 4.50
MAX_DAILY_LOSSES = 10
STALE_AFTER_SECONDS = 300
COST_MAX_SHARE_PCT = 10.0          # box doc §4: stop >= 10x the round trip
COST_VETO_SHARE_PCT = 20.0         # B4 LIVE veto; advisory here, never a gate

# Registered cost model (owner decision 2026-11-22, REVIEW-2026-11-22-a6-cost-decision.md).
# $0.40 stays binding for the CURRENT structstop1.5 window; $0.57 is the yardstick
# for the NEXT window from 2026-12-01 21:00 UTC and must be written into that
# window's pre-registration before its first trade. Nothing here re-costs a bar.
COST_REGISTERED_RT = 0.40
COST_MEASURED_RT = 0.57
COST_SPREAD_MEDIAN = 0.55          # measured spread-only median (quote logger)
COST_NEXT_FROM = datetime(2026, 12, 1, 21, 0)

# §7 private manual observation record — header only, never filled rows.
OBSERVATION_FIELDS = (
    "timestamp_utc", "bot_trade_id", "side", "bot_entry", "bot_sl", "bot_tp",
    "manual_entry", "manual_exit", "pressure_source", "pressure_metric",
    "pressure_timeframe", "pressure_value_at_entry", "pressure_value_at_stop_touch",
    "last_closed_bar_utc", "contemporaneous_action", "reason_code",
    "max_hold_or_exit_rule", "post_stop_markout_horizons", "mfe", "mae",
    "hypothetical_exit", "estimated_cost", "notes_without_account_identifiers",
)
CSV_HEADER = ",".join(OBSERVATION_FIELDS)

OBSERVATION_RULES = (
    "One row per eligible signal/stop event — including events where you do NOT override the stop, and events that lose.",
    "Keep bot and manual entries separate; call them 'matched' only when timestamps and setup really match.",
    "Timestamp the entry, the stop event and the decision BEFORE looking at the recovery path.",
    "A price that later touches the former target is a counterfactual mark-out, NOT a win under the bot's rules.",
    "Require >=100 matched post-stop observations before any exploratory screen; then write a NEW dated pre-registration. It never becomes an engine gate.",
    "Keep the file private and outside Git: no account identifiers, credentials, balances or unredacted notes.",
    "The manual pressure/hold rule is still undefined (A8). This desk implements no rule and judges none.",
)

NOTES = (
    "No demonstrated edge: the paper book is negative even at $0.00 cost (docs/ANALYSIS-2026-11-22-a6-all-in-cost-model.md). Cost cannot be the whole problem.",
    "The strong 8/8 signal is near a coin flip at 15-60 min (docs/ANALYSIS-2026-10-19-signal-outlook.md); box breakouts/fades cleared 0 of 8 measured geometries (docs/ANALYSIS-2026-10-20-box-theory-manual-trading.md).",
    "The pressure gauge is collinear with side — context, never a signal (docs/ANALYSIS-2026-10-16-dashboard-pressure.md).",
    "A stop is not enforceable across the daily/weekly break: run tools/check_gap_rides.py for the current ride count and damage. The bot's 30-min entries-only guard is derived from the observed price-log break.",
    "One position at a time, never move to breakeven before +0.75R, charge the round trip on EVERY entry, and log every manual trade (docs/ANALYSIS-2026-10-20-box-theory-manual-trading.md §4).",
    "The bot's open paper trade is drawn on the Chart tab as white (entry), rose (stop) and emerald (target) lines. They are location markers, not a forecast.",
)

DISCLAIMER = ("Display-only · paper only · no order, no gate, no strategy variable, "
              "no cost re-basing, no file write. Nothing here is a forecast or "
              "permission to trade real money (G2 remains a separate owner decision).")


# ── small parsers ───────────────────────────────────────────────────────────

def _f(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _ts(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(value).strip(), fmt)
        except ValueError:
            continue
    return None


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def market_quiet(dt):
    """Mirror of pressure.market_quiet (weekend / broker daily break).

    Display only: a silent log in those hours is normal, and a stop across the
    break is not enforceable. Pinned to pressure.market_quiet by the tests.
    """
    return dt.weekday() >= 5 or dt.hour >= 21 or dt.hour < 2


# ── the bot's open PAPER position ───────────────────────────────────────────

def open_position(status, now=None):
    """Facts about the bot's open paper trade, or an explicit 'none' result.

    `status` is the dashboard's status.json dict. Malformed / half-written rows
    are reported as unusable, never coerced into a plausible-looking position.
    """
    now = now or _utcnow()
    out = {"ok": False, "reason": "no open paper trade", "paper_only": True,
           "side": None, "entry": None, "stop": None, "target": None,
           "risk_usd": None, "reward_usd": None, "rr": None,
           "ratcheted": False, "be_armed": None, "trade_num": None,
           "entry_time": None, "age_min": None, "time_left_min": None,
           "cost_share_pct": None, "note": ""}
    if not status or not status.get("trade_active"):
        return out
    entry, stop, target = (_f(status.get(k)) for k in
                           ("entry_price", "stop_loss", "take_profit"))
    if None in (entry, stop, target):
        out["reason"] = "open trade has no usable entry / stop / target"
        return out
    risk = abs(entry - stop)
    reward = abs(target - entry)
    ratcheted = risk < 1e-9
    entry_ts = _ts(status.get("entry_time"))
    age = max(0.0, (now - entry_ts).total_seconds() / 60.0) if entry_ts else None
    age_note = (" Entry time is missing/unparseable, so age and the 240-min "
                "time-stop clock are unknown." if entry_ts is None else "")
    out.update({
        "ok": True, "reason": "open paper position",
        "side": (str(status.get("trade_type") or "").upper() or "—"),
        "entry": entry, "stop": stop, "target": target,
        "risk_usd": round(risk, 2), "reward_usd": round(reward, 2),
        "rr": round(reward / risk, 2) if risk > 0 else None,
        "ratcheted": ratcheted,
        "be_armed": bool(status.get("be_armed")),
        "trade_num": status.get("current_trade_num"),
        "entry_time": entry_ts.strftime("%Y-%m-%d %H:%M:%S") if entry_ts else None,
        "age_min": round(age, 1) if age is not None else None,
        "time_left_min": (round(max(0.0, MAX_HOLD_MINUTES - age), 1)
                          if age is not None else None),
        "cost_share_pct": (round(100.0 * COST_REGISTERED_RT / risk, 1)
                           if risk > 0 else None),
        "note": (("The stop is already at entry (breakeven scratch) — no risk left on "
                  "the bot's side." if ratcheted else
                  "Paper only: these are simulated levels, not broker orders. A manual "
                  "trade on the same side would sit in the same stop cluster.") + age_note),
    })
    return out


def open_levels(status):
    """Chart lines for the bot's open PAPER trade (empty when flat).

    `kind` drives colour/dash in the Chart tab. A ratcheted stop is folded into
    the entry label so two labels never sit on one price. No wall clock is read.
    """
    if not status or not status.get("trade_active"):
        return []
    entry, stop, target = (_f(status.get(k)) for k in
                           ("entry_price", "stop_loss", "take_profit"))
    if None in (entry, stop, target):
        return []
    side = (str(status.get("trade_type") or "").upper() or "paper")
    ratcheted = abs(entry - stop) < 1e-9
    out = [{"label": (f"paper {side} entry = BE stop" if ratcheted
                      else f"paper {side} entry"),
            "price": entry, "kind": "open_entry"}]
    if not ratcheted:
        out.append({"label": f"paper {side} stop", "price": stop,
                    "kind": "open_stop"})
    out.append({"label": f"paper {side} target", "price": target,
                "kind": "open_target"})
    return out


# ── cost + break-even arithmetic ───────────────────────────────────────────

def cost_basis(now=None):
    """Which round-trip number is binding, and which is deferred.

    Deliberately does NOT switch the number at COST_NEXT_FROM: the pre-registration
    for the next window must state $0.57 BEFORE its first trade. Silently swapping
    it here would be the post-outcome re-cost the 2026-11-22 decision forbids.
    """
    now = now or _utcnow()
    left = max(0, math.ceil((COST_NEXT_FROM - now).total_seconds() / 86400.0))
    return {
        "binding_rt": COST_REGISTERED_RT,
        "binding_label": "$0.40 registered for the CURRENT structstop1.5 window",
        "spread_median": COST_SPREAD_MEDIAN,
        "all_in_rt": COST_MEASURED_RT,
        "next_rt": COST_MEASURED_RT,
        "next_from": COST_NEXT_FROM.strftime("%Y-%m-%d %H:%M UTC"),
        "next_status": ("applies to the NEXT window only once its pre-registration "
                        "states it; no net reading is re-stated at $0.57 here"),
        "days_left": left,
        "sentence": (f"${COST_REGISTERED_RT:.2f} round trip is binding now "
                     f"(owner decision 2026-11-22). The measured all-in "
                     f"${COST_MEASURED_RT:.2f} starts with the NEXT window from "
                     f"{COST_NEXT_FROM.strftime('%Y-%m-%d %H:%M UTC')} "
                     f"(~{left} d), after its pre-registration is written."),
    }


def break_even_wr(rr=RR_TARGET, cost_rt=COST_REGISTERED_RT, risk_usd=None,
                  scratch_share=0.0):
    """Decisive win rate needed to break even, with cost on EVERY entry.

    W = p*D decisive wins, L = (1-p)*D losses, S scratches, N = D+S entries.
    p*(rr+1) - 1 = (1 + S/D) * cost/R, so a book with scratches needs MORE than
    the scratch-free lower bound. At 1:1.5 with zero cost this is 40%. Returns a
    percentage or None when the geometry is unusable; never a guess.
    """
    if risk_usd is None or risk_usd <= 0 or rr is None or rr <= 0 or cost_rt is None:
        return None
    share = min(max(scratch_share or 0.0, 0.0), 0.95)
    scratch_ratio = share / (1.0 - share)
    pct = 100.0 * (1.0 + (1.0 + scratch_ratio) * (cost_rt / risk_usd)) / (1.0 + rr)
    return round(pct, 2)


def cost_ruler(atr, costs=None):
    """Spread as a share of R for stops of 1..4 ATR. Arithmetic, not opinion.

    This is the single most useful manual number: a 1-ATR stop on this tape can
    pay a fifth of its risk in spread before price moves at all.
    """
    atr = _f(atr)
    if not atr or atr <= 0:
        return []
    costs = costs or (COST_REGISTERED_RT, COST_MEASURED_RT)
    out = []
    for mult in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0):
        risk = round(mult * atr, 2)
        out.append({
            "atr_mult": mult, "risk_usd": risk,
            "shares": [{"cost_rt": c, "pct": round(100.0 * c / risk, 1)}
                       for c in costs],
            "verdict": ("too tight" if 100.0 * max(costs) / risk > COST_VETO_SHARE_PCT
                        else "cautious" if 100.0 * max(costs) / risk > COST_MAX_SHARE_PCT
                        else "cost-affordable"),
        })
    return out


# ── the pre-trade checklist ─────────────────────────────────────────────────

def checklist(status, ctx, now=None):
    """Read the engine's gates back as ADVICE for a human, never as a gate.

    `ctx` is the dashboard's pressure_context() dict (feed / setup / location /
    portfolio / risk_now). Missing reads become 'unknown', never a green light.
    """
    now = now or _utcnow()
    ctx = ctx or {}
    feed = ctx.get("feed") or {}
    setup = ctx.get("setup") or {}
    location = ctx.get("location") or {}
    portfolio = ctx.get("portfolio") or {}
    risk_now = ctx.get("risk_now") or {}
    checks = []

    def add(key, label, state, value, detail):
        checks.append({"key": key, "label": label, "state": state,
                       "value": str(value), "detail": detail})

    # 1. feed — no fresh bar means every level below is untrustworthy.
    if feed.get("ok"):
        age = feed.get("age_seconds")
        if age is None:
            add("feed", "Fresh price feed", "unknown", "—", "bar age unavailable")
        elif age > STALE_AFTER_SECONDS:
            add("feed", "Fresh price feed", "block", f"{age // 60:.0f} min old",
                "No fresh closed bar. Do not read levels or place a manual trade off them.")
        else:
            add("feed", "Fresh price feed", "pass", f"{age}s old",
                "The last closed bar is current; levels roll every minute.")
    else:
        add("feed", "Fresh price feed", "unknown", "—",
            feed.get("reason") or "feed read unavailable — check the logger first")

    # 2. ATR band (the engine skips outside it).
    atr = _f(setup.get("atr")) or _f((status or {}).get("atr"))
    if atr is None:
        add("atr", "ATR in the bot's band", "unknown", "—", "no ATR on the last bar")
    elif MIN_ATR <= atr <= MAX_ATR:
        add("atr", "ATR in the bot's band", "pass", f"${atr:.2f}",
            f"Inside {MIN_ATR:.2f}-{MAX_ATR:.2f}: the bot is allowed to trade here.")
    else:
        add("atr", "ATR in the bot's band", "block", f"${atr:.2f}",
            f"Outside {MIN_ATR:.2f}-{MAX_ATR:.2f}: the engine auto-skips; a {atr:.2f} ATR "
            "tape changes every stop distance in dollars.")

    # 3. blackouts (direction-aware: the London window blocks BUYs only).
    blocked = portfolio.get("sides_blocked") or {}
    blocked_sides = [s for s, reason in blocked.items() if reason]
    if not portfolio:
        add("blackout", "News / session blackout", "unknown", "—", "portfolio read unavailable")
    elif len(blocked_sides) >= 2:
        add("blackout", "News / session blackout", "block", "both sides",
            "; ".join(str(blocked[s]) for s in blocked_sides))
    elif blocked_sides:
        add("blackout", "News / session blackout", "warn", blocked_sides[0],
            f"{blocked[blocked_sides[0]]} — the other side is still open.")
    else:
        nxt = portfolio.get("next_window")
        if isinstance(nxt, dict):
            nxt_text = f"{nxt.get('label') or 'none'} {nxt.get('at') or ''}".strip()
        elif isinstance(nxt, (tuple, list)) and nxt:
            nxt_text = str(nxt[0])
            if len(nxt) > 2 and hasattr(nxt[2], "strftime"):
                nxt_text += f" at {nxt[2].strftime('%H:%M')} UTC"
        else:
            nxt_text = "none"
        add("blackout", "News / session blackout", "pass", "clear",
            f"Next window: {nxt_text} (the London window blocks BUYs only).")

    # 4. escalating SL cooldown — the churn the 10-05 review measured.
    left = _f(portfolio.get("cooldown_minutes_left")) or 0.0
    if left > 0:
        add("cooldown", "Stop-loss cooldown", "warn", f"{left:.0f} min left",
            portfolio.get("cooldown_note") or
            "The bot is standing aside after a stop; an instant same-side re-entry "
            "is the churn that bled the 0.75R book.")
    else:
        add("cooldown", "Stop-loss cooldown", "pass", "clear",
            "No escalating cooldown is running on the paper side.")

    # 5. daily loss breaker.
    sls = _f(portfolio.get("daily_sls"))
    if portfolio.get("breaker_on"):
        add("breaker", "Daily loss breaker", "block", f"{sls or 0:.0f}/{MAX_DAILY_LOSSES}",
            "The bot is in trend-side-only mode. A bad tape day is not a reason to add manual risk.")
    elif sls is None:
        add("breaker", "Daily loss breaker", "unknown", "—", "daily SL count unavailable")
    else:
        add("breaker", "Daily loss breaker", "pass", f"{sls:.0f}/{MAX_DAILY_LOSSES}",
            "Room remains before the bot's trend-side-only breaker.")

    # 6. closed market / daily break — a stop cannot be enforced across the gap.
    if market_quiet(now):
        add("closure", "Market open (no gap)", "block", "closed",
            "Weekend, rollover or the broker's daily break. A stop is not enforceable "
            "across that hole; see tools/check_gap_rides.py.")
    else:
        add("closure", "Market open (no gap)", "pass", "open",
            "The bot's 30-min entries-only guard is derived from the observed daily "
            "break; do not open a position into that closure.")

    # 7. cost as a share of the structural stop's risk.
    risks = [_f((location.get(s) or {}).get("risk")) for s in ("buy", "sell")]
    risks = [r for r in risks if r and r > 0]
    risk = min(risks) if risks else None
    quote = risk_now.get("quote") or {}
    spread = _f(quote.get("spread"))
    if spread is None or quote.get("stale"):
        spread = COST_SPREAD_MEDIAN
        spread_note = "measured median, no fresh quote"
    else:
        spread_note = "fresh quote"
    if risk is None:
        add("cost_share", "Spread vs your risk", "unknown", "—",
            "no structural stop geometry on this bar")
    else:
        share = 100.0 * spread / risk
        state = ("block" if share > COST_VETO_SHARE_PCT
                 else "warn" if share > COST_MAX_SHARE_PCT else "pass")
        add("cost_share", "Spread vs your risk", state, f"{share:.1f}% of R",
            f"${spread:.2f} round trip ({spread_note}) against the tighter structural "
            f"stop of ${risk:.2f}. Keep the stop >= 10x the cost (<= 10% of R); "
            "the B4 LIVE veto refuses above 20%.")

    # 8. one position at a time (manual advice, NOT an engine gate).
    pos = open_position(status, now)
    if pos.get("ok"):
        add("one_position", "One position at a time", "warn",
            f"bot {pos['side']} open",
            f"The paper book already holds {pos['side']} with its stop at "
            f"${pos['stop']:.2f}. A manual trade on the same side is one more "
            "position on the same stop cluster (box doc §4).")
    else:
        add("one_position", "One position at a time", "pass", "flat",
            "No open paper position. The manual one-position rule is yours to keep.")
    return checks


def verdict(checks):
    """Conditions only. Never says buy or sell, never scores a setup."""
    counts = {"pass": 0, "warn": 0, "block": 0, "unknown": 0}
    for c in checks or []:
        counts[c.get("state", "unknown")] = counts.get(c.get("state", "unknown"), 0) + 1
    state = ("block" if counts["block"] else "warn" if counts["warn"] or counts["unknown"]
             else "pass")
    headline = {
        "block": "SIT OUT — at least one condition is red",
        "warn": "CAUTION — read the amber rows before adding any risk",
        "pass": "CONDITIONS READ OK — still no demonstrated edge",
    }[state]
    return {"state": state, "headline": headline, "counts": counts,
            "detail": ("This is a conditions checklist, not a signal. It cannot say "
                       "whether to buy or sell, and it never changes the bot.")}


# ── the one-screen brief ────────────────────────────────────────────────────

def brief(status, ctx, now=None):
    """Everything the Manual desk tab / CLI renders, in one JSON-safe dict."""
    now = now or _utcnow()
    ctx = ctx or {}
    status = status or {}
    pos = open_position(status, now)
    checks = checklist(status, ctx, now)
    setup = ctx.get("setup") or {}
    atr = _f(setup.get("atr")) or _f(status.get("atr"))
    cost = cost_basis(now)
    return {
        "ok": True,
        "as_of": now.strftime("%Y-%m-%d %H:%M UTC"),
        "open": pos,
        "levels": open_levels(status),
        "checks": checks,
        "verdict": verdict(checks),
        "cost": cost,
        "break_even": {
            "pct_nocost": break_even_wr(RR_TARGET, 0.0, 6.0),
            "pct_registered": break_even_wr(RR_TARGET, COST_REGISTERED_RT, 6.0),
            "pct_with_scratches": break_even_wr(RR_TARGET, COST_REGISTERED_RT, 6.0, 0.27),
            "pct_next_cost": break_even_wr(RR_TARGET, COST_MEASURED_RT, 6.0),
            "note": ("Decisive-only (TP/(TP+SL)) at 1:1.5 on a $6.00 stop, cost charged "
                     "on EVERY entry. 40% is the uncosted floor; with the book's ~27% "
                     "scratch share it rises again. This is arithmetic, not a target."),
        },
        "ruler": cost_ruler(atr),
        "atr": atr,
        "notes": list(NOTES),
        "observation": {
            "header": CSV_HEADER,
            "fields": list(OBSERVATION_FIELDS),
            "rules": list(OBSERVATION_RULES),
            "hint": ("Keep the CSV outside Git (manual_observations*.csv is ignored). "
                     "python3 tools/manual_desk_report.py --template prints the header only."),
        },
        "disclaimer": DISCLAIMER,
    }
