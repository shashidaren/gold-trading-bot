# HANDOFF-HISTORY — dated session archaeology (append-only)

`docs/HANDOFF.md` §1 holds the **current** state. This file holds the dated blocks §1 replaced, newest
first. **Nothing here is current:** numbers are as of the date on the block, and every conclusion that
still matters has been carried forward into HANDOFF §1/§4/§5/§6 or a dated `REVIEW-`/`ANALYSIS-` doc.

**Read it when** you need the *why* behind a live rule or the full record of an incident — never for
numbers. For sessions before 2026-10-05, `archive/PROJECT_LOG.md` is the changelog of record.

**Add to it** by appending at the top with a dated `## ` heading, moving the block out of HANDOFF §1 in
the same commit (HANDOFF §11 rule 5). Never edit a historical block to change a conclusion — write a new
block or a REVIEW instead; that is what makes this file trustworthy. (Created 2026-10-15, when §1 was
223 lines and 92% of it was history no session had pruned.)

---

## 2026-10-26 14:15 UTC — §1 before the full-system audit / LIVE-gate rewrite

**This is the complete HANDOFF §1 block as it stood for collection 335 (697 closed trades, structural-stop era n=200, PR #58 deployed, pre-DST offset verification). Nothing below is current.**

### Replaced §1 block

## 1. Where things stand (as of **2026-10-25 — data collection 335; PR #58 deployed 02:48:12 UTC (`71317da`); bar log through 2026-10-23 20:57 UTC**)

**Current stance (reconciled 2026-10-25 ~03:00 UTC after PR #58 merge + autosync `71317da`; judgement recorded 2026-10-19 21:19 UTC):** paper-only; `engine.py` remains `TRADING_MODE = "FORWARD_TEST"`. PR #58 (`d38117a`: `#697` duplicate-number fix `8d84dcf` + 30-min entries-only daily-closure gap guard `4d911fa`) was merged and **deployed onto `/opt/gold` at 2026-10-25 02:48:12 UTC** (`71317da`) into the **closed weekend market** (smoke gate passed on host; zero trades active or opened since). On this session branch (`arena/c5824a9f-gold-trading-bot`), `derive_daily_closure()` gained a **DST-responsiveness refinement (`1c02b2c`)** so a Sunday `±1 h` DST transition adapts on Day 1 from the weekend reopen / post-weekend break rather than lagging ~10 trading days behind a 30-day mode, while stop/TP geometry (`SL_CLEAR_ATR = 0.5`, `RR_TARGET = 1.5`) is **held unchanged** per owner decision until the post-DST broker offset (`+2h` EU vs `+3h` US) is observed tonight/Monday.

**The book:** **697 closed trades** (140W/301L/253BE/3TIME; 31.7% decisive [27.6–36.2]), engine ledger **$136.66**, true equity **$119.70**, net **−$659.10** at the assumed $0.40 round trip (−0.214R/trade on the report's mean-1R scale). **No paper trade is open** (`status.json` `next_trade_num: 698`); the last closed bar is Friday `2026-10-23 20:57:08 UTC` ($3 996.21, ATR $1.24, RSI 71.4). Quote logging (`data collection 335`, `7b2e2ea`) has **10/14 complete UTC days, 1/2 weekends**, median $0.55 (31 653 rows), **currently STALE**: the newest synced row is **`2026-10-24 15:34:30 UTC`** (~11.3 h before the `02:48 UTC` autosync, with no `quotes-2026-10-25.csv`), meaning `mt5quotes-gold` (or the Wine MT5 terminal) stopped writing on Saturday afternoon. **Host action before Sunday reopen:** restart/verify `mt5quotes-gold` and `mt5feed` so weekend #2 and the first post-DST tick offset are captured. The $0.40 model stays registered until the 14-day/two-weekend target is met (`win_rate_report.py --spread`).

**The structural-stop evaluation was judged at its registered time gate (2026-10-19 21:00 UTC).** That judgement used the latest then-available snapshot, **n=139**; the n=150 arm was never reached, and under the registered "whichever comes first" wording the arm **lapsed with the gate** — later era growth is an observation, not a re-opened PASS/SCREEN judgement (`docs/REVIEW-2026-10-20-post-gate-refresh.md`). The era has since grown to **n=200** (55W/90L/53BE/2TIME) on the post-gate rows. The mechanical guard still **PASSES**: 0 post-cutover stops inside the tested level, 83.5% level-bound, median risk 3.33 ATR, median clearance +0.50 ATR.

Readings on n=200 (observation only — the recorded decision is the n=139 one): SL/day **6.00**, SL share **45.00%** (≤47.0%), scratch share **26.50%**, gross R/trade **−0.052R**, decisive WR **37.93% [30.4–46.0]**. Gross era P&L **−$61.49** (net **−$141.49** at $0.40), drawdown $117.02. The recorded judgement still stands: **SCREEN MET, PASS NOT MET** on the sample the bar was judged on, and **no demonstrated edge**. Do not quote the grown-sample numbers as a verdict.

**The separate §7 closure-gap REVERT trigger FIRED at 3/2 — and its required gap guard is now DEPLOYED (`71317da`).** Counting a post-cutover trade open across a >5-minute log hole classified as a scheduled daily/weekly closure gives **3** (#595, #610, #687) vs threshold 2 (`docs/REVIEW-2026-10-19-struct-stop-judgement.md` §3; `tools/check_gap_rides.py`). None of the three reopened through its stop or exited worse; one stop was ratcheted to entry, no weekend closure was ridden, and tightest reopen headroom was #610 at +$4.15. Note also that **0 of 200** post-cutover entries fell inside `[20:28, 22:00)`, whereas all 3 pre-cutover closure rides (#95, #409, #476) entered at `20:56–20:58 UTC`.

**Gap guard + next stop-geometry step (owner-decided 2026-10-25):**
- **Deployed (`71317da`, 2026-10-25 02:48:12 UTC):** `docs/PREREG-2026-10-25-gap-guard-daily-closure.md` — `GUARD_CUTOFF_MIN = 30`, **entries only** (no flattening), schedule derived from observed price-log daily breaks (`20:58 → 22:00 UTC` under `+3h`), fail-open below 3 breaks, wired ahead of trade-number assignment in both execute paths (Scenario Z).
- **DST refinement on this branch (`1c02b2c`):** EU summer time ended `2026-10-25 01:00 UTC` (US ends `2026-11-01 06:00 UTC`). A 30-day modal window (19 summer breaks) would lag ~10 trading days after a `±1 h` shift; `derive_daily_closure()` now uses a 5-break recent baseline plus immediate Day-1/Day-2 `±60 min` adaptation from the Sunday weekly reopen / post-weekend breaks (immune to feed outages; +7 hermetic checks in Scenario Z).
- **Next eligible strategy decision (after Sunday reopen / Monday confirms `+2h` vs `+3h`):** owner chose to **hold `SL_CLEAR_ATR = 0.5` + gap guard until the post-DST offset is observed**, then decide between (a) pre-registering **`structstop1.5` (`SL_CLEAR_ATR = 1.5`)** — breakeven net (`−0.000R/trade` at $0.20/side, `−0.023R` at measured $0.275/side vs live `−0.102R`/`−0.132R`, `docs/ANALYSIS-2026-10-25-stop-hunt-markouts-and-clearance-grid.md`) — or (b) executing the literal 10-05 §7 structural-stop revert (`2·ATR / 3·ATR`, worst in replay at `−0.130R`/`−0.176R`, 66.4% stops inside level). The 0.25 ATR level test remains ineligible.

**Ledger numbering fix DEPLOYED (`8d84dcf` via `71317da`):** `restore_open_trade_from_status()` now restores `next_trade_num` (`max` with CSV-derived value; smoke Scenario Y), preventing future restart-with-open-trade duplicates like `#697` (`docs/REVIEW-2026-10-25-duplicate-trade-number.md`). The historical duplicate `#697` row in `trades.csv` was deliberately left un-renumbered (row-based tools and balance chain are unaffected).

**The dashboard pressure composite remains a side proxy, not a signal.** The current re-join at n=200 is still collinear with side and has no within-side `against` bucket (BUY 76 aligned / 5 mixed; SELL 114 aligned / 5 mixed). The owner's manual pressure/hold observation remains a separate, unmeasured hypothesis. The signal-outlook read (re-run on n=200) still shows no directional edge after an 8/8 signal (pooled 48.5% [42–55] trade's way at 30m, median −0.02R; 48.0% [41–55] at 60m, median −0.12R; barrier-race target-first 30.8%/33.6% vs the 40% driftless reference). These are base rates for manual context, never a forecast, entry gate, sizing, or hold-past-stop input.


## 2026-10-25 02:55 UTC — §1 before the post-PR-#58 autosync reconciliation

**This is the complete HANDOFF §1 block as it stood for collection 334 (697 closed trades, structural-stop era n=200, before PR #58 merged and deployed via autosync `71317da` at 2026-10-25 02:48:12 UTC). Nothing below is current.**

### Replaced §1 block

## 1. Where things stand (as of **2026-10-25 — data collection 334; latest data through 2026-10-23 20:57 UTC**)

**Current stance (session refresh 2026-10-25 ~01:45 UTC; judgement recorded 2026-10-19 21:19 UTC):** paper-only; `engine.py` remains `TRADING_MODE = "FORWARD_TEST"`. No engine, filter, parameter, gate or deployment change was made in this session. The checked-in data is the latest available synced snapshot (autosync commit `fd7e5c4`, 2026-10-24 15:00 UTC), not a host heartbeat; production process/revision and any unsynced rows remain operator-only and unverified.

**The book:** **697 closed trades** (140W/301L/253BE/3TIME; 31.7% decisive [27.6–36.2]), engine ledger **$136.66**, true equity **$119.70**, net **−$659.10** at the assumed $0.40 round trip (−0.214R/trade on the report's mean-1R scale). **No paper trade is open** at the snapshot; the 20:57 bar is $3 996.21, ATR $1.24, RSI 71.4. Quote logging has **10/14 complete UTC days, 1/2 weekends**, median $0.55; the newest synced row is 2026-10-24 14:59:30 (Saturday — market-closed, frozen tick), so the sample is simply awaiting the next sync, and a 10-21 tick stall up to ~1 h is noted for the host health check. The $0.40 model stays registered until the 14-day/two-weekend target is met (`win_rate_report.py --spread`).

**The structural-stop evaluation was judged at its registered time gate (2026-10-19 21:00 UTC).** That judgement used the latest then-available snapshot, **n=139**; the n=150 arm was never reached, and under the registered "whichever comes first" wording the arm **lapsed with the gate** — later era growth is an observation, not a re-opened PASS/SCREEN judgement (see `docs/REVIEW-2026-10-20-post-gate-refresh.md`). The era has since grown to **n=200** (55W/90L/53BE/2TIME) on the post-gate rows. The mechanical guard still **PASSES**: 0 post-cutover stops inside the tested level, 83.5% level-bound, median risk 3.33 ATR, median clearance +0.50 ATR.

Readings on n=200 (observation only — the recorded decision is the n=139 one): SL/day **6.00**, SL share **45.00%** (≤47.0%), scratch share **26.50%**, gross R/trade **−0.052R**, decisive WR **37.93% [30.4–46.0]**. Gross era P&L **−$61.49** (net **−$141.49** at $0.40), drawdown $117.02. The recorded judgement still stands: **SCREEN MET, PASS NOT MET** on the sample the bar was judged on, and **no demonstrated edge**. Do not quote the grown-sample numbers as a verdict.

**The separate §7 closure-gap REVERT trigger remains FIRED — 3/2.** Counting a post-cutover trade open across a >5-minute log hole classified as a scheduled daily/weekly closure gives **3** (#595, #610, #687) vs threshold 2. None of the three reopened through its stop or exited worse; one stop was ratcheted to entry, no weekend closure has been ridden, and the tightest reopen headroom is #610 at +$4.15. The bar and counting rule are recorded in `docs/REVIEW-2026-10-19-struct-stop-judgement.md` §3; damage rows unchanged (see `tools/check_gap_rides.py`).

The pre-registered response is **REVERT with the gap guard first**; therefore the 0.25 ATR level test is not eligible. **The guard is now REGISTERED and IMPLEMENTED (2026-10-25, owner-approved)**: `docs/PREREG-2026-10-25-gap-guard-daily-closure.md` — 30-minute cutoff, **entries only** (no flattening), schedule derived from the observed price-log break (currently 20:58 → 22:00 UTC), fail-open when underivable; `engine.py` guards both trade paths before a trade number is assigned, smoke Scenario Z covers it (smoke PASSED, check_data 0 fail/8 warn, gap-ride count unchanged at 3/2). **Deploy is GATED (owner-approved) on an observed post-DST-transition broker offset** (window 10-25 01:00 → 11-01 06:00 UTC) — no deploy on a guessed UTC close. **Next eligible action:** once the guard is deployed, prepare the single-commit structural-stop revert in the registered order; verify fresh host data and the deployed executable before relying on either. Until then the checked-in engine still contains the structural stop and remains paper-only. The #697 duplicate-trade-number fix sits in commit `8d84dcf` on the session branch, **PR not created** pending the owner's say-so; the historical duplicate row was deliberately not renumbered.

**Ledger numbering finding (2026-10-25):** the synced ledger contains **two rows numbered #697** (the 10-23 11:17 BUY, SL −$8.70, and the 10-23 15:15 SELL, TIME −$0.36 — the SELL should have been #698). Root cause is a latent engine bug: on a restart while a trade is open, `restore_open_trade_from_status()` restores `current_trade_num` from `status.json` but **not** `next_trade_num`, and `trades.csv` rows are written only at close — so the trade opened next reuses the open trade's number. Same pattern as the long-standing duplicates #1/#2/#3 (09-04) and #171 (09-15). **No current metric or judgement is affected** (every tool is row-based; the balance chain and `status.json` agree); the ledger key is simply non-unique, and the bug will recur on the host at the next restart-with-open-trade until fixed. A two-line engine fix + smoke scenario is proposed in `docs/REVIEW-2026-10-25-duplicate-trade-number.md` §5; **not applied** — owner review pending, then a deploy decision.

**The dashboard pressure composite remains a side proxy, not a signal.** The current re-join at n=200 is still collinear with side and has no within-side `against` bucket (BUY 76 aligned / 5 mixed; SELL 114 aligned / 5 mixed). The owner's manual pressure/hold observation remains a separate, unmeasured hypothesis. The signal-outlook read (re-run on n=200) still shows no directional edge after an 8/8 signal (pooled 48.5% [42–55] trade's way at 30m, median −0.02R; 48.0% [41–55] at 60m, median −0.12R; barrier-race target-first 30.8%/33.6% vs the 40% driftless reference). These are base rates for manual context, never a forecast, entry gate, sizing, or hold-past-stop input.

---

## 2026-10-25 01:45 UTC — §1 before the 2026-10-25 session refresh

**This is the complete HANDOFF §1 block as it stood for the 2026-10-23 14:59 UTC snapshot (696 closed trades, structural-stop era n=199), superseded by the 2026-10-25 session refresh (697 closed, era n=200, duplicate #697 finding). Nothing below is current.**

### Replaced §1 block

## 1. Where things stand (as of **2026-10-23 — latest data through 14:59 UTC**)

**Current stance (session refresh; judgement recorded 2026-10-19 21:19 UTC):** paper-only; `engine.py` remains `TRADING_MODE = "FORWARD_TEST"`. No engine, filter, parameter, gate or deployment change was made in this session. The checked-in data is the latest available synced snapshot, not a host heartbeat; production process/revision and any unsynced rows remain operator-only and unverified.

**The book:** **696 closed trades** (140W/301L/253BE/2TIME; 31.7% decisive [27.6–36.2]), engine ledger **$137.02**, true equity **$120.06**, net **−$658.34** at the assumed $0.40 round trip (−0.215R/trade on the report's mean-1R scale). **No paper trade is open** at the snapshot; the 14:59 bar is $3 999.53, ATR $3.03, RSI 57.1. `data_collection` was `unknown` in older snapshots; the 324 collection here is the checked-in data. Quote logging has **9/14 complete UTC days, 1/2 weekends**, median $0.55; the latest report is STALE (newest row ~0.4 h old), so process health remains an ops check. The $0.40 model stays registered until the 14-day/two-weekend target is met (`win_rate_report.py --spread`).

**The structural-stop evaluation was judged at its registered time gate (2026-10-19 21:00 UTC).** That judgement used the latest then-available snapshot, **n=139**; the n=150 arm was never reached, and under the registered "whichever comes first" wording the arm **lapsed with the gate** — later era growth is an observation, not a re-opened PASS/SCREEN judgement (see `docs/REVIEW-2026-10-20-post-gate-refresh.md`). The era has since grown to **n=199** (55W/90L/53BE/1TIME) on the post-gate rows. The mechanical guard still **PASSES**: 0 post-cutover stops inside the tested level, 83.4% level-bound, median risk 3.32 ATR, median clearance +0.50 ATR.

Readings on n=199 (observation only — the recorded decision is the n=139 one): SL/day **6.00**, SL share **45.23%** (≤47.0%), scratch share **26.63%**, gross R/trade **−0.053R**, decisive WR **37.93% [30.4–46.0]**. Gross era P&L **−$61.13** (net **−$140.73** at $0.40), drawdown $117.02. The recorded judgement still stands: **SCREEN MET, PASS NOT MET** on the sample the bar was judged on, and **no demonstrated edge**. Do not quote the grown-sample numbers as a verdict.

**The separate §7 closure-gap REVERT trigger remains FIRED — now 3/2.** Counting a post-cutover trade open across a >5-minute log hole classified as a scheduled daily/weekly closure gives **3** (#595, #610, #687) vs threshold 2; #687 (SELL 2026-10-22 20:20→22:24, 124 min, SELL stop $4 029.78) is also post-cutover and daily-break, like #595/#610. Neither #595/#610 reopened through its stop or exited worse; one stop was ratcheted to entry, and no weekend closure has been ridden — #687 also reopened $4.46 above its SELL stop with $0.00 adverse past it. These damage facts do not add a condition to the registered count. The bar and counting rule are recorded in `docs/REVIEW-2026-10-19-struct-stop-judgement.md` §3; damage rows unchanged, count now 3/2 (see `tools/check_gap_rides.py`).

The pre-registered response is **REVERT with the gap guard first**; therefore the 0.25 ATR level test is not eligible. The guard is still not operationally specified (no approved cutoff or open-position policy), and the production host/data state is unverified. **The owner was asked directly on 2026-10-20 and chose to leave it undefined for now:** scope "leave it blocked for now", schedule source "not sure yet", cutoff 30 min *if* a window is ever adopted — a preference attached to no adopted scope, **not** an approved `N` (`docs/REVIEW-2026-10-20-post-gate-refresh.md` §4; do not re-ask the same questions). This session records the refreshed state but does **not** invent a guard, revert code, or deploy. **Next eligible action:** the owner's own dated pre-registration of the guard (including cutoff, schedule source, and whether it blocks new entries or also closes open paper positions), then a reviewed guard change and the prescribed revert in order; verify fresh host data and executable before any deployment. Until then, the checked-in engine still contains the structural stop and remains paper-only.

**Accounting incident reconciled (2026-10-19):** malformed rows #626–645 were quarantined from backed-up evidence using `tools/repair_phantom_ledger.py`; at that reconciliation the checked-in ledger held 657 valid closed trades and passed `check_data.py` (0 fail; 8 documented warnings). The raw-row reconciliation and evidence are in `docs/REVIEW-2026-10-19-negative-balance.md` and `incident_backups/`. **Host-side verification of the running executable/revision remains operator-only**; do not infer production process health from this checkout alone.

**The dashboard pressure composite remains a side proxy, not a signal.** The current re-join at n=199 is still collinear with side and has no within-side `against` bucket (BUY 76 aligned / 5 mixed; SELL 113 aligned / 5 mixed). The owner's manual pressure/hold observation remains a separate, unmeasured hypothesis. The signal-outlook read still shows no directional edge after an 8/8 signal (50.4% [42–59] trade-way at 30m, median +0.02R; 50.7% [42–59] at 60m at n=139). These are base rates for manual context, never a forecast, entry gate, sizing, or hold-past-stop input.

**Box theory (manual, unmeasured in the ledger):** asked 2026-10-20 whether boxes can be used for manual trades. Measured on the same tape (`tools/box_report.py`, `docs/ANALYSIS-2026-10-20-box-theory-manual-trading.md`): breakout and fade entries land on or below the driftless reference at both box sizes, and 74–75% of breaks close back inside within 15 min. **Verdict: box = a place to put a stop, not a signal.** Display/advice only — no gate, no runtime change; manual box trades are not in `trades.csv` and are not evidence until logged (bar: n≥100, positive after spread). The dashboard renders the same read in its **📦 Boxes & Timing** tab (`?tab=boxes`) — boxes, the seven-condition checklist, the setup card and the measured footer.

**Chart & Placement tab (2026-10-23, display-only, no deploy action yet):** a fourth dashboard tab
(`?tab=chart`, `chart.py`) draws the recent tape as candles (M1/M5/M15 toggle), overlays the same
`pressure.box_geometry()` levels the Boxes tab reads, shades the sessions and the engine's blackout
windows, and prints — per side — the entry, stop (outside the *far* box edge) and target (one box
width) with the spread as a share of R. It exists because the dashboard had no price chart at all and
because geometry, not prediction, is what survives in this repo's own measurements. **It adds no
indicator that has not been measured:** Fibonacci, pivots, round numbers, VWAP, volume profile,
trendlines, Ichimoku and MACD are deliberately absent (unmeasured, or undrawable on a tick-volume
feed, or subjective), and the tab says so in its own copy. The cost ruler is arithmetic only. Like
every other panel it is display-only: no gate, no order, no write, no `engine.py` import
(`docs/PROPOSAL-2026-10-23-manual-chart-tab.md`; tests `tools/test_manual_chart.py`, 32 hermetic).
The shipped defaults are M5 and 140 bars. Nothing here changes the open struct-stop window, the
fired §7 gap trigger, or any threshold in §4.

**Manual Scalping workspace — REMOVED 2026-10-23 (owner: "probably don't need the scalper tab any
more").** manual_scalp.py, scalp_template.py, docs/MANUAL-SCALPING.md, both test files, the four
`/scalp*` routes and the nav link are deleted; `GOLD_MANUAL_JOURNAL_FILE` is read by nothing. Any
host-local `manual_scalp_journal.json` is orphaned, not migrated — it was self-reported, never
broker-verified, and was explicitly not evidence. The measured reason the page is not a loss: its own
chart layer carries the finding that tight manual gold scalps lose on cost alone (`chart.py`), and the
v1 ledger puts the round trip at 14.0% of the median risk (19.5% on 20-bar box entries). Original
build note follows for archaeology only.

**Manual Scalping workspace (2026-10-23, dashboard + manual-journal write only; no engine change):**
the owner approved a separate manual page rather than crowding the bot tabs. **`/scalp`** now combines
the existing M5/M1/M15 chart and box levels, compact feed/session/risk/volatility/chop context, an
editable entry/stop/target + cash-risk + spread + contract calculator, and a separate decision journal.
It deliberately has **no auto-refresh**, so market refreshes cannot erase an editing ticket. Copying a
Chart & Placement BUY/SELL reference does not change its SKIP/WATCH verdict. The calculator charges the
round-trip spread on both legs, rounds lots **down** to the volume step, and the server recalculates every
submission and close. Defaults ($500 calculation balance, 1% risk, $0.55 spread, 100 oz/lot, 0.01 step)
are editable and **not broker-read**; the operator must verify the real contract/cost. **No order route
exists:** “Record externally taken” and “Record close” only journal self-reported external activity.
Rows are `SKIPPED` / `OPEN` / `CLOSED` in host-local, git-ignored **`manual_scalp_journal.json`**
(`GOLD_MANUAL_JOURNAL_FILE` overrides), never `trades.csv` or engine state. Writes are atomic, mode 0600;
corruption is shown as an error, never reset to empty. This is the one dashboard page that writes, and it
writes only that file; the existing bot panels remain read-only. Self-reported rows are not broker-verified
or evidence of edge; the ≥100-closed-trade, positive-after-cost review bar still applies. Full schema,
formulas and operating rules: docs/MANUAL-SCALPING.md (deleted). Tests: tools/test_manual_scalp.py
and tools/test_scalp_dashboard.py (both deleted; the route test hashed `trades.csv` before/after).
Autosync `DASH_CHANGED` now includes the dashboard helpers (`pressure.py`, `chart.py`, `manual_scalp.py`,
`scalp_template.py`) as well as `dashboard.py`; `CORE_CHANGED` and the engine remain untouched.

**Box watch, chop read and Telegram notifier (2026-10-21, display + tooling only):** asked whether the BUY/SELL watch cards could be improved, whether the tape is choppy, and for a Telegram message when the indicators line up. Three additions, all display-only: **(1)** a measured chop read (`pressure.box_chop`) — at the 14:59 snapshot **14 of 18 breaks in the last 24 h closed back inside within 15 min (78%) vs a 74% baseline**, so chop is *normal*, while the tape is genuinely range-bound (efficiency ratio 0.04/0.02) and the 20-bar box is compressed (3.0 ATR vs a 4.7 median); **(2)** retest tracking on a box **frozen at the break** (`pressure.box_retest`: `extended`/`retesting`/`held`/`failed`) — 94% of breaks are retested within 30 bars (median 3) and entering the held retest measured **59.0% vs a 57.2% reference, the same −$0.31/trade** as entering the break; **(3)** an optional Telegram notifier (`tools/box_alert.py`, `deploy/boxalert.service`) that sends one rate-limited message when the checklist, a fresh break, ≤10%-of-R geometry and no-chase all line up — measured volume **5.1/day** over a 7-day replay. **Both new reads were tested as filters and both came back negative** (a 10 pp "chop filter" found on overlapping events vanished and partly reversed under the one-position convention — the same trap as 09-28 pooled momentum). They gate nothing, they never touch `engine.py`, and the numbers travel with every read: `docs/ANALYSIS-2026-10-21-box-chop-retest-alerts.md`.

**Telegram routing (2026-10-23, message policy only — no engine logic, gate or parameter change):** the owner asked to keep Telegram for the indicator notices only. Measured on the 10 trading days to 10-23 the chat carried **≈82 messages/day (worst 101)**, of which **36.8/day were cooldown/blackout skip notices** and ≈5.1/day were the box-watch notice. Now: the engine's messages carry a kind and `GOLD_TELEGRAM_KINDS` in `/opt/gold/.env` selects them (unset = unchanged, recommended `none` or `feed,risk`); the autosync digest is routine-twice-daily (`GOLD_DIGEST_EVERY_HOURS=12`), silent, with a new `🧾 trades:` trade report, and **incidents still send immediately and buzz**; the optional box notifier also sends a **07:00 / 13:00 UTC session watch plan** (levels, both alert prices, blockers, measured context, no-edge footer). Expected traffic ≈7–9/day. This changes nothing about what the engine trades, and it does not loosen the alert rule — the plan and the notice both carry the measured 0-of-8 verdict. `docs/PROPOSAL-2026-10-23-telegram-routing.md`; smoke Scenario X.

**Journal + indicator audit (2026-10-23, display-only, no engine change):** owner asked for "more indicators?" and a self-journalling BUY/SELL tracker. **Shipped:** `tools/journal.py` — the self-journal (gross/net, BUY vs SELL, hour/session/weekday, RSI/ATR/wick/EMA geometry, streak, plus a lab that computes BB %B, MACD hist, Stoch %K, ADX, CCI, Donchian 20, ATR percentile, volume ratio, EMA slope, trend strength, BB width from the log alone). **Result on the live era (n=198, 38.2% dec):** no extra indicator clears the repo's adoption bar (n≥25, ≥5 pp, same direction within BUY and within SELL, holds in an up-tape subperiod, P/L/trade not worse than -$0.10). The two closest hints — **ATR percentile quiet <25th 55.6% vs volatile >75th 31.5% (Δ33.7 pp, p=0.014)** and **volume spike >1.3× 46.2% vs thin 20.5% (Δ24.7 pp, p=0.23; whole book 45.0% vs 20.5% p=0.031)** — are now shown as *context* in the dashboard Journal tab; volume is tick volume, not traded volume, so VWAP stays out. Other classics (Bollinger, MACD, Stoch, ADX, CCI, Donchian, BB width) test as side-proxies or noise. Audit doc: `docs/INDICATOR-AUDIT-2026-10-23.md`. **Dashboard Journal tab (display-only):** `pressure.journal_read()` + `pressure._extra_indicators_series()` wired into `dashboard.py` (`?tab=journal`), with gross vs net, buy vs sell bars, recent 30/10, session/ATR/hour splits, and last-bar BB/Stoch/ATR-pctile/MACD/Donchian reads. Like the Simple/Boxes/Chart tabs, a dashboard change restarts the dashboard only.

---

## 2026-10-21 11:59 UTC — §1 before the 11:59 UTC data refresh

**This is the complete HANDOFF §1 block as it stood for the 2026-10-20 08:59 UTC snapshot (644 closed trades, structural-stop era n=147), superseded by the 2026-10-21 11:59 UTC refresh (657 closed trades, era n=160). Nothing below is current.**

### Replaced §1 block

## 1. Where things stand (as of **2026-10-20 — data collection 294; latest data through 08:59 UTC**)

**Current stance (post-gate data refresh; judgement recorded 2026-10-19 21:19 UTC):** paper-only; `engine.py` remains `TRADING_MODE = "FORWARD_TEST"`. No engine, filter, parameter, gate or deployment change was made in this refresh. The checked-in data is the latest available synced snapshot, not a host heartbeat; production process/revision and any unsynced rows remain operator-only and unverified.

**The book:** **644 closed trades** (128W/277L/237BE/2TIME; 31.6% decisive), engine ledger **$174.73**, true equity **$157.76**, net **−$599.84** at the assumed $0.40 round trip. One paper trade is open in the checked-in status: **SELL #646 @ $4120.28** (stop $4127.65, TP $4109.22, no BE armed). Quote logging has 6.7 days (6/14 complete UTC days, 1/2 weekends) and a first-look median $0.55 spread/round trip; the 14-day/two-weekend target is not met, so $0.40 remains the registered cost assumption.

**The structural-stop evaluation was judged at its registered time gate (2026-10-19 21:00 UTC).** That judgement used the latest then-available snapshot, **n=139**; the n=150 arm was never reached, and under the registered "whichever comes first" wording the arm **lapsed with the gate** — later era growth is an observation, not a re-opened PASS/SCREEN judgement (see `docs/REVIEW-2026-10-20-post-gate-refresh.md`). The era has since grown to **n=147** (43W/66L/37BE/1TIME; 12 entry dates) on the post-gate rows. The mechanical guard still **PASSES**: 0 post-cutover stops inside the tested level, 81.6% level-bound, median clearance +0.50 ATR, median risk 3.29 ATR.

Post-gate readings on n=147 (observation only — the recorded decision is the n=139 one): SL/day **5.50**, SL share **44.90%** (≤47.0%), scratch share **25.17%**, gross R/trade **−0.028R**, decisive WR **39.45% [30.8–48.8]**. Gross era P&L is **−$23.43**; at the assumed $0.40 round trip it is about **−$82 (−0.098R/trade)**. The recorded judgement still stands: **SCREEN MET, PASS NOT MET** on the sample the bar was judged on, and **no demonstrated edge**. Do not quote the grown-sample numbers as a verdict.

**The separate §7 closure-gap REVERT trigger remains FIRED.** Counting a post-cutover trade open across a >5-minute log hole classified as a scheduled daily/weekly closure gives **2/2** (#595, #610); the eight post-gate trades added **no** new ride. Neither ride reopened through its stop or exited worse; one stop was ratcheted to entry, and no weekend closure has been ridden. These damage facts do not add a condition to the registered count. The bar and counting rule are recorded in `docs/REVIEW-2026-10-19-struct-stop-judgement.md` §3.

The pre-registered response is **REVERT with the gap guard first**; therefore the 0.25 ATR level test is not eligible. The guard is still not operationally specified (no approved cutoff or open-position policy), and the production host/data state is unverified. **The owner was asked directly on 2026-10-20 and chose to leave it undefined for now:** scope "leave it blocked for now", schedule source "not sure yet", cutoff 30 min *if* a window is ever adopted — a preference attached to no adopted scope, **not** an approved `N` (`docs/REVIEW-2026-10-20-post-gate-refresh.md` §4; do not re-ask the same questions). This session records the refreshed state but does **not** invent a guard, revert code, or deploy. **Next eligible action:** the owner's own dated pre-registration of the guard (including cutoff, schedule source, and whether it blocks new entries or also closes open paper positions), then a reviewed guard change and the prescribed revert in order; verify fresh host data and executable before any deployment. Until then, the checked-in engine still contains the structural stop and remains paper-only.

**Accounting incident reconciled (2026-10-19):** malformed rows #626–645 were quarantined from backed-up evidence using `tools/repair_phantom_ledger.py`; the checked-in ledger is now 644 valid closed trades and passes `check_data.py` (0 fail; 8 documented warnings). The raw-row reconciliation and evidence are in `docs/REVIEW-2026-10-19-negative-balance.md` and `incident_backups/`. **Host-side verification of the running executable/revision remains operator-only**; do not infer production process health from this checkout alone.

**The dashboard pressure composite remains a side proxy, not a signal.** The re-join at n=147 is still collinear with side and has no within-side `against` bucket (BUY 63 aligned / 4 mixed; SELL 77 aligned / 3 mixed). The owner's manual pressure/hold observation remains a separate, unmeasured hypothesis. The signal-outlook read still shows no directional edge after an 8/8 signal (50.4% [42–59] trade-way at 30m, median +0.02R; 50.7% [42–59] at 60m at n=139). These are base rates for manual context, never a forecast, entry gate, sizing, or hold-past-stop input.

**Box theory (manual, unmeasured in the ledger):** asked 2026-10-20 whether boxes can be used for manual trades. Measured on the same tape (`tools/box_report.py`, `docs/ANALYSIS-2026-10-20-box-theory-manual-trading.md`): breakout and fade entries land on or below the driftless reference at both box sizes, and 74–75% of breaks close back inside within 15 min. **Verdict: box = a place to put a stop, not a signal.** Display/advice only — no gate, no runtime change; manual box trades are not in `trades.csv` and are not evidence until logged (bar: n≥100, positive after spread). The dashboard renders the same read in its **📦 Boxes & Timing** tab (`?tab=boxes`) — boxes, the seven-condition checklist, the setup card and the measured footer.


## 2026-10-20 11:57 UTC — §1 before the post-gate data refresh

**This is the complete HANDOFF §1 block as it stood for the 2026-10-19 18:10 UTC snapshot (636 closes, structural-stop n=139), written just after the 21:19 judgement.** Superseded on 2026-10-20 when the synced data reached 08:59 UTC with 644 closes and the era at n=147 — see `docs/REVIEW-2026-10-20-post-gate-refresh.md`. Nothing below is current.

### Replaced §1 block

## 1. Where things stand (as of **2026-10-19 — latest data through 18:10 UTC**)

**Current stance (judgement recorded 2026-10-19 21:19 UTC; latest synced data to 18:10 UTC):** paper-only; `engine.py` remains `TRADING_MODE = "FORWARD_TEST"`. No engine, filter, parameter, gate or deployment change was made. The checked-in data is the latest available snapshot, not a host heartbeat; production process/revision and any unsynced rows after 18:10 remain operator-only and unverified.

**The book:** **636 closed trades** (124W/276L/234BE/2TIME; 31.0% decisive), engine ledger **$142.16**, true equity **$125.18**, net **−$629.22** at the assumed $0.40 round trip. No open trade in the checked-in status. Quote logging has 6.1 days (5/14 complete UTC days, 1/2 weekends) and a first-look median $0.55 spread/round trip; the sample target is not met, so $0.40 remains the registered cost assumption.

**The structural-stop evaluation reached its registered time gate at 21:00 UTC.** The latest checked-in snapshot is still through 18:10 UTC: **n=139** (39W/65L/34BE/1TIME; 11 entry dates), so the n=150 arm was not reached. The mechanical guard passes: 0 post-cutover stops inside the tested level, 81.3% level-bound, median clearance +0.50 ATR, median risk 3.27 ATR. Replay calibration is 99.8% on the 0.75R master and 99.7% on max-hold.

The registered **SCREEN MET** on that snapshot: SL/day **5.91**, SL share **46.76%** (≤47.0%), scratch share **24.46%**, gross R/trade **−0.071R**, decisive WR **37.50% [28.8–47.1]**. **PASS was not met**: n=139 <150 and the Wilson 95% lower bound 28.8% is not >32.1%. Gross era P&L is **−$56.01**; at the assumed $0.40 round trip it is **−$111.61 (−0.142R/trade)**. There is no demonstrated edge.

**The separate §7 closure-gap REVERT trigger FIRED.** Counting a post-cutover trade open across a >5-minute log hole classified as a scheduled daily/weekly closure gives **2/2** (#595, #610). Neither reopened through its stop or exited worse; one stop was ratcheted to entry, and no weekend closure was ridden. These damage facts do not add a condition to the registered count. The bar and counting rule are recorded in `docs/REVIEW-2026-10-19-struct-stop-judgement.md` §3.

The pre-registered response is **REVERT with the gap guard first**; therefore the 0.25 ATR level test is not eligible. The guard is not operationally specified (no approved cutoff or open-position policy), and the production host/data state is unverified. This session records the fired trigger but does **not** invent a guard, revert code, or deploy. **Next eligible action:** owner-defined and dated pre-registration of the guard (including cutoff, schedule source, and whether it blocks new entries or also closes open paper positions), then a reviewed guard change and the prescribed revert in order; verify fresh host data and executable before any deployment. Until then, the checked-in engine still contains the structural stop and remains paper-only.

**Accounting incident reconciled (2026-10-19):** malformed rows #626–645 were quarantined from backed-up evidence using `tools/repair_phantom_ledger.py`; the checked-in ledger has advanced to 636 valid closed trades and passes `check_data.py` (0 fail; 8 documented warnings). The raw-row reconciliation and evidence are in `docs/REVIEW-2026-10-19-negative-balance.md` and `incident_backups/`. **Host-side verification of the running executable/revision remains operator-only**; do not infer production process health from this checkout alone.

**The dashboard pressure composite remains a side proxy, not a signal.** The latest re-join at n=139 is still collinear with side and has no within-side `against` bucket. The owner's manual pressure/hold observation remains a separate, unmeasured hypothesis. The signal-outlook re-read at n=139 still shows no directional edge after an 8/8 signal: 50.4% [42–59] trade-way at 30m (median +0.02R) and 50.7% [42–59] at 60m. These are base rates for manual context, never a forecast, entry gate, sizing, or hold-past-stop input.

**Box theory (manual, unmeasured in the ledger):** asked 2026-10-20 whether boxes can be used for manual trades. Measured on the same tape (`tools/box_report.py`, `docs/ANALYSIS-2026-10-20-box-theory-manual-trading.md`): breakout and fade entries land on or below the driftless reference at both box sizes, and 74–75% of breaks close back inside within 15 min. **Verdict: box = a place to put a stop, not a signal.** Display/advice only — no gate, no runtime change; manual box trades are not in `trades.csv` and are not evidence until logged (bar: n≥100, positive after spread). The dashboard renders the same read in its **📦 Boxes & Timing** tab (`?tab=boxes`) — boxes, the seven-condition checklist, the setup card and the measured footer.

---

## 2026-10-19 21:19 UTC — §1 before the scheduled structural-stop judgement

**This is the complete HANDOFF §1 block as it stood for the latest checked-in data snapshot (log to 2026-10-19 18:10 UTC, 636 closes, structural-stop n=139), before the 21:00 UTC judgement was recorded.** The snapshot and interim state are historical; the current state is in HANDOFF §1 and the judgement is in `docs/REVIEW-2026-10-19-struct-stop-judgement.md`.

### Replaced §1 block

## 1. Where things stand (as of **2026-10-19 — data collection 287**)

**Current stance (2026-10-19, checked-in data to 18:10 UTC):** paper-only; `engine.py` remains `TRADING_MODE = "FORWARD_TEST"`. Dashboard context and signal-outlook panels are display-only; this refresh makes no runtime or strategy change.

**The book:** **636 closed trades** (124W/276L/234BE/2TIME; 31.0% decisive), engine ledger **$142.16**, true equity **$125.18**, net **−$629.22** at the assumed $0.40 round trip. No open trade in the checked-in status. The quote logger has collected 6.1 days (5 complete UTC days, 1/2 complete weekends), with a first-look median $0.55 spread/round trip; its 14-day/two-weekend target is not met, so $0.40 remains the registered cost assumption.

**The only open experiment** is the un-stacked structural stop (entries ≥ **2026-10-06 03:00 UTC**): **n=139** (39W/65L/34BE/1TIME), 11 entry dates. Mechanical guard **PASS**: zero stops inside the tested level; 81.3% level-bound, median clearance +0.50 ATR, median risk 3.27 ATR.

The latest interim read now has the full registered **SCREEN MET**: SL/day **5.91**, SL share **46.76%** (≤47.0%), scratch share **24.46%**, gross R/trade **−0.071R**, decisive WR **37.50% [28.8–47.1]**. This is not yet a PASS or the scheduled confirmatory judgement: PASS additionally requires **n≥150** and Wilson 95% lower bound **>32.1%**; at n=139 the lower bound is 28.8%, with 11 trades to n=150. Original thresholds remain binding.

**The §7 closure-gap revert trigger remains at its threshold** — 2 of 2 post-cutover rides across daily closures (#595 on 10-14 and #610 on 10-15). Neither reopen gapped through the stop; neither exit printed worse than its stop/target; no weekend closure was ridden, and measured gap damage remains $0.00. The counting rule and trigger status must be explicitly resolved first at the scheduled judgement. Evidence: `docs/REVIEW-2026-10-19-struct-stop-screen.md` §3; reproduce with `python3 tools/check_gap_rides.py`.

**Next eligible action:** the confirmatory judgement at **2026-10-19 21:00 UTC** or n=150, whichever comes first. Resolve the gap trigger and record the counting rule first; re-run the structural-stop guard, `strategy_lab.py --calib-only`, and `check_gap_rides.py`; then record the registered screen/PASS/revert decision. The already-registered 0.25 ATR level test remains blocked until that judgement permits it. No runtime rule changed in this refresh.

**Accounting incident reconciled (2026-10-19):** malformed rows #626–645 were quarantined from backed-up evidence using `tools/repair_phantom_ledger.py`; the checked-in ledger has advanced to 636 valid closed trades and passes `check_data.py` (0 fail; 8 documented warnings). The raw-row reconciliation and evidence are in `docs/REVIEW-2026-10-19-negative-balance.md` and `incident_backups/`. **Host-side verification of the running executable/revision remains operator-only**; do not infer production process health from this checkout alone.

**The dashboard pressure composite remains a side proxy, not a signal.** The latest re-join at n=139 is still collinear with side and has no within-side `against` bucket. The owner's manual pressure/hold observation remains a separate, unmeasured hypothesis. The signal-outlook re-read at n=139 still shows no directional edge after an 8/8 signal: 50.4% [42–59] trade-way at 30m (median +0.02R) and 50.7% [42–59] at 60m. These are base rates for manual context, never a forecast, entry gate, sizing, or hold-past-stop input.

### Definitions (binding)

| Term | Meaning |
|------|---------|
| **Decisive WR** | TP / (TP + SL). **Excludes** BE and TIME. |
| **BE exit** | Scratch: SL was ratcheted to entry; P&L ≈ $0. Neutral for WR, cooldown, daily breaker. |
| **TIME exit** | Max-hold close (`MAX_HOLD_MINUTES`). Neutral bucket like BE (own counter; excluded from decisive WR; ignored by SL streak / daily breaker). |
| **0.75R era** | Entries with `Entry_Time ≥ 2026-09-15 06:00 UTC` (PR #9 deploy). |
| **Max-hold era** | Entries after max-hold deploy (~2026-09-21 06:00 UTC autosync). **No counter reset** — falsification bar stays on the whole 0.75R book. |
| **Ratchet geometry** | Reconstruct original SL/TP from `ATR_At_Entry` when `Stop_Loss == Entry_Price` (never key only on `Exit_Reason == "BE"` — some TPs also show that geometry). |
| **R/trade (Rmult)** | `Profit ÷ actual risk`. Actual risk = \|Entry − Stop\|, recovered from the **reward leg** (`\|TP − Entry\| ÷ 1.5`) on rows whose stop was ratcheted to entry — never from `Exit_Reason == "BE"` alone. `tools/strategy_lab.py` and `tools/win_rate_report.py` both do this. **Backward-compatible:** before 2026-10-05 the engine always set risk = 2·ATR, so `Profit ÷ (2·ATR_At_Entry)` gives the identical number on every historical row (that was the definition used in REVIEW-2026-10-05); the two only diverge once `SL_CLEAR_ATR` can bind. |
| **Structural stop / level-bound** | The stop is set by the 20-bar level rather than by `ATR_SL_MULT·ATR` (replay share under the new rule: **80.2%**). Checkable on any era with `tools/check_structural_stop.py`. |
| **Clearance** | ATR by which the stop sits BEYOND the tested level (positive = the level must break for the stop to print). Pre-2026-10-05 median was **−0.42 ATR** (i.e. inside, stop fires on a retest); the rule requires ≥ 0 always and ≥ `SL_CLEAR_ATR` when level-bound. |
| **Session band** | Entry hour in UTC: "Asia/rollover" = 23:00–06:59; "London/NY" = 07:00–22:59. Named 2026-10-05 §5a; **downgraded later the same day** — costed/cascade-aware replay shows the gap collapses from 0.268R to 0.085R once the stop is structural (it was a proxy for stop geometry). Never a live gate. |
| **Struct-stop era** | Entries ≥ **2026-10-06 03:00 UTC** (`strategy_lab.LIVE_CUTOVER` — the autosync deploy time; the 10-05 21:00 in older text was the plan, corrected 10-13). A real isolation window (the rule changed), unlike the max-hold deploy which did not reset the counter. Judge per `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` §7 at n≥100; n<60 is not a result in either direction. |

## 2026-10-19 18:10 UTC — §1 before the 636-trade refresh

**This is the complete HANDOFF §1 block as it stood at the 2026-10-19 11:59 UTC snapshot** (data collection 282), moved here when §1 was refreshed in place under HANDOFF §11 rule 5. These numbers and the n=133 screen status are historical; the current state is in HANDOFF §1.

### Replaced §1 block

## 1. Where things stand (as of **2026-10-19 — data collection 282**)

**Current stance (2026-10-19, data to 11:59 UTC):** paper-only; `engine.py` remains
`TRADING_MODE = "FORWARD_TEST"`. Dashboard-only PR adds risk now, market map and
costed evidence; see `docs/ANALYSIS-2026-10-19-dashboard-context.md` for scope. **New:** a **Simple Summary** tab (`pressure.py` volatility guard) translates ATR/spread/blackout/cooldown/breaker/closure/gaps into `🟢 Calm / 🟡 Caution / 🔴 Pause (avoid trading if volatile)` in plain English — display-only, never a gate.

**The book:** **630 closed trades** (123W/276L/229BE/2TIME; 30.8% decisive), engine ledger
**$137.42**, true equity $120.44, net **−$631.56** at the assumed $0.40 round trip.
No open trade in the checked-in status. Quote sample remains insufficient to replace
that registered assumption (last full review: 5 complete days, 1 weekend).

**The only open experiment** is the un-stacked structural stop (entries ≥
**2026-10-06 03:00 UTC**): **n=133** (38W/65L/29BE/1TIME), 11 entry dates.
Mechanical guard PASS, zero stops inside the tested level. Screen remains **NOT MET**:
SL share **48.87% > 47.0%**. Other screen checks pass: SL/day 5.91, scratch 21.80%,
gross R/trade −0.080R, decisive WR 36.89% [28.2–46.5]. This dashboard work does not
judge or modify the experiment; the scheduled review and original thresholds still govern.

**The §7 closure-gap revert trigger is AT its threshold — 2 of 2 post-cutover rides over a daily market
closure** (#595 on 10-14, #610 on 10-15; no weekend closure has been ridden, neither stop gapped
through, $0.00 of gap damage so far). It is the **first item of the 21:00 judgement**, and the counting
rule must be recorded there. Evidence and the decision procedure:
`docs/REVIEW-2026-10-19-struct-stop-screen.md` §3; the count is reproducible with
`python3 tools/check_gap_rides.py` (new, read-only).

**Next eligible action:** the confirmatory judgement at **2026-10-19 21:00 UTC** (or n=150, whichever
comes first), in §7 order — **(0)** resolve the gap trigger, **(a)** re-run the guard + `--calib-only` +
`check_gap_rides.py`, **(b)** judge B/C, **(c)** only then consider the already-registered 0.25 ATR level
test. **No runtime rule was changed in the 10-19 sessions**; the level test stays blocked behind it.

**Accounting incident reconciled (2026-10-19):** twenty invalid rows (#626–645, 2026-10-18 23:05 –
2026-10-19 02:23 UTC) had blank Entry_Time and zero Take_Profit, covering BUY TP and SELL TP/BE/SL
variants; raw equity **−$58,393.96** was phantom accounting (twenty rows booked **−$58,544.65** from the
$150.69 reference). Last valid ledger balance: **$150.69** after #625. Raw counts were 644 rows / 138 TP;
the valid subset **624 rows / 122 TP** is restored via quarantine. The 20-row suffix was quarantined with
continuity + status/numbering checks (`tools/repair_phantom_ledger.py`); the reconciled ledger passes
`check_data.py` (0 fail) and `check_structural_stop.py` PASS (n=127) still holds. See `incident_backups/`
for the quarantined evidence and `docs/REVIEW-2026-10-19-negative-balance.md` for the incident record.
**Host-side verification is still open and operator-only**: the checked-in risk-sizer correction passes
the smoke tests, but production deployment/process identity is **unverified** — do not assume the forward
stream is healthy.

**The dashboard pressure composite remains a side proxy, not a signal** (calibration: collinear with
side, no within-side contrast). The owner's manual pressure/hold observation is a separate, unmeasured
research hypothesis; do not change engine behavior from it. The owner's "where is it headed on a very
strong signal?" question is now measured (`docs/ANALYSIS-2026-10-19-signal-outlook.md`, dashboard 🧭
panel, `tools/signal_outlook.py`): after an 8/8 taken signal the 15–60 min direction is a **coin flip**
(pooled 48.9% [41–57] @30m, live era) with a wide two-sided cone — the outlook is base rates + barrier
odds for manual supervision, **never a forecast, gate, sizing or hold-past-stop input**.

## 2026-10-19 — §1 as it stood before the 10-19 early sessions (numbers as of data collection 276–279)

**This is HANDOFF §1 exactly as it stood between the 2026-10-17 session and the 2026-10-19 early
sessions**, moved here on 2026-10-19 when §1 was rewritten in place (HANDOFF §11 rule 5). **Nothing here
is current** — the numbers are as of data collection 276–279 (log to 2026-10-19 02:59 UTC) and the
struct-stop judgement it points at (2026-10-19 21:00 UTC) has not happened yet. What still matters has
been carried forward into HANDOFF §1/§4/§5/§6, into the era timeline, and into
`docs/REVIEW-2026-10-19-struct-stop-screen.md`.

### The §1 prose that was replaced (2026-10-19, before this session)

### §1 as written (2026-10-19, before the early sessions) (as of **2026-10-19 — data collection 276**)

**Current stance (2026-10-19):** paper-only; `engine.py` remains `TRADING_MODE = "FORWARD_TEST"`.
**Accounting incident reconciled (2026-10-19):** twenty invalid rows (#626–645,
2026-10-18 23:05 – 2026-10-19 02:23 UTC) had blank Entry_Time and zero Take_Profit,
covering BUY TP and SELL TP/BE/SL variants; raw equity **−$58,393.96** was phantom
accounting (twenty rows booked **−$58,544.65** from the $150.69 reference). Last
valid ledger balance: **$150.69** after #625. Raw counts were 644 rows / 138 TP;
valid subset **624 rows / 122 TP** is restored via quarantine. The 20-row suffix was
quarantined with continuity + status/numbering checks (see `tools/repair_phantom_ledger.py`);
the reconciled ledger is **624 rows, 122W/271L/229BE/2TIME, $150.69** and passes
`check_data.py` (0 fail). `check_structural_stop.py` PASS (n=127) still holds.
Snapshot now reflects the reconciled state; see `incident_backups/` for the quarantined
evidence and `docs/REVIEW-2026-10-19-negative-balance.md` for prior incident context.
status ledger with validated replay-loader metrics; FRESH does not mean data integrity passed.
The checked-in risk-sizer correction passes smoke tests, but production deployment/process
identity is **unverified**; do not assume the forward stream is healthy.
See `docs/REVIEW-2026-10-19-negative-balance.md` for evidence and recovery prerequisites.
The book has **624 closed trades** (122W/271L/229BE/2TIME; 31.0% decisive) and remains negative at
the assumed $0.40 round-trip cost. The only open forward-test experiment is the un-stacked structural
stop (127 trades since 2026-10-06 03:00 UTC). Its geometry check passes with zero stops inside the
level, but the screen is **not met**: the current SL share is 47.24% against a strict ≤47.0% bar;
the other four screen measures pass. Review at 2026-10-19 21:00 UTC or n=150, whichever comes first.
The dashboard pressure composite remains a **side proxy, not a signal**. The owner's manual
pressure/hold observation is a separate, unmeasured research hypothesis; do not change engine behavior
from it.

### The dated §1 blocks that moved out (10-16, the n=120 look, 10-17)

### 2026-10-16 — dashboard market-context layer (display-only, **no runtime change**)

- **What shipped on the branch:** `pressure.py` (new read-only module), `tools/pressure_report.py`
  (new CLI), `dashboard.py` panels + a read-only context layer, `tools/smoke_test.py` **Scenario U**
  (45 checks), `docs/ANALYSIS-2026-10-16-dashboard-pressure.md`, README/HANDOFF. **`engine.py`,
  `trade_filter.py`, every parameter, gate, exit and the autosync/deploy path: untouched.** Autosync
  classifies a `dashboard.py` change as `DASH_CHANGED` — dashboard restart only, never the engine
  (`docs/AUTOSYNC.md`).
- **The gauge, and the trap it survived.** The tape composite (60 bars: volume-weighted flow 0.30,
  60-bar momentum 0.20, EMA50−EMA200 0.20, EMA50 30-bar slope 0.15, RSI posture 0.15) reads
  **BUY 71.9% / SELL 28.1%** ("Tape pushed UP hard") at the last bar. But the trend gate makes
  direction ≈ side (§2), so the composite was **measured before being trusted**: joined to every
  entry in the struct-stop era (n=120) and the max-hold era (n=347), bucketed on one pre-specified
  split per side. Verdict in both eras: **"collinear with side — not separable within-side"** —
  buy-pressure at entry spans BUY 49–81 (median 75) and SELL 14–42 (median 22), and the `against`
  bucket has **0 trades on either side in either era**. It is context, not a gate, and the dashboard
  prints that verdict from a live re-join (10-min cache) instead of a hand-typed note.
- **What the panel actually answers** (the useful part): *would the engine take this bar, and if not,
  what is the first thing missing* (BUY 6/8 gates at the last bar — failing the ≥38% rejection wick and
  the 1.10–4.50 ATR bounds); *is price at a level at all* (floor $4181.23 / ceiling $4187.24, price
  $4188.62 = **above the range**, floor 7.62 ATR below price); *what would the live rule risk*
  (level-bound BUY stop $7.88 = 3.9 ATR, TP $4200.43; SELL $1.94); *do the risk gates even allow it*
  (no blackout now, next NY pre-market 12:25 UTC; SL cooldown clear; 2/10 daily SLs; 19 blocked
  setups in the last 24 h — 12 cooldown, 7 blackout); and *is the data alive* (last bar, open-market
  gaps in the unit the 09-29 review used).
- **Honesty mechanics, all machine-checked.** Scenario U pins every mirrored threshold to
  `engine.py`/`trade_filter.py` and the §7 thresholds to the 10-05 analysis doc (the dashboard must
  **never** import the engine, and must not drift from it either), pins `STRUCT_STOP_CUTOVER` to
  `strategy_lab.LIVE_CUTOVER`, proves `pressure.py` is read-only + stdlib-only by AST, and asserts the
  behaviour that matters: the 20-bar level is the engine's previous-20-bars rule, risk comes from the
  reward leg, a weekend close is **not** an outage while an open-market stall **is** (open-market
  minutes — the live log reproduces the 09-29 stall as 284 open minutes), and the §7 card reports
  SCREEN/PASS/REVERT exactly as written. The panel's R/trade reproduces `win_rate_report.py`'s cost
  view to the digit (struct-stop era **−0.053R** = $/trade ÷ mean 1R $5.74, @0.00 spread).

### Struct-stop era at the n=120 look (unchanged bar, **not yet a judgement**)

- **All five §7 screen checks are inside their bars** at n=120 (10 session dates, entries ≥ 2026-10-06
  03:00 UTC): B1 SL/day **5.60** (≤6.5 ✔) · B2 SL share **46.7%** (≤47% ✔ — **0.3 pp of headroom**,
  was 47.7% on 10-15) · B3 scratch **22.5%** (≤35% ✔) · C1 R/trade **−0.053** (≥−0.10 ✔) ·
  C2 decisive WR **39.1%** CI[29.8,49.3] (≥36% ✔). Geometry: A4 level-bound **83.3%** (70–90 ✔),
  A5 median risk **3.27 ATR** (2.7–3.5 ✔). Revert triggers **clear** (R −0.053 vs ≤−0.20; avg SL
  $5.92 vs >$8.60; era DD $91.35 vs >$250). Status: **SCREEN MET — 30 trades short of PASS**
  (PASS needs n≥150 **and** Wilson LB >32.1%).
- **Guard green:** `check_structural_stop.py` → **PASS**, struct-stop cutover n=120, **0 stops inside
  the level**, median clearance +0.50 ATR, boundary bracket confirmed (#498 02:39:09 old rule →
  #499 03:33:05 new rule). `strategy_lab --calib-only` recall **100.0/100.0**.
- **Still not a result.** Gross expectancy is still negative, the window's judgement is the scheduled
  **2026-10-19 21:00 UTC review** (or n=150), and its thresholds are exactly as written on 10-05.
  The 10-16 dashboard work is display-only and deliberately does **not** touch that window.
- **Quote logger** collected 2/14 days (median spread **$0.55**/oz, p95 $0.58; report flags STALE when
  the newest row is >1 h old). The $0.40 round trip remains an assumption until 14 days incl. two
  weekends land; `win_rate_report.py --spread` / `strategy_lab.py --cost` re-cost the book meanwhile.
- **No open trade.** Last closed **#617 BUY TP +$6.64**; #618 BUY SL −$8.87 (live rule, 3.24 ATR risk).
  Skips total 1,413 rows (19 in the last 24 h).

### 2026-10-17 — risk sizer + gates (merged, **deployed**, then corrected in place)

- **Deployed into a closed market.** PR #34 merged 2026-10-16 22:54:47; autosync `d5b81151`
  deployed it **2026-10-16 23:01:54 UTC** (engine restarted 23:02:09) — the §7/§10 rule dates a
  runtime change from its deploy, so that is the cutover for this change too. Gold had closed at
  20:57 UTC, so **no trade ran under it**: the ledger is 624 closed and the struct-stop era is
  still n=127. The first bar it could have acted on is the **Sunday 10-18 reopen**.
- **Three defects, found by measuring the deployed code against its own claim, all corrected in
  the follow-up commit below.** (1) The sizer sized off `self.balance` — the **paper ledger**
  ($150.69), not a broker account — so its "skip below `volume_min`" rule bit the forward test:
  replayed on the era's own 127 entries it skips **76.4%** at the era's rolling balance and
  **84–91%** at $180/$151, while at the $500 ledger start it would instead have sized **0.02** lots
  on 16/127 (128/449 in the 0.75R book). It is a flow stop and a confound, not the R-invariant
  no-op PR #34 claimed: per-trade R is preserved, but the entry stream, the cascade and n are not.
  (2) `execute_simulated_trade` armed the state machine *before* the sizer check and its refuse
  branch returned without clearing it, leaving the previous trade's SL/TP armed against the new
  entry price — the next candle then **logged a trade that was never taken** (reproduced
  hermetically). (3) The LIVE path fell back to the paper ledger when `account_info()` was
  unavailable, and its "Sending:" log printed `LOT_SIZE` instead of the sized volume.
- **What the correction does (one commit, no strategy/param change).** `size_lots()` becomes
  **LIVE-only** — with no broker account it returns `LOT_SIZE`, so the **paper book is
  byte-identical to pre-PR-34** and the struct-stop window is un-stacked again; the trade is
  committed **atomically** (size → refuse → arm), so a skip leaves no position, no trade number
  and no stale SL/TP; LIVE refuses the order when `account_info()` is unavailable. **The FOMC
  17:55–18:30 blackout is reverted** (blackouts are frozen by §6.1, and the window changed the
  entry stream the 10-19 judgement is taken on: it blocked 3 of 127 era entries, +$15.80, moving
  era R/trade by **~0.023R**, roughly a quarter of the headroom to the −0.10R bar) — re-register
  it after 2026-10-19. `MIN_SPREAD_POINTS` stays (LIVE-only, so paper-inert). `ATR_SL_MULT` /
  `RR_TARGET` / `SL_CLEAR_ATR` untouched; the 1:2 target stays blocked until 10-19 (§6.1).
- **Deploy gate now covers it.** `tools/smoke_test.py` **Scenario V** (paper lot parity, LIVE
  sizing arithmetic at $180.15/$2,400, the skip-path invariant, the frozen 4-window blackout list
  + a positive control). PR #34 shipped with **zero** smoke coverage of its own code — Scenario U
  only pinned the dashboard mirrors.
- **No new era boundary.** The paper book takes the same trades at the same lot as pre-PR-34, so the
  struct-stop window (entries ≥ 2026-10-06 03:00 UTC) continues **without an isolation break** — this
  commit's own deploy time is not a cutover, and nothing is re-sliced (§7, §11 rule 3).
- **Current struct-stop screen at n=127: NOT MET.** The mechanical geometry check passes (0 stops
  inside their level); four of the five screen measures are inside their bars, but SL share is
  **47.24% vs the strict ≤47.0% limit**. Do not round this up to a pass. The remaining review is
  2026-10-19 21:00 UTC or n=150, whichever comes first; PASS still requires n≥150 and Wilson LB
  >32.1%. **Deferred:** the weekend / flat-before-close gate (§6.3(h), separate post-10-19 PR).
  Pre-registration + erratum: `docs/PREREG-2026-10-17-risk-sizer.md`.

**Dated session history is in `docs/HANDOFF-HISTORY.md`** (append-only, newest first): §1 as it stood on
10-15, the 10-13 tooling session, the 10-05 state block, the 09-29 feed outage, and the stances as
written then. §1 is current-state only — see §11 rule 5.

## 2026-10-15 — data refresh + struct-stop era past the n≥100 screen; HANDOFF restored

**This is HANDOFF §1 exactly as it stood on 2026-10-15**, moved here on 2026-10-16 when §1 was
rewritten in place (HANDOFF §11 rule 5). **Nothing here is current.** The numbers are as of
data collection 243–246; everything that still matters was carried forward into the 2026-10-16 §1,
and the struct-stop judgement it points at (2026-10-19 21:00 UTC) has not happened yet.

### §1 as written (2026-10-15) (as of **2026-10-15, ~14:00 UTC — data collection 243**)

### 2026-10-15 update — data refresh + struct-stop era past n=100 screen (no runtime change)

- **Snapshot refreshed.** `handoff_check.py --update` brought the machine-checked block current to 2026-10-15 11:59 UTC (data collection 243, 606 closed, no open trade). Integrity still **0 fail / 8 warn**.
- **Struct-stop era now n=109** (entries ≥ 2026-10-06 03:00 UTC). Crossed the pre-registered n≥100 screen. Outcomes: **34W / 52L / 22BE / 1TIME**; decisive WR **39.5%**; gross **−$30.23 (−$0.277/trade)**; at assumed $0.40 RT **−$0.119R/trade** (from `win_rate_report.py --spread 0.40`). Guard still **PASS** (0 stops inside level; level-bound share 82.6%, median clearance +0.50 ATR, median risk 3.23 ATR).
- **Against the pre-registered bars** (from `ANALYSIS-2026-10-05-stop-loss-geometry.md` §7, unchanged): SL events **5.2 / calendar day** (bar ≤6.5 ✔); SL share **47.7%** (bar ≤47% — still marginal ✗ by 0.7 pp); BE share **20.2%** (≤35% ✔); avg SL loss **$5.91** vs pre-change ~$3.91 = **1.51×** (revert >2.2× ✔); peak-to-trough DD in era **$76.84** (revert >$250 ✔). Gross expectancy still negative. **Not yet a PASS/FAIL judgement** — the scheduled 10-19 21:00 review (targeting n≈130) comes next; this is the first look past the screen.
- **Quote logger is collecting.** `xm_data/` has quotes-2026-10-13..15.csv + symbol_spec. Median spread **$0.55** (p95 $0.58) per oz. Report currently notes STALE (newest row ~2h old at check time — normal if market closed or logger paused). Cost model is moving from pure assumption toward measurement; full 14-day (incl. weekends) still needed before replacing the $0.20/side constant.
- **No open trade.** Last closed #607 BUY SL −$5.91. Equity (true) **$150.96** (engine ledger $167.93, drift +$16.97). Net-of-assumed-cost ledger **−$591.44**.
- **Still no runtime change.** Struct-stop window remains the only live experiment. Do not stack another change until the 10-19 review judges the bars.

### 2026-10-15 (later) — HANDOFF restored and consolidated (docs only, **no runtime change**)

- **The file had been truncated; it is restored.** The daily doc job rewrote `docs/HANDOFF.md` twice on 10-15:
  `43884e1` (14:06 UTC) wrote the single line `PLACEHOLDER - will replace`, and `072459d` (14:07 UTC) put back
  the front matter + §1 only. **§2–§11 were lost** — the gates, the evidence base, next steps, the verification
  ritual, data gotchas, architecture, the deploy runbook and the **§11 protocol itself** — along with the §1
  history blocks, `Definitions` and the 09-29 feed-outage record. **`handoff_check.py` still said FRESH** (it only
  read the snapshot block), so nothing flagged it. Content recovered from `712d106` (the 10-13 version).
- **The gate now checks structure, not just freshness.** `tools/handoff_check.py` gained `doc_structure()`:
  every `## 1.`–`## 11.` section must exist, placeholder markers are flagged, and every `§N` reference must
  resolve. `--update` **refuses to stamp a truncated file**, and smoke Scenario P covers all three rules.
- **§1 no longer accumulates.** The dated session blocks (10-13 tooling, the 10-05 state, the 09-29 outage,
  the superseded stances) moved to **`docs/HANDOFF-HISTORY.md`** (append-only, newest first); §1 keeps the
  current state and pointers only. That is the whole of the 10-15 shrinkage: 223 lines of §1 were 92% history
  that no session ever pruned. New rule 5 in §11 stops it coming back.
- **Why it matters beyond tidiness:** the file is rewritten by an automated daily job, and an 886-line / 68 KB
  document is more than that job can reliably reproduce — the truncation is a symptom of the size. A smaller
  §1 (and a hard structural gate) is the mitigation.

**Current stance (2026-10-15, later):** still **paper-only**, no runtime change. Stop-loss question answered in
`docs/ANALYSIS-2026-10-15-stop-loss-rate.md`: the replay-vs-live gap is closed (tooling fix), and the next candidate, the 0.25 ATR level test, is **pre-registered on paper** (`docs/PREREG-2026-10-15-level-test-0.25.md`) to be deployed only after the 10-19 review.

**Current stance (2026-10-15):** unchanged and still **paper-only**. Edge is **not confirmed**, and neither the
10-15 data refresh nor this docs pass claims one. The struct-stop era has crossed its pre-registered n≥100
**screen** (n=109, 39.5% decisive WR, gross −$0.277/trade, −$0.119R/trade at the assumed cost) with the
mechanical invariant **PASS**ing and every revert trigger clear, but the SL-share bar is still marginal
(47.7% vs ≤47%) and expectancy is still negative — so the judgement stays exactly where the bar put it:
the scheduled **2026-10-19 21:00 UTC review (targeting n≈130)**, thresholds as written on 10-05.
**No runtime change is stacked on the open window.** The honest one-line summary of the book: 606 closed
trades, 31.2% decisive, engine ledger **$167.93** from a $500 start (true equity $150.96, drift +$16.97),
**−$591.44** at the assumed $0.20/side — i.e. **−$0.576/trade true, −$0.976/trade at the assumed cost**.
The cost model is moving from assumption toward measurement (quote logger collecting, median spread
$0.55/oz; needs 14 days incl. two weekends) — a reason to keep measuring, not to size up.

**Dated session history is in `docs/HANDOFF-HISTORY.md`** (append-only, newest first): the 10-13 tooling
session, the 10-05 state block, the 09-29 feed outage, and the stances as written then. §1 is current-state
only — see §11 rule 5.



- **What this session did.** Branch `arena/3f12a4a6-gold-trading-bot`, **no PR yet** (the owner asked to
  finalise first). Compared gold with `bitcoin-trading-bot`'s improvements and changed **only** `tools/`,
  `deploy/` (one new unit file), `docs/`, `.gitignore`, `README.md`, `archive/PROJECT_LOG.md`. `engine.py`, `trade_filter.py`, `dashboard.py` and every
  parameter, gate and exit: **untouched**; the struct-stop window is undisturbed. Verdict per BTC item (done /
  queued / not for gold, with evidence): `docs/ANALYSIS-2026-10-13-btc-port-assessment.md` §3.
- **The struct-stop cutover is 2026-10-06 03:00 UTC, not 10-05 21:00.** PR #28 merged 10-06 00:31:53 and autosync
  deployed it at 03:00:04. #495–#498 (1W/3L, −$9.90) ran the **old** rule and are **not** in the era, so the era is
  **n = 78**. The guard had been red on this: `check_structural_stop.py` now **PASSES** (A1 stop-inside-level **= 0**;
  min clearance +0.36 ATR, level-bound median +0.50; level-bound share 82.1%; median risk 3.23 ATR — all inside the
  A2/A4/A5 bars; the one level-bound trade under 0.5 ATR, #550, is a duplicated log candle, not an engine fault) and
  it now **proves the deploy boundary from the ledger** (last OLD-rule #498 02:39:09 → first NEW-rule #499 03:33:05).
  Erratum at the top of `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md`; thresholds in its §7 unchanged.
- **Replay-harness fix.** `strategy_lab` took the 20-bar level over 19 prior bars; the engine uses 20 (the lab now
  equals the engine's logged `Dynamic_Floor` on 99.81% of bars, was 85.97%). Funnel recall 99.8/99.7 → **100.0/100.0**;
  quoted replay figures move the way the design argued (stop-inside-level 63.8% → 66.4%; master-era replay
  structstop −0.101R → −0.076R at $0.20/side; "better in 3 of 4 eras" unchanged). No conclusion reverses.
- **This file is now machine-checked.** The snapshot block at the top is recomputed by `tools/handoff_check.py`
  and every autosync digest carries `📝 handoff: fresh|STALE` (advisory). §1 had been **8 days / 82 trades stale**
  (it said 493 closed; the box had 575) and the "daily job" last refreshed it on 09-25 (PR #22).
- **Struct-stop era, first look — DESCRIPTIVE ONLY. n = 78 is below the pre-registered n = 100 screen; this is NOT a
  result, in either direction, and the bar is unchanged.** 25W/37L/15BE/1TIME; decisive WR **40.3%** [29.0–52.7];
  gross **−$0.70** (−$0.009/trade, **+0.007R**); **−$31.90 = −$0.409/trade at the assumed $0.40 round trip**;
  SL events **5.1/calendar day** (bar ≤ 6.5); SL share **47.4%** (bar ≤ 47% — marginal); BE share **19.2%** (≤ 35%);
  avg SL loss $5.57 vs $3.91 on the pre-change 0.75R book = **1.42×** (revert > 2.2×); era drawdown below start
  **$13.77** (revert > $250; peak-to-trough $59.67); trades open across a price-log gap **0** (revert at 2+); longest
  hold 240.1 min (the one TIME exit, #526, in-session). **Moving the four old-rule trades out flatters the era by
  $9.90 (−$10.60 → −$0.70 gross)** — disclosed with before/after numbers in the assessment, F1. Pace is ~10.7
  trades/day, so n = 100 lands ~10-15 and the **10-19 21:00 review comes first at n ≈ 130** (weekends are thin).
- **Latent, not bitten:** the daily-loss breaker counts SLs among the last 30 ledger rows (34 entries under-counted,
  never silently off) — queued for the post-window runtime PR (assessment F3).
- **Built after the first review — all tooling, deployable by autosync with no engine restart:**
  - `win_rate_report.py --spread X`: the net-of-cost view (ties to the snapshot, −$549.51 at $0.40 a round trip).
  - **The GOLD quote + contract-spec logger** — `tools/mt5_quotes.py`, `deploy/mt5quotes.service` (installs as
    `mt5quotes-gold`), `tools/xm_quote_report.py`, `tools/broker_time.py`, `docs/XM-LOGGER.md`. Read-only, privacy
    allow-lists (the repo is public), gold's closures handled (a frozen tick is a `STALE` row, never an outage, and
    never moves the learned server offset). Autosync now commits `xm_data/` and the digest has a `📡 xm logger:`
    line; a ⚠️ is raised only when the *logger* stops (newest row > 15 min old), never because gold is shut.
  - **The large-N path** — `tools/history_to_log.py` (proves the server-time → UTC conversion against the live log's
    MT5 era, **observes** a DST change inside the overlap, refuses rather than guesses), `strategy_lab --bars` /
    `--ratchet`, `docs/ACCELERATE-TESTING.md`. **Calibration, like for like** (the live struct-stop era, same window,
    zero cost): the replay gives **+0.066 R/trade** (n=77), the ledger **+0.007** (n=78) — the replay is ≈ **0.06 R/trade
    more generous than live**: inside the noise at this n (SE ≈ 0.1) but in the direction its caveats predict, so read
    absolute replay P&L as optimistic and trust only differences between rows.
  - Smoke is now **A–T, 315 checks, ~10 s, hermetic**; 62 mutations of the new code were all killed; the autosync
    wiring was exercised in a sandbox (bare origin, stubbed `curl`/`systemctl`): fresh / stale / frozen-feed /
    crashed-report / not-installed / `xm_data`-conflict cases, and — the one that matters for this very deploy — the
    **old `autosync.sh` merging its own new version mid-run finishes cleanly** (git replaces files, the running bash
    keeps the old inode). **Neither the logger nor the dump has run against a real terminal** (none exists in the
    sandbox): the first run on the box is their real validation.
- **Decided by the owner (2026-10-13):** leave `NOTIFY` as is (not ported); the `--spread` view, the logger and the
  large-N path: **build** (done above).
- **On the box, in this order — tooling-only, safe inside the window:** (1) after the merge autosync deploys
  everything (no engine restart: `CORE_CHANGED` stays 0); (2) **install `mt5quotes-gold`** (`docs/XM-LOGGER.md` §3)
  **before Sunday 2026-10-25** — the server clock changes that day and the logger's offset column is the evidence
  for the DST rule, and the cost model is still a guess (−$319.51 gross vs −$549.51 at $0.20/side) until it has
  14 days incl. 2 weekends; (3) one `mt5_history_dump.py --bars 100000 --timeframe M1`, then `history_to_log.py` and
  `strategy_lab --bars` (`docs/ACCELERATE-TESTING.md` §2) — its output shows the proof, and anything under a 90%
  exact-OHLC match is refused.

---

## 2026-10-05 (2nd session) — §1 state as it stood then (numbers are as of 10-05)

- Repo: `shashidaren/gold-trading-bot`, default branch `main`. The 10-05 second session (branch
  `arena/bf9e984a-gold-trading-bot`, PR #28) **shipped one runtime change**: the
  **structural stop** (`SL_CLEAR_ATR`/`RR_TARGET` in `engine.py`, §4) plus the
  costed/stateful replay harness that was the stated blocker for judging exit
  changes (`tools/strategy_lab.py`) and a geometry guard (`tools/check_structural_stop.py`).
  Everything else — entries, gates, ratchet trigger, max-hold, lot, mode — is untouched.
  Read `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` (evidence + the pre-registered bar)
  and `docs/REVIEW-2026-10-05.md` (earlier verdict) before proposing anything else.
- Historical deploys unchanged: **PR #15 MERGED** (09-21, `MAX_HOLD_MINUTES =
  240` live ~06:00); **PR #9** (09-15) BE 0.30→0.75R; **PR #7** (09-10) ratchet
  + BUY-only London blackout + trend-side daily breaker. Production-host
  hardening/verification still **not performed** (§6 item 0).
- Current ledger (**data collection 226**, last bar 2026-10-13 11:59 UTC; **not frozen**, §1a):
  **575 closed / 1 active** (SELL #577 since 10:30, SL 4189.49 / TP 4172.28, ratchet not armed — verified not
  stuck), 110W / 248L / 215BE / **2 TIME** → **30.7% decisive** [26.2–35.7], paper P&L from $500
  **−$319.51 → $180.49** (engine ledger $197.46, drift +$16.97), **−0.136R/trade** (avg 1R $4.08), payoff 1.54,
  scratch rate 37.4%. **At the assumed $0.20/side the same ledger is −$549.51 (−$0.956/trade, −0.253R)** — scratches
  pay a spread the paper engine never books. Integrity **0 fail / 8 warn**; synthetic smoke **A–T passed** (315 checks).
  The 10-05 figures this replaces: 493 closed, 28.8% decisive, −$308.91 → $208.05, −0.163R.
  - **0.75R master book** (entries ≥09-15 06:00; **now includes the struct-stop era**): **n=400**,
    92W/189L/117BE/2TIME, **32.7% decisive** [27.5–38.4], **−$195.31 = −$0.488/trade**; the part *before* the
    deploy (n=322): 67W/152L/102BE/1TIME, 30.6% [24.9–37.0], −$0.604/trade = −0.162R, 8.0 SL/trading day.
    The original −$0.40 falsification bar remains tripped (formally since 09-17).
  - **Max-hold era** (entries ≥09-21 06:00, re-reviewed 10-05, isolation closed): **n=305**,
    72W/148L/83BE/**2TIME**, **32.7% decisive** [26.9–39.2], **−$154.70 = −$0.507/trade**. The 240-min cap bound in-session
    exactly once, **#526** (10-08 BUY, ratchet armed, closed at the cap after 240.1 min, +$0.48); the other TIME exit is
    the **weekend-gap hold #476** (49.1 h, −$1.52) — the cap cannot fire while the market is closed, so positions can ride a
    daily/weekly closure with an unenforceable stop (LIVE risk).
  - 0.30R era unchanged: n=130, 10W/22L/98BE, 31.2% decisive, −$0.321/trade.
    Pre-ratchet: n=45, 17.8%, −$1.834/trade. 0.75R pre-maxhold: n=95, 32.8%,
    −$0.427/trade.
- **Fallback step-2 (ratchet-off) is now ANSWERABLE and the answer is no.** The trigger was met
  (n=209 → now n=223, −$0.646/trade ≤ −$0.40) and the blocker was the missing
  costed/stateful/era-matched harness — that harness exists now (`tools/strategy_lab.py`, funnel
  recall 99.7–100% per era). Its verdict: ratchet-off gross is ≈ breakeven (−0.052R), it works
  only by deleting the scratch bucket (**61.7% of trades become full stop-outs** vs 45.4% today),
  and **stacked on the shipped structural stop it adds nothing (−0.131R vs −0.124R)**.
  **Recommendation: drop step 2 rather than spend an isolation slot on it** (owner may override;
  never back to 0.30R). See `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` §8(e).
- **`H-side-awareness` DROPPED (10-05, its own bar):** (a) 27 decisive in the
  60-min counter-trend bucket ≥25 ✔; **(b) FAIL** — 60-min aligned BUY better
  (+8.1 pp) but aligned SELL worse (−6.4 pp), and the failing side flips at
  240 min; **(c) FAIL** — no rising-gold sub-period supplies the comparison.
  No BUY ban / SELL-only / momentum gate. BUY-side bleed is observation only:
  max-hold BUY n=92, 24.6% decisive, −$1.306/trade vs SELL 35.7%, +$0.008,
  Fisher p=0.2031 (**weaker** than the 10-01 p=0.1137).
- **Session-band candidate DOWNGRADED (10-05, second session).** It was measured costed and
  cascade-aware for the first time: baseline replay Asia/rollover +0.022R vs London/NY −0.246R
  (gap 0.268R) — but under the structural stop the same split is +0.001R vs −0.084R (**gap
  0.085R**). The band was mostly a **proxy for the stop-geometry defect** (wider LDN/NY tape puts
  a 2·ATR stop inside the level more often), so it fails REVIEW-2026-10-05 §5a's own
  independence clause (b) and must NOT be stacked on the current window. The older
  ledger-only figures (39.8% vs 25.4% dec, pooled Fisher p=0.034) stand as description, not as
  a tradeable gate.
- **Ledger description, unchanged by today:** the master-era bleed is still
  Asia/rollover-better (125 trades 39.8% dec, +$0.258/trade) than London/NY (179, 25.4%,
  −$1.073) and BUY (24.5% dec all-time, −$0.995/trade) worse than SELL (33.3%, −$0.265).
- Candidate refresh done era-correct **and risk-normalized** (R = Profit ÷
  2·ATR): **RSI≥45 still dropped** (−0.151R keep vs −0.135R skip master);
  **MAX_ATR 4.50→2.50 normalized-rejected** (−0.146R vs −0.143R — the dollar
  gap was position risk; ATR≥2.0 actually beats ATR<2.0 in R); **ATR<2.0
  rejected**; **post-BE <5-min same-side re-entry** is the strongest queued
  candidate (−0.325R vs −0.104R master; −0.389R vs −0.111R max-hold) but stays
  observational pending the stateful cascade replay + a pre-registered bar.
- **ANALYSIS-2026-10-01 §4 tool corrections — now mostly covered by
  `tools/strategy_lab.py`, which is the canonical replay for exit/gate decisions:** cost model
  on every exit including BE ✓, SL-streak + wall-clock cascade with production semantics ✓
  (block only while the *last closed trade* was an SL; escalation at streak ≥ 2; daily breaker
  counted by `Exit_Time`), direction-aware blackouts + era-correct gates ✓, era labelling ✓,
  per-era funnel recall as a self-check ✓. **Still open:** MFE/MAE alignment + era labels in
  `analyze_losers.py`; decisive-WR labels + current-rule fallbacks in `pathwalk_sims.py` /
  `phantom_trades.py`; `validate_gates.py` still replays gates ledger-side (cascade-ignorant).
  Those tools remain descriptive only — their simulated profit must not pick a change.
- Live bot historically runs from `/opt/gold` via systemd (`goldbot`, `mt5feed`,
  Wine `mt5`); daily HANDOFF job + autosync every 3 h (§10). Live-host state
  cannot be inferred from this checkout alone.

---

## 2026-09-29 — 🛑 feed outage: 6 h of silent starvation (was §1a)

- **What happened:** the host rebooted at **08:29:15 UTC** (journal
  `-- Boot c22469d0… --`). `goldbot`, `mt5feed` and `mt5` all restarted at
  08:29:18, but **`mt5.service` never came back — stuck in
  `deactivating (stop-sigterm)`**, so the terminal published no more bars.
  `mt5_last_candle.json` froze at `ts=1790681280` (11:28 server / 08:28 UTC,
  mtime 08:29) and `status.json` froze at 08:29:19 → dashboard **STALE** from
  ~08:34 (the only detector that worked).
- **Why it was invisible:** the engine stayed `active (running)` and looped on
  the *deduped* candle, whose `continue` jumped over the stale-feed guard, and
  `feed_stale_seconds()` reads `_last_price_mono` — never set after a restart —
  so it reported `0.0` ("fresh") the whole time. No journal line, no Telegram
  alert; the 09:00/12:00/15:00 autosync digests said `data: no new data` and
  `check_data.py` was 0 fail.
- **Precursor (undocumented):** a second stall **09-28 17:50:05 → 09-29
  03:33:37** (9.7 h, ~283 open-market minutes) with the same signature — so the
  failure hit twice in 24 h, and the ~09-28 "slide" discussion never noticed it.
- **Impact (historical):** ~6 h of London/NY missing (engine does **not**
  backfill) + ~283 open minutes on 09-28. **No trade was open across either
  outage** (#397 exit 09-28 17:40:02, #403 exit 09-29 07:51:03) → no phantom P&L.
  At the outage the ledger froze at 402 closed, 64W/166L/172BE, −$254.99.
  **Recovery now visible in CSVs:** 09-29 14:47:39 (6 h 18 min gap); another
  14:50:40→15:43:06 gap also overlaps no trade. Data advances through 10-01
  14:59:04; §1 has current numbers. This does not prove server-side hardening.
  **Strategy/params untouched; the max-hold isolation window is undisturbed.**
- **Fix shipped (detection only, `docs/REVIEW-2026-09-29-feed-outage.md`):**
  engine feed-health check (`feed_publisher_age_seconds()` = sidecar heartbeat,
  missing/corrupt file, price-event stall — evaluated **before** the dedup,
  journal print every 5 min, Telegram on the 30-min cooldown, one recovery
  line); smoke **Scenario L**; autosync digest now carries
  `📈 candles: ok|STALE N open min`.
- **Ops follow-ups (server-side, not in the repo):** harden `mt5.service`
  (`Restart=always`, `RestartSec=10`, `TimeoutStopSec=30`,
  `KillMode=control-group`, `systemctl enable`), use the recovery runbook in
  §7 of the review, and treat the Wine MT5 terminal as the least reliable
  component (the 08:29 reboot cause is still unexplained).

---

## Stances as written then (superseded, kept verbatim)

**Current stance (2026-10-13):** unchanged and still **paper-only**. Edge is **not confirmed** and nothing in the
10-13 session claims one — it fixed the guard, not the strategy. The struct-stop era is at n=78 with its mechanical
invariant **passing**; the pre-registered read is at n≥100 / **2026-10-19 21:00 UTC**, with the thresholds exactly as
written on 10-05. The honest one-line summary of the book: gross **−0.136R/trade** over 575 trades, **−0.253R at the
assumed cost**, with the new stop's era sitting near gross break-even on 78 trades — which is a reason to keep
measuring (and to measure the cost for real), not a reason to size up.

**Prior stance (2026-10-05, end of day):** Edge is **not confirmed** — and today's
change does not claim one. The pre-change book (0.75R master −$0.581/trade, max-hold
−$0.646) still loses before realistic costs, and the costed replay of the new geometry is
still negative (−0.106R at $0.30 round trip); it halves the bleed and removes a mechanical
defect (a stop that sat inside the level the entry was anchored to), which is why it shipped.
**First real measurement is a pre-registered forward read at n≥100 (~2026-10-19), never
before** — bar and revert triggers in `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` §7.
The **10-05 re-review is complete**
(`docs/REVIEW-2026-10-05.md`): isolation closed at n=209, the max-hold cap
never bound an in-session trade, and the fallback **step-2 trigger is met** —
so a **ratchet-off experiment is eligible but not approved**: it needs the
costed/stateful harness and an explicit pre-registration + sign-off first.
`H-side-awareness` is **dropped** on its own terms. New candidate (not
adopted): the London/NY session-band bleed. **No runtime change was made or
adopted at the 10-05 *scheduled review* (that review changed nothing).** The structural
stop is the first runtime change since 09-21 and it is a **reversible experiment**: one
commit, `git revert` if the bar fails. Stay paper-only and do **not** treat the bot as
income. Capital decisions remain evidence-gated, not promised by the existing
calendar timeline (§11).


### 2026-10-19 — superseded dashboard-session snapshot

## 1. Where things stand (as of **2026-10-19 — data collection 279**)

**Current stance (2026-10-19, ~06:00 UTC):** paper-only; `engine.py` remains `TRADING_MODE = "FORWARD_TEST"`.

**The book:** **624 closed trades** (122W/271L/229BE/2TIME; 31.0% decisive), engine ledger **$150.69**,
true equity $133.71, net **−$615.89** at the assumed $0.40 round trip. The quote logger has **5/14
complete days, 1/2 weekends** collected (first-look median spread $0.55) — **not enough to replace the
$0.40 assumption**, which therefore stands.

**The only open experiment** is the un-stacked **structural stop** (entries ≥ **2026-10-06 03:00 UTC**),
now **n=127 closed** (37W/60L/29BE/1TIME) over 10 entry dates. Its mechanical guard is green
(`check_structural_stop.py` **PASS** — **0 stops inside their level**, median clearance +0.50 ATR;
replay recall 100.0/100.0), but the pre-registered **screen is NOT met**: **SL share 47.24% against the
strict ≤47.0% bar**; the other four screen measures pass (SL/day 6.00 ≤ 6.5, scratch 22.83% ≤ 35%,
R/trade −0.065R ≥ −0.10R, decisive WR 38.14% [29.1–48.1] ≥ 36%). A PASS is unreachable at n=127
(Wilson LB 29.1% < the required 32.1%), and the era is negative after costs (−$98.30, −0.135R at $0.40).

