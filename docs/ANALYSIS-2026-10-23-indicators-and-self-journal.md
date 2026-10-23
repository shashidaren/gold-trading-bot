# ANALYSIS 2026-10-23 — more indicators, and a self-journal with a success rate

**Owner asks (this session):**
> “Need help with the indicators — if there's any more, that we can add to further
> improve, just checking if you can self journal the buy/sell and see the success
> rate as well.”

**Status:** display-only + tooling. **No `engine.py` / `trade_filter.py` change, no
parameter, gate, exit, deployment or host action.** The checked-in engine remains
`TRADING_MODE = "FORWARD_TEST"`, the structural-stop window is untouched, and the
§7 closure-gap REVERT trigger remains FIRED with its gap-guard blocker unresolved.

**Data used:** the checked-in snapshot through **2026-10-23 11:59:08 UTC** — 695
closed trades (140W/300L/253BE/2TIME), structural-stop era n=198
(55W/89L/53BE/1TIME), 49,956 logged bars. `check_data.py`: 0 fail / 8 warn.

---

## 1. What was asked, and what can honestly be delivered

Two different requests hide in the message:

1. **“Any more indicators we can add to improve?”** This repo has a binding rule
   (HANDOFF §11): an indicator is not added to the engine because it is popular or
   looks useful. It is added only after a **pre-registered, dated bar**, measured
   with the costed/stateful harness, out of sample, one variable at a time — and
   the structural-stop window is still open with a fired revert trigger. The one
   safe, useful thing to build is therefore the **measurement path**: implement the
   candidates properly, measure whether they separate the bot's own outcomes, and
   let the evidence decide.
2. **“Self journal the buy/sell and see the success rate.”** This can be built
   now, display-only, from data already tracked. No engine change and no second
   source of truth are needed: every decision is derivable from
   `forward_test_log.csv` (the bar the engine acted on) + `trades.csv` (what
   happened) + `status.json` (the open trade).

Delivered in this session:

| file | what it does |
|---|---|
| `indicators.py` | 18 causal candidate fields in 13 families (ADX/DMI, MACD, Bollinger %B/bandwidth, Stochastic, Keltner, Donchian, efficiency ratio, ATR percentile, RVOL, RSI slope, body, close-location, gap) — deterministic, stdlib-only, **causal**; plus descriptions, pre-declared splits and the direction rules. |
| `journal.py` | the self-journal read layer: one record per closed trade with the pre-entry context, outcome, R, MFE/MAE and a one-line thesis; success accounting (decisive WR with Wilson CI, all-in rate, R/trade, payoff, profit factor, drawdown, streaks); per-side / per-session / per-day splits; give-back review; open trade; the candidate scoreboard with a permutation guard. |
| `tools/journal_report.py` | prints the journal; `--csv` exports the flat per-trade record; `--json` for machines. |
| `tools/indicator_lab.py` | measures the candidates three ways: on the bot's own entries, on the whole tape (forward drift), and as regime/“when does the tape move” splits. |
| `dashboard.py` | a fifth tab, **📓 Journal** (`?tab=journal`): the same read layer rendered — success cards, newest pages, side/session tables, the last 14 entry days, what the journal noticed, what the risk layer blocked, and the measured indicator scoreboard. Display-only. |
| `tools/test_indicators.py`, `tools/test_journal.py` | 17 + 17 hermetic tests. `smoke_test.py` **Scenario X** adds the accounting + noise-floor checks to the deploy gate. |

---

## 2. The candidate indicators — and why these

The engine already reads: EMA50/EMA200 + 30-bar slope + 0.3 ATR proximity, RSI
window (BUY 30–68 / SELL 32–70), ATR bounds 1.10–4.50, the 20-bar floor/ceiling
with a 0.38 wick rejection, and a disabled volume gate. The candidates were chosen
to be **new information**, not a re-skin of those:

