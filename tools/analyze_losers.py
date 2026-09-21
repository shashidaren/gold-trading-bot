#!/usr/bin/env python3
"""
Losing-trade analysis: replay every trade's 1-min bar path to find
why winners win and losers lose, and test counterfactual exits/filters.
Read-only: writes nothing to the CSVs.

BE-era note (ratchet live 2026-09-10 ~12:34 UTC): BE rows log the RATCHETED
stop (Stop_Loss == Entry_Price), so the original 2xATR risk geometry is
reconstructed from ATR_At_Entry wherever R-multiples are needed. BE
scratches are reported as a neutral third outcome, never lumped with losses.
"""
import csv, statistics
from datetime import datetime, timedelta

def load_trades():
    rows = []
    with open("trades.csv", newline="") as f:
        for r in csv.DictReader(f):
            side = r["Trade_Type"]
            entry = float(r["Entry_Price"])
            reason = r["Exit_Reason"]
            atr = float(r["ATR_At_Entry"])
            sl = float(r["Stop_Loss"])
            tp = float(r["Take_Profit"])
            if reason == "BE" or abs(entry - sl) < 1e-9:
                # Logged SL is the ratcheted stop (= entry). This happens on
                # BE scratches AND on winners the ratchet armed before the TP
                # printed (engine logs the live stop at exit time) - so the
                # test is geometric, not reason-based. Reconstruct the original
                # 2xATR/3xATR geometry for R math.
                if side == "BUY":
                    sl, tp = entry - 2 * atr, entry + 3 * atr
                else:
                    sl, tp = entry + 2 * atr, entry - 3 * atr
            rows.append({
                "type": side,
                "entry_t": datetime.strptime(r["Entry_Time"], "%Y-%m-%d %H:%M:%S"),
                "exit_t": datetime.strptime(r["Exit_Time"], "%Y-%m-%d %H:%M:%S"),
                "entry": entry,
                "sl": sl,
                "tp": tp,
                "exit_p": float(r["Exit_Price"]),
                "reason": reason,
                "profit": float(r["Profit"]),
                "rsi": float(r["RSI_At_Entry"]),
                "atr": atr,
                "wick": float(r["Wick_Ratio_At_Entry"].replace("%", "")),
                "ema50": float(r["EMA50_At_Entry"]),
                "ema200": float(r["EMA200_At_Entry"]),
            })
    return rows

def load_bars():
    bars = []
    with open("forward_test_log.csv", newline="") as f:
        for r in csv.DictReader(f):
            try:
                bars.append({
                    "t": datetime.strptime(r["Timestamp"], "%Y-%m-%d %H:%M:%S"),
                    "o": float(r["Open"]), "h": float(r["High"]),
                    "l": float(r["Low"]), "c": float(r["Close"]),
                })
            except (ValueError, KeyError):
                continue
    return sorted(bars, key=lambda b: b["t"])

trades = load_trades()
bars = load_bars()
print(f"Loaded {len(trades)} trades, {len(bars)} 1-min bars "
      f"({bars[0]['t']} -> {bars[-1]['t']})\n")

# ---------- 1. Baseline stats ----------
wins  = [t for t in trades if t["reason"] == "TP"]
losses = [t for t in trades if t["reason"] == "SL"]
bes   = [t for t in trades if t["reason"] == "BE"]
times = [t for t in trades if t["reason"] == "TIME"]
gross_w = sum(t["profit"] for t in wins)
gross_l = sum(t["profit"] for t in losses)
gross_t = sum(t["profit"] for t in times)
dec = wins + losses
print(f"== BASELINE ==  Trades: {len(trades)}  W: {len(wins)}  L: {len(losses)}  "
      f"BE: {len(bes)}  TIME: {len(times)}")
