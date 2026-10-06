# ANALYSIS 2026-10-05 — stop-loss rate, the inert level test, and the structural stop

**Asking question (owner):** *"rethink new strategy as there's a lot of stop loss, do changes
if necessary and update handoff with details."*

| | |
|---|---|
| **Data** | `forward_test_log.csv` 31,222 M1 bars 2026-09-01 14:25 → 2026-10-05 20:58 UTC; `trades.csv` **493** closed trades |
| **Ledger at judgement time** | 84W/208L/200BE/1TIME → **28.8% decisive** [23.9–34.2], **−$308.91** net, **−0.163R/trade** (1R = the trade's own 2·ATR risk ≈ $3.84), payoff 1.51, uncosted breakeven decisive WR at 1:1.5 = **40.0%** |
| **Shipped** | **one** runtime change in `engine.py`: the stop must clear the 20-bar level (`SL_CLEAR_ATR = 0.5`), TP keeps 1:1.5 against the **actual** risk (`RR_TARGET`). Entries, gates, ratchet, max-hold, lot, sizing: **untouched** |
| **Cutover** | **2026-10-05 21:00 UTC** (next autosync). New isolation window = entries ≥ cutover. Nothing was judged on post-cutover data before this file was written — §7 is the contract |
| **Rejected** | the level-test re-scale, the session-band gate, ratchet-off, and **every** stop-widening arm that trades expectancy for win rate (§8) |
| **Not claimed** | this is **not** a demonstrated edge. Costed replay is still negative at every cost tested (−0.106R to −0.179R). It is a defect fix that halves the bleed and makes the stop mean what the docs already said it meant |

---

## 0. Answer in four sentences

The stop-loss rate is high because **the stop is not a structural stop**. The entry gate is
supposed to require a test of the 20-bar floor/ceiling, but its tolerance is expressed in
**price-%** (`FLOOR_BUFFER_PCT = 0.0020` ≈ $8.30 on a $4,150 market ≈ **4.5× the median
ATR**), so it passes on 86.9% of all bars and selects for nothing; entries therefore fill a
median **2.42 ATR away** from the level they claim to bounce off, and a 2·ATR stop lands
*inside* the range on **63.8%** of trades — price only has to come *back* to the level for
the stop to print (median SL lifetime **7.2 min**, 46% ≤ 7 min of a 240-min budget). Putting
the stop beyond the level removes that class entirely by construction, and in costed,
era-matched replay it improves R/trade in **3 of 4 parameter eras**, halves the per-day bleed
(−$13.90 → −$5.83 at $0.15/side), cuts stop-outs per day 8.2 → 5.4 and halves replay max
drawdown ($255 → $175) — while costing more per stop-out (−$4.20 → −$6.80) and holding ~2×
longer.

## 1. Method — and the harness that was missing

`docs/ANALYSIS-2026-10-01-stop-loss-rate.md` §4 listed four deficiencies that made every
prior counterfactual unusable for an exit/gate decision: no cost model, no portfolio state
(one position, 30/60-min SL cooldown, daily breaker), gates replayed with the wrong
direction/era, and no era labels. Those counterfactuals (`exit_sims.py`, `pathwalk_sims.py`,
`phantom_trades.py`) are **cascade-ignorant** — they price a counterfactual
on a trade list whose *sequencing* the change would itself alter. Changing the exit geometry is
exactly such a change: with wider stops, holds lengthen, occupancy blocks other entries, and
the cooldown re-times the book (replay trade count 326 → 217 with **no entry-gate change at
all**). So the prerequisite was a simulator, and it is now in the repo:

**`tools/strategy_lab.py` (new, canonical for this and every future exit/gate question).**
Read-only; regenerates the funnel from the 1-min log with engine-faithful indicators
(SMA-seeded EMA50/200, simple-mean RSI-14/ATR-14, 20-bar floor/ceiling **excluding the
current bar**, and the decision-time convention that `log_candle` writes *pre*-update values),
then replays the **whole** strategy — gate order, direction-aware blackouts, daily breaker,
cooldown with production semantics (blocked only while the *last closed trade* was an SL; a
BE/TIME scratch switches the block off; escalation at streak ≥ 2; the streak is transparent to
BE and broken by TP), one-position occupancy with same-bar re-entry, ATR bounds, engine
intra-bar exit ordering (arm-ratchet → stop → target → TIME at close, stop wins ties), a cost
per side applied to **every** exit including BE, and the era-correct ratchet trigger
(0.30R before 09-15 06:00, 0.75R after, off where the ledger says so).

Calibration before any counterfactual was trusted (`--calib-only`):

| era | ledger entries | raw signals | entry-stream recall |
|---|---|---|---|
| pre-gates (<09-10 12:34) | 45 | 510 | 68.9% *(expected: the gate stack itself changed mid-era)* |
| 0.30R (09-10 12:34 → 09-15 06:00) | 130 | 353 | **100.0%** |
| 0.75R master (≥09-15 06:00) | 318 | 1,943 | **99.7%** |
| max-hold (≥09-21 06:00) | 223 | 1,404 | **99.6%** |

The **funnel is reproduced**; the taken-set overlap is 77% (435/563 replay trades have a ledger
entry in the same minute) and the residual is cascade timing, not a gate difference — two
harness bugs were found and fixed on the way there (a BE scratch must switch the cooldown off;
the daily breaker counts SLs by `Exit_Time`), which moved that overlap from 64% → 77%. Absolute
replay P&L still differs from the ledger (−0.213R vs −0.288R at the same cost model), so
**every decision below is a row-to-row delta, never an absolute.**

## 2. The level test is inert

```
engine.py L962  tested_floor = l <= dynamic_floor * (1 + FLOOR_BUFFER_PCT)   # 0.0020
```

At $4,150 that tolerance is **$8.30**. The median ATR at entry is **$1.83**
(p10 $1.23 / p95 $3.19), so the tolerance is ≈ **4.5 ATR** while *every* other threshold in
the funnel is ATR-scaled (wick ratio, RSI band, EMA distance, ATR bounds). Consequences, all
measured:

* `Tested_Floor == True` on **86.9%** of the 31,222 logged bars (89.1% recomputed over the
  0.75R era) — the gate filters almost nothing. `status.json`'s own funnel agrees
  (936/1,031 candidate bars reached "tested floor").
* Of the bars that pass it, **44.5%** close **more than 2 ATR above** the level.
* `MAX_BELOW_EMA_ATR = 0.30` (anti-chase guard) is what makes that possible: median
  (EMA50 − level)/ATR at entry is only **0.93**, so "close near the EMA" and "close near the
  level" can only coexist in flat tape — the level test is not just loose, it is *structurally
  unreachable* in a trending one (only 17.3% of bars have EMA50 within 1.0 ATR of the floor).
* The ATR-scaled version of the same idea already exists as a research gate in
  `tools/validate_gates.py`: `PROX0.5` keeps 55 trades at 28% decisive, `PROX1.0` keeps 120 at
  33% — i.e. tightening the *entry* was tried on the ledger and did nothing for WR.

## 3. …so the stop is a noise stop, not a structural one

Given the entry above, `risk = 2·ATR` is not "below support", it is *inside the range*:

| measure | value |
|---|---|
| median \|entry − level\| at entry | **2.42 ATR** (ledger, n=318) / 2.45 ATR (replay, n=326) / p90 4.04 |
| trades whose stop sat **inside** the level | **203/318 = 63.8%** (replay: 210/326 = 64.4%) |
| SL exits that were that class | **95/149 = 63.8%** ledger / 98/148 = 66.2% replay — two thirds of stop-outs needed no structural break |
| median shortfall of the stop vs the level | **0.42 ATR** |
| SL-exit lifetime | median **7.2 min**, p90 20.0 min, 46.2% ≤ 7 min, 97.6% ≤ 30 min (budget: 240) |
| trades that touched +1·ATR before the SL | 22.3% |
| ratchet trigger vs noise | 0.75R = **1.5·ATR** — the same order as one bar's noise, which is why 32.8% of trades scratch |

Two earlier figures in the docs (68.6%/69.1%) counted BE-ratcheted rows by their *logged* stop,
which the ratchet has already moved to entry; `tools/check_structural_stop.py` recovers the
original geometry from the reward leg instead (TP is never touched by the ratchet), giving the
63.8% above. Use the tool, not memory.

## 4. The change

```python
risk = max(ATR_SL_MULT * atr, abs(entry - level) + SL_CLEAR_ATR * atr)   # SL_CLEAR_ATR = 0.5
stop = entry -/+ risk
tp   = entry +/- RR_TARGET * risk          # RR_TARGET = ATR_TP_MULT / ATR_SL_MULT = 1.5
```

`level` is the same 20-bar `dynamic_floor` / `dynamic_ceiling` the rejection gate was measured
against — no new state, no reorder of `evaluate_candle` (the level and `self.atr` are both the
decision-time values, i.e. *before* `update_indicators`, which is what `log_candle` writes and
what the replay reproduces).

Properties, by construction and verified:

1. **The stop can never be inside the level again** — clearance ≥ 0.5 ATR when the level
   binds, and when it doesn't bind the level is closer than 2·ATR so the ATR stop is already
   beyond it. Replay under the new rule: **0 of 217** trades have a stop inside their level (210
   of 326 before). Post-cutover `tools/check_structural_stop.py` must print **0**; that check is
   step 1 of the bar in §7 and it is a code check, not a luck check.
2. **Zero behaviour change unless the level demands it** — `level is None` (history too short,
   restore path) or |entry−level| ≤ 1.5·ATR reproduces the old SL/TP exactly. Locked by
   `tools/smoke_test.py` Scenario N, including "the BE ratchet arms at 0.75R **of the new
   risk**" and "a restart mid-trade keeps the wider stop" (`status.json` →
   `restore_open_trade_from_status`).