| candidate | what it adds that the engine cannot see |
|---|---|
| ADX (14) + ±DI | trend **strength** and a direction — the engine knows the EMA direction, not whether the tape is trending or flat |
| MACD (12/26/9) | a slower momentum view than RSI/level |
| Bollinger %B (20, 2σ) | how extreme a rejection is inside a volatility band |
| Bollinger bandwidth | compression/expansion — ATR bounds are fixed dollars |
| Stochastic %K/%D | a shorter-cycle overbought/oversold read |
| Keltner position | close vs EMA20 in **ATR** units (an ATR-scaled second band) |
| Donchian position | the 20-bar box as one number (deliberately kept to test collinearity) |
| Efficiency ratio (30) | a deterministic chop read (net travel ÷ total travel) |
| ATR percentile (200) | regime-relative volatility instead of fixed dollar bounds |
| RVOL (20) | participation — **tick volume**, not traded contracts (see §5) |
| RSI slope (5) | the RSI direction, not just its level |
| Body / close-location / gap | one-bar candle anatomy and discontinuity |

**Deliberately absent:**

* **VWAP / volume profile** — the feed carries MT5 *tick count*. A VWAP on it is a
  guess in a formula, and a volume profile is worse.
* **Fibonacci / pivots / round numbers** — unmeasured levels; the proposal that
  built the Chart tab already refuses them.
* **RSI divergence, trendlines, H&S, Elliott** — the swing definition is
  subjective; two people get two answers, so it cannot be pre-registered.
* **Ichimoku / Supertrend / Hull** — more moving averages of the same closes;
  they would be tested as MACD-like momentum, not as new information.

The full definitions live in `indicators.DESCRIPTIONS`; the splits and direction
rules are in `indicators.SPLITS` / `DIRECTIONAL_RULES` and are declared **before**
the outcomes are looked at.

---

## 3. Result 1 — on the bot's own entries, no candidate earns a place

Method: for each closed trade in the structural-stop era, take the **last log bar
strictly before the entry minute** (the same convention as the pressure
calibration; the entry bar itself is never used). Split the 198 entries at the
pre-declared threshold, compare **decisive WR** (TP/(TP+SL)) and R/trade between
the two buckets, and check:

* **family-wise noise floor** — shuffle the outcomes 200 times and record the best
  lift random labels produce *across all 18 features and both directions*; the
  real best lift must clear the 95th percentile;
* **split-half stability** — the same sign in both halves of the sample;
* **redundancy** — |correlation| with side / RSI / ATR / EMA-spread must stay
  below 0.70.

Measured on the 198-entry era (144 decisive):

| candidate | split | high bucket WR (dec) | low bucket WR (dec) | lift | verdict |
|---|---|---|---|---|---|
| RVOL (20) | ≥1 / <1 | 47.7% (31/65) | 30.4% (24/79) | **+17.3 pp** | inside noise |
| ATR percentile (200) | ≥50 / <50 | 32.1% (25/78) | 45.5% (30/66) | −13.4 pp | inside noise |
| Bollinger bandwidth | ≥0.162 / <0.162 | 31.9% (22/69) | 44.0% (33/75) | −12.1 pp | inside noise |
| 20-bar range position | ≥0.5 / <0.5 | 32.4% (24/74) | 44.3% (31/70) | −11.9 pp | inside noise |
| Bollinger %B | ≥0.5 / <0.5 | 32.4% (23/71) | 43.8% (32/73) | −11.4 pp | inside noise |
| +DI vs −DI | agrees with side / against | 40.2% (47/117) | 29.6% (8/27) | +10.5 pp | inside noise |
| Stochastic %K | ≥50 / <50 | 32.8% (22/67) | 42.9% (33/77) | −10.0 pp | inside noise |
| Gap from prior close | ≥0 / <0 | 42.9% (33/77) | 32.8% (22/67) | +10.0 pp | inside noise |
| MACD histogram | ≥0 / <0 | 33.8% (23/68) | 42.1% (32/76) | −8.3 pp | inside noise |
| Candle body | ≥0 / <0 | 41.9% (31/74) | 34.3% (24/70) | +7.6 pp | inside noise |
| Close location in bar | ≥0.5 / <0.5 | 41.7% (30/72) | 34.7% (25/72) | +6.9 pp | inside noise |
| Efficiency ratio (30) | ≥0.3 / <0.3 | 43.3% (13/30) | 36.8% (42/114) | +6.5 pp | inside noise |
| Keltner position | ≥0 / <0 | 35.1% (26/74) | 41.4% (29/70) | −6.3 pp | inside noise |
| Stochastic %D | ≥50 / <50 | 35.7% (25/70) | 40.5% (30/74) | −4.8 pp | inside noise |
| +DI (14) | ≥21.9 / <21.9 | 38.8% (31/80) | 37.5% (24/64) | +1.2 pp | inside noise |
| RSI slope (5) | ≥0 / <0 | 38.8% (26/67) | 37.7% (29/77) | +1.1 pp | inside noise |
| −DI (14) | ≥22.4 / <22.4 | 38.6% (27/70) | 37.8% (28/74) | +0.7 pp | inside noise |
| ADX (14) | ≥20 / <20 | 38.1% (40/105) | 38.5% (15/39) | −0.4 pp | inside noise |