print(f"Win rate: {len(wins)/len(dec)*100:.1f}% decisive ({len(wins)}/{len(dec)}), "
      f"{len(wins)/len(trades)*100:.1f}% all-in   Net P/L: {gross_w+gross_l+gross_t:+.2f} "
      f"(+{gross_w:.2f} / {gross_l:.2f} / TIME {gross_t:+.2f})")
avg_rr = statistics.mean((t['tp']-t['entry'])/(t['entry']-t['sl']) if t['type']=='BUY'
                         else (t['entry']-t['tp'])/(t['sl']-t['entry']) for t in trades)
avg_risk = statistics.mean(abs(t['entry']-t['sl']) for t in trades)
avg_reward = statistics.mean(abs(t['tp']-t['entry']) for t in trades)
print(f"Avg risk/trade: ${avg_risk:.2f}  Avg TP distance: ${avg_reward:.2f}  "
      f"Avg planned R:R = 1:{avg_rr:.2f}")
print(f"Breakeven win rate at 1:1.5 R:R = 40.0% (decisive)  -> actual {len(wins)/len(dec)*100:.1f}% is way below\n")

# ---------- 2. Replay trades on 1-min bars: MAE / MFE ----------
def replay(t):
    """Return dict with MAE/MFE in $R and runup stats using 1-min bars."""
    path = [b for b in bars if t["entry_t"] <= b["t"] <= t["exit_t"]]
    if not path:
        return None
    if t["type"] == "BUY":
        mfe = max(b["h"] for b in path) - t["entry"]   # best favorable
        mae = t["entry"] - min(b["l"] for b in path)   # worst adverse
    else:
        mfe = t["entry"] - min(b["l"] for b in path)
        mae = max(b["h"] for b in path) - t["entry"]
    risk = abs(t["entry"] - t["sl"])
    return {"mfe": mfe, "mae": mae, "mfe_R": mfe / risk, "mae_R": mae / risk,
            "n_bars": len(path),
            "dur_min": (t["exit_t"] - t["entry_t"]).total_seconds() / 60}

replayed = 0
for t in trades:
    r = replay(t)
    if r:
        t.update(r); replayed += 1
print(f"Replayed {replayed}/{len(trades)} trades against 1-min bars "
      f"(trades outside log range have no bars)\n")

# ---------- 3. Losers that were winners first (the key insight) ----------
print("== LOSERS THAT WERE IN PROFIT FIRST ==")
thresh = [0.25, 0.33, 0.5, 0.66, 0.75, 1.0]
los_re = [t for t in losses if "mfe_R" in t]
for th in thresh:
    n = sum(1 for t in los_re if t["mfe_R"] >= th)
    print(f"  Losers that reached +{th:.2f}R before dying: {n}/{len(los_re)} "
          f"({n/len(los_re)*100:.0f}% of losers)")
print()
# Winners' MAE = how much heat winners take
win_re = [t for t in wins if "mfe_R" in t]
be_re = [t for t in bes if "mfe_R" in t]
tm_re = [t for t in times if "mfe_R" in t]
if win_re:
    print(f"  Winners: avg MAE {statistics.mean(t['mae_R'] for t in win_re):.2f}R "
          f"| avg MFE {statistics.mean(t['mfe_R'] for t in win_re):.2f}R")
if los_re:
    print(f"  Losers : avg MAE {statistics.mean(t['mae_R'] for t in los_re):.2f}R "
          f"| avg MFE {statistics.mean(t['mfe_R'] for t in los_re):.2f}R  "
          f"<- losers DO move our way first\n")
if be_re:
    print(f"  BE     : avg MAE {statistics.mean(t['mae_R'] for t in be_re):.2f}R "
          f"| avg MFE {statistics.mean(t['mfe_R'] for t in be_re):.2f}R  "
          f"<- scratches arm (+0.30R) then return to entry\n")
if tm_re:
    print(f"  TIME   : avg MAE {statistics.mean(t['mae_R'] for t in tm_re):.2f}R "
          f"| avg MFE {statistics.mean(t['mfe_R'] for t in tm_re):.2f}R  "
          f"<- held the full stop window without a touch\n")

