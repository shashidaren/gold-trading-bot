# Reversal-Before-TP Pain-Point Audit & Post-Window Enhancement Queue (2026-11-27)

**Status:** dated empirical analysis + planning backlog update (`docs/EXECUTION-PLAN.md` §2j / §3 **A9**).
**Paper-only — NO `engine.py` / `trade_filter.py` / strategy / parameter / cost / ledger / order-path change.**
Market is closed at the snapshot (**2026-11-27 17:59:02 UTC**, data collection **607**); `SL_CLEAR_ATR` stays `0.5`, `BE_TRIGGER_R` stays `0.75`, `RR_TARGET` stays `1.5`, `TRADING_MODE` stays `FORWARD_TEST`, and **$0.40 round trip ($0.20/side) stays registered** through `2026-12-01 21:00 UTC` (`docs/REVIEW-2026-11-22-a6-cost-decision.md`).

---

## 1. Snapshot & Session Ritual Baseline (Collection 607)

All checks below ran on the synced checkout at `3c59e6b` (`2026-11-27 17:59:02 UTC`):

| Check | Result on Collection 607 |
|---|---|
| `tools/check_data.py` | **0 fail / 9 documented warnings** · 1,079 closed trades, 83,215 M1 bars (`2026-09-01 14:25:02 → 2026-11-27 17:59:02`), 2,404 skipped signals, no open trade (`next_trade_num: 1080`) |
| Whole book | **241W / 474L / 360BE / 4TIME** · **33.7% decisive WR [30.3–37.3]** (cost-free 1:1.5 breakeven = 40.0%) · scratch 33.4% · gross **−$422.26 (−$0.391/t, −0.075R/t)** · engine ledger **$94.68** / true equity **$77.74** (drift $16.94) · net at registered $0.40 **−$853.86 (−0.152R/t)** · diagnostic all-in $0.57 (`cost_model.py`): **−$1,037.25** |
| Structural-stop era (`>= 2026-10-06 03:00`) | **n = 582** (**156W / 263L / 160BE / 3TIME**) · decisive **37.2% [32.7–42.0]** · gross **−$103.45 (−$0.178/t, −0.028R/t on pressure scale; −0.049R/t on runway scale)** · SL/day 5.98 · SL share 45.2% · scratch 27.5% · avg SL $6.22 · era DD $207.87 · B1–B3, C1–C2, A4–A5 OK; R4/R5 clear |
| Recent 100 trades (`#980..#1079`) | **29W / 39L / 31BE / 1TIME** · **42.6% decisive** · gross **+$40.30** · net at $0.40 **+$0.30** (sampling variance inside one month, not a cleared bar) |
| `tools/check_structural_stop.py` | **PASS** · 0/582 stops inside level · 81.6% level-bound · +0.50 ATR median clearance · 3.09 ATR median risk |
| `tools/check_gap_rides.py` | **9** scheduled-closure rides (registered §7 threshold 2; 1 reopen gapped through stop: `#815 −$2.77`; 0 worse exits; 4 scratch stops; 0 weekend rides) |
| `tools/xm_quote_report.py` | **42/14 complete UTC days, 5/2 weekends** · 88,505 fresh rows · median round trip **$0.55** across 501 matched trades · EU DST rule 100.00% · spec `2026-11-27 14:27:56 UTC` (`REAL`, 1:1000, build 6230, IOC, min 0.01 / step 0.001 / max 50, spread 55 pts) |
| `tools/equity_runway.py` | Burn **−$0.69/t** at $0.40 → **~112 trades (~8.5 trading days)** to $0.00 (diagnostic at $0.57: **−$0.86/t → ~90 trades / ~6.8 trading days**; 90% CI 108–1675). Owner policy **"no rebaseline ever — let it go negative"** unchanged |
| `tools/live_readiness.py` | **17 PASS / 0 TODO / 3 MANUAL · LIVE GATE CLOSED** |
| `tools/feed_forensics.py --days 14` | **1 flagged hole: `BOTH FEEDS DOWN 2026-11-26 19:27 → 20:55` (88 open min, 0 exposed trades).** Inspection of `xm_data/quotes-2026-11-26.csv` confirms live ticks through `19:24:30` then `NOOFFSET` through `23:00:00` — coinciding with the **2026-11-26 US Thanksgiving early market close**, which falls outside `xm_quote_report.in_closed_window()`'s regular `20:55–23:10` rule. **Zero trades were exposed** |

Gold declined **−$837/oz** over the forward test (`$4,373.88` on 2026-09-01 → `$3,646.52` on 2026-11-27; ATR `$2.39`).

---

## 2. Why Trades Reverse Before Hitting TP (Empirical Pathwalk, `n = 582`)