`n dec` = decisive trades in that bucket. All 18 rows are inside the family-wise
noise floor; the split values are pre-declared (`indicators.SPLITS`), except the
median splits, which are fitted to this sample (one number per feature, named in
the table and covered by the §5 limits).

**The best-looking bucket is RVOL at +17.3 pp — and random labels produce a best
lift of +25.0 pp on this design 95% of the time (global p = 0.525).** The R/trade
view agrees: best +0.315R vs a null 95th percentile of +0.463R (p = 0.510).

That is not a defect of RVOL. It is what 18 looks at 144 decisive trades can
produce: the confidence interval on a 65-vs-79 split is ±12 pp, and picking the
largest of 18 such gaps is exactly how a backtest invents an edge. The honest
answer on this sample is **no measured addition**.

Two other findings worth recording:

* **The DI-vs-side row is near-tautological, and still does not help.** The engine
  only trades with the trend, so ±DI usually agrees with the side (117 decisive
  trades agree, 27 disagree). Those 27 are the interesting cells — and they win
  29.6% (8/27, a CI wide enough to contain everything), so the "agrees" bucket's
  40.2% is mostly restating the trend gate rather than adding information. The
  board reports it because it is a real split, not because it is a candidate.
* **The engine's own filters leave little room.** RSI is already confined to
  30–70, ATR to 1.10–4.50, and entries sit near the EMA. A candidate that helps on
  the whole tape has less opportunity inside the slice the bot already selected.
  That is why §4 matters as a second, independent read.

Re-run: `python3 tools/journal_report.py` (or `tools/indicator_lab.py`).

---

## 4. Result 2 — on the whole tape, the candidates do not predict direction

Method: every candidate becomes its own deterministic direction rule
(`DIRECTIONAL_RULES`), sampled every 30 bars, forward drift measured over the next
30 minutes with windows censored at log gaps (no guessing across a closure), hit
rate with a Wilson CI against the 50% driftless reference. Nine rules = nine
looks, so the adoption line also includes a Bonferroni correction (p < 0.0056).

Snapshot: the tracked log 2026-09-01 → 2026-10-23 (1,606 usable non-overlapping
windows; median |30-min drift| 2.50 ATR; always-BUY 47.1% [44.7–49.6]).

| rule | n | hit rate [95% CI] | median favourable drift |
|---|---|---|---|
| EMA50 vs EMA200 (baseline) | 1,600 | 49.1% [46.6–51.5] | −0.06 ATR |
| MACD histogram sign | 1,605 | 49.5% [47.0–51.9] | −0.04 ATR |
| ADX ≥20 with ±DI | 1,047 | 49.4% [46.4–52.4] | −0.04 ATR |
| Stochastic %K vs %D | 1,606 | 49.4% [46.9–51.8] | −0.05 ATR |
| Bollinger %B >0.5 | 1,606 | 49.1% [46.6–51.5] | −0.07 ATR |
| 20-bar range position | 1,606 | 48.8% [46.3–51.2] | −0.10 ATR |
| Efficiency ratio ≥0.3 | 312 | 50.0% [44.5–55.5] | +0.02 ATR |
| RSI slope sign | 1,602 | 49.9% [47.4–52.3] | +0.00 ATR |
| Last bar body sign | 1,563 | 49.3% [46.9–51.8] | −0.07 ATR |