# ---------- 4. Exit geometry: measured elsewhere, on purpose ----------
# A naive replay here (score each trade by its max favourable excursion inside
# the *actual* exit window) produced confident nonsense on BE-era data: it
# reported "TP 1.50R -> 0.6% win rate" against a real 19.4%, because BE
# scratches died ~2 min after entry and a looser exit can never be judged
# inside the window the old exit left open. Sequence-aware replay with an
# explicit walk horizon is the honest tool for that question.
print("== COUNTERFACTUAL EXITS ==")
print("  not here - use tools/pathwalk_sims.py (sequence-aware, SL-first,")
print("  extended-horizon rows) or the 5b/5c grid in tools/win_rate_report.py.")
print()

# ---------- 5. Feature comparison ----------
print("== ENTRY FEATURES: winners vs losers vs BE vs TIME ==")
def feat(name, fn):
    ws = [fn(t) for t in wins]; ls = [fn(t) for t in losses]; bs = [fn(t) for t in bes]
    ts_ = [fn(t) for t in times]
    line = f"  {name:28s} W avg {statistics.mean(ws):8.2f}" if ws else f"  {name:28s} W avg      n/a "
    line += f"   L avg {statistics.mean(ls):8.2f}" if ls else "   L avg      n/a"
    if bs:
        line += f"   BE avg {statistics.mean(bs):8.2f}"
    if ts_:
        line += f"   TIME avg {statistics.mean(ts_):8.2f}"
    print(line)
feat("RSI at entry", lambda t: t["rsi"])
feat("ATR at entry", lambda t: t["atr"])
feat("Wick ratio %", lambda t: t["wick"])
feat("EMA50-EMA200 gap ($ trend)", lambda t: abs(t["ema50"] - t["ema200"]))
feat("Entry dist from EMA50 ($)", lambda t: t["entry"] - t["ema50"])
feat("Risk (SL distance $)", lambda t: abs(t["entry"] - t["sl"]))
feat("Duration (min)", lambda t: (t["exit_t"] - t["entry_t"]).total_seconds()/60)
print()

# ---------- 6. Time-of-day analysis ----------
print("== TIME OF DAY (UTC) ==")
from collections import defaultdict
by_hour = defaultdict(lambda: [0, 0, 0, 0])  # W, L, BE, TIME
for t in trades:
    h = t["entry_t"].hour
    if t["reason"] == "TP": by_hour[h][0] += 1
    elif t["reason"] == "SL": by_hour[h][1] += 1
    elif t["reason"] == "BE": by_hour[h][2] += 1
    else: by_hour[h][3] += 1
for h in sorted(by_hour):
    w_, l_, b_, tm_ = by_hour[h]
    bar = "#" * w_ + "-" * l_ + "=" * b_ + "T" * tm_
    dec_h = w_ + l_
    wr = f"{w_/dec_h*100:.0f}% dec" if dec_h else "no decisive"
    extra = f" TIME{tm_}" if tm_ else ""
    print(f"  {h:02d}:00  W{w_} L{l_} BE{b_}{extra}  {bar}  ({wr})")
print()

# ---------- 7. ATR buckets ----------
print("== ATR AT ENTRY BUCKETS ==")
buckets = [(1.0, 1.2), (1.2, 1.4), (1.4, 1.7), (1.7, 2.0), (2.0, 99)]
for lo, hi in buckets:
    ts = [t for t in trades if lo <= t["atr"] < hi]
    if not ts: continue
    w_ = sum(1 for t in ts if t["reason"] == "TP")
    l_ = sum(1 for t in ts if t["reason"] == "SL")
    b_ = sum(1 for t in ts if t["reason"] == "BE")
    tm_ = sum(1 for t in ts if t["reason"] == "TIME")
    wr = f"{w_/(w_+l_)*100:.0f}% dec" if (w_ + l_) else "no decisive"
    extra = f"/{tm_}TIME" if tm_ else ""
    print(f"  ATR {lo:.1f}-{hi if hi<90 else 'up'}: {len(ts)} trades, W{w_}/L{l_}/BE{b_}{extra} ({wr})")
