#!/usr/bin/env python3
"""cost_model — the all-in round-trip cost model the A6 queue step asks for.

Everything else in this repo re-costs the ledger at ONE flat number ($0.40 round
trip, i.e. `strategy_lab.py --cost 0.20` per side). That number was registered
before any quote existed. `tools/xm_quote_report.py` §3 measures the SPREAD leg
only; this tool adds the three legs that were missing — commission, slippage and
swap — states which of them are measured and which are assumptions, and then
re-costs the ledger and the canonical replay inside a sensitivity range.

    python3 tools/cost_model.py                    full report
    python3 tools/cost_model.py --json             machine-readable
    python3 tools/cost_model.py --root . --dir xm_data

WHAT IS OBSERVED AND WHAT IS NOT (this split is the point of the tool)

  leg          value used              class      why
  -----------  ----------------------  ---------  -------------------------------------------
  spread       $0.55 / round trip      OBSERVED   quote logger, joined at entry and exit
  commission   $0.00                   ASSUMED    no commission field exists in the captured
                                                  account/symbol spec; XM prices metals on the
                                                  spread. Unobservable from this repo — carried
                                                  as a sensitivity (+$0.10 RT) instead of a fact.
  slippage     $0.01 / side (2 ticks)  ASSUMED    not observable: the ledger books fill = stop /
                                                  target price. Bounded by the tick (0.01) and
                                                  the broker's MARKET/IOC execution. Sensitivity
                                                  0.00 / 0.01 / 0.02 per side.
  swap         exact from the spec      COMPUTED   swap_long/swap_short points, triple-WED, and
                                                  the rollover instant derived from the SAME EU
                                                  DST rule the logger confirmed (server 00:00).

The tool never writes, never imports engine.py and never changes a rule. A cost
model can only RE-STATE the book, it cannot make it profitable: every number here
is applied after the fact to trades that already happened.

Exit code 0 always (it is a report); use --json to consume it elsewhere.
"""
import argparse
import csv
import json
import os
import statistics as st
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import broker_time as BT          # noqa: E402  the confirmed EU DST rule
import strategy_lab as L          # noqa: E402  ledger loader + LIVE_CUTOVER + ATR multiples

UTC = timezone.utc

# --- reference numbers (mirrors; nothing here is a trading rule) --------------
LOT = 0.01                        # the engine's fixed size: 0.01 lot = 1 oz at a 100 oz contract
RR = L.ATR_TP_MULT / L.ATR_SL_MULT      # 1.5 — the ledger's TP survives the BE ratchet
REGISTERED_RT = 0.40              # the registered round trip everything is judged against
SLIP_PER_SIDE = 0.01              # ASSUMED: one tick (point 0.01) of adverse fill per side
COMMISSION_RT = 0.00              # ASSUMED: spread-priced account, no commission field in the spec
SLIP_SENSITIVITY = (0.00, 0.01, 0.02)   # per side, $ (0 = frictionless fill, 0.02 = two ticks)
COMMISSION_SENSITIVITY = (0.00, 0.05, 0.10)   # round trip, $ (a hypothetical commission account)
JOIN_TOL_S = 75                   # a ledger entry/exit joins a usable quote within this
VETO_PCT_OF_R = 20.0              # engine.LIVE_COST_MAX_PCT_OF_R — the live-path cost veto
MEDIAN_1R_FALLBACK = None         # never invent one: no quotes/ledger => no share-of-R read


# =====================================================================================
# swap — the leg the ledger cannot see
# =====================================================================================
def _swap_day_enum(sw):
    """MT5 ENUM_DAY_OF_WEEK uses SUNDAY=0 .. SATURDAY=6; PyPI weekday() is MONDAY=0.
    Return the Python weekday number of the TRIPLE day (3 = WEDNESDAY -> 2)."""
    try:
        enum = int(sw.get("swap_rollover3days", 3))
    except (TypeError, ValueError):
        enum = 3
    return (enum - 1) % 7