The owner's core observation — both automated and manual trades move sharply into profit and then reverse before TP — is exact in the data:

- **Favourable excursion vs conversion (`trades.csv` + M1 `forward_test_log.csv`, struct-stop era `n = 582`):**
  - **62.2%** (`362/582`) printed `MFE >= +0.50R` on closed M1 bars.
  - **54.3%** (`316/582` by outcome geometry: `160 BE + 156 TP`; `295/582` = `50.7%` on M1 bar closes) reached **`>= +0.75R`** and armed the breakeven ratchet — yet only **26.8%** (`156/582`) ever hit the `+1.50R` TP.
  - **Half of all ratcheted runs died at `$0`:** of the `316` trades that armed BE, **`160` (`50.6%`) reversed back to entry**. Among those `160` BE exits, **48.1%** (`77/160`, median MFE **`+1.00R`**) had already reached **`+1.00R` or better**, and **16.2%** (`26/160`) reached **`>= +1.25R`**.
  - **Even full SL trades moved favourably first:** among the `263` SLs (median hold `17.0` min), **52.5%** (`138/263`, median MFE `+0.27R`) printed `>= +0.25R`, and **22.1%** (`58/263`) reached `+0.50R–+0.74R` just short of the BE trigger before stopping out.
  - **Post-SL snap-back:** **25.1%** (`66/263`) of SLs returned to entry within `15` minutes, and **87.9%** (`58/66`) of those touched the former TP within `24` hours — while **34.6%** (`54/156`) of TP winners endured **`>= 0.50R` adverse excursion** on the way to target.
- **No-ratchet R:R sweep (`strategy_lab.py`, `structstop+nord`, post-cutover):**

| Target (`rr`) | Coin-flip `1/(1+rr)` | Replay `decWR` | `n` | Gross R/t | Gross `$` | Net R/t @ $0.40 | Net `$` @ $0.40 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `0.75` | `57.1%` | **`55.3%`** | `703` | `-0.032R` | `-$50.52` | `-0.103R` | `-$331.72` |
| `1.00` | `50.0%` | **`50.7%`** | `611` | `+0.015R` | `+$129.44` | `-0.057R` | `-$114.96` |
| `1.25` | `44.4%` | **`45.1%`** | `528` | `+0.014R` | `+$108.45` | `-0.057R` | `-$102.75` |
| `1.50` | `40.0%` | **`39.6%`** | `474` | `-0.007R` | `+$100.86` | `-0.079R` | `-$88.74` |
| `2.00` | `33.3%` | **`33.9%`** | `418` | `+0.044R` | `+$229.13` | `-0.028R` | `+$61.93` |

Every target ratio lands right on the driftless random-walk curve `1 / (1 + RR)`. Lowering TP raises win rate only linearly along the coin-flip boundary while magnifying the spread penalty per trade; raising TP only helps slightly in gross dollars when BE is off (`33.9%` at `2.0R`) and does not overcome spread on M1.

---

## 3. Five Root Causes Measured on Collection 607

1. **Inert M1 level test & timeframe noise (`engine.py`, `signal_outlook.py`, `box_report.py`):**
   - `FLOOR_BUFFER_PCT = 0.0020` (`$7.29–$8.97` ≈ **3.1–4.5× ATR**) passes ~80–89% of bars, so the bot does not enter at true structural extremes.
   - `signal_outlook.py --era structstop` shows M1 signals sit near `50%` at every horizon (`52.2%` up at 30m vs `50.4%` unconditional baseline), and `box_report.py` shows `74–75%` of M1 box breaks close back inside within 15 minutes.
2. **The `+0.75R` BE ratchet + cooldown-leak churn (`strategy_lab.py`, post-cutover `n = 599` vs `474`):**
   - Because `34.6%` of real TP trades experience `>= 0.50R` retracements and M1 noise regularly retraces `0.75R`, setting the stop to entry turns surviving winners into `$0` scratches while still paying `$0.40–$0.57` round-trip spread — **and** because `BE` exits clear `SL` cooldown (`trade_filter.py`), they trigger immediate re-entries (`+125` extra churn trades post-cutover).
   - **Updated BE-ratchet comparison (post-cutover `83,178` bars — re-opens the 2026-10-05 `n=217` closure for post-`2026-12-01` planning):**