3. **1:1.5 survives** — TP is a multiple of the actual risk, so `R` keeps meaning "the
   distance to my real stop", the ratchet trigger stays at 0.75R, and the 40% breakeven
   arithmetic in `tools/win_rate_report.py` stays valid. Because the pre-change engine set
   `risk = 2·ATR` **always**, `Profit ÷ (2·ATR)` and `Profit ÷ actual risk` coincide on every
   historical row — the definition change is backward-compatible to the byte.
4. **Both sides, both paths** — BUY mirrors to the ceiling for SELL; `execute_live_trade`
   measures from the order price (the fill) rather than the bar close, so a LIVE-mode book
   would inherit the same geometry (still `TRADING_MODE="FORWARD_TEST"`; not a step toward live).

Share of trades that actually bind: **80.2%** (replay, master era; 174/217). Median risk
2.00 → **3.07 ATR** ($3.75 → $6.27 per trade; the paper ledger books $1 of P&L per $1.00 of
price move, which is 0.01 lot XAU = 1 oz).

## 5. Evidence (era-consistent, costed, stateful)

`python3 tools/strategy_lab.py --table --only baseline,structstop` — every cell is an
independent cascade restarted at the era boundary. `baseline` = pre-change production;
`structstop` = post-change production. `$0.15–0.20/side` ($0.30–0.40 round trip) is the honest
band for 0.01-lot gold.