def rollover_nights(entry, exit_, rule="eu", triple_python_weekday=2):
    """Nights a position is carried through broker rollover, and how many are triple.

    The broker charges swap when server time crosses 00:00. That instant is derived
    from the confirmed EU rule (`broker_time.server_to_utc`), and the night is
    labelled by the server date of the rollover INSTANT — the night that ENDS at
    Wednesday 00:00 server is the "Wednesday" swap, which is how MT5 presents it.
    MT5 reports `swap_rollover3days` as ENUM_DAY_OF_WEEK
    (SUNDAY=0 … SATURDAY=6) = 3 = WEDNESDAY, which in that convention charges the
    night that ENDS on Wednesday 00:00 (the rollover out of Tuesday night).

    CONVENTION RISK, disclosed rather than hidden: the alternative reading labels
    the night by the session that TRADED it (so the same instant is "Tuesday").
    The two differ only for a position held across ONE night at that boundary. In
    the current book
    the whole swap total is -$3.45, so the ambiguity is worth a few cents; it is
    not what makes the book negative. See the summary block.

    -> (nights, triple_nights)
    """
    if exit_ <= entry:
        return 0, 0
    nights = triple = 0
    day = (entry - timedelta(days=2)).date()
    last = exit_.date() + timedelta(days=2)
    while day <= last:
        r = BT.server_to_utc(datetime(day.year, day.month, day.day), rule)
        if entry < r <= exit_:
            nights += 1
            if day.weekday() == triple_python_weekday:
                triple += 1
        day += timedelta(days=1)
    return nights, triple


def swap_for_trade(side, entry, exit_, sw, rule="eu", triple_python_weekday=2):
    """Signed USD swap for one trade at 0.01 lot. Negative = paid.

    MT5 POINTS mode: swap = points x point x contract x lots. At 0.01 lot on a
    100 oz contract and point 0.01 that is $0.01 per point.
    """
    point = float(sw.get("point") or 0.01)
    contract = float(sw.get("trade_contract_size") or 100.0)
    per_point = point * LOT * contract
    pts = float(sw.get("swap_long") if side.upper() == "BUY" else sw.get("swap_short") or 0.0)
    nights, triple = rollover_nights(entry, exit_, rule, triple_python_weekday)
    # a triple night charges the swap three times
    return (pts * (nights + 2 * triple)) * per_point, nights, triple


# =====================================================================================
# spread — reuse the measured leg, do not re-derive it
# =====================================================================================
def load_quote_legs(root, qdir, trades):
    """Join each trade's entry and exit to a usable quote; return measured spread cost.

    Deliberately the SAME helper `xm_quote_report.py` uses, so the two tools can
    never disagree about the measured spread. -> ([(trade, spread_usd)], median)
    """
    import xm_quote_report as QR
    samples, _bad, _files = QR.load_quotes(qdir)
    if not samples:
        return [], None
    spec = QR.load_spec(qdir) or {}
    contract = (spec.get("symbol_info") or {}).get("trade_contract_size") or 100.0
    joined = QR.trade_costs(trades, samples, contract)
    pairs = [(t, c) for t, c, _se, _sx in joined]
    return pairs, (QR.pct(sorted(c for _, c in pairs), .5) if pairs else None)


def one_r_usd(t):
    """This trade's 1R in USD (reward leg / RR — the repo's ratchet-safe definition)."""
    try:
        return abs(t["tp"] - t["ep"]) / RR
    except (TypeError, ZeroDivisionError):
        return None