| Variant (post-cutover) | `n` | Outcomes | `decWR` | Gross R/t (`$`) | Net @ `$0.40` (`R/t`, `$`) | Net @ `$0.57` (`R/t`, `$`) | Max DD (`$0.40`) |
|---|---:|---|---:|---:|---:|---:|---:|
| `structstop` (`BE=0.75`, live) | `599` | `158W/261L/176BE/4T` | `37.7%` | `-0.039R (-$94.65)` | `-0.113R (-$334.25)` | `-0.145R (-$436.08)` | `$404.0` |
| `structstop` (`BE=1.00`) | `540` | `174W/262L/98BE/6T` | `39.9%` | `-0.000R (+$23.48)` | `-0.072R (-$192.52)` | `-0.102R (-$284.32)` | `$308.1` |
| `structstop` (`BE=1.25`) | `491` | `175W/264L/39BE/13T` | `39.9%` | `-0.002R (+$108.19)` | `-0.073R (-$88.21)` | `-0.103R (-$171.68)` | `$235.3` |
| `structstop+nord` (`BE=off`) | `474` | `182W/278L/0BE/14T` | `39.6%` | `-0.007R (+$100.86)` | `-0.079R (-$88.74)` | `-0.109R (-$169.32)` | `$222.7` |
| `structstop1.5` (`BE=0.75`) | `482` | `133W/205L/133BE/11T` | `39.3%` | `-0.004R (+$3.60)` | `-0.061R (-$189.20)` | `-0.085R (-$271.14)` | `$329.1` |
| `structstop1.5` (`BE=1.00`) | `434` | `146W/205L/66BE/17T` | `41.6%` | `+0.044R (+$176.10)` | `-0.012R (+$2.50)` | `-0.035R (-$71.28)` | `$231.2` |
| `structstop1.5+nord` (`BE=off`) | `396` | `152W/220L/0BE/24T` | `40.9%` | `+0.035R (+$142.75)` | `-0.020R (-$15.65)` | `-0.043R (-$82.97)` | `$242.7` |

*Note on the Oct 5 closure (`docs/HANDOFF.md` §6 item 2):* On Oct 5 (`n=217`), `structstop+nord` trailed `-0.131R` vs `-0.124R`. On the 2.7× larger post-cutover sample (`n=599`), turning BE off outperforms `+0.75R` by **`+$195.51` gross / `+$245.51` net at `$0.40` (`+$266.76` at `$0.57`)** with **45% lower max drawdown (`$222.7` vs `$404.0`)**, and raises `structstop1.5` by `+$0.041R/t` (`-$15.65` vs `-$189.20` at `$0.40`). Even so, **every M1 variant above still reads negative R/trade after costs**.
3. **Spread drag + `structstop1.5` grown-sample cooling:**
   - Observed median spread is **$0.55** (all-in **$0.57**), consuming **9.1% p50 / 16.6% p90** of 1R (effectively pushing the 1:1.5 breakeven WR to **~43.8%**).
   - Meanwhile, **`structstop1.5`** cooled from `43.1% decWR / -0.000R` on Oct 25 (`n=163`) to **`39.3% decWR / -0.061R` (`-$189.20`) at `$0.40`** (`-0.085R / -$271.14` at `$0.57`) on the full post-cutover tape (`n=482`). It still clears `0.5 ATR`, so G1/A2 remains registered, **but clearance widening alone will not make M1 profitable**.
   - In the live ledger (`n=582`), risk buckets split: `<= 2.00 ATR` (`n=76`, `30.9% dec`, `-$67.03`), `2.01–3.00 ATR` (`n=202`, `40.7% dec`, `+$43.87`), `> 3.00 ATR` (`n=304`, `36.5% dec`, `-$80.29`, where TP sits `4.5–9.0 ATR` away and struggles to finish before M1 reversion).
4. **Macro downtrend vs M1 relief bounces:**
   - In the `struct-stop` era, **`SELL` (`n=336`) is `40.0% decWR / +$91.79 gross`** (`Nov: 41.1% / +$114.40 gross / +$47.60 net at $0.40`), while **`BUY` (`n=246`) bled `33.3% decWR / -$195.24 gross` (`-$293.64` net at $0.40)** — buying M1 counter-trend bounces inside a `-$837/oz` macro decline reverses faster than TP. Note that EMA50 extension filters failed pre-cutover OOS check, so simple M1 distance gates are not sufficient.
5. **`16:00–17:59 UTC` London-close / NY-midday chop (consistent across both eras):**
   - Pre-cutover `0.75R`: `n=33`, `3W/22L/8BE` (**`12.0% decWR`**, `-$76.53` gross).
   - Struct-stop era: `n=47`, `8W/26L/12BE/1T` (**`23.5% decWR`**, `-$76.12` gross).
   - Combined (`n=80`): `11W/48L/20BE/1T` (**`18.6% decWR`**, `-$152.65` gross; BUYs **`3W/26L = 10.3% decWR, -$118.65`**). In `strategy_lab` stateful replay (`$0.40`), blocking `16:00–18:00 UTC` improves pre-cutover (`-0.263R → -0.205R` live; `-0.179R → -0.097R` BE-off) and slightly trims post-cutover (`-0.113R → -0.110R` live; `-0.079R → -0.066R` BE-off). Still insufficient alone — must be tested out-of-sample on large-N history before any pre-registration.