**Every 95% CI straddles 50%, and no rule survives the multiple-look correction.**
This is the same answer the 2026-10-19 signal-outlook read gave (50.4% at 30m on
the bot's 8/8 signals), now confirmed on the raw tape and a broader indicator set.

The third read — “when does the tape move?” — is direction-free and also negative
for the actionable version: high-ADX windows had a **lower** median |drift| (2.33
ATR) than low-ADX ones (2.86 ATR), and the ATR percentile, efficiency ratio and
RVOL splits moved the median |drift| by less than 0.25 ATR. A regime read is not a
direction read; it cannot pick a side, and on this sample it does not even select
a meaningfully bigger move.

**Verdict for “more indicators”: NO — not on this sample.** Nothing here is worth
adding to `engine.py`. The useful output of the exercise is the measurement path
itself: the next indicator idea can be scored in one command instead of argued
about.

---

## 5. What would it take to adopt one anyway?

A candidate that ever clears the board needs, in this order:

1. **A dated pre-registration** written before the data is used, naming: the
   feature, the exact split, the bucket sizes, the primary metric (decisive WR or
   net R/trade at a stated cost), the minimum effect, the sample/time gate, and
   the revert rule.
2. **Out-of-sample confirmation** — the split-half check here is a screen, not a
   confirmation. The large-N path (`tools/history_to_log.py` →
   `strategy_lab.py --bars`) exists for this and is still a first-run-on-the-box
   task.
3. **A costed, stateful replay** with `tools/strategy_lab.py` across all parameter
   eras; a candidate that only works on the current era is noise.
4. **One variable at a time.** The structural-stop window is open and its §7
   closure-gap REVERT trigger has fired; the pre-registered response takes
   precedence. Nothing may be stacked on it.
5. **Owner sign-off**, then the deploy gate (smoke scenarios, cutover from the
   autosync commit time, not the plan).

Also binding: the candidates' *definitions* are not thresholds to tune. If a split
is changed after seeing an outcome, the result is a new experiment, not a rescue.

Limits stated with the numbers:

* **n=198 / 144 decisive** in the era; the Wilson CI on a half-sample is ±12 pp.
  “Inside noise” means exactly that — not “proven useless”.
* **Overlapping information.** RVOL, body and close-location all partly measure the
  same bar; Donchian position is largely the 20-bar level the engine already uses.
  The redundancy column in the board makes this visible.
* **Tick volume.** RVOL cannot be read as traded size, and its +17.3 pp bucket is
  the least trustworthy cell in the table for that reason.
* **Selection.** The median splits are fitted to the sample (one number per
  feature); the permutation guard covers the *feature/direction selection*, not
  that fitting. It is a screen, not a p-value to quote.
* **One tape.** Gold fell over much of this log (median 30-min drift −0.29 ATR).
  A direction rule tested across one regime can look balanced by luck.

---

## 6. The self-journal — what it records and what it says

### 6.1 How a page is built

For every closed trade:

* the **context** is the last log bar strictly before the entry minute: the
  engine's logged RSI/ATR/wick/EMAs, the 20-bar floor/ceiling distance in ATR,
  range position, session, and the 18 candidate fields;
* the **thesis** is a one-line deterministic summary, e.g.
  `SELL · 20-bar ceiling +3.23 ATR · upper wick 60% · RSI 48.6 · EMA −0.90 ATR · ADX 19 weak · ER 0.17`;
* the **outcome** is the ledger's own exit reason, R from the reward leg
  (`|TP − Entry| ÷ 1.5`, never the ratcheted stop), hold time, MFE/MAE from the
  bars after the entry bar;
* the **success accounting** is explicit: decisive WR = TP/(TP+SL) with a Wilson
  CI; all-in = TP/all; R/trade includes BE and TIME; net charges the assumed
  $0.40 round trip on **every** closed trade, scratches included.

The journal is **derived, not written**. It cannot disagree with the ledger, and
re-running it fills in history rather than starting from today. The dashboard
rebuilds it on demand (cached ~2 minutes); `--csv` is an explicit export.

### 6.2 The book at 2026-10-23 11:59 UTC

| slice | n | record | decisive WR [95% CI] | R/trade | net at $0.40 |
|---|---|---|---|---|---|
| all closed | 695 | 140W/300L/253BE/2TIME | 31.8% [27.6–36.3] | −0.13R | −$649.24 |
| **struct-stop era** | **198** | **55W/89L/53BE/1TIME** | **38.2% [30.7–46.3]** | **−0.03R** | **−$131.63** |
| pre-struct-stop | 497 | 85W/211L/200BE/1TIME | 28.7% [23.9–34.1] | −0.18R | −$517.61 |
| last 7 entry days | 71 | 18W/29L/24BE | 38.3% [25.8–52.6] | −0.03R | −$33.35 |
| today (entry date) | 8 | 2W/4L/2BE | 33.3% [9.7–70.0] | −0.13R | −$7.26 |

Payoff 1.55 : 1, breakeven WR **39.3%**, profit factor 0.72. The era's 38.2% is
above the old uncosted 32.1% line and below the **costed** breakeven — which is
the same conclusion as the 2026-10-19 judgement: **SCREEN MET, no demonstrated
edge, PASS not met**. The journal does not re-judge the experiment; it just puts
the arithmetic in one place.

**Two R/trade conventions, deliberately both visible.** The journal averages each
trade's own R (`Profit ÷ that trade's risk`) and calls it **mean R/trade** — the
era reads **−0.03R**. `pressure_report.py` and HANDOFF §1 divide the era's gross $
per trade by the *mean* 1R — **−0.046R**. They differ only because risk size varies
across trades; neither is wrong, and the journal never silently mixes them.

By side (all eras): BUY 27.4% decisive / −0.22R −$424.88; SELL 36.0% / −0.06R
−$224.36. By session: Asia/rollover 37.5% / −0.04R; London/NY 27.4% / −0.20R —
the same descriptive gap the 2026-10-05 review downgraded to a **proxy for stop
geometry**, not a gate.

### 6.3 What the journal noticed

* **140 of 695 trades (20.1%) were at least +0.75R ahead at some point and did not
  finish there.** Of those, 133 scratched on the ratchet and 6 gave the gain back
  and hit the stop; 46 winners first ran ≥0.5R against. **Median give-back
  (peak minus final) +1.06R; the sum of those give-backs is 154.5R** — it is a
  record of what the exit rule chose, not an unused profit forecast.
* This is the trade-off the 0.75R ratchet was *chosen* for: the 2026-09-15 review
  showed the 0.30R version converted ~$222 of runs into $0. The journal records the
  cost of that choice; it does not argue for removing it (and removal was already
  measured and rejected on 2026-10-05).
* The largest pages are listed in the tab (`#187 BUY BE +1.50R→0.00R`,
  `#596 BUY BE +1.48R→0.00R`, `#526 BUY TIME +1.45R→+0.05R`).