# =====================================================================================
# the model
# =====================================================================================
def build(root=ROOT, qdir=None, rule="eu"):
    qdir = qdir or os.path.join(root, "xm_data")
    ledger = os.path.join(root, "trades.csv")
    trades = L.load_ledger(ledger) if os.path.exists(ledger) else []
    import xm_quote_report as QR
    spec = QR.load_spec(qdir) or {}
    sw = spec.get("symbol_info") or {}

    joined, median_spread = load_quote_legs(root, qdir, trades)
    measured = {t["num"]: c for t, c in joined}

    rows = []
    for t in trades:
        spread = measured.get(t["num"])
        swap, nights, triple = swap_for_trade(t["side"], t["et"], t["xt"], sw, rule)
        # the fallback spread is the measured median, never $0 and never the assumption
        s = spread if spread is not None else median_spread
        rows.append(dict(num=t["num"], side=t["side"], era=(t["et"] >= L.LIVE_CUTOVER),
                         pnl=t["pnl"], r1=one_r_usd(t), spread=s, spread_measured=spread is not None,
                         commission=COMMISSION_RT, slippage=2 * SLIP_PER_SIDE,
                         swap=swap, nights=nights, triple=triple))

    modelled = [r for r in rows if r["spread"] is not None]
    measured_rows = [r for r in modelled if r["spread_measured"]]

    def rt(r, slip=SLIP_PER_SIDE, comm=COMMISSION_RT):
        """All-in round trip for one trade, USD (swap signed)."""
        return r["spread"] + comm + 2 * slip + r["swap"]

    def block(subset, label):
        n = len(subset)
        if not n:
            return None
        gross = sum(r["pnl"] for r in subset)
        spend = [rt(r) for r in subset]
        r1 = st.median([r["r1"] for r in subset if r["r1"]])
        meas = [r for r in subset if r["spread_measured"]]
        out = dict(label=label, n=n, n_measured=len(meas), gross=gross,
                   median_spread=st.median([r["spread"] for r in meas]) if meas else None,
                   swap=sum(r["swap"] for r in subset),
                   carried=sum(1 for r in subset if r["nights"]),
                   all_in_mean=st.mean(spend), all_in_median=st.median(spend),
                   spread_mean=st.mean([r["spread"] for r in meas]) if meas else None,
                   spread_fallback_used=n - len(meas),
                   all_in_p90=QR.pct(sorted(spend), .9), all_in_max=max(spend),
                   median_1r=r1, at={})
        for cost, name in ((REGISTERED_RT, "registered"), (None, "all_in")):
            for slip in ((SLIP_PER_SIDE,) if cost is not None else SLIP_SENSITIVITY):
                key = f"{name}_{cost if cost is not None else slip:.2f}"
                spend_i = (cost if cost is not None else None)
                tot = 0.0
                for r in subset:
                    c = spend_i if spend_i is not None else rt(r, slip=slip)
                    tot += r["pnl"] - c
                out["at"][key] = dict(net=tot, per_trade=tot / n,
                                      r_per_trade=(tot / n / r1) if r1 else None)
        return out

    whole = block(modelled, "whole modelled book")
    era = block([r for r in modelled if r["era"]], "struct-stop era")

    # spread as a share of THIS trade's own 1R, and which share the live veto blocks
    shares = sorted(100.0 * r["spread"] / r["r1"] for r in measured_rows if r["r1"])
    all_in_shares = sorted(100.0 * rt(r) / r["r1"] for r in measured_rows if r["r1"])
    vetoed = [r for r in measured_rows if r["r1"] and 100.0 * rt(r) / r["r1"] > VETO_PCT_OF_R]

    return dict(
        root=root,
        trades=len(trades), modelled=len(modelled),
        coverage=dict(joined=len(joined), missing=len(trades) - len(joined),
                      note="joinable trades are MEASURED; unjoinable ones (mostly pre-logger) "
                           "fall back to the measured MEDIAN, and every share-of-1R figure below "
                           "is computed on measured trades only"),
        legs=dict(
            spread=dict(value=median_spread, kind="OBSERVED",
                        source="xm_data quotes joined at entry and exit (+-%ds)" % JOIN_TOL_S),
            commission=dict(value=COMMISSION_RT, kind="ASSUMED",
                            source="no commission field in the captured account/symbol spec; "
                                   "spread-priced metals account (sensitivity %s)" %
                                   (COMMISSION_SENSITIVITY,)),
            slippage=dict(value=2 * SLIP_PER_SIDE, kind="ASSUMED",
                          source="ledger books fill = stop/target price; one 0.01 tick per side "
                                 "is the planning default (sensitivity per side %s)" %
                                 (SLIP_SENSITIVITY,)),
            swap=dict(value=sum(r["swap"] for r in rows), kind="COMPUTED",
                      source="swap_long %.2f / swap_short %.2f points, triple charged on the %s "
                             "rollover (ENUM_DAY_OF_WEEK convention, see the docstring), rollover "
                             "instant from the confirmed EU rule" %
                             (sw.get("swap_long") or 0, sw.get("swap_short") or 0,
                              {0: "MON", 1: "TUE", 2: "WED", 3: "THU", 4: "FRI", 5: "SAT",
                               6: "SUN"}.get(_swap_day_enum(sw), "?"))),
        ),
        spread_share_of_1r=dict(p50=QR.pct(shares, .5), p90=QR.pct(shares, .9),
                                max=shares[-1] if shares else None, n=len(shares)),
        all_in_share_of_1r=dict(p50=QR.pct(all_in_shares, .5), p90=QR.pct(all_in_shares, .9),
                                max=all_in_shares[-1] if all_in_shares else None,
                                n=len(all_in_shares), veto_pct=VETO_PCT_OF_R,
                                vetoed=len(vetoed),
                                vetoed_pct=100.0 * len(vetoed) / max(1, len(measured_rows))),
        whole=whole, era=era,
        recommendation=dict(
            registered_now=REGISTERED_RT,
            suggested_rt=round((median_spread or 0.0) + 2 * SLIP_PER_SIDE + COMMISSION_RT, 2),
            basis="measured spread median + 2 x one-tick slip + 0 commission",
            note="re-cost with `strategy_lab.py --cost %.2f` per side and `win_rate_report.py "
                 "--spread %.2f`; the owner decides whether to replace the registered $0.40, and "
                 "nothing changes until that decision is recorded" %
                 ((median_spread or 0.0) / 2 + SLIP_PER_SIDE, (median_spread or 0.0) + 2 * SLIP_PER_SIDE),
        ),
        carried=sorted([dict(num=r["num"], side=r["side"], nights=r["nights"],
                             triple=r["triple"], swap=r["swap"]) for r in rows if r["nights"]],
                       key=lambda d: d["num"]),
        assumptions=[
            "spread is measured, not assumed; everything else is stated as a value AND a class",
            "slippage and commission are NOT observable from a quotes CSV — they are planning "
            "values with a sensitivity range, and they must not be quoted as measurements",
            "swap is computed from the captured spec and the confirmed DST rule; it is exact for "
            "the nights held, including the triple-Wednesday charge",
            "costs are applied to trades that already happened: a cost model re-states the book "
            "and can never make it profitable",
            "the registered $0.40 round trip stays registered until the owner accepts a "
            "replacement; this tool recommends, it does not re-register",
        ],
    )