```
== TABLE cost/side $0.15 (round trip $0.30) ==
  era          variant          n  decWR   SL%  BE%  T     R/t     $/t   $/day n/day   hold  maxDD  avgSL$  avgTP$ payoff  medR$ medRATR
  pre-ratchet  baseline       106   40.6% 59.4%   0% 0  -0.084  -0.219   -2.58  11.8   9.0m   74.4   -3.58    4.71  1.31  3.01   2.00
  pre-ratchet  structstop      79   35.1% 63.3%   0% 2  -0.192  -0.723   -6.35   8.8  22.1m  111.1   -6.01    9.30  1.55  6.08   3.56
  0.30R        baseline       129   20.7% 17.8%  77% 1  -0.194  -0.788  -20.32  25.8   2.0m  101.6   -4.39    5.08  1.16  3.73   2.00
  0.30R        structstop      94   25.9% 21.3%  70% 1  -0.166  -1.205  -22.66  18.8   7.0m  113.3   -7.40    7.99  1.08  5.52   2.93
  075R pre-mh  baseline       100   35.5% 40.0%  38% 0  -0.154  -0.538   -8.97  16.7   9.5m   59.2   -4.02    5.39  1.34  3.70   2.00
  075R pre-mh  structstop      63   36.4% 44.4%  27% 2  -0.123  -0.875   -9.18  10.5  17.1m   91.3   -6.65    8.63  1.30  5.81   2.94
  max-hold     baseline       226   30.8% 47.8%  31% 1  -0.245  -0.861  -14.98  17.4  10.0m  194.7   -4.25    5.98  1.41  3.80   2.00
  max-hold     structstop     157   38.4% 43.9%  25% 5  -0.089  -0.298   -3.60  12.1  24.1m   95.1   -6.88   10.38  1.51  6.30   3.09
  075R MASTER  baseline       326   32.1% 45.4%  33% 1  -0.217  -0.767  -13.90  18.1  10.0m  255.5   -4.20    5.79  1.38  3.75   2.00
  075R MASTER  structstop     217   37.4% 44.7%  25% 7  -0.106  -0.484   -5.83  12.1  22.0m  175.2   -6.80    9.99  1.47  6.27   3.07
```