* The risk layer blocked 35 engine signals in the last 24 h of the skip log — 24
  SL cooldowns and 11 blackouts. `skipped_trades.csv` logs no side, so these are
  counts, not a success rate; the blocked-signal research stays in
  `tools/phantom_trades.py`. The journal anchors its 24-hour window to the
  **newest skip row**, not the wall clock, so re-running it later prints the same
  number; `pressure_report.py` uses the wall clock (29 in the same run), which is
  why the two panels can differ by a few rows.
* The open trade #697 BUY (entry $4027.91, stop $4019.21, target $4040.96) is
  shown as an **unfinished page** and is excluded from every rate.

### 6.4 The 📓 Journal tab

The tab (`?tab=journal`) renders the same read layer, server-side, in the
dashboard's existing card language:

* four headline cards — decisive WR for the current rule (with its CI), the
  record, net at the assumed cost, and expectancy/payoff/breakeven;
* today and the last 7 entry days;
* the open page, clearly marked as **not counted** and re-priced from the newest
  logged close on every request;
* the newest 12 pages (side, exit, R, MFE, MAE, hold, and the one-line thesis);
* per-side and per-session tables, the last 14 entry days, the give-back review
  and the blocked-signal counts;
* the candidate scoreboard with its family-wise verdict and noise floor.

