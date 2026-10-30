#!/usr/bin/env python3
"""
Paper-ledger runway — "how many trades until the simulated balance runs out?"

Read-only. It reads `trades.csv` + `status.json`, writes nothing and imports no engine
module, so it can be run at any time, from anywhere, without touching the bot.

    python3 tools/equity_runway.py                 # repo root
    python3 tools/equity_runway.py --root /opt/gold
    python3 tools/equity_runway.py --json
    python3 tools/equity_runway.py --strict        # exit 1 once true equity is at/below $0 (alert only)

Why this exists (docs/ANALYSIS-2026-10-30-simulated-equity-and-paper-runway.md)
-----------------------------------------------------------------------------
The simulated balance is a **counter, not capital**. The paper book trades a fixed
0.01 lot (`engine.size_lots()` returns `LOT_SIZE` whenever there is no broker account),
so the number in `status.json` cannot change an entry, an exit, a lot size or a
parameter. What it *can* do is run out: the engine books every loss against it and
has no floor, so it will cross zero and keep trading on a negative balance.

The number the owner actually needs is the **runway** — how many closed trades of
burn are left before that happens. This tool prints it so the decline is a forecast
rather than a surprise.

**Policy (owner decision 2026-10-30):** the ledger is **never** rebaselined —
"no rebaseline ever — let it go negative". The book is expected to cross zero and
keep trading on a negative balance; that is deliberate, and it is the reason this
tool only ever READS. `--strict` is an accounting alert (exit 1 at/under $0), not a
trigger for an edit. The §5 rebaseline proposal is printed as **not adopted** so the
record of what was considered survives; see the doc's §8.

Definitions (same as every other tool in this repo)
--------------------------------------------------
  risk per trade   recovered from the reward leg: |TP - Entry| / 1.5, because TP is
                   logged and TP = 1.5 x the ACTUAL risk in both regimes. Falls back
                   to 2 x ATR on rows with no usable TP. Identical to
                   tools/win_rate_report.py, which is the reference implementation.
  R/trade          Profit / risk.
  gross            as booked by the engine (no spread).
  net              gross minus `--cost` per side applied to EVERY trade, scratches
                   included - the strategy_lab cost model. $0.20/side is the
                   REGISTERED assumption ($0.40 round trip); $0.275/side is the
                   MEASURED spread-only figure from tools/xm_quote_report.py.
  true equity      START_BALANCE + summed ledger P&L (tools/handoff_check.py's
                   definition). It ignores the historical balance-reset drift, which
                   is why the engine ledger and true equity differ.
  runway           true equity / |net $ per trade|, in closed trades, plus the era's
                   trades-per-active-day to turn that into trading days. A bootstrap
                   range is printed because a point estimate off 261 trades is not
                   a forecast.
"""
import argparse
import csv
import json
import os
import random
import statistics
import sys
from datetime import datetime

START_BALANCE = 500.0        # engine.START (paper ledger start); handoff_check's base too
LIVE_CUTOVER = "2026-10-06 03:00"   # strategy_lab.LIVE_CUTOVER - the structural-stop era
RR_TARGET = 1.5              # engine.RR_TARGET: TP = 1.5 x actual risk
ATR_SL_MULT = 2.0            # fallback geometry only (engine.ATR_SL_MULT)
STRUCT_ERA = "struct-stop era"

# --------------------------------------------------------------------------- #
# OWNER DECISION (2026-10-30): the ledger is NEVER rebaselined.
#   verbatim: "no rebaseline ever - let it go negative"
# recorded in the analysis doc below, §8 (it declines the §5 proposal that this
# tool used to describe). Nothing in this file may be read as permission to edit
# trades.csv or status.json: the tool is read-only and the policy forbids the edit.
# The §5 numbers are kept only so the declined proposal stays on the record.
# --------------------------------------------------------------------------- #
POLICY_MODE = "never_rebaseline"      # owner decision; see the doc's §8.1/§8.2
REBASELINE_PERMITTED = False          # no top-up, no reset, no ledger edit - ever
RESET_FLOOR_USD = 0.0                 # the level at which the DECLINED §5 rule would have fired;
                                      # kept as an ALERT threshold only (negative-ledger warning)
RESET_TO_USD = START_BALANCE          # what the DECLINED §5 rule would have rebased to
POLICY_DOC = "docs/ANALYSIS-2026-10-30-simulated-equity-and-paper-runway.md"


# --------------------------------------------------------------------------- #
def risk_of(row):
    """Actual risk in $, reconstructed the way win_rate_report.py / strategy_lab.py do."""
    try:
        entry = float(row.get("Entry_Price") or 0)
        tp = float(row.get("Take_Profit") or 0)
        atr = float(row.get("ATR_At_Entry") or 0)
    except (TypeError, ValueError):
        return None
    if entry and tp:
        r = abs(tp - entry) / RR_TARGET
        if r > 0:
            return r
    if atr > 0:
        return ATR_SL_MULT * atr
    return None