* **Direction is cost-insensitive**: ΔR/trade vs baseline = **+0.083R** gross, +0.111R at
  $0.15/side, +0.121R at $0.20, **+0.148R** at $0.35 (the change gains as costs rise because
  it cuts the *number* of round trips 33%).
* **Era**: better in **3 of 4** (0.30R −0.194→−0.166; 0.75R pre-max-hold −0.154→−0.123;
  max-hold −0.245→−0.089, the era that is actually live). **Worse in pre-ratchet**
  (−0.084→−0.192) — expected and mechanical: with no ratchet there is nothing to protect a
  wider stop, so the bigger loss is unconditional (avg SL −$3.58 → −$6.01, BE 0%). Read it as
  *"this change needs the ratchet; do not ship it together with ratchet-off"*.
* **Stability of the improvement** (master era, $0.20/side, 5 chronological chunks of n≈43):
  ΔR = **+0.058, +0.044, +0.260, +0.276, −0.031** → 4 of 5 better; the most recent fifth is
  flat-to-slightly-worse. Leave-one-day-out over the 18 sessions: R/trade stays in
  **[−0.173, −0.100]** (baseline in [−0.289, −0.19]) — the *improvement* is not one day, but
  neither level reaches 0. 5 of 18 days are net positive (total −$126.71, worst −$36.34,
  best +$80.50).
* **Not an ATR-mix artifact**: ΔR by entry ATR = +0.198 (1.1–1.6), +0.165 (1.6–2.1),
  **+0.008 (2.1+)**. It is a quiet-tape fix — where the level is far relative to a small ATR.
* **Both sides improve**: BUY −0.290 → −0.194R (WR 28.4 → 33.3%), SELL −0.198 → −0.052R
  (35.3 → 41.2%); side gap unchanged in sign, Fisher p=0.65 → no new side story.

## 6. What it does **not** do — and what it costs

* **Still negative.** −0.106R/trade at $0.30 round trip on 217 trades. Costed breakeven
  decisive WR at 1:1.5 is 40.0% *before* costs, ≈ **42.2%** once the ~$0.30 round trip is
  charged against a ~$6.3 median R — structstop's 37.4% is under both. **Do not call this an
  edge, do not size up, do not go live.**