---

## 4. Queued Enhancement Backlog (Added to `docs/EXECUTION-PLAN.md` §3 Track A / A9)

Nothing below changes today's open rules (`SL_CLEAR_ATR = 0.5`, `BE_TRIGGER_R = 0.75`, `$0.40` cost through `2026-12-01 21:00 UTC`). These items enter the plan as **A9** in priority order once the current window / host prerequisites allow:

1. **E1 — Large-N higher-timeframe `goldbot/` validation (`M15`/`H1` via MT5 history dump — top offline priority):**
   - `python3 -m goldbot --compare` on the 88-day log has only `7` trades on `15m` (`4W/1L/2BE`, `80.0% decWR`, `+$75.03` net, cost `3.6%` of 1R) and `1` on `1h` (`+$35.87`, `2.3%` of 1R) — far too few to judge, and moving off M1 cuts spread share from ~10–14% to `2–3.6%` while escaping M1 mean-reversion noise.
   - **Action when host access is run:** execute `tools/mt5_history_dump.py` (`365+` days M1) → `tools/history_to_log.py --dst eu` → `python3 -m goldbot --bars <converted.csv>` and `tools/strategy_lab.py --bars <converted.csv>` (`docs/ACCELERATE-TESTING.md`). Zero live-bot side effects.
2. **E2 — Post-`2026-12-01` BE ratchet removal / raise + cooldown-leak closure (re-opens Oct 5 closure):**
   - Candidate for the **first post-`2026-12-01` pre-registration** (costed at **`$0.57` round trip / `$0.285/side`** per A6): test `BE_TRIGGER_R = None` (off) or `1.0R` (and whether `BE` preserves `SL` cooldown), isolated as one variable after `A2`/`A5` (or instead of stacking on `structstop1.5` only if G1/A2 is revised by the owner).
3. **E3 — ATR-scaled level-test tolerance (`PREREG-2026-10-15-level-test-0.25.md`):**
   - Replace `FLOOR_BUFFER_PCT = 0.0020` with `0.25 ATR` (`~50%` selective vs `~80%` pass-all) — already pre-registered, queued strictly behind `A2`/`A5` (or large-N OOS re-verification, as `structstop+tol0.25` still runs `-0.157R @ $0.40` / `-0.206R @ $0.57` on post-cutover M1 alone).
4. **E4 — Exploratory large-N OOS screens (`16:00–17:59 UTC` blackout & HTF trend alignment):**
   - Must first clear multi-regime out-of-sample testing on a 365+ day MT5 history dump before earning a dated pre-registration (prevents overfitting to the Sep–Nov downtrend).
5. **E5 — Manual trading execution guardrails (`A8` context / `docs/MANUAL-TRADING.md`):**
   - Anchor boxes/stops on **H1/H4** (`1R >= 10× cost`, `<10%` spread drag); take profit at `1.0×` opposing structure (`1:1–1:1.25`) instead of forcing `1.5×` wide stops; avoid ratcheting to BE before `+0.75R–+1.0R`; treat `16:00–17:59 UTC` and counter-HTF bounces cautiously; log `>= 100` matched rows in the private §7 journal before any rule claim.

---

## 5. Verification

Verified directly on collection 607 (`2026-11-27 17:59:02 UTC`):
- `python3 tools/check_data.py` → `0 fail, 9 warn`
- `python3 tools/handoff_check.py` → `FRESH` after `--update`
- `python3 tools/check_structural_stop.py` → `PASS`
- `python3 tools/check_gap_rides.py` → `9/2`, `1` gap-through (`#815`), `0` worse exits
- `python3 tools/pressure_report.py --root .` → `37.2%` dec, `-0.028R` gross
- `python3 tools/xm_quote_report.py` → `42/14` days, `5/2` weekends, `$0.55` median, EU rule `100.00%`
- `python3 tools/cost_model.py` → `-$1,037.25` whole book / `-$436.34` era all-in (`$0.57`)
- `python3 tools/equity_runway.py` / `--cost 0.285` → `~112t (8.5d)` / `~90t (6.8d)`
- `python3 tools/live_readiness.py` → `17 PASS / 0 TODO / 3 MANUAL · CLOSED`
- `python3 tools/feed_forensics.py --days 14` → `1` hole (`2026-11-26 19:27→20:55`, `88` open min, `0` exposed trades; Thanksgiving early close `NOOFFSET`)
- `python3 -m goldbot --compare` → `15m: 7 trades (+$75.03, 3.6% cost)` / `1h: 1 (+$35.87)` / `4h: 1 (-$56.50)` / `24h: 0`