It is cached for 120 s and keyed on **both** `trades.csv` and `status.json`, so a
new open/close rebuilds it instead of showing the previous trade. Only the
trimmed view is cached — never the 50k-bar series or the 695 entry records — so
the dashboard process does not pin tens of megabytes. The panel has no form, no
button that acts, and imports no engine module.

### 6.5 What “success rate” means here

| term | definition | why it is not the only number |
|---|---|---|
| decisive WR | TP/(TP+SL) | excludes BE/TIME, so it flatters a strategy that scratches a lot |
| all-in | TP/all closed | counts every scratch against |
| R/trade | mean Profit ÷ actual risk | size-neutral; includes BE/TIME |
| net at $0.40 | gross − $0.40 × trades | the cost model is assumed, not measured yet |
| payoff / breakeven | avg win ÷ avg loss; 100/(1+payoff) | the live 1.55:1 needs **39.3%**, not 40% |

The dashboard shows decisive WR, all-in, net, R/trade, payoff and breakeven side by
side precisely so no single rate can be read as the verdict.

---

## 7. How to use it

```bash
# the journal (text) + scoreboard on the current-rule entries
python3 tools/journal_report.py

# flat per-trade record for a spreadsheet
python3 tools/journal_report.py --csv journal.csv

# the indicator lab (board + whole-tape walk + regime table)
python3 tools/indicator_lab.py
python3 tools/indicator_lab.py --era all --permutations 500
python3 tools/indicator_lab.py --json

# the page
GOLD_DATA_DIR=. python3 dashboard.py        # ?tab=journal
```

Both tools are read-only and exit 0. The dashboard tab is display-only: no form,
no order, no write, and it never imports the engine.

---

## 8. Verification (this session)

| check | result |
|---|---|
| `python3 tools/test_indicators.py` | **17 pass** |
| `python3 tools/test_journal.py` | **17 pass** |
| `python3 tools/smoke_test.py` | **SMOKE TEST PASSED** (Scenario X added: journal accounting, open-trade exclusion, reward-leg risk, give-backs, CSV header, real separation flagged, noise not rescued) |
| `python3 tools/test_dashboard_context.py` (Flask in a temp venv) | **15 pass** (Journal tab render added) |
| `python3 tools/test_manual_chart.py` / `test_box_alert.py` / `test_box_report.py` / `test_box_watch.py` / `test_signal_outlook.py` | 32 / 34 / 14 / 6 / 9 pass |
| `python3 -m py_compile` (engine, filter, pressure, chart, journal, indicators, dashboard, all tools) | OK |
| `python3 tools/check_data.py` | 0 fail / 8 warn |
| `python3 tools/check_structural_stop.py` | PASS at n=198, 0 stops inside the level |
| `python3 tools/check_gap_rides.py` | still **2/2**, trigger at threshold |
| `python3 tools/pressure_report.py` | era n=198, SCREEN MET, all five checks inside their bars |
| dashboard render | 200; journal tab present; page build ~3.9 s first time, ~1.1 s cached |

Not run: anything on the production host, a Telegram send, or a real deploy. The
dashboard-only change still needs **owner sign-off** before deploy (a
`dashboard.py`/`journal.py`/`indicators.py` change restarts the dashboard only,
never `goldbot`).

---

## 9. Files and what changed

* **new** `indicators.py`, `journal.py`
* **new** `tools/journal_report.py`, `tools/indicator_lab.py`,
  `tools/test_indicators.py`, `tools/test_journal.py`
* `dashboard.py` — import + cached `journal_context()` + 📓 Journal tab
  (`?tab=journal`); no trading path touched
* `tools/smoke_test.py` — Scenario X
* `tools/test_dashboard_context.py` — TABS assertion + Journal tab render test
* `docs/HANDOFF.md` — snapshot/data refresh + §1/§4/§5/§6/§9/§10/§11 and the era
  timeline; §1 replaced block archived to `docs/HANDOFF-HISTORY.md`
* this document; `docs/EXECUTION-PLAN.md` and `README.md` tool index;
  `archive/PROJECT_LOG.md` entry