* **The stop-out bill does not shrink** — total SL dollars at $0.15/side −$621.61 →
  −$659.43; there are **fewer, bigger** stops (148 → 97 events, −$4.20 → −$6.80 each, max
  single loss −$8.82 → −$12.22). The P&L gain comes from the *other* legs: scratches 33% → 25%
  and avg TP +$5.79 → +$9.99, i.e. noise stops and premature scratches were replaced by
  outcomes. The worst day improves (−$43.58 → −$34.54) because a bad day has fewer legs.
* **Volume −33%** (18.1 → 12.1 trades/day) with no entry change: longer holds (median 10 →
  22 min) occupy the single position and re-time the 30/60-min cooldown. Expect **fewer
  samples per week**, so the §7 bar is ~8 trading days to n=100, not 5.
* **TIME exits 1 → 7 (3.2%)** and holds are 2.2× longer → more exposure to the daily/weekly
  closure gap that #476 rode for 49.1 h. The cap itself is unchanged (240 min) and cannot fire
  while the market is shut; this raises the value of the queued pre-close/flat-before-close
  guard rather than lowering it.
* **The daily-loss breaker bites less**: it counts SLs, and SLs/day fall 8.2 → 5.4, so a bad
  day now needs more real damage before `MAX_DAILY_LOSSES` halts it. Accepted; §7 monitors the
  per-day number directly instead.
* Per-stop risk in $ rises ~50%: a 5-SL day is ≈ −$34 (was −$21). Inside the ~$200 drawdown
  budget at $500 / 0.01 lot; **lot size stays 0.01** and `MAX_HOLD_MINUTES = 240` stays
  structural. Replay max drawdown improved ($255 → $175) but that is one path, not a
  distribution.

## 7. PRE-REGISTERED BAR — written 2026-10-05, before any post-cutover trade existed

**Window:** entries with `Entry_Time ≥ 2026-10-05 21:00 UTC` ("struct-stop era"). One variable:
the stop/TP geometry. Nothing else may be changed inside this window; no re-slicing of eras to
find a better cut. First judgement (**screen**) at **n = 100** closed trades (~8 trading days at 12/day),
confirmatory (**pass/fail**) at **n = 150** or **2026-10-19 21:00 UTC**, whichever comes first. **n < 60 is not
a result** — not in either direction.

**Judge in this order** (a failure at step A invalidates the reading of step C):

**A. Is the code doing what the model says?** (check after ~10–20 trades, not at n=100)

| # | metric | requirement |
|---|---|---|
| A1 | `tools/check_structural_stop.py --since 2026-10-05` → stop INSIDE level | **must be 0** (was 63.8% pre-change) |
| A2 | same tool → median clearance | ≥ 0 ATR for every trade, ≥ 0.5 ATR on level-bound ones |
| A3 | `python3 tools/strategy_lab.py --calib-only` (funnel is untouched, so it must not move) | recall still 99.6–100% on the 0.75R-master / max-hold rows; if it drifts the harness and the engine disagree — fix that **before** reading any P&L row |
| A4 | level-bound share | 70–90% (replay 80.2%); outside that, tape structure changed and the comparison is not like-for-like |
| A5 | median risk in ATR | 2.7–3.5 (replay 3.07) |

**B. The stated purpose — fewer stop-outs.** per `tools/win_rate_report.py` on the new era:

| # | metric | bar |
|---|---|---|
| **B1** | SL events / calendar day | **≤ 6.5** (pre-change replay 5.4; baseline 8.2, ledger 8.2/day) |
| **B2** | SL share of closed trades | **≤ 47%** (baseline replay 45.4%) |
| **B3** | BE (scratch) share | **≤ 35%** (baseline 32.8%, ledger 40.6%) |

**C. Expectancy** (the only part that could justify keeping it as more than a defect fix):

