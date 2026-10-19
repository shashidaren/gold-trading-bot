# ANALYSIS 2026-10-19 — signal outlook: where does price head after a very strong signal?

**Status:** shipped on the branch, **display-only / read-only**. No `engine.py` /
`trade_filter.py` change, no parameter, gate, exit or strategy change — the open
**struct-stop window** (entries ≥ 2026-10-06 03:00 UTC) and its 2026-10-19 21:00 UTC
judgement are untouched.

**Owner ask:** "trading seems extremely difficult to do this manually from candle
pattern — could we have a rough estimate where it's headed given very strong signal?"

**Short answer:** yes, a rough estimate now exists (`tools/signal_outlook.py` + the
dashboard 🧭 panel) — but on this bot's own history the honest estimate is a **cone
centred near entry with coin-flip direction**, not an arrow. After the bot's strictest
signal (all 8 gates — what "very strong" means here), price 30 minutes later had
closed the trade's way **49% of the time [95% CI 41–57]** in the live-rule era, with a
median move of **−0.02R**. What *can* be estimated reliably is how far price typically
travels in **both** directions and how often the target prints before the stop
(~1 time in 3, vs the 40% the 1:1.5 geometry needs). Manual candle-reading feels
impossible at these horizons because, in this data, the direction after even an 8/8
pattern carries no measurable short-horizon edge over following the EMA trend
anywhere. Details, limits and the worked live example below.

**Files:** `pressure.py` (`signal_outlook` / `outlook_now`, section 5b — same
read-only layer as the pressure panels), `tools/signal_outlook.py` (new CLI),
`dashboard.py` (🧭 panel, 10-min cached like the calibration join),
`tools/test_signal_outlook.py` (9 hermetic tests), `README.md`, `docs/HANDOFF.md`.

---

## 1. Method (read before quoting any number)

- **"Very strong signal" = a trade the engine actually took.** Every row of
  `trades.csv` passed all funnel gates *and* the risk layer, so the ledger is the
  ground-truth sample — no second funnel implementation that could drift from
  `engine.py`. Skipped signals are excluded by design: `skipped_trades.csv` logs no
  side. The one-position rule censors overlapping signals; this measures the signals
  the bot acted on.
- **Forward walk:** for each entry, bars stamped *strictly after* `Entry_Time` in
  `forward_test_log.csv` (the signal bar's own range is never counted), out to
  15/30/60/240 minutes of wall clock (240 = `MAX_HOLD_MINUTES`, a trade's full life).
- **Censoring, never guessing:** a window is dropped (and counted) if any log gap
  inside it exceeds 5 min, if the last bar falls >2 min short of the horizon
  (closure / end of log), or if <70% of the 1-min bars are present.
- **Units:** drift signed the trade's way (+ = favourable), in **R** where risk is the
  repo's reward leg `|TP − Entry| / 1.5` (ratcheted rows keep their original geometry,
  HANDOFF §8), and in **ATR** (`ATR_At_Entry`). A SELL's favourable extreme is the bar
  **LOW**. MFE/MAE are full-window path extremes (exits ignored). The **barrier race**
  is the first touch of +1.5R vs −1R on the raw path, *without* the breakeven ratchet;
  a single 1-min bar spanning both is counted separately ("same-bar", 0 in every cell
  below — the barriers are simply too far apart for one minute at these R sizes).
- **Splits are the repo's pre-existing ones:** by side first (HANDOFF §8 — pooled
  direction claims are the momentum trap), eras `structstop` (live rule) and `075`
  (≥2026-09-15 06:00). No new bucket was invented to make the numbers nicer; the one
  exploratory slice (wick size, §4) is labelled as such.
- **Baseline:** non-overlapping every-Hth-bar drift in the EMA50-vs-EMA200 direction,
  same era, same censoring — "just follow the trend anywhere". If the signal rows do
  not beat it, the candle pattern added no measured direction.
- Data: checked-in CSVs, 44,623 log bars to 2026-10-19 14:59 UTC, 632 closed trades.
  `tools/check_data.py` 0 fail (8 documented warns) before measuring. Reproduce with
  `python3 tools/signal_outlook.py --root .` (and `--era 075`).

## 2. Live-rule era (struct-stop, n=135: 65 BUY / 70 SELL; ledger hold median 25 min, p90 84)

Closed the trade's way at the horizon (Wilson 95% CI); median drift; target-first share
of decisive races vs the **40%** driftless reference for +1.5R/−1R barriers (the target
is 1.5× further, so 50% is the wrong yardstick):

| sample | horizon | n | closed its way | > $0.40 cost | median drift | race TGT:SL (neither) | target-first |
|---|---|---|---|---|---|---|---|
| BUY | 15m | 65 | 40.0% [29–52] | 35.4% | −0.17R / −0.56 ATR | 5:8 (52) | 38.5% [18–64] |
| BUY | 30m | 65 | 49.2% [37–61] | 47.7% | −0.09R | 14:20 (31) | 41.2% [26–58] |
| BUY | 60m | 64 | 46.9% [35–59] | 43.8% | −0.12R | 17:32 (15) | 34.7% [23–49] |
| SELL | 15m | 70 | 50.0% [39–61] | 38.6% | −0.00R / −0.02 ATR | 3:18 (49) | 14.3% [5–35] |
| SELL | 30m | 70 | 48.6% [37–60] | 44.3% | −0.02R | 9:28 (33) | 24.3% [13–40] |
| SELL | 60m | 70 | 52.9% [41–64] | 51.4% | +0.12R | 18:35 (17) | 34.0% [23–47] |
| Pooled | 30m | 135 | **48.9% [41–57]** | 45.9% | **−0.02R**, cone [−0.67R, +0.62R] | 23:48 (64) | 32.4% [23–44] |
| Pooled | 60m | 134 | 50.0% [42–58] | 47.8% | −0.02R | 35:67 (32) | 34.3% [26–44] |
| Pooled | 240m | 114 (21 cens.) | 50.9% [42–60] | 50.9% | +0.08R | 44:67 (3) | 39.6% [31–49] |