print()

# ---------- 8. RSI buckets ----------
print("== RSI AT ENTRY BUCKETS ==")
for lo, hi in [(30, 45), (45, 55), (55, 62), (62, 70)]:
    ts = [t for t in trades if lo <= t["rsi"] < hi]
    if not ts: continue
    w_ = sum(1 for t in ts if t["reason"] == "TP")
    l_ = sum(1 for t in ts if t["reason"] == "SL")
    b_ = sum(1 for t in ts if t["reason"] == "BE")
    tm_ = sum(1 for t in ts if t["reason"] == "TIME")
    wr = f"{w_/(w_+l_)*100:.0f}% dec" if (w_ + l_) else "no decisive"
    extra = f"/{tm_}TIME" if tm_ else ""
    print(f"  RSI {lo}-{hi}: {len(ts)} trades, W{w_}/L{l_}/BE{b_}{extra} ({wr})")
print()

# ---------- 9. Consecutive loss clusters & day analysis ----------
print("== BY DAY ==")
by_day = defaultdict(lambda: [0, 0, 0, 0, 0.0])  # W, L, BE, TIME, pnl
for t in trades:
    d = t["entry_t"].date()
    if t["reason"] == "TP": by_day[d][0] += 1
    elif t["reason"] == "SL": by_day[d][1] += 1
    elif t["reason"] == "BE": by_day[d][2] += 1
    else: by_day[d][3] += 1
    by_day[d][4] += t["profit"]
for d in sorted(by_day):
    w_, l_, b_, tm_, p = by_day[d]
    extra = f" TIME{tm_}" if tm_ else ""
    print(f"  {d}: W{w_} L{l_} BE{b_}{extra}  P/L {p:+.2f}")
print()

# ---------- 10. Filter ideas: what if we skipped trades with feature X ----------
print("== FILTER EXPERIMENTS (would skipping help?) ==")
def experiment(name, keep_fn):
    kept = [t for t in trades if keep_fn(t)]
    skipped = [t for t in trades if not keep_fn(t)]
    if not kept or not skipped: return
    def stats(ts):
        w = sum(1 for t in ts if t["reason"] == "TP")
        l = sum(1 for t in ts if t["reason"] == "SL")
        tm = sum(1 for t in ts if t["reason"] == "TIME")
        dec = w + l
        wr = w / dec * 100 if dec else 0
        extra = f", {tm}TIME" if tm else ""
        return f"{len(ts):2d} ({wr:4.0f}%W dec, {sum(t['profit'] for t in ts):+7.2f}{extra})"
    print(f"  {name:46s} keep {stats(kept)} | skipped {stats(skipped)}")

experiment("RSI <= 60 (skip momentum-chasing)", lambda t: t["rsi"] <= 60)
experiment("RSI between 40-60", lambda t: 40 <= t["rsi"] <= 60)
experiment("RSI >= 45 (skip weak-hand entries)", lambda t: t["rsi"] >= 45)
experiment("ATR <= 1.8 (skip high vol)", lambda t: t["atr"] <= 1.8)
experiment("ATR between 1.1-1.6", lambda t: 1.1 <= t["atr"] <= 1.6)
experiment("EMA gap >= 8 (strong trend only)", lambda t: abs(t["ema50"]-t["ema200"]) >= 8)
experiment("Skip 08:00-09:59 UTC (early London)", lambda t: t["entry_t"].hour not in (8, 9))
experiment("Skip 23:00-06:59 UTC (Asia/rollover)", lambda t: 7 <= t["entry_t"].hour < 23)
experiment("Entry within 0.5 ATR above EMA50", lambda t: (t["entry"]-t["ema50"]) <= 0.5*t["atr"])
