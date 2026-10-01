# Analysis — 2026-10-01: high stop-loss percentage (no bot changes)

**Request:** verify the high stop-loss rate, change nothing in the bot, and
leave any required work as notes for the next session.

**Decision: no strategy, parameter, runtime-data, or deployment changes this
session.** The loss rate is real, but there is no evidence here of a broken
stop calculation or a reason to widen/tighten stops immediately. The current
strategy still has negative paper expectancy. Keep the existing isolation
window; prepare the scheduled review, rather than tuning to the percentage.
**Analysis-tool corrections are needed before choosing the next experiment.**

Source handoff: `docs/HANDOFF.md` (there is no `logs/HANDOFF.md` in this checkout).
Snapshot: commit `3e734c479c189b01fa29c44de9586e921bbd6a3e`, data collection 160;
`status.json` / last candle **2026-10-01 14:59:04 UTC**, last closed trade
2026-10-01 12:16:03 UTC, **448 closed / 0 active**, 28,116 candle rows and
933 skipped signals. October 1 is **a partial day**, not a completed daily test.
This is a repository-snapshot review, not verification of the production host.
All dollar figures below are the engine's paper model, not broker-verified
returns; its simulation books one price unit as one dollar and omits realistic
execution costs.

## 1. What the high percentage actually means

- **SL / all closed trades:** 184 / 448 = **41.1%**.
- **SL / decisive outcomes:** 184 / (77 + 184) = **70.5%**.
- **Decisive win rate:** 77 / 261 = **29.5%**, Wilson 95% CI **24.3–35.3%**.
- **Breakeven exits:** 187 / 448 = **41.7%**; they are not stop-loss losses.
- TIME exits: **0**. All-in TP rate: 77 / 448 = **17.2%**.