| verdict | condition |
|---|---|
| **SCREEN (n ≥ 100)** | net R/trade ≥ **−0.10R** (cost-0 ledger scale; the paper engine books no costs) **and** decisive WR ≥ **36%** **and** B1–B3 hold. This is a screen, not a pass: at n=100 a 36% WR still has a Wilson 95% LB of ~27%, i.e. it does not yet exclude the 32.1% the old rule replayed |
| **PASS (n ≥ 150)** | the screen conditions still hold **and** the 95% Wilson lower bound of decisive WR **exceeds 32.1%** (the pre-change replay point estimate for this book; the ledger's own was 28.8%). At n=150 that needs **WR ≈ 40%** — the same number as the uncosted 1:1.5 breakeven, so a PASS means the new book clears breakeven *before* costs rather than merely beating the old rule |
| **KEEP, no edge** | the R/trade bar holds but WR lands in 36–40% (LB ≤ 32.1%): keep the geometry — it is mechanically correct and it halves the bleed — and record that the strategy still has **no demonstrated edge** |
| **REVERT** | net R/trade ≤ **−0.20R** at n ≥ 100 (no better than the −0.217R/−0.245R it replaced), **or** average SL loss > **2.2×** the pre-change average (real per-stop cost worse than the modelled 1.5× — spread/slippage on a wider stop), **or** **any** post-cutover trade has a stop inside its level after A1 was shown to work (i.e. a code regression, not a strategy result), **or** paper account drawdown from the era's starting balance exceeds **$250** before n = 100 |
| **Extra revert trigger (gap risk)** | 2 or more post-cutover trades found open across a daily/weekly closure with an unenforceable stop — that is the §6 cost of longer holds materialising; revert and take the gap guard first |

Report with `python3 tools/win_rate_report.py` (decisive-only WR is the binding metric; BE
neutral, TIME excluded from WR but booked in P&L/trade) **plus** the per-day columns from
`python3 tools/strategy_lab.py --table --only baseline,structstop` on the new window. No other
sims are admissible for this decision (§1).

If PASS: next isolation slot, in order, is the **entry-tolerance re-scale** *only if* the owner
wants to spend 2 weeks on an era-unstable idea (§8(a)), otherwise the **pre-close/flat-before-close
gap guard** (a risk fix, not an expectancy fix). If REVERT: `git revert` the single commit, record
the outcome here, and stop treating "less stop loss" as a design goal in itself.

## 8. Rejected, with numbers — do not re-derive these on the same data

| candidate | costed replay verdict | why it was rejected |
|---|---|---|
| **(a) ATR-rescale the level test** (`tol = 0.15/0.25/0.5/1.0 ATR`, or force a pierce) | dose-response at $0.20/side: live −0.208R (n=428) → 1.00 −0.143 → 0.50 −0.208 → 0.25 −0.096 → 0.15 −0.081 → **0.00 −0.054R (n=103)** | Pooled numbers look best in the repo, but **era-unstable**: tol0.15 gives 0 winners of 21 decisive in the 0.30R era and −0.273R vs −0.154R in 0.75R-pre-max-hold; the 0.0-pierce variant's near-miss bucket is the *worst* class of all (−0.25..0 ATR short of the level: **14.3% decisive, −0.409R**, n=11). It also needs 2–4× more data per judgement (n=99–103 in 18 sessions). Registered, not adopted; `--grid level` reproduces it in ~2 s |
| **(b) Widen the stop only** (level + 0.5 ATR, TP left at 3·ATR) | 47.9% decisive, −0.053R gross / −0.107R at $0.15 | Buys win rate by degrading the ratio from 1:1.5 to ~1:1 — exactly the trap named in ANALYSIS-2026-10-01 §5.6 ("do not change SL/TP multiples merely to improve win rate"). No better than the shipped RR-preserving form, and it invalidates the 40% breakeven yardstick |
| **(c) Pure stop widening, RR held** (min SL 2.5 / 3.0 / 3.5 ATR with TP 1.5×) | −0.107R / −0.134R / worse; WR up to 50.7% | Inflation of WR with **no** expectancy gain, avg SL $4.05 → $6.53, replay maxDD still $364. Rejected on §5.6 grounds and on the data |
| **(d) Tighten stops instead** (min SL 1.5 / 1.0 ATR) | −0.257R / −0.425R | Far worse; recorded so nobody retries "smaller stop = fewer stops" |
| **(e) Ratchet off** | ≈ breakeven gross (−0.052R at $0.15/side, −0.162R at $0.20) with **61.7% of trades ending in a full stop-out** (45.4% today); max-hold −0.082R at $0.15/side — *better than that era's −0.245R baseline*. **With the shipped stop** (`structstop+nord`, $0.20): −0.131R vs **−0.124R** for `structstop` alone, SL share 59.2%, TIME 9 | The 10-01 §4 harness was the stated blocker for this question; it now exists and the answer is **no improvement worth an isolation slot**: the R gain comes from deleting the scratch bucket rather than from better outcomes, and once the stop is structural it is **redundant** (Δ −0.007R, i.e. noise). Recommendation: **drop ANALYSIS-2026-10-01 §5.1 "fallback step 2"** (owner may still override; the bar shape in §7 applies) |
| **(f) Session-band gate** (trade only 23:00–06:59 UTC) | baseline: Asia +0.022R vs LDN/NY −0.246R (gap 0.268R, pooled Fisher p=0.034). Under `structstop`: +0.001R vs −0.084R (**gap 0.085R**) | The band was largely a **proxy for the stop-geometry defect** (LDN/NY tape is wider, so the 2·ATR stop sits inside the level more often). Once the stop is structural the effect mostly disappears — so it must not be stacked on top of this change, and REVIEW-2026-10-05 §5a's candidate should be **downgraded** (it fails its own independence clause (b): the effect is not robust to the exit rule) |
| **(g) Stack (a) on the shipped change** | `sweep+stop` ≡ `sweep`; tol0.25+band +0.244R | One variable per window; and with A1's property guaranteed the entry-side tolerance no longer changes stop placement at all (0.0% "stop inside level" for every ATR-scaled tolerance) |

## 9. How **not** to read this file

* Do not quote `exit_sims.py` / `pathwalk_sims.py` / `phantom_trades.py` numbers for an exit or
  gate decision. They are cascade-ignorant by construction (§1) and their
  remaining §4 corrections (MFE/MAE alignment, decisive-WR labels) are still open.
* Do not compare an absolute replay $ to a ledger $. Use row-to-row deltas at matched cost; the
  replay is −0.213R where the ledger is −0.288R for reasons the harness cannot see.
* Intra-bar ordering is unknowable from OHLC. This replay uses the engine's own convention
  (ratchet → stop → target → TIME, stop wins ties). A looser stop always looks slightly better
  under a fixed convention; that bias is why §7 demands A1 (a code fact) before any P&L reading.
* n = 21–103 slices of an 18-session book. `--calib-only` proves the *funnel*, not the future.
* The 5th chunk of §5 and the whole pre-ratchet era both argue against over-confidence.

## 10. Reproduce

```bash
python3 tools/check_data.py                                          # expect: 0 fail, 8 warn
python3 tools/smoke_test.py                                          # A–N PASS (L now pins the clock)
python3 tools/win_rate_report.py                                     # ledger baseline, eras, ratchet grid
python3 tools/strategy_lab.py --calib-only                           # funnel recall (must stay ~100%)
python3 tools/strategy_lab.py --only structstop --cost 0.15          # per-era / per-side / band / chunk detail
python3 tools/strategy_lab.py --table --only baseline,structstop     # every number in §5
python3 tools/strategy_lab.py --grid level                           # §8(a) dose-response
python3 tools/check_structural_stop.py                               # §7-A1/A2 (post-cutover: 0 inside)
python3 tools/check_structural_stop.py --since 2026-10-05            # once new data exists
```

Changed files: `engine.py` (constants + `structural_risk` + both execute paths + comments),
`tools/strategy_lab.py` (new; `--table`, `--era`, `structstop` arms), `tools/smoke_test.py`
(Scenario N; Scenario L clock pinned), `tools/win_rate_report.py` (risk recovered from the TP
leg so R stays correct for level-bound and ratcheted rows), `tools/check_structural_stop.py`
(new).