# =====================================================================================
# rendering
# =====================================================================================
def _usd(x):
    return f"${x:+.2f}" if x is not None else "—"


def _at(blk, key):
    if not blk:
        return None
    return blk["at"][key]


def render(m):
    L_ = []
    add = L_.append
    add("cost model — all-in round trip for GOLD at 0.01 lot (1 oz). Read-only; changes no rule.")
    add("")
    add("== 1. THE FOUR LEGS ==")
    add(f"  {'leg':12s}{'$/round trip':>14s}  {'class':10s} why")
    for name in ("spread", "commission", "slippage", "swap"):
        leg = m["legs"][name]
        val = leg["value"]
        if val is None:
            show = "— (no data)"
        elif name == "swap":
            show = f"{val:+.2f} (book total)"
        else:
            show = f"${val:.2f}"
        add(f"  {name:12s}{show:>14s}  {leg['kind']:10s} {leg['source']}")
    add("")
    add("  OBSERVED = measured from xm_data.  ASSUMED = a planning value, not a measurement.")
    add("  COMPUTED = exact from the captured spec + the confirmed DST rule.")
    add("")
    cov = m["coverage"]
    add("== 2. COST AS A SHARE OF EACH TRADE'S OWN 1R (measured trades only, n=%d of %d) ==" %
        (m["all_in_share_of_1r"]["n"], m["trades"]))
    add("  %d joined a usable quote; %d fell back to the measured median and are excluded here." %
        (cov["joined"], cov["missing"]))
    s, a = m["spread_share_of_1r"], m["all_in_share_of_1r"]
    if s["n"]:
        add(f"  spread only : p50 {s['p50']:5.1f}%  p90 {s['p90']:5.1f}%  max {s['max']:5.1f}%")
        add(f"  all-in      : p50 {a['p50']:5.1f}%  p90 {a['p90']:5.1f}%  max {a['max']:5.1f}%")
        add(f"  the live veto (engine.LIVE_COST_MAX_PCT_OF_R = {a['veto_pct']:.0f}% of 1R) blocks "
            f"{a['vetoed']} of {a['n']} measured trades ({a['vetoed_pct']:.1f}%) at the all-in cost")
    else:
        add("  no trade joins a quote yet — nothing to read")
    add("")
    add("== 3. RE-COSTED LEDGER (net USD, costs charged on every trade including scratches) ==")
    for blk in (m["whole"], m["era"]):
        if not blk:
            continue
        add(f"  {blk['label']}  n={blk['n']} ({blk['n_measured']} measured)  gross {_usd(blk['gross'])}  "
            f"swap {blk['swap']:+.2f}  ({blk['carried']} carried overnight)")
        add(f"    {'model':40s}{'net $':>10s}{'$/trade':>10s}{'R/trade':>10s}")
        reg = _at(blk, "registered_0.40")
        add(f"    {'$0.40 registered round trip':40s}{reg['net']:>10.2f}{reg['per_trade']:>10.3f}"
            f"{reg['r_per_trade']:>10.3f}")
        for slip in SLIP_SENSITIVITY:
            row = _at(blk, "all_in_%.2f" % slip)
            tag = "all-in (spread+swap), %.2f slip/side" % slip
            if slip == SLIP_PER_SIDE:
                tag += "  <- default"
            add(f"    {tag:40s}{row['net']:>10.2f}{row['per_trade']:>10.3f}{row['r_per_trade']:>10.3f}")
        if blk["median_spread"] is not None:
            add(f"    measured spread on the {blk['n_measured']} joined trades: mean ${blk['spread_mean']:.2f} "
                f"median ${blk['median_spread']:.2f} | median 1R ${blk['median_1r']:.2f}")
        add("")
    add("== 4. COMMISSION SENSITIVITY (what a commission-charged account would add) ==")
    if m["whole"]:
        base = _at(m["whole"], "all_in_%.2f" % SLIP_PER_SIDE)["net"]
        for comm in COMMISSION_SENSITIVITY:
            add(f"  +${comm:.2f}/round trip -> whole book net {base - comm * m['whole']['n']:+.2f}"
                + ("   (the captured account: spread-priced)" if comm == 0 else ""))
    else:
        add("  (no data)")
    add("")
    add("== 5. OVERNIGHT CARRIES (the swap leg, itemised) ==")
    if m["carried"]:
        for r in m["carried"]:
            add(f"  #{r['num']:<4} {r['side']:4s} {r['nights']} night(s)"
                f"{' incl. ONE TRIPLE' if r['triple'] else '':18s} swap {r['swap']:+.2f}")
        add(f"  book total swap {m['legs']['swap']['value']:+.2f} — small and both-sided (longs pay, "
            "shorts earn); it does not explain the deficit")
    else:
        add("  no trade was carried through a rollover")
    add("")
    rec = m["recommendation"]
    add("== 6. WHAT THE REGISTERED $0.40 SHOULD BE COMPARED AGAINST ==")
    add(f"  registered now            : ${rec['registered_now']:.2f} per round trip (unchanged, still binding)")
    add(f"  suggested re-cost figure  : ${rec['suggested_rt']:.2f} per round trip  ({rec['basis']})")
    add(f"  -> {rec['note']}")
    add("  the recommendation is a MEASUREMENT gap, not a strategy change: it makes the ledger look")
    add("  worse, never better, and it must be accepted by the owner before any bar is re-read")
    add("")
    add("== 7. WHAT THIS DOES AND DOES NOT SETTLE ==")
    for a_ in m["assumptions"]:
        add(f"  - {a_}")
    return "\n".join(L_)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--dir", default=None, help="quote data dir (default <root>/xm_data)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    m = build(root=a.root, qdir=a.dir)
    print(json.dumps(m, indent=2) if a.json else render(m))
    return 0


if __name__ == "__main__":
    sys.exit(main())