Thus "70.5% stop-loss" is correct **among TP/SL outcomes**, not among every
trade. Fixing the denominator does not fix the economics: gross gains
**$441.20**, gross losses **$692.89**, net **−$251.69**, profit factor **0.637**.
Average TP earns $5.73 versus $3.77 lost per SL. At planned 1:1.5 risk/reward,
about **40% decisive wins** are required before costs (roughly 39.7% using
this book's realised average payoff). The observed rate is materially below
that benchmark. Variable ATR risk means win rate alone is not an equity test.

Cumulative P&L from the nominal $500 start gives **$248.31**, a **50.3% loss**.
`status.json` / final `Balance_After` show $265.28, the known **+$16.97 reset
drift**. Do not mistake the engine balance for a reconciled account balance.

### Era split — do not blame a new rule using the pooled book

Boundaries are the existing handoff's entry-time boundaries, not newly chosen
cutoffs. TP/SL/BE are closed-trade counts; TIME is zero throughout.

| Book | n | TP / SL / BE | SL / all | SL / decisive | Decisive WR (95% CI) | Net P&L | $/trade |
|---|---:|---|---:|---:|---|---:|---:|
| Pre-ratchet, before 09-10 12:34 | 45 | 8 / 37 / 0 | 82.2% | 82.2% | 17.8% [9.3–31.3] | −$82.51 | −$1.834 |
| 0.30R, 09-10 12:34 → 09-15 06:00 | 130 | 10 / 22 / 98 | 16.9% | 68.8% | 31.2% [18.0–48.6] | −$41.69 | −$0.321 |
| 0.75R before max-hold, 09-15 06:00 → 09-21 06:00 | 95 | 20 / 41 / 34 | 43.2% | 67.2% | 32.8% [22.3–45.3] | −$40.61 | −$0.427 |
| Max-hold era, since 09-21 06:00 | 178 | 39 / 84 / 55 | 47.2% | 68.3% | 31.7% [24.1–40.4] | −$86.88 | −$0.488 |
| **0.75R master book** (last two rows combined) | **273** | **59 / 125 / 89** | **45.8%** | **67.9%** | **32.1% [25.8–39.1]** | **−$127.49** | **−$0.467** |

The first four rows partition all 448 trades. The master row is a subtotal,
not a fifth independent era. CIs describe nominal sampling uncertainty, not
regime/serial-correlation uncertainty or profitability after costs.

The move from 0.30R to 0.75R reduced scratches from **75.4% to 32.6%**; fewer
trades get rescued at entry, so an increase in *SL/all* is partly mechanical.
It is not, by itself, proof that the original stop became too tight. Different
market periods and variable risk also prevent a causal before/after verdict.

There is **no fresh collapse** versus the September 29 handoff: the 46 added
trades are 13 TP / 18 SL / 15 BE, **+$3.30**. October 1 so far is
8 TP / 6 SL / 6 BE, **+$22.22**. This improves the headline, but two good
sub-windows do not erase the losing master/current-era books.

## 2. Verification: what is and is not broken

### Ledger and stop geometry

`tools/check_data.py`: **0 fail / 8 warn**. Schema, numeric fields, chronology
and status/ledger counts agree; no duplicate entry timestamps. Known warnings
include historical numbering/balance resets, missing bars and gap-spanning
trades. An integrity pass does **not** prove an uninterrupted feed or an edge.

Independent CSV checks on the **273-trade 0.75R book** found:

- All **125 SL rows are actual negative-P&L full stops**, not mislabelled BE.
  Loss / original 2×ATR risk is **0.9956–1.0040R**, median **1.0000R**;
  deviations are consistent with logged rounding.
- All **89 BE rows have stop = entry and zero logged P&L**. All 59 TPs have
  positive P&L. Direction-signed exit-minus-entry agrees with logged Profit
  to the CSV's cent precision on every row.
- Logged original SL distance agrees with 2×ATR within $0.01; TP distance
  agrees with 3×ATR within $0.02. Original geometry must be reconstructed on
  ratcheted rows, including TPs, not only on BE rows.
- **148 / 273 trades (54.2%) armed the ratchet**: 59 eventually reached TP,
  89 scratched. The mechanism is operating; that does not establish an edge.
- A separate current-rule bar walk, excluding the signal bar and preserving
  logged levels, reproduces **59 TP / 125 SL / 89 BE and −$127.49**. The
  observed loss rate is not just a dashboard or mixed-era replay artefact.

### Risk-gate and implementation checks

Source settings remain: **SL 2×ATR / TP 3×ATR / BE 0.75R / max-hold 240 min**;
ATR 1.10–4.50; SL cooldown 30/60 min; daily breaker 10 SLs, **trend-side-only,
not a hard daily halt**. BUY RSI bounds are 30–68; SELL uses mirrored 32–70.

A timestamp-aware audit of current-era recorded entries found **no blackout
violations, no entries inside the required post-SL cooldown, and no rounded
ATR/RSI/EMA-distance violations**. Logged entry EMA ordering is also aligned
with side. This is an audit of available ledger fields, not proof of every
historical signal gate or of production deployment.

`tools/smoke_test.py`: **SMOKE TEST PASSED (A–M)**, including BUY/SELL exits,
BE threshold/persistence, TIME behaviour and feed/restart guards. It uses
synthetic data in temporary directories, with no production/network actions.

### Max-hold and feed caveats

**Zero TIME exits at n=178**. Longest current-era hold is **67.97 min**
(#409 BUY, 09-29 20:58:08 → 22:06:06, BE across the normal daily closure).
Median current-era SL hold is **9.02 min**. A 240-min cap cannot cure stop-outs
that mostly happen within minutes; it has not bound any recorded trade here.
This supports "not responsible for the current SL rate", not "proved useful".
The handoff's old ">60-min holds ≈0" review target is not a guarantee of the
240-min rule: 60–240 min holds are allowed, and a closure delays execution.
Record that distinction at the review; it is not a reason to shorten the cap
in this session.

The feed is **not still frozen at September 29 in this snapshot**. Bars resume
at **09-29 14:47:39**, after the documented 6 h 18 min gap; another gap runs
14:50:40 → 15:43:06. No real trade overlaps those two outage intervals. The
normal daily closure crossed by #409 is a separate execution-model caveat.
Verify heartbeat, deployment and MT5 service hardening **on the host** next
session; current CSVs cannot establish that the server-side follow-ups shipped.

## 3. Where the losing outcomes are concentrated

### BUY weakness — real observation, not a justified BUY ban

| Max-hold-era side | n | TP / SL / BE | Decisive WR | P&L | $/trade |
|---|---:|---|---:|---:|---:|
| BUY | 72 | 11 / 37 / 24 | 22.9% | −$103.83 | −$1.442 |
| SELL | 106 | 28 / 47 / 31 | 37.3% | +$16.95 | +$0.160 |

BUY/SELL Fisher p = **0.1137** in this era (0.4282 in the 0.75R master book).
The SELL profit is not stable: September 28 SELLs alone made **+$41.92**;
excluding that day leaves **−$24.97**. Do not adopt SELL-only trading or a new
BUY blocker from this comparison. The registered `H-side-awareness` must still
clear its existing bar at the formal review.

At the original analysis's **60-min diagnostic**: whole-book counter-trend
outcomes total **24 decisive** (16 BUY, 8 SELL), below the ≥25 bar. Within BUY,
aligned WR exceeds counter-trend by 6.25 pp, but within SELL the gap is
**−16.12 pp**, failing the required common direction. On the 0.75R book the
gaps are only **+3.95 pp / −8.45 pp**; on the max-hold book both are negative.
**No momentum/side gate qualifies.** Do not repeat the older handoff's
"all (a)(b)(c) fail" as though that were an automated, current scoreboard;
score the actual registered criteria, with sides and eras separated.

### Immediate same-side re-entry after BE — keep as a research candidate

Using the **already queued** <5-min post-scratch idea, measured strictly as
entry less than five minutes after the immediately preceding BE exit:

| Book | Fast post-BE entries | TP / SL / BE | Decisive WR | P&L / trade | Other entries: WR / P&L per trade |
|---|---:|---|---:|---:|---|
| 0.75R master | 54 | 9 / 30 / 15 | 23.1% | −$1.345 | 34.5% / −$0.250 (n=219) |
| Max-hold | 33 | 4 / 18 / 11 | 18.2% | −$1.676 | 34.7% / −$0.218 (n=145) |

All these fast re-entries are on the **same side** as the scratched trade.
The 54 entries account for **−$72.65** of the master book's −$127.49. This is
consistent with repeated attempts in a weak setup, but is **not proof that
skipping them would save that money**: a pause changes later opportunities.
Fisher p is 0.2458 / 0.2052, and side/day clustering matters. Test a fixed
five-minute pause prospectively or with a full stateful signal replay; do not
simultaneously change BE's SL-streak semantics or remove cooldown protection.

### Previously queued RSI / ATR filters are not a ready fix

Current **0.75R-era** kept versus skipped buckets:

| Candidate | Kept: n / decisive WR / $ per trade | Skipped: n / decisive WR / $ per trade |
|---|---|---|
| RSI ≥45 | 174 / 32.5% / −$0.493 | 99 / 31.4% / −$0.422 |
| ATR <2.5 | 228 / 32.1% / −$0.422 | 45 / 32.1% / −$0.694 |
| RSI ≥45 AND ATR <2.5 | 146 / 33.3% / −$0.350 | 127 / 30.7% / −$0.601 |

RSI alone does not improve $/trade. ATR buckets have essentially identical WR;
less dollar loss at low ATR can simply reflect smaller dollar risk, not better
entries. The combo looks less bad in the master book but **does not persist
in the max-hold era**: kept −$0.529/trade versus skipped −$0.449/trade,
31.7% decisive in both. None is approved; do not resurrect an old ratchet-era
adoption claim using pooled data.

## 4. Replay results: audit the analysis before changing the bot

Existing reports ran successfully, but successful execution is not equivalent
to current-rule validation. Required corrections for the next analysis session:

1. **`tools/win_rate_report.py`:** `NEW` pools 0.30R and 0.75R entries, while the
   grid still marks 0.30R as live and says that row should match ACTUAL. Add
   explicit current/master/max-hold-era reporting and matched-rule baseline
   calibration. Its cascade simulation resets the SL streak on BE, unlike
   production, and estimates elapsed minutes using the bar index, not actual
   timestamps. Neither should decide a cooldown/ratchet change as-is.
2. **Costs:** multiplying gains **and losses** by 0.985 is not an execution-cost
   model: it even makes losses smaller and leaves scratches free. Model bid/ask,
   commissions/slippage and gap fills consistently on **all exits**, including
   BE, and confirm broker point/lot economics before any LIVE proposal.
3. **`tools/validate_gates.py`:** `NOH8` still blocks both sides in its historical
   report, though the live London gate is BUY-only. It also compares some
   pre-update indicator values to post-update entry rules. Correct the era/side
   handling before treating BLOCK labels as live gate violations.
4. **`tools/analyze_losers.py`:** MFE/MAE includes the signal candle and often
   omits the exit candle, whose log timestamp is 1–3 seconds after Exit_Time.
   Its scratch narrative still says 0.30R. Correct alignment/era labels before
   using run-up statistics to choose a tighter ratchet or a different SL.
5. **Other replays:** `pathwalk_sims.py` prints all-in `win%`, not decisive WR,
   and has old ratchet labels/fallback estimates. `phantom_trades.py` does not
   reproduce current BE behaviour and its sequential view does not represent
   the full real-plus-skipped portfolio/cooldown cascade. Its +$819 phantom
   total is **not** attainable profit or evidence to remove protective gates.

### Era-matched diagnostic (not a production backtest)

A separate inline, read-only check used only **observed actual entries**, the
logged target, original stop (or target-distance / 1.5 when stop = entry),
subsequent logged bars, and the engine's arm-before-stop / stop-before-target
candle ordering. A second pass filtered entries for position occupancy and
30/60-min cooldown, preserving SL streaks across BE, resetting on TP, and
starting cooldown only after SL. It used actual exit-bar timestamps, no
"actual outcome" fallback, and no 0.985 haircut. All paths resolved within
240 min; no synthetic TIME fallback was needed. The only >5-min gap crossed
by these no-ratchet paths was #409's normal daily closure, not a feed outage.

| Book / hypothetical rule | Taken | TP / SL / BE | Gross paper P&L |
|---|---:|---|---:|
| 0.75R baseline, independent **and** occupancy/cooldown pass | 273 | 59 / 125 / 89 | −$127.49 |
| Same entries, ratchet off, independent | 273 | 100 / 173 / 0 | −$46.81 |
| Ratchet off, occupancy/cooldown pass | 191 | 72 / 119 / 0 | **+$1.45** |
| Max-hold baseline, independent **and** occupancy/cooldown pass | 178 | 39 / 84 / 55 | −$86.88 |
| Same max-hold entries, ratchet off, independent | 178 | 63 / 115 / 0 | −$43.37 |
| Max-hold ratchet off, occupancy/cooldown pass | 130 | 49 / 81 / 0 | **+$9.37** |

These results support researching the queued ratchet-off fallback, **not a
confirmed profitable replacement**. The +$1.45 is only **$0.0076/taken trade**
before costs. Illustrative—not estimated broker—costs of $0.05/trade turn it
into **−$8.10**; $0.10/trade gives **−$17.65**. The max-hold-only replay becomes
+$2.87 / −$3.63 at those same costs. The observed-entry stream omits signals
that an alternative position/cooldown history would make available; this is
still not a full strategy replay or an out-of-sample test.

Intrabar uncertainty remains: **21** current-era scratches arm and touch entry
within the same one-minute bar. None of those bars also touches the original
SL. Matching the engine confirms its implementation, not the unknowable tick
sequence. Obtain tick data or bound alternative OHLC orderings before claiming
realistic execution or changing this convention. No convention changed today.

## 5. Next-session work, in order

1. **Refresh data and verify operations first.** Confirm the production feed,
   alert/dedup deployment, and MT5 service hardening on the host. Keep outage
   intervals identified; do not treat absent bars as a quiet market. Re-run
   integrity before every new performance claim.
2. **Correct analysis tooling only**, addressing §4, and add tests that replay
   each era's actual rule close to its ledger before comparing alternatives.
   Keep runtime strategy and parameters unchanged while validating research.
3. **Formal max-hold re-review:** existing target **~2026-10-05 or n≈200**
   post-deploy closed trades; currently **178**, 22 short of 200. Pin the exact
   deploy boundary from host logs. Judge P&L/day, $/trade, TIME count/P&L and
   gap/exposure risk, not a headline SL percentage. Do not reset the master
   0.75R falsification book.
4. The original ratchet falsification remains tripped: **−$0.467/trade at
   n=273**, below −$0.40. The **step-2 bar is still proposed, not newly
   pre-registered or approved here**: post-deploy ≤−$0.40/trade at n≥200. Current
   post-deploy is −$0.488 at n=178, so that size condition is not met. Confirm
   or amend the proposed bar explicitly at the review; if proceeding, register
   a **costed, stateful, isolated ratchet-off experiment**, not an assumed win.
5. Score `H-side-awareness` against its **unchanged registered criteria**.
   Retain the fixed five-minute post-BE pause as a separate, later candidate.
   Do not combine it with ratchet-off, SL-streak reset, RSI, ATR, side bans or
   new blackouts in one test. Each needs its own decision bar and isolation.
6. **Do not change SL/TP multiples merely to improve win rate.** Wider stops
   increase loss size; nearer targets reduce payoff. Require chronological,
   costed, out-of-sample expectancy and drawdown evidence for such a proposal.
   Stay paper-only; broker-side stops/BE, position sizing and a reconciled costs
   model remain prerequisites, not work shipped in this session.

## 6. Reproduction / scope record

Commands run on the unchanged snapshot:

```bash
python3 tools/check_data.py          # 0 fail / 8 warn
python3 tools/win_rate_report.py      # completed; caveats in §4
python3 tools/momentum_regime.py      # completed; prints the registered bar
python3 tools/validate_gates.py       # completed; not a current-rule proof
python3 tools/analyze_losers.py       # completed; MFE/MAE caveats in §4
python3 tools/phantom_trades.py       # completed; phantom != realised profit
python3 tools/pathwalk_sims.py        # completed; denominator/replay caveats
python3 tools/smoke_test.py           # SMOKE TEST PASSED (A–M), temp files only
```

Supplementary counts used `csv.DictReader`, UTC entry-time era splits,
`Decimal(Profit)` sums, Wilson CIs on TP/(TP+SL), and the existing
`momentum_regime.py` Fisher calculation. Re-entry groups used the immediately
previous closed row's reason and actual Entry_Time − Exit_Time, not an MFE
proxy. The diagnostic's method and assumptions are recorded in §4; no new
analysis executable was added.

**Only this analysis, `docs/HANDOFF.md`, and the project-journal changelog were
edited. No engine, filter, dashboard, tool, deploy file, CSV or status change;
no production restart, parameter deployment, or new experiment adoption.**
