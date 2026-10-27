#!/usr/bin/env python3
"""
journal.py — self-journaling BUY/SELL ledger with indicator-aware success rates.

WHAT THIS IS
    The bot's own diary, read from the files it already writes. Every row in
    trades.csv is a BUY or SELL the engine took; skipped_trades.csv is every
    gate-blocked attempt; forward_test_log.csv is the indicator tape at entry.
    This tool joins them, enriches each trade with the contemporaneous tape
    (RSI, ATR, EMA gap/distance, wick, slope, level geometry, session, plus a
    lab of *additional* indicators computed from the log), and prints the
    success rate sliced every way the repo has learned to distrust pooling.

    Display-only: never writes trades.csv, never imports engine.py, stdlib +
    math only. The ledger stays the source of truth; this is a lens.

WHAT THIS IS NOT
    Not a signal, not a gate, not a sizing rule. No number here may enter
    engine.py/trade_filter.py without a pre-registered bar (HANDOFF §11). The
    "additional indicators" below are measured on this tape and shown with
    their n, CI and p-value — most will be noise, as the existing calibration
    already warns.

WHY A JOURNAL
    The owner asked for a self-journal: "log every BUY/SELL and see its success
    rate, plus check if more indicators would help". The existing tools each
    answer part of that (win_rate_report = baseline, analyze_losers = path,
    momentum_regime = side split, signal_outlook = forward walk), but none
    gives a single buy-vs-sell diary with indicator context. This does.

    Success = decisive outcome: TP wins / (TP+SL). BE and TIME are neutral
    buckets (booked in $/trade, excluded from WR) per HANDOFF §8. Costs are
    applied only when --cost is given; default is gross as the ledger books it.

USAGE
    python3 tools/journal.py                         # gross, struct-stop era focus
    python3 tools/journal.py --cost 0.40             # net of assumed $0.40 round trip
    python3 tools/journal.py --era all               # whole book
    python3 tools/journal.py --era structstop        # live rule only (>=2026-10-06 03:00)
    python3 tools/journal.py --era 075               # 0.75R era (>=2026-09-15 06:00)
    python3 tools/journal.py --era clear15           # the structstop1.5 window (not started -> it says so)
    python3 tools/journal.py --json /tmp/j.json      # machine-readable for dashboard
    python3 tools/journal.py --csv /tmp/journal.csv  # enriched trade-by-trade export

    --era choices: structstop (default, the live rule), 075, maxhold, all, clear15
    --cost is round-trip $/trade charged on EVERY trade incl. scratches (assumed, not measured)
    Exit code 0 always (report, not gate).

DESIGN NOTES
    * Risk per trade is recovered from the REWARD leg: |TP-Entry|/1.5 (HANDOFF §8),
      never from ATR_At_Entry, which understates level-bound trades since 2026-10-05.
    * Indicator lab (BB, MACD, Stoch, ADX, CCI, Donchian, ATR percentile) is
      computed from log closes/highs/lows only, with the same EMA/RSI/ATR
      definitions as engine.py/strategy_lab.py (simple means, not Wilder — the
      repo's convention since 2026-10-05). Small n buckets are flagged, not hidden.
    * Fisher exact p-values are two-sided; Wilson 95% CIs use z=1.96 (repo convention).
    * The file owns no schedule: run it after any data drop or wire it into the
      dashboard Journal tab (pressure.py journal_read() reuses this logic).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from collections import defaultdict, Counter
from datetime import datetime, timedelta

ROOT_DEFAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DEFAULT)

# ── era boundaries ────────────────────────────────────────────────────────
CUTOVERS = {
    "structstop": datetime(2026, 10, 6, 3, 0),
    "075":        datetime(2026, 9, 15, 6, 0),
    "maxhold":    datetime(2026, 9, 21, 6, 0),
    "all":        datetime(2020, 1, 1),
    # the registered structstop1.5 window (docs/PREREG-2026-10-26-structstop1.5.md). Its boundary
    # is the host DEPLOY time, not the registration date, so it is resolved at run time and is
    # None until A2 ships: --era clear15 then reports "not started" instead of quietly falling
    # back to the 0.5 ATR era and mixing the two windows.
    "clear15":    None,
}
DEFAULT_ERA = "structstop"


def resolve_cutover(era):
    """(label, datetime|None) for an --era name; None = that window has not started."""
    if era != "clear15":
        return era, CUTOVERS[era]
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import strategy_lab as _sl          # canonical deploy times, same import the other tools use
    except Exception:                       # noqa: BLE001 - a report must not die on an import
        return era, None
    return _sl.CLEAR15_ERA, _sl.CLEAR15_CUTOVER
RR_TARGET = 1.5
ATR_SL_MULT = 2.0

# ── helpers ───────────────────────────────────────────────────────────────
def _f(v):
    try:
        x = float(str(v).strip().rstrip("%"))
        return x if math.isfinite(x) else None
    except: return None

def _ts(s):
    if not s: return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try: return datetime.strptime(str(s).strip(), fmt)
        except: continue
    return None

def wilson(w, n, z=1.96):
    if n == 0: return (0.0, 0.0)
    p = w/n; d = 1+z*z/n
    c = (p+z*z/(2*n))/d
    h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))/d
    return (max(0,c-h)*100, min(1,c+h)*100)

def fisher_p(a_w, a_l, b_w, b_l):
    """Two-sided Fisher exact via log-factorial (no scipy)."""
    try:
        import math as _m
        tot = a_w+a_l+b_w+b_l
        if tot == 0 or (a_w+a_l)==0 or (b_w+b_l)==0: return 1.0
        # Use hypergeometric tail; for n up to ~700 exact is fine.
        from math import comb
        # Build contingency table margins
        n = a_w+a_l; K = a_w+b_w; N = tot
        # Probability of observing k = a_w under null
        def hg(k): return comb(K,k)*comb(N-K, n-k)/comb(N,n) if 0<=k<=K and 0<=n-k<=N-K else 0.0
        p_obs = hg(a_w)
        p = 0.0
        for k in range(max(0, n-(N-K)), min(n,K)+1):
            pk = hg(k)
            if pk <= p_obs+1e-12: p += pk
        return min(1.0, p)
    except: return 1.0

# ── data load ─────────────────────────────────────────────────────────────
def load_trades(path):
    rows=[]
    if not os.path.isfile(path): return rows
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            try:
                rows.append({
                    "num": int(r["Trade_Num"]), "side": r["Trade_Type"].strip(),
                    "et": _ts(r["Entry_Time"]), "xt": _ts(r["Exit_Time"]),
                    "entry": _f(r["Entry_Price"]), "sl": _f(r["Stop_Loss"]), "tp": _f(r["Take_Profit"]),
                    "xp": _f(r["Exit_Price"]), "reason": (r["Exit_Reason"] or "").strip().upper(),
                    "pnl": _f(r["Profit"]) or 0.0, "bal": _f(r["Balance_After"]),
                    "rsi": _f(r["RSI_At_Entry"]), "atr": _f(r["ATR_At_Entry"]),
                    "wick": _f(r["Wick_Ratio_At_Entry"]), "ema50": _f(r["EMA50_At_Entry"]), "ema200": _f(r["EMA200_At_Entry"]),
                    "raw": r,
                })
            except: continue
    return rows

def load_log(path):
    rows=[]
    if not os.path.isfile(path): return rows
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            ts=_ts(r.get("Timestamp")); 
            if not ts: continue
            rows.append({"ts": ts, "o": _f(r.get("Open")), "h": _f(r.get("High")), "l": _f(r.get("Low")), "c": _f(r.get("Close")),
                         "atr": _f(r.get("ATR")), "rsi": _f(r.get("RSI")), "ema50": _f(r.get("EMA_50")), "ema200": _f(r.get("EMA_200")),
                         "vol": _f(r.get("Volume")), "wick": _f(r.get("Wick_Ratio")), "raw": r})
    rows.sort(key=lambda x: x["ts"])
    return rows

def load_skipped(path):
    rows=[]
    if not os.path.isfile(path): return rows
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append({"ts": _ts(r.get("Timestamp")), "reason": (r.get("Reason") or "").strip(), "price": _f(r.get("Price")), "atr": _f(r.get("ATR")), "raw": r})
    return rows

# ── enrichment: join trades to log + derived fields ──────────────────────
def enrich_trades(trades, log_rows, cost=0.0):
    # index log by minute for fast join
    log_by_min = {r["ts"].replace(second=0,microsecond=0): r for r in log_rows}
    ts_list = sorted(log_by_min)
    # also sorted list for additional indicator computation (need series)
    closes = [r["c"] for r in log_rows if r["c"] is not None]
    # Precompute additional indicators over log series (for lab)
    extra = compute_extra_indicators(log_rows)  # dict ts-> {bb_pctb, macd_hist, stoch_k, adx, cci, donchian_pos, atr_pctile, vol_ratio}
    out=[]
    for t in trades:
        # risk from reward leg (HANDOFF §8)
        risk = None
        if t["entry"] is not None and t["tp"] is not None:
            risk = abs(t["tp"]-t["entry"])/RR_TARGET
            if not (risk and risk>0 and math.isfinite(risk)):
                risk = None
        if risk is None and t["atr"] is not None:
            risk = ATR_SL_MULT * t["atr"]
        t["risk"] = risk
        t["R"] = (t["pnl"]/risk) if risk else None
        t["costed_pnl"] = t["pnl"] - cost
        t["costed_R"] = (t["costed_pnl"]/risk) if risk else None
        # join to log at entry (nearest minute within 2 min)
        et = t["et"]
        join=None
        if et:
            for delta in (0,1,-1,2,-2):
                k=(et+timedelta(minutes=delta)).replace(second=0,microsecond=0)
                if k in log_by_min: join=log_by_min[k]; break
        if join:
            t["log_at_entry"]=join
            # derived
            ema50=join.get("ema50"); ema200=join.get("ema200"); atr=join.get("atr"); c=join.get("c")
            t["ema_gap"]= (ema50-ema200) if (ema50 and ema200) else None
            t["ema_dist"]= (t["entry"]-ema50) if (t["entry"] and ema50) else None
            t["ema_dist_atr"]= (t["ema_dist"]/atr) if (t["ema_dist"] is not None and atr) else None
            t["rsi_at_entry_log"]= join.get("rsi")
            # level distance: use raw floor/ceiling if available (not in log extract, but approximate via entry vs log floor)
            # approximate: we don't have floor in this simplified join; use ema_dist as proxy
            t["hour"]= et.hour if et else None
            t["dow"]= et.weekday() if et else None  # 0=Mon
            # extra indicators at entry
            ex = extra.get(join["ts"])
            if ex: t.update(ex)
        else:
            t["log_at_entry"]=None
            t["ema_gap"]=None; t["ema_dist"]=None; t["ema_dist_atr"]=None; t["hour"]= et.hour if et else None; t["dow"]= et.weekday() if et else None
            # still set extra to None
            for k in ("bb_pctb","macd_hist","macd_sign","stoch_k","adx","cci","donchian_pos","atr_pctile","vol_ratio","bb_width_atr","ema_slope_atr","trend_strength_atr"):
                t.setdefault(k, None)
        # session label
        h=t.get("hour")
        if h is not None:
            if 7 <= h < 12: t["session"]="London"
            elif 12 <= h < 16: t["session"]="NY open"
            elif 16 <= h < 22: t["session"]="NY/Late"
            elif 22 <= h or h < 2: t["session"]="Rollover"
            else: t["session"]="Asia"
        else: t["session"]=None
        # streak: will be filled in order pass below
        out.append(t)
    # streak in chronological order
    out.sort(key=lambda x: x["et"] or datetime.min)
    streak=0
    for t in out:
        t["streak_before"]=streak
        if t["reason"]=="SL": streak+=1
        elif t["reason"]=="TP": streak=0
        # BE/TIME do not break streak per trade_filter semantics (BE is transparent)
    return out

def compute_extra_indicators(log_rows):
    """Compute BB, MACD, Stoch, ADX, CCI, Donchian, ATR percentile, EMA slope etc. per log bar."""
    out={}
    if len(log_rows)<30: return out
    # Build arrays in time order (already sorted)
    bars = [r for r in log_rows if r["c"] is not None and r["h"] is not None and r["l"] is not None]
    n=len(bars)
    closes=[b["c"] for b in bars]; highs=[b["h"] for b in bars]; lows=[b["l"] for b in bars]
    atrs=[b["atr"] for b in bars]
    # EMA helper
    def ema(series, period):
        res=[None]*len(series)
        if len(series)<period: return res
        sma=sum(series[:period])/period
        res[period-1]=sma
        k=2/(period+1)
        for i in range(period, len(series)):
            res[i]=series[i]*k + res[i-1]*(1-k)
        return res
    ema12=ema(closes,12); ema26=ema(closes,26)
    macd_line=[ (a-b) if (a is not None and b is not None) else None for a,b in zip(ema12,ema26)]
    macd_signal=ema([x if x is not None else 0 for x in macd_line],9)  # rough; zeros for None won't affect much after warmup
    # For proper signal, we need to handle Nones: recompute only on valid macd
    # Simpler: compute signal over macd_line where available
    # We'll do a second pass that skips Nones properly
    sig2=[None]*n; buf=[]
    for i, v in enumerate(macd_line):
        if v is None: sig2[i]=None; continue
        buf.append(v)
        if len(buf)>=9:
            if sig2[i-1] is None and len(buf)==9:
                sig2[i]=sum(buf[-9:])/9
            elif sig2[i-1] is not None:
                k=2/(9+1); sig2[i]=v*k+sig2[i-1]*(1-k)
    # BB 20,2
    bb_pctb=[None]*n; bb_width_atr=[None]*n
    for i in range(n):
        if i<19: continue
        win=closes[i-19:i+1]
        sma=sum(win)/20
        var=sum((x-sma)**2 for x in win)/20
        sd=math.sqrt(var) if var>0 else 0
        upper=sma+2*sd; lower=sma-2*sd
        width=upper-lower
        c=closes[i]
        bb_pctb[i]= (c-lower)/width if width>1e-9 else 0.5
        atr=atrs[i]
        bb_width_atr[i]= width/atr if atr and atr>0 else None
    # Stochastic %K 14, %D 3 (we report %K)
    stoch_k=[None]*n
    for i in range(n):
        if i<13: continue
        hh=max(highs[i-13:i+1]); ll=min(lows[i-13:i+1])
        rng=hh-ll
        stoch_k[i]= 100*(closes[i]-ll)/rng if rng>1e-9 else 50.0
    # ADX 14 simplified (Wilder not used by repo; use simple variant consistent with ATR calc)
    # We'll compute +DM, -DM, TR, then DX, then ADX as SMA
    plus_dm=[0]*n; minus_dm=[0]*n; tr=[0]*n
    for i in range(1,n):
        up=highs[i]-highs[i-1]; dn=lows[i-1]-lows[i]
        plus_dm[i]= up if (up>dn and up>0) else 0
        minus_dm[i]= dn if (dn>up and dn>0) else 0
        tr[i]= max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
    # Wilder smoothing would be ideal but simple SMA is repo-consistent (ATR uses simple mean)
    adx=[None]*n
    # Need +DI, -DI, DX
    pdi=[None]*n; mdi=[None]*n; dx=[None]*n
    for i in range(n):
        if i<14: continue
        # avg over 14
        atr14 = sum(tr[i-13:i+1])/14 if any(tr[i-13:i+1]) else None
        pdm14 = sum(plus_dm[i-13:i+1])/14
        mdm14 = sum(minus_dm[i-13:i+1])/14
        if not atr14 or atr14==0: continue
        pdi[i]= 100*pdm14/atr14; mdi[i]= 100*mdm14/atr14
        s=pdi[i]+mdi[i]
        dx[i]= 100*abs(pdi[i]-mdi[i])/s if s>0 else 0
    for i in range(n):
        if i<27: continue  # need 14 DX for ADX
        win=[dx[j] for j in range(i-13,i+1) if dx[j] is not None]
        if len(win)==14: adx[i]=sum(win)/14
    # CCI 20
    cci=[None]*n
    for i in range(n):
        if i<19: continue
        tps=[(highs[j]+lows[j]+closes[j])/3 for j in range(i-19,i+1)]
        sma=sum(tps)/20
        md=sum(abs(x-sma) for x in tps)/20
        cci[i]= (tps[-1]-sma)/(0.015*md) if md>1e-9 else 0
    # Donchian 20 position
    don_pos=[None]*n
    for i in range(n):
        if i<20: continue
        hh=max(highs[i-20:i]); ll=min(lows[i-20:i])
        rng=hh-ll
        don_pos[i]= (closes[i]-ll)/rng if rng>1e-9 else 0.5
    # ATR percentile (vs last 100)
    atr_pctile=[None]*n
    for i in range(n):
        atr=atrs[i]
        if atr is None: continue
        win=[a for a in atrs[max(0,i-100):i] if a is not None]
        if len(win)<20: continue
        # percentile rank
        cnt=sum(1 for x in win if x <= atr)
        atr_pctile[i]= 100*cnt/len(win)
    # EMA slope in ATR units
    ema50_vals=[b.get("ema50") for b in bars]
    slope_atr=[None]*n
    trend_strength_atr=[None]*n
    for i in range(n):
        e50=ema50_vals[i]; e200=bars[i].get("ema200"); atr=atrs[i]
        if e50 and e200 and atr and atr>0:
            trend_strength_atr[i]=(e50-e200)/atr
        if i>=30:
            prev=ema50_vals[i-30]
            if e50 and prev and atr and atr>0:
                slope_atr[i]=(e50-prev)/atr
    # Volume ratio vs MA (if available)
    vol_ratio=[None]*n
    for i in range(n):
        v=bars[i].get("vol")
        if v is None: continue
        win=[bars[j].get("vol") for j in range(max(0,i-20),i) if bars[j].get("vol") is not None]
        if win:
            ma=sum(win)/len(win)
            vol_ratio[i]= v/ma if ma>0 else None
    # Collect per timestamp
    for i,b in enumerate(bars):
        ts=b["ts"]
        hist=None; sign=None
        if macd_line[i] is not None and sig2[i] is not None:
            hist=macd_line[i]-sig2[i]
            sign= "bull" if hist>0 else ("bear" if hist<0 else "flat")
        out[ts]={
            "bb_pctb": bb_pctb[i],
            "bb_width_atr": bb_width_atr[i],
            "macd_hist": hist,
            "macd_sign": sign,
            "stoch_k": stoch_k[i],
            "adx": adx[i],
            "cci": cci[i],
            "donchian_pos": don_pos[i],
            "atr_pctile": atr_pctile[i],
            "vol_ratio": vol_ratio[i],
            "ema_slope_atr": slope_atr[i],
            "trend_strength_atr": trend_strength_atr[i],
        }
    return out

# ── stats helpers ─────────────────────────────────────────────────────────
def bucket_stats(trades, cost=0.0):
    w=sum(1 for t in trades if t["reason"]=="TP")
    l=sum(1 for t in trades if t["reason"]=="SL")
    be=sum(1 for t in trades if t["reason"]=="BE")
    tm=sum(1 for t in trades if t["reason"]=="TIME")
    n=len(trades)
    dec=w+l
    wr= (100*w/dec) if dec else 0.0
    lb, ub = wilson(w, dec)
    pnl = sum(t["pnl"] for t in trades) - cost*n if n else 0.0
    per = pnl/n if n else 0.0
    # R stats
    rs=[t["R"] for t in trades if t["R"] is not None and t["reason"] in ("TP","SL")]
    # costed R
    crs=[t["costed_R"] for t in trades if t["costed_R"] is not None and t["reason"] in ("TP","SL")]
    avg_r = sum(rs)/len(rs) if rs else None
    avg_cr = sum(crs)/len(crs) if crs else None
    # 1R median risk
    risks=[t["risk"] for t in trades if t["risk"]]
    avg_risk = sum(risks)/len(risks) if risks else None
    return {"n":n,"w":w,"l":l,"be":be,"tm":tm,"dec":dec,"wr":wr,"lb":lb,"ub":ub,"pnl":pnl,"per":per,"avg_r":avg_r,"avg_cr":avg_cr,"avg_risk":avg_risk}

def print_bucket_row(label, st, width=34, show_cost=False):
    dec=st["dec"]; n=st["n"]
    if n==0:
        print(f"  {label:{width}s} n=  0  --")
        return
    wr_str = f"{st['wr']:5.1f}% dec [{st['lb']:4.1f},{st['ub']:4.1f}]" if dec else "  no decisive "
    res = f"{st['w']:2d}W/{st['l']:2d}L/{st['be']:2d}BE" + (f"/{st['tm']}T" if st["tm"] else "")
    pnl_label = "net" if show_cost else "P/L"
    per = st["per"]
    print(f"  {label:{width}s} n={n:3d}  {res}  {wr_str}  {pnl_label} {st['pnl']:+7.2f}  /trade {per:+.3f}" + (f"  avgR {st['avg_r']:+.3f}" if st["avg_r"] is not None else ""))

# ── main report ───────────────────────────────────────────────────────────
def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".", help="dir holding trades.csv / forward_test_log.csv")
    ap.add_argument("--era", default=DEFAULT_ERA, choices=sorted(CUTOVERS), help="sample era (default: structstop, the live rule)")
    ap.add_argument("--cost", type=float, default=0.0, help="assumed round-trip cost $/trade charged on every trade incl. scratches (default 0 = gross)")
    ap.add_argument("--json", dest="json_out", default=None, help="write JSON to this path")
    ap.add_argument("--csv", dest="csv_out", default=None, help="write enriched journal CSV to this path")
    args=ap.parse_args(argv)

    root=os.path.abspath(args.root)
    trades_path=os.path.join(root,"trades.csv")
    log_path=os.path.join(root,"forward_test_log.csv")
    skip_path=os.path.join(root,"skipped_trades.csv")
    status_path=os.path.join(root,"status.json")

    trades=load_trades(trades_path)
    log_rows=load_log(log_path)
    skipped=load_skipped(skip_path)
    era_label, cutover = resolve_cutover(args.era)
    if cutover is None:
        print(f"Journal — `{args.era}` window has NOT STARTED: no deploy time is recorded, and a "
              f"pre-deploy trade may never be counted into it. Set strategy_lab.CLEAR15_CUTOVER from "
              f"the host's `autosync: merge upstream` commit time after the A2 deploy "
              f"(docs/PREREG-2026-10-26-structstop1.5.md). Nothing to report — exiting 0.")
        return 0

    # filter era
    era_trades=[t for t in trades if (t["et"] or datetime.min) >= cutover]
    all_trades=trades  # for comparison
    enriched_all=enrich_trades(all_trades, log_rows, cost=args.cost)
    enriched=enrich_trades(era_trades, log_rows, cost=args.cost)
    # era-enriched subset for slicing
    enriched_all_era=[t for t in enriched_all if (t["et"] or datetime.min) >= cutover]

    cost_tag = f" (cost ${args.cost:.2f}/trade)" if args.cost else " (gross)"
    print(f"Journal — self-journaling BUY/SELL with success rates  ({len(trades)} closed trades, {len(log_rows)} log bars)")
    print(f"Era: {args.era} = {era_label}  |  cutover {cutover}  |  n_era={len(era_trades)}  n_all={len(trades)}{cost_tag}")
    if log_rows: print(f"Log: {log_rows[0]['ts']} -> {log_rows[-1]['ts']}  |  skipped rows {len(skipped)}")
    status=None
    if os.path.isfile(status_path):
        try:
            with open(status_path) as f: status=json.load(f)
            print(f"Status: {'open '+status.get('trade_type','?')+' #'+str(status.get('current_trade_num','?'))+' @ '+str(status.get('entry_price','?')) if status.get('trade_active') else 'no open trade'}  equity ${status.get('equity','?')}  {status.get('last_update','')}")
        except: pass
    print("Display-only: no file is written except --json/--csv. No engine gate is touched.")
    print("Success = TP/(TP+SL) decisive; BE/TIME neutral; R = P/L / risk where risk=|TP-Entry|/1.5 (HANDOFF §8).")
    print()

    # 1 Baseline
    print("== 1. BASELINE — overall success ==")
    print(f"  -- All time (n={len(trades)}) --")
    print_bucket_row("all trades", bucket_stats(enriched_all, cost=args.cost), show_cost=bool(args.cost))
    if args.era != "all":
        print(f"  -- Era {args.era} (n={len(era_trades)}) --")
        print_bucket_row(f"era {args.era}", bucket_stats(enriched, cost=args.cost), show_cost=bool(args.cost))
    # side
    for side in ("BUY","SELL"):
        st=bucket_stats([t for t in enriched_all_era if t["side"]==side], cost=args.cost)
        print_bucket_row(f"{side} ({args.era})", st, show_cost=bool(args.cost))
    # overall side p-value
    buy_w=sum(1 for t in enriched_all_era if t["side"]=="BUY" and t["reason"]=="TP"); buy_l=sum(1 for t in enriched_all_era if t["side"]=="BUY" and t["reason"]=="SL")
    sell_w=sum(1 for t in enriched_all_era if t["side"]=="SELL" and t["reason"]=="TP"); sell_l=sum(1 for t in enriched_all_era if t["side"]=="SELL" and t["reason"]=="SL")
    p=fisher_p(buy_w,buy_l,sell_w,sell_l)
    print(f"  BUY vs SELL Fisher p={p:.4f}  (SELL currently {bucket_stats([t for t in enriched_all_era if t['side']=='SELL'], cost=args.cost)['wr']:.1f}% vs BUY {bucket_stats([t for t in enriched_all_era if t['side']=='BUY'], cost=args.cost)['wr']:.1f}%)")
    if args.cost:
        print(f"  net P/L at ${args.cost:.2f} round trip: ${bucket_stats(enriched_all_era, cost=args.cost)['pnl']:+.2f}  ({bucket_stats(enriched_all_era, cost=args.cost)['per']:+.3f}/trade)")
    print()
    # era table
    print("== 2. ERAS — did the rule change help? ==")
    for era in ("structstop","075","maxhold","all"):
        co=CUTOVERS[era]
        ts=[t for t in enriched_all if (t["et"] or datetime.min) >= co]
        st=bucket_stats(ts, cost=args.cost)
        wflag=" <- live rule" if era=="structstop" else ""
        print_bucket_row(f"{era:12s} (>= {co.date()})", st, show_cost=bool(args.cost))
        if wflag: print(f"    {wflag}")
    print()

    # 3 Time slices
    print("== 3. WHEN — hour, session, weekday ==")
    # hour
    for h in range(24):
        ts=[t for t in enriched_all_era if t.get("hour")==h]
        if not ts: continue
        st=bucket_stats(ts, cost=args.cost)
        # only show hours with n>=5 to avoid noise, but show all with hint
        if st["n"]>=8:
            print_bucket_row(f"{h:02d}:00 UTC", st, show_cost=bool(args.cost))
    print("  -- sessions (UTC) --")
    for sess in ("Asia","London","NY open","NY/Late","Rollover"):
        ts=[t for t in enriched_all_era if t.get("session")==sess]
        if not ts: continue
        st=bucket_stats(ts, cost=args.cost)
        print_bucket_row(sess, st, show_cost=bool(args.cost))
    print("  -- weekday (0=Mon) --")
    for d in range(7):
        ts=[t for t in enriched_all_era if t.get("dow")==d]
        if not ts: continue
        st=bucket_stats(ts, cost=args.cost)
        names=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
        print_bucket_row(names[d], st, show_cost=bool(args.cost))
    print()

    # 4 Entry-indicator buckets (native funnel fields)
    print("== 4. ENTRY TAPE — RSI / ATR / wick / EMA geometry ==")
    # RSI
    print("  RSI at entry (ledger field):")
    for lo,hi in [(30,45),(45,55),(55,62),(62,70)]:
        ts=[t for t in enriched_all_era if t["rsi"] is not None and lo <= t["rsi"] < hi]
        st=bucket_stats(ts, cost=args.cost)
        print_bucket_row(f"  RSI {lo:2d}-{hi:2d}", st, show_cost=bool(args.cost))
    # ATR
    print("  ATR at entry:")
    for lo,hi in [(1.0,1.2),(1.2,1.4),(1.4,1.7),(1.7,2.0),(2.0,99)]:
        ts=[t for t in enriched_all_era if t["atr"] is not None and lo <= t["atr"] < hi]
        if not ts: continue
        st=bucket_stats(ts, cost=args.cost)
        print_bucket_row(f"  ATR {lo:.1f}-{hi if hi<90 else 'up':3}", st, show_cost=bool(args.cost))
    # Wick
    print("  Wick ratio %:")
    for lo,hi in [(0,38),(38,50),(50,65),(65,100)]:
        ts=[t for t in enriched_all_era if t["wick"] is not None and lo <= t["wick"] < hi]
        if not ts: continue
        st=bucket_stats(ts, cost=args.cost)
        lab=f"  wick {lo:2d}-{hi:2d}%" + (" (below funnel)" if hi<=38 else "")
        print_bucket_row(lab, st, show_cost=bool(args.cost))
    # EMA distance
    print("  Price vs EMA50 (in ATR):")
    for lo,hi,label in [(-99,-0.5,"well below"),(-0.5,0.0,"just below"),(0.0,0.3,"near/above (funnel)"),(0.3,99,"far above")]:
        ts=[t for t in enriched_all_era if t.get("ema_dist_atr") is not None and lo <= t["ema_dist_atr"] < hi]
        if not ts: continue
        st=bucket_stats(ts, cost=args.cost)
        print_bucket_row(f"  EMA dist {label:18s}", st, show_cost=bool(args.cost))
    # EMA gap (trend strength)
    print("  EMA50-EMA200 gap (trend strength, $):")
    for lo,hi in [(0,3),(3,6),(6,10),(10,99)]:
        ts=[t for t in enriched_all_era if t.get("ema_gap") is not None and lo <= abs(t["ema_gap"]) < hi]
        if not ts: continue
        st=bucket_stats(ts, cost=args.cost)
        print_bucket_row(f"  gap {lo:2.0f}-{hi if hi<90 else 'up':3} $", st, show_cost=bool(args.cost))
    # Streak
    print("  Streak before entry (consecutive SLs):")
    for s in (0,1,2):
        ts=[t for t in enriched_all_era if t.get("streak_before")==s]
        if not ts: continue
        st=bucket_stats(ts, cost=args.cost)
        print_bucket_row(f"  streak {s}", st, show_cost=bool(args.cost))
    ts=[t for t in enriched_all_era if (t.get("streak_before") or 0) >=3]
    if ts: print_bucket_row("  streak 3+", bucket_stats(ts, cost=args.cost), show_cost=bool(args.cost))
    print()

    # 5 Additional indicator lab (the "what more could we add?" answer)
    print("== 5. INDICATOR LAB — extra indicators, measured the same way ==")
    print("  Each row is a bucket of that indicator AT ENTRY. Fisher p compares best vs worst bucket;")
    print("  nothing below is a gate — a 5 pp gap needs n>=25 and side-split confirmation (HANDOFF §8).")
    def lab_section(title, key, buckets, fmt="{:.1f}"):
        print(f"  {title}:")
        best=None; worst=None
        rows=[]
        for lo,hi,label in buckets:
            ts=[t for t in enriched_all_era if t.get(key) is not None and lo <= t[key] < hi]
            if not ts: continue
            st=bucket_stats(ts, cost=args.cost)
            rows.append((label, st, ts))
            print_bucket_row(f"    {label}", st, width=28, show_cost=bool(args.cost))
            if best is None or st["wr"]>best["wr"]: best=st
            if worst is None or st["wr"]<worst["wr"]: worst=st
        if best and worst and best["dec"]>=5 and worst["dec"]>=5:
            # approximate p via best vs worst buckets' W/L
            # find corresponding rows
            # we already have counts in best/worst
            p=fisher_p(best["w"],best["l"], worst["w"],worst["l"])
            print(f"      best {best['wr']:.1f}% vs worst {worst['wr']:.1f}%  Δ{best['wr']-worst['wr']:+.1f}pp  Fisher p={p:.3f}" + ("  <- notable" if p<0.05 and abs(best['wr']-worst['wr'])>=5 else ""))

    lab_section("Bollinger %B (20,2) — position in band", "bb_pctb",
                [(0,0.2,"far lower (<0.2)"),(0.2,0.4,"lower 0.2-0.4"),(0.4,0.6,"middle 0.4-0.6"),(0.6,0.8,"upper 0.6-0.8"),(0.8,1.5,"far upper (>0.8)")])
    lab_section("MACD histogram sign + strength", "macd_hist",
                [(-99,0,"bear (hist<0)"),(0,99,"bull (hist>0)")])
    # finer MACD
    macd_buckets=[t for t in enriched_all_era if t.get("macd_hist") is not None]
    if macd_buckets:
        # tertiles
        vals=sorted(t["macd_hist"] for t in enriched_all_era if t.get("macd_hist") is not None)
        if len(vals)>=30:
            q1=vals[len(vals)//3]; q2=vals[2*len(vals)//3]
            lab_section("MACD histogram tertiles", "macd_hist", [(-99,q1,f"<{q1:.2f} (bear)"),(q1,q2,f"{q1:.2f}..{q2:.2f} (mid)"),(q2,99,f">{q2:.2f} (bull)")])
    lab_section("Stochastic %K (14) — momentum extreme", "stoch_k",
                [(0,20,"oversold <20"),(20,50,"20-50"),(50,80,"50-80"),(80,101,"overbought >80")])
    lab_section("ADX (14) — trend strength", "adx",
                [(0,15,"weak <15"),(15,25,"15-25"),(25,40,"strong 25-40"),(40,99,"very strong >40")])
    lab_section("CCI (20) — overbought/oversold", "cci",
                [(-999,-100,"<-100 oversold"),(-100,100,"-100..100 neutral"),(100,999,">100 overbought")])
    lab_section("Donchian 20 position — breakout vs mid-range", "donchian_pos",
                [(0,0.2,"near low <0.2"),(0.2,0.5,"0.2-0.5"),(0.5,0.8,"0.5-0.8"),(0.8,1.01,"near high >0.8")])
    lab_section("ATR percentile vs last 100 bars — volatility regime", "atr_pctile",
                [(0,25,"quiet <25th"),(25,50,"25-50th"),(50,75,"50-75th"),(75,101,"volatile >75th")])
    lab_section("Volume vs 20-bar MA — participation", "vol_ratio",
                [(0,0.7,"thin <0.7x"),(0.7,1.0,"0.7-1.0x"),(1.0,1.3,"1.0-1.3x"),(1.3,99,"spike >1.3x")])
    lab_section("EMA slope (30-bar, in ATR) — momentum", "ema_slope_atr",
                [(-99,-0.5,"falling <-0.5"),(-0.5,0.5,"flat -0.5..0.5"),(0.5,99,"rising >0.5")])
    lab_section("Trend strength (EMA50-EMA200 in ATR)", "trend_strength_atr",
                [(-99,-1,"bear >1 ATR"),(-1,1,"weak -1..1"),(1,99,"bull >1 ATR")])
    lab_section("BB width in ATR — squeeze vs expansion", "bb_width_atr",
                [(0,3,"squeeze <3 ATR"),(3,5,"3-5 ATR"),(5,99,">5 ATR wide")])
    print()

    # 5b Side-split check for any promising lab indicator (HANDOFF §8: within-side)
    print("== 5b. SIDE-SPLIT CHECK — does any lab gap survive BUY/SELL separately? ==")
    # Pick top candidate: BB %B middle vs extremes is often discussed; test it side-split
    for key, label in [("bb_pctb","BB %B"),("stoch_k","Stoch"),("adx","ADX"),("atr_pctile","ATR pctile")]:
        # define best bucket as middle vs extremes for BB, or trend for others — just show pooled vs side
        all_vals=[t.get(key) for t in enriched_all_era if t.get(key) is not None]
        if len(all_vals)<30: continue
        # simple median split
        med=sorted(all_vals)[len(all_vals)//2]
        lo_ts=[t for t in enriched_all_era if t.get(key) is not None and t[key] < med]
        hi_ts=[t for t in enriched_all_era if t.get(key) is not None and t[key] >= med]
        lo_st=bucket_stats(lo_ts, cost=args.cost); hi_st=bucket_stats(hi_ts, cost=args.cost)
        p=fisher_p(lo_st["w"],lo_st["l"], hi_st["w"],hi_st["l"])
        print(f"  {label} median split {med:.2f}: below n={lo_st['n']} {lo_st['wr']:.1f}% vs above n={hi_st['n']} {hi_st['wr']:.1f}%  p={p:.3f}")
        for side in ("BUY","SELL"):
            lo_s=[t for t in lo_ts if t["side"]==side]; hi_s=[t for t in hi_ts if t["side"]==side]
            if len(lo_s)<10 or len(hi_s)<10: continue
            ls=bucket_stats(lo_s, cost=args.cost); hs=bucket_stats(hi_s, cost=args.cost)
            ps=fisher_p(ls["w"],ls["l"], hs["w"],hs["l"])
            print(f"    {side}: below {ls['wr']:.1f}% (n={ls['dec']} dec) vs above {hs['wr']:.1f}%  p={ps:.3f}")
    print()

    # 6 Skipped vs taken (gate leak)
    if skipped:
        print("== 6. SKIPPED vs TAKEN — was the gate protecting you? ==")
        # skipped reasons bucketed
        buckets=defaultdict(int)
        for s in skipped:
            reason=s.get("reason") or "Other"
            low=reason.lower()
            if low.startswith("blackout"): buckets["Blackout"]+=1
            elif low.startswith("sl cooldown"): buckets["SL cooldown"]+=1
            elif low.startswith("daily loss"): buckets["Daily breaker"]+=1
            elif low.startswith("atr too low"): buckets["ATR too low"]+=1
            elif low.startswith("atr too high"): buckets["ATR too high"]+=1
            else: buckets[reason.split(":")[0][:28]]+=1
        for k,v in sorted(buckets.items(), key=lambda kv: -kv[1]):
            print(f"  {k:20s} {v:4d} blocked")
        print(f"  (taken {len(era_trades)} vs blocked {len(skipped)} in file; file covers whole history, not just era)")
        print()

    # 7 Recent form
    print("== 7. RECENT FORM — last 30 trades ==")
    recent=enriched_all_era[-30:] if len(enriched_all_era)>=10 else enriched_all_era
    if recent:
        st=bucket_stats(recent, cost=args.cost)
        print_bucket_row("last 30 in era", st, show_cost=bool(args.cost))
        # last 10
        if len(enriched_all_era)>=10:
            st10=bucket_stats(enriched_all_era[-10:], cost=args.cost)
            print_bucket_row("last 10 in era", st10, show_cost=bool(args.cost))
        # streak
        # compute last streak
        last_reason = enriched_all_era[-1]["reason"] if enriched_all_era else None
        print(f"  last outcome: {last_reason}  streak_before next: {enriched_all_era[-1].get('streak_before')}  (cooldown respects escalated 30/60m rule)")
    print()

    # 8 Recommendations (auto-generated from this data, not hardcoded)
    print("== 8. WHAT THIS JOURNAL SAYS — suggestions, not rules ==")
    # Compare buy vs sell
    buy_st=bucket_stats([t for t in enriched_all_era if t["side"]=="BUY"], cost=args.cost)
    sell_st=bucket_stats([t for t in enriched_all_era if t["side"]=="SELL"], cost=args.cost)
    if buy_st["wr"] and sell_st["wr"]:
        gap=sell_st["wr"]-buy_st["wr"]
        if abs(gap) >= 5:
            print(f"  • Side matters: SELL {sell_st['wr']:.1f}% vs BUY {buy_st['wr']:.1f}% (Δ{gap:+.1f}pp, p={p:.3f}). SELL has led in down-tape; do not add a BUY-biased indicator without side-split proof (HANDOFF §8).")
        else:
            print(f"  • Side gap is modest (SELL {sell_st['wr']:.1f}% vs BUY {buy_st['wr']:.1f}%, Δ{gap:+.1f}pp) — no strong side to favour right now.")
    # ATR
    atr_low=[t for t in enriched_all_era if t.get("atr") is not None and t["atr"]<1.2]
    atr_high=[t for t in enriched_all_era if t.get("atr") is not None and t["atr"]>=2.0]
    if atr_low and atr_high:
        ls=bucket_stats(atr_low, cost=args.cost); hs=bucket_stats(atr_high, cost=args.cost)
        if ls["n"]>=10 and hs["n"]>=10:
            print(f"  • ATR regime: low-ATR (<1.2) {ls['wr']:.1f}% vs high-ATR (≥2.0) {hs['wr']:.1f}% — high-ATR trades cost more (wider stops) and have trailed below 30% in prior eras; MAX_ATR filter already exists at 4.5, tighten only with pre-reg.")
    # RSI
    rsi_low=[t for t in enriched_all_era if t.get("rsi") is not None and t["rsi"]<45]
    rsi_hi=[t for t in enriched_all_era if t.get("rsi") is not None and t["rsi"]>=45]
    if rsi_low and rsi_hi:
        ls=bucket_stats(rsi_low, cost=args.cost); hs=bucket_stats(rsi_hi, cost=args.cost)
        if ls["n"]>=20:
            print(f"  • RSI filter (≥45): keep {hs['wr']:.1f}% (n={hs['n']}) vs skip {ls['wr']:.1f}% (n={ls['n']}) — candidate #1 from win_rate_report §6; adopt only if skip bucket n≥30, gap ≥5pp and side-split holds.")
    # Hour
    # Find best/worst hour with n>=10
    hour_stats=[]
    for h in range(24):
        ts=[t for t in enriched_all_era if t.get("hour")==h]
        if len(ts)>=10: 
            st=bucket_stats(ts, cost=args.cost); hour_stats.append((h,st))
    if hour_stats:
        hour_stats.sort(key=lambda x: x[1]["wr"])
        worst=hour_stats[0]; best=hour_stats[-1]
        print(f"  • Session timing: best hour {best[0]:02d}:00 {best[1]['wr']:.1f}% vs worst {worst[0]:02d}:00 {worst[1]['wr']:.1f}% (both n≥10) — intraday edges decay; London/NY band bleed is already a named candidate (REVIEW-2026-10-05 §5a), do not add a new session filter without isolation.")
    print(f"  • Indicator lab: all extra indicators above are display-only until they clear the same bar as any funnel change — n≥25, ≥5pp gap, same direction within BUY and within SELL, holds in an up-tape subperiod, P/L/trade not worse than -$0.10, dated REVIEW + isolation (HANDOFF §11).")
    print(f"  • Journal discipline: log every BUY/SELL with this tool (or dashboard Journal tab) before looking at the next bar's outcome; at least 100 post-era observations with costs are needed before any 'improvement' is credible.")
    print()

    # CSV export
    if args.csv_out:
        cols=["num","side","et","xt","reason","pnl","costed_pnl","risk","R","costed_R","rsi","atr","wick","ema50","ema200","hour","session","dow","ema_gap","ema_dist_atr","streak_before","bb_pctb","macd_hist","stoch_k","adx","cci","donchian_pos","atr_pctile","vol_ratio","ema_slope_atr","trend_strength_atr","bb_width_atr"]
        with open(args.csv_out,"w",newline="") as f:
            w=csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for t in enriched_all_era:
                row={}
                for c in cols:
                    v=t.get(c)
                    if isinstance(v, datetime): v=v.strftime("%Y-%m-%d %H:%M:%S")
                    row[c]=v
                row["num"]=t.get("num"); row["side"]=t.get("side"); row["et"]=t.get("et").strftime("%Y-%m-%d %H:%M:%S") if t.get("et") else None; row["xt"]=t.get("xt").strftime("%Y-%m-%d %H:%M:%S") if t.get("xt") else None; row["reason"]=t.get("reason"); row["pnl"]=t.get("pnl")
                w.writerow(row)
        print(f"Wrote enriched journal CSV: {args.csv_out}  ({len(enriched_all_era)} rows)")

    # JSON
    if args.json_out:
        payload={
            "era": args.era, "cutover": str(cutover), "cost": args.cost,
            "n_all": len(trades), "n_era": len(era_trades), "n_log": len(log_rows),
            "baseline_all": bucket_stats(enriched_all, cost=args.cost),
            "baseline_era": bucket_stats(enriched, cost=args.cost),
            "buy": bucket_stats([t for t in enriched_all_era if t["side"]=="BUY"], cost=args.cost),
            "sell": bucket_stats([t for t in enriched_all_era if t["side"]=="SELL"], cost=args.cost),
            "by_hour": {str(h): bucket_stats([t for t in enriched_all_era if t.get("hour")==h], cost=args.cost) for h in range(24) if any(t.get("hour")==h for t in enriched_all_era)},
            "by_session": {s: bucket_stats([t for t in enriched_all_era if t.get("session")==s], cost=args.cost) for s in ("Asia","London","NY open","NY/Late","Rollover")},
            "recent_30": bucket_stats(enriched_all_era[-30:], cost=args.cost) if len(enriched_all_era)>=10 else None,
            "trades": [{"num":t["num"],"side":t["side"],"et": str(t["et"]),"reason":t["reason"],"pnl":t["pnl"],"costed_pnl":t["costed_pnl"],"R":t["R"],"rsi":t.get("rsi"),"atr":t.get("atr"),"hour":t.get("hour"),"session":t.get("session")} for t in enriched_all_era[-50:]],
        }
        with open(args.json_out,"w") as f: json.dump(payload,f,indent=2,default=str)
        print(f"Wrote JSON: {args.json_out}")

    return 0

if __name__=="__main__": sys.exit(main())