Path travel (pooled medians): by 60m price had typically been **+1.02R** the trade's
way at its best *and* **−1.03R** against it at its worst (MFE/MAE). At 30m, 64 of 135
signals had touched **neither** barrier — most "where is it headed?" answers at trade
horizons are honestly "still between the stop and the target, having visited both
sides of entry".

**Baseline (same era):** trend-anywhere closed the trend's way 49.6% [45–54] at 30m
(median −0.01 ATR, n=425) vs the signals' median −0.08 ATR. The 8/8 pattern does not
beat "be aligned with the EMAs somewhere" on short-horizon direction in this era.

## 3. Larger sample (0.75R era, n=457 — older 2·ATR stop before 2026-10-06)

Same shape with tighter intervals: pooled closed-its-way 43.3% [39–48] @15m, 48.3%
[44–53] @30m, 49.7% [45–54] @60m; target-first 28.4% [23–35] @15m, 33.0% [28–38]
@30m (113:229 — the CI sits *below* the 40% barrier reference), 38.1% [33–43] over
the full 240m life. Note the whole-book side asymmetry (SELLs look "better" than BUYs,
e.g. 60m favourable 57.7% vs 43.3% across all 632 trades) is the §8 regime artefact:
gold fell from ~$4,483 to ~$4,146 across the sample and side ≈ trend direction. In the
live era both sides sit at ~50% — do not read the pooled history as "SELL signals
predict better".

## 4. Does a *stronger-looking* candle help? (exploratory — no bar proposed)

Wick ratio at entry (all signals already ≥38%), pre-registered-style buckets
38–55 / 55–75 / 75%+, 30-min forward walk: target-first share was 30–34% in **every**
bucket in both eras, and the biggest wicks (75%+) had the *worst* median drift
(−0.67R, n=44, 0.75R era; −0.52R, n=14, live era). Small cells, post-hoc slice —
reported only to close the obvious follow-up: there is currently no measured
"even stronger subset" to point an arrow at, and the tape-pressure composite cannot
supply one either (collinear with side, ANALYSIS-2026-10-16). Any such subset would
need a dated pre-registration + `strategy_lab.py` before it could gate anything.

## 5. What shipped, and the live example

`tools/signal_outlook.py` prints: (1) **NOW** — if a side passes 8/8 on the last
closed bar, today's entry/stop/target plus the era base rates transferred onto
today's risk (cone = entry ± historical drift-R quartiles × today's risk — an
assumption printed with the numbers); (2) the §2 tables per side; (3) the baseline;
(4) reading limits. The dashboard 🧭 panel renders the same core
(`pressure.outlook_now`, cached 10 min like the calibration join; a dashboard change
restarts only the dashboard — `docs/AUTOSYNC.md`).

The checked-in data ends on exactly such a bar — **2026-10-19 14:59 UTC: SELL 8/8**
at $4,145.60 (stop $4,149.58, target $4,139.63, risk $3.98). The rough estimate from
the 70 live-era SELLs:

> +30m: median ≈ **$4,145.69** (i.e. about where it started), middle-50% cone
> **$4,143.62–$4,148.12**; closed lower (SELL's way) 49% [37–60] of the time; target
> reached before stop in 24% [13–40] of decisive 30-min races; in 33/70 cases neither
> barrier had printed by 30m. Typical travel by 30m: ~$2.47 favourable / ~$3.26
> adverse at the extremes (median MFE 0.62R / MAE 0.82R × $3.98).

That is the correct mental model for manual supervision: expect chop around entry
with excursions both ways; the trade's edge (if any) lives in the stop/target/ratchet
geometry over its full life, not in a predictable heading over the next few candles.

## 6. What this does NOT authorize

- **Not a forecast and not an entry/hold/size input.** No number here may enter
  `engine.py`/`trade_filter.py` without a pre-registered bar (HANDOFF §11); this doc
  is not one. In particular it must not be used to hold past a stop ("the cone says
  it comes back") — the same tables show the adverse tail travels just as far.
- **Not evidence of edge.** The book remains paper-only and negative at the assumed
  $0.40 round trip (HANDOFF §1); the race shares below the 40% geometry reference at
  15–60m are consistent with that, and the ~40% at 240m is what a driftless path with
  these barriers produces. The struct-stop judgement (2026-10-19 21:00 UTC / n=150)
  remains the only live experiment and is judged on its own §7 bar, not on this.
- **Not a licence to pool sides or eras.** Every renderer shows side + era + n + CI
  next to each number; quoting a bare "49%" without them recreates the §8 trap.

## 7. Verification

- `python3 -m unittest tools.test_signal_outlook tools.test_dashboard_context` — 13
  tests pass (incl. Flask render with the new panel; run under a venv with `flask`,
  which this sandbox lacked — hosted box already runs the dashboard).
- `python3 tools/smoke_test.py` — **PASSED** (Scenario U's AST checks confirm the new
  `pressure.py` code stays stdlib-only and write-free; no engine constant drifted).
- `python3 tools/signal_outlook.py --root .` (struct-stop + `--era 075`, `--json`)
  and `python3 tools/pressure_report.py --root .` — run clean; the outlook numbers
  reproduce an independent exploratory script cell-for-cell before being committed.
- `python3 tools/check_data.py` — 0 fail (pre-existing 8 warns). No runtime file,
  CSV or `status.json` was modified by this work (`git diff` shows docs + read layer).