def load_trades(path):
    out = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            et = (row.get("Entry_Time") or "").strip()
            if not et:
                continue                      # malformed/quarantined row: no entry, no trade
            try:
                profit = float(row.get("Profit") or 0)
            except (TypeError, ValueError):
                continue
            out.append((et, profit, risk_of(row)))
    return out


def q(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    i = min(len(xs) - 1, max(0, int(round(p * (len(xs) - 1)))))
    return xs[i]


def summarise(trades, cutoff=None):
    """Counts, gross R/trade and median 1R $ over a slice of the ledger."""
    sel = [t for t in trades if cutoff is None or t[0] >= cutoff]
    rs = [p / r for (_et, p, r) in sel if r]
    risks = [r for (_et, _p, r) in sel if r]
    return dict(
        n=len(sel), joinable=len(rs),
        gross_usd=sum(p for (_et, p, _r) in sel),
        r_per_trade=(statistics.fmean(rs) if rs else None),
        median_risk=(statistics.median(risks) if risks else None),
        rs=rs, days=sorted({t[0][:10] for t in sel}),
    )


def count_outcomes(path):
    """W/L/BE/TIME straight off the rows - win_rate_report's buckets."""
    c = {"TP": 0, "SL": 0, "BE": 0, "TIME": 0}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            if not (row.get("Entry_Time") or "").strip():
                continue
            reason = (row.get("Exit_Reason") or "").strip().upper()
            if reason in c:
                c[reason] += 1
    return c


def bootstrap_runway(rs, usd_per_trade_risk, equity, draws=2000, seed=0):
    """5th/95th percentile of trades-to-zero over a bootstrap of the era's R/trade.

    `usd_per_trade_risk` is the median 1R in $, so a draw's burn is
    |mean R| x that. Draws where the mean R is >= 0 have no runway (no burn).
    """
    if not rs or equity is None or not usd_per_trade_risk:
        return None, None, None
    rnd = random.Random(seed)
    n = len(rs)
    out = []
    zero_or_better = 0
    for _ in range(draws):
        m = sum(rnd.choices(rs, k=n)) / n
        if m >= 0:
            zero_or_better += 1
            continue
        out.append(equity / (abs(m) * usd_per_trade_risk))
    return (q(out, 0.05), q(out, 0.95), zero_or_better / draws)


# --------------------------------------------------------------------------- #
def build(root, cost_per_side):
    trades_path = os.path.join(root, "trades.csv")
    status_path = os.path.join(root, "status.json")
    if not os.path.isfile(trades_path):
        raise SystemExit(f"no trades.csv under {root!r}")

    trades = load_trades(trades_path)
    outcomes = count_outcomes(trades_path)

    ledger = None
    open_trade = None
    if os.path.isfile(status_path):
        with open(status_path) as f:
            st = json.load(f)
        try:
            ledger = float(st.get("equity"))
        except (TypeError, ValueError):
            ledger = None
        if st.get("trade_active"):
            open_trade = f"{st.get('trade_type')} #{st.get('current_trade_num')}"

    gross_total = sum(p for (_et, p, _r) in trades)
    true_equity = START_BALANCE + gross_total
    drift = (ledger - true_equity) if ledger is not None else None

    book = summarise(trades)
    era = summarise(trades, LIVE_CUTOVER)

    rt_cost = 2.0 * cost_per_side

    def net_r(s):
        if not s["r_per_trade"] or not s["median_risk"]:
            return None
        return s["r_per_trade"] - rt_cost / s["median_risk"]

    book_net_r, era_net_r = net_r(book), net_r(era)

    def usd_per_trade(s, r):
        if r is None or not s["median_risk"]:
            return None
        return r * s["median_risk"]

    era_usd = usd_per_trade(era, era_net_r)
    trades_per_day = (era["n"] / len(era["days"])) if era["days"] else None

    runway = days = lo = hi = p_no_burn = None
    if era_usd is not None and era_usd < 0 and true_equity > 0:
        runway = true_equity / abs(era_usd)
        days = (runway / trades_per_day) if trades_per_day else None
    lo, hi, p_no_burn = bootstrap_runway(era["rs"], era["median_risk"], true_equity)

    def wr_pct(c):
        decisive = c["TP"] + c["SL"]
        return (100.0 * c["TP"] / decisive) if decisive else None

    return dict(
        root=os.path.abspath(root),
        cost_per_side=cost_per_side,
        round_trip_cost=rt_cost,
        closed=trades and len(trades),
        outcomes=outcomes,
        decisive_wr_pct=wr_pct(outcomes),
        ledger=ledger,
        true_equity=true_equity,
        drift=drift,
        open_trade=open_trade,
        book=dict(n=book["n"], joinable=book["joinable"], gross_usd=book["gross_usd"],
                  r_per_trade=book["r_per_trade"], net_r_per_trade=book_net_r,
                  median_risk=book["median_risk"]),
        era=dict(name=STRUCT_ERA, since=LIVE_CUTOVER, n=era["n"], joinable=era["joinable"],
                 active_days=len(era["days"]), trades_per_active_day=trades_per_day,
                 gross_usd=era["gross_usd"], r_per_trade=era["r_per_trade"],
                 net_r_per_trade=era_net_r, median_risk=era["median_risk"],
                 usd_per_trade=era_usd),
        runway=dict(usd_per_trade=era_usd, trades=runway, trading_days=days,
                    trades_p05=lo, trades_p95=hi, p_no_burn=p_no_burn),
        policy=dict(doc=POLICY_DOC, mode=POLICY_MODE,
                    rebaseline_permitted=REBASELINE_PERMITTED,
                    alert_floor_usd=RESET_FLOOR_USD,
                    at_or_below_zero=(true_equity <= RESET_FLOOR_USD),
                    to_go_usd=(true_equity - RESET_FLOOR_USD),
                    declined_proposal_usd=dict(floor_usd=RESET_FLOOR_USD,
                                               rebase_to_usd=RESET_TO_USD,
                                               status="registered 2026-10-30, DECLINED by owner")),
    )


def fmt(x, spec="{:.2f}"):
    return "-" if x is None else spec.format(x)


def report(d):
    print("Paper-ledger runway — read-only. The simulated balance is a counter, not capital.")
    print(f"  root {d['root']}")
    o = d["outcomes"]
    print(f"\n  ledger    engine ${fmt(d['ledger'])}  (status.json equity) · "
          f"true equity ${fmt(d['true_equity'])}  (500 + summed P&L) · "
          f"drift ${fmt(d['drift'])}")
    print(f"  book      n={d['closed']}  {o['TP']}W/{o['SL']}L/{o['BE']}BE/{o['TIME']}TIME  "
          f"decisive {fmt(d['decisive_wr_pct'], '{:.1f}%')}  ·  open: {d['open_trade'] or 'none'}")
    b, e = d["book"], d["era"]
    print(f"  whole book  gross {fmt(b['r_per_trade'], '{:+.3f}')}R/t  "
          f"net {fmt(b['net_r_per_trade'], '{:+.3f}')}R/t at ${d['round_trip_cost']:.2f} RT  "
          f"(median 1R ${fmt(b['median_risk'])})")
    print(f"  {e['name']}  n={e['n']}  gross {fmt(e['r_per_trade'], '{:+.3f}')}R/t  "
          f"net {fmt(e['net_r_per_trade'], '{:+.3f}')}R/t  (median 1R ${fmt(e['median_risk'])})")
    print(f"  burn        ${fmt(e['usd_per_trade'], '{:+.2f}')} per closed trade "
          f"(era, net at ${d['round_trip_cost']:.2f} RT)")
    print(f"  pace        {fmt(e['trades_per_active_day'], '{:.1f}')} trades per active day "
          f"({e['active_days']} active days in the era)")
    r = d["runway"]
    if r["trades"] is not None:
        print(f"  RUNWAY      ~{r['trades']:.0f} closed trades "
              f"(~{fmt(r['trading_days'], '{:.1f}')} trading days) to $0.00")
        if r["trades_p05"] is not None:
            print(f"              bootstrap 90% range {r['trades_p05']:.0f}-{r['trades_p95']:.0f} "
                  f"trades ({100 * (r['p_no_burn'] or 0):.0f}% of draws have no burn at all)")
    else:
        print("  RUNWAY      no burn in the era sample (or the ledger is already at/below the floor)")
    p = d["policy"]
    print(f"\n  owner decision (2026-10-30)  NO REBASELINE - the ledger is never edited  ({p['doc']} §8)")
    print("    \"no rebaseline ever - let it go negative\"")
    print("    -> no top-up, no reset, no edit to trades.csv or status.json; a negative balance is expected")
    prop = p["declined_proposal_usd"]
    print(f"    declined proposal (NOT adopted): rebaseline at true equity <= ${prop['floor_usd']:.2f} "
          f"to ${prop['rebase_to_usd']:.0f}")
    if p["at_or_below_zero"]:
        print(f"    ALERT: true equity ${fmt(d['true_equity'])} is at/below $0 - the book is now trading "
              f"on a negative ledger.\n           That is the owner's chosen policy. Edit nothing.")
    else:
        print(f"    state: ${fmt(p['to_go_usd'])} of true equity left before the zero crossing (no action "
              f"attached)")
    print("\n  The balance moves no trade, no bar and no era: era DD, R/trade and the")
    print("  registered PASS/REVERT thresholds are all computed from the ledger's P&L,")
    print("  never from the starting balance. Judge the strategy in R, never in %.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".", help="repo/deploy root holding trades.csv + status.json")
    ap.add_argument("--cost", type=float, default=0.20,
                    help="cost per side in $ (default 0.20 = the registered $0.40 round trip; "
                         "0.275 is the measured spread-only figure)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 once true equity is at/below $0 (an accounting alert; the owner's "
                         "2026-10-30 decision is that nothing is ever rebaselined)")
    a = ap.parse_args(argv)
    if a.cost < 0:
        raise SystemExit("--cost must be >= 0")
    d = build(a.root, a.cost)
    if a.json:
        print(json.dumps(d, indent=2, default=str))
    else:
        report(d)
    if a.strict and d["policy"]["at_or_below_zero"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
