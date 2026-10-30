"I'm working on my Gold trading bot. Here is my project log: [paste the contents of PROJECT_LOG.md]. Currently, I want to work on [X]."

# Gold Engine - Development & Strategy Log

## ️ Architecture Overview
The bot is split into two distinct files to separate signal generation from risk management:
1. **`engine.py`**: Handles data ingestion (Twelve Data / MT5), indicator calculation (EMA, RSI, ATR), and price-action signal generation (The "Funnel").
2. **`trade_filter.py`**: Acts as the final portfolio-level gatekeeper. Checks time blackouts, SL cooldowns, and ATR minimums before allowing execution.

## 🎯 Current Strategy Rules (The Funnel)
For a BUY signal to trigger, ALL of the following must be true:
1. **Tested Floor**: Price drops to the 20-candle low (with 0.20% buffer — note this is a
   *price-%*, ≈4.5× the median ATR at today's gold price, so in practice it passes on ~87% of
   bars; the shipped fix was to move the stop beyond the level rather than silently re-tune the
   entry. See `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` §2.)
2. **Valid Rejection**: Lower wick is ≥ 38% of the total candle range.
3. **Held Support**: Candle closes *above* the dynamic floor.
4. **Trend Confirmed**: EMA 50 > EMA 200 (Uptrend only).
5. **RSI Filter**: RSI is between 30.0 and 68.0.
6. **ATR Filter**: ATR > 1.10.
7. **Trade Filter**: Passes `trade_filter.py` checks (No blackouts, no SL cooldown).

## ⚙️ Current Parameters
### engine.py
- `LOOKBACK_PERIOD` = 20
- `WICK_RATIO_TARGET` = 0.38
- `EMA_FAST` = 50, `EMA_SLOW` = 200
- `ATR_SL_MULT` = 2.0, `ATR_TP_MULT` = 3.0
- `SL_CLEAR_ATR` = 0.5, `RR_TARGET` = 1.5 — **structural stop, live 2026-10-06 03:00 UTC** (planned 10-05 21:00; autosync deployed it at 03:00:04):
  `risk = max(2·ATR, |entry − 20-bar level| + 0.5·ATR)`, `TP = RR_TARGET × actual risk`
  (so 1:1.5 is held against the real stop; identical to the old geometry when the level does
  not bind). Why: the level test's 0.20% price buffer is ≈4.5× the median ATR, so entries fill
  a median 2.42 ATR from the level and a plain 2·ATR stop sat *inside* the range on 63.8% of
  the 0.75R master book (`docs/ANALYSIS-2026-10-05-stop-loss-geometry.md`)
- `BE_TRIGGER_R` = 0.75 (breakeven ratchet: SL -> entry at +0.75R; was 0.30 from
  2026-09-10 to 2026-09-15 — raised after the 164-trade review)
- `MAX_HOLD_MINUTES` = 240 (max-hold time stop, live 2026-09-21: any open trade
  older than 4 h closes at market with reason TIME — neutral bucket like BE,
  price exits take priority, wall-clock, engine-side only)
- `REQUIRE_VOLUME_CONFIRM` = False
- `REQUIRE_TREND_CONFIRM` = True
- `MIN_ATR` = 1.10

### trade_filter.py
- `SL_COOLDOWN_MINUTES` = 30
- `MIN_ATR_TO_TRADE` = 1.10
- **Blackouts (UTC)**: London Open (07:55-08:15), NY Open (12:25-12:45), NY Volatility (13:55-14:15).

## 📝 Changelog & Recent Fixes
- **[2026-10-26 → dashboard 🚦 Readiness tab: timeline in days, completed vs pending (DISPLAY-ONLY; NO runtime change / NO order)]** Owner ask: *"add another tab in the dashboard to gauge a readiness timeline in days and whats completed and what pending for my reference, after the updates wecan merge the changes"*. Added **`readiness.py`** — stdlib-only, read-only display layer (no engine import, no state write, no order path) that mirrors `docs/EXECUTION-PLAN.md` §3/§4 and formats `tools/live_readiness.py`: elapsed forward-test / structural-stop-era days, days left to the 14-day/2-weekend cost sample, the 2026-11-01 US DST cross-check and the 2026-12-01 pre-registered window, plus conditional ~2–4 month edge and ~6–12 month G2 reviews; a dated **completed** milestone list (11 items), six **pending** owner/host blockers, and all 20 live gate checks (9 PASS / 8 TODO / 3 MANUAL → **LIVE GATE CLOSED**). `tools/live_readiness.py` gained `quote_progress()` / `snapshot()` so the CLI and the tab share one quote read. `dashboard.py` gained the `?tab=readiness` nav button + panel, a 5-minute cached read (`?readiness=refresh` forces it), and is independent of `pressure.py` so a broken trading read cannot hide the timeline. `tools/autosync.sh` watches `readiness.py` and `tools/live_readiness.py` in both `DASH_CHANGED` and the hand-edit guard — dashboard-only restart, engine untouched. New **`tools/test_readiness_tab.py`** (16 hermetic tests: day maths, timeline states, gate/scorecard wiring, missing-data dashes, render, degraded read, cache/refresh); updated the existing `TABS` assertion in `tools/test_dashboard_context.py`. Suites: readiness 16 OK, dashboard 17 OK, `live_readiness` 18 OK, smoke A–Z+AA PASSED, 64 `goldbot` tests, `py_compile` OK. Docs: README, `docs/AUTOSYNC.md`, `docs/HANDOFF.md` §10 + cheat sheet, `docs/EXECUTION-PLAN.md` §0. **Day counts are conditional estimates, not deadlines or a profit forecast; no strategy parameter, gate, `TRADING_MODE` or order path changed.**
- **[2026-10-26 → full-system review, “Follow execution plan” queue, LIVE-path hardening (NO strategy change / NO deploy / NO order)]** Owner ask: *“review everything … finalise engine … i just need to state 'follow execution plan' until we get something workable for live trade.”* Re-ran every session check on collection 349 (709 closes, era n=212, log to 10-26 11:59 UTC): `check_data` 0 fail/8 warn, `handoff_check` STALE→FRESH (old §1 archived to HANDOFF-HISTORY per §11 rule 5), `check_structural_stop` PASS (0 inside, 83.0% level-bound, +0.50 ATR clearance, 3.32 ATR risk), `check_gap_rides` 3/2 (no gap-through/worse exit/weekend), `pressure_report` SCREEN MET (37.5% [30.2–45.4], −0.054R), `--calib-only` 99.8%, `xm_quote_report` 11/14 days + 1/2 weekends, median $0.55. **DST gate MET:** broker offset +3h→+2h at 2026-10-25 22:00:30 UTC, EU rule 100% of 24 379 rows — the 10-25 `hold_for_dst` decision is released. New findings: (i) ~2 h of open-market M1 bars are missing on the price path at the Sunday reopen (quotes fresh from 22:00, bar log resumes 23:59:24) → host `mt5feed`/`goldbot` check; (ii) `derive_daily_closure()` still derives `(20:58, 22:00)` because no post-DST daily break is logged yet → verify after 10-26 evening; (iii) captured spec `filling_mode=2` (IOC only) while `execute_live_trade` hard-coded `ORDER_FILLING_FOK` — every real order would likely have been rejected. **Shipped (LIVE path only, ZERO paper behaviour change):** `live_armed()` + `/opt/gold/LIVE_HALT` kill switch (fail-closed, checked in `run_live` and before `order_send`), `resolve_order_filling()` from the symbol bitmask (refuses when no FOK/IOC policy), `run_live` now evaluates **closed** M1 bars (position 1) with `mt5_next_candle` dedup and its own persisted `live_last_candle_ts` watermark in `status.json`. New **`tools/live_readiness.py`** — 20 read-only AST/data/evidence checks (`--json`, `--strict`), currently **9 PASS / 8 TODO / 3 MANUAL → LIVE GATE CLOSED**; new `tools/test_live_readiness.py` (18 tests) and smoke **Scenario AA** (arm gate, filling bitmask, captured spec, source pins, functional fake-MT5 closed-bar loop + restart dedup). All suites PASS: smoke A–Z+AA, 64 `goldbot` tests, 18 new tests, `py_compile`. **No `engine.py` strategy parameter, gate, exit or `TRADING_MODE` changed.** Refreshed clearance grid: 1.5 ATR −0.024R/t at $0.20/side vs live −0.110 (3/4 of the 10-25 pre-declared bar) → wrote `docs/PREREG-2026-10-26-structstop1.5.md` as a **DRAFT pending G1 owner sign-off**. Rebuilt `docs/EXECUTION-PLAN.md` around the canonical prompt **“Follow execution plan.”** (alias “Execute the plan.”) with an explicit authority contract (paper-only; G1 prereg sign-off, G2 real money), a ritual, Track A (strategy evidence), Track B (LIVE engineering), Track C (go/no-go) and a definition of “workable for live trade”. Full record: `docs/REVIEW-2026-10-26-full-system-audit.md`. Verdict unchanged: **no demonstrated edge after costs; no real orders.**
- **[2026-10-21 → "Execute the plan": every-session verification + handoff refresh (docs only; NO runtime change)]** Session start = the plan's first eligible step: ran `check_data.py` (0 fail / 8 warn; 657 trades, 129W/285L/241BE/2TIME, 31.2% decisive), `handoff_check.py` (FRESH after snapshot rewrite — old §1 archived to `docs/HANDOFF-HISTORY.md` per §11 rule 5), `check_structural_stop.py` (PASS at struct-stop n=160: 0 post-cutover stops inside the level, 81.9% level-bound, median clearance +0.50 ATR, median risk 3.32 ATR; cutover bracket #498 OLD at 10-06 02:39:09 → #499 NEW at 10-06 03:33:05, LIVE_CUTOVER 10-06 03:00 inside), `check_gap_rides.py` (still 2/2 #595/#610, 0 gapped through, 0 worse exit — extra §7 REVERT trigger stays fired; gap guard owner-undefined since 10-20, left blocked for now, not re-asked), `pressure_report.py` (SCREEN MET on all five checks at n=160: SL/day 5.7 ≤ 6.5, SL share 46.2% ≤ 47.0%, scratch 25.6% ≤ 35%, R/trade −0.065 ≥ −0.10R, decisive WR 37.3% ≥ 36%; PASS not met — n<150 arm lapsed with the 10-19 time gate, grown n=160 is observation only), `xm_quote_report.py` (7.8 days, 7/14 complete UTC days + 1/2 weekends, median spread $0.55 vs $0.40 assumption — $0.40 stands). Era timeline table + HANDOFF §1/§6 updated with the 11:59 UTC snapshot (engine ledger $138.86, true equity $121.91, net −$640.89, open paper trade BUY #659 @ $4132.76). No engine/filter/param change, no guard, no revert, no deploy. Next eligible action per the plan remains blocked on the owner's dated pre-registration of the gap guard; nothing was invented or shipped in its place.
- **[2026-10-20 (later) → dashboard 📦 Boxes & Timing tab (DISPLAY-ONLY; NO runtime change)]** Owner ask: *"Maybe we create on a another tab in dashboard and proably give me some info and whwn to trade ?"*. Added a third dashboard tab (`?tab=boxes`, remembered in `localStorage`) rendering the 2026-10-20 box read: **(1)** a verdict banner (mid-box / waiting-for-trigger / blocked-by-session-or-risk-or-volatility-or-feed / weak-geometry / candidate-with-context); **(2)** the boxes table — the engine's own 20-bar level, the last 1h (60 bars), the last 4h (240 bars) and the prior **trading** day (a Sunday evening is not a day to draw a box on; 600+ bars required) — with in-box position and $ distance to both edges; **(3)** the **seven-condition checklist** (Location ≤0.5 ATR from an edge or a live trigger · Trigger = a *fresh* close beyond an edge or a rejection of it, `BOX_FRESH_BARS=3` so a break price left days ago is not a setup · Feed age, where a closed market makes staleness expected rather than a fault · Session = weekend/daily break/engine blackouts · Risk state = SL cooldown + daily breaker · Volatility = the engine's own $1.10–$4.50 ATR band · Geometry = the $0.55 spread as a share of R, the check that kills most box setups); **(4)** a setup card (entry, stop past the far edge, measured-move target, risk, reward, R:R, spread share of R, plus the engine's structural stop on the same edge); **(5)** the measured footer (8 geometries, 0 cleared; 74–75% of breaks fail within 15 min). **One bug found and fixed while wiring it:** a rejection at a box *high* was quoting the box *low* as its edge (the side is the trade direction, not the edge) — the trigger now carries the tested edge explicitly, and Scenario U pins it. **One shared source of truth:** `pressure.box_geometry()` / `pressure.box_status()` (stdlib-only, read-only, no engine import) now back both the tab and `tools/box_report.py` (`live_boxes` calls the same geometry — the CLI numbers are unchanged to the cent), so the two cannot drift. `tail_rows()` gained a `window_bytes` argument so the panel can reach a prior trading day without reading the whole multi-MB log; geometry is cached against the log's size+mtime and the live checks recompute per request. **`engine.py`, `trade_filter.py`, every gate/param/exit and the deploy path untouched** — autosync classifies a dashboard-only change as `DASH_CHANGED` (dashboard restart only, never the engine). Tests: `tools/test_dashboard_context.py` gains 10 box tests (box excludes the judged bar, rejection quotes the high and is a SELL, a stale break is not a trigger, a fresh break is, geometry cannot be a candidate when it fails, a closed market blocks, the measured verdict travels, short/gappy tapes refuse, the tab renders); smoke Scenario U gains **U11** (6 checks). Suite: box tests 14/14, dashboard-context 13/13 (venv flask), `check_data.py` 0 fail, smoke PASSED, `handoff_check.py` FRESH.
- **[2026-10-20 → box theory for manual trading: measured, answered, tooled (READ-ONLY; NO runtime change)]** Owner ask: *"Need your advise if i can incorporate box theory in my manual trade for gold"*. Built **`tools/box_report.py`** (new, read-only, stdlib + `pressure`) + **`tools/test_box_report.py`** (14 hermetic tests) and wrote **`docs/ANALYSIS-2026-10-20-box-theory-manual-trading.md`**. Method: box = high/low of the **N bars strictly before** the judged bar (same convention as the engine's floor); every **close** outside it is a break; **sequential one-position sampling** (overlapping 1-min events are not independent and made a Wilson CI absurdly tight — the first draft produced "EDGE" cells with negative expectancy and was discarded); forward walk censored at any gap >3 min or the end of tape; a bar spanning target and stop counts as a **stop**; reference = `risk/(risk+target)`, the share a no-edge coin produces; EDGE requires the Wilson lower bound above that reference **and** positive expectancy after the $0.55 measured round trip. Four geometries (structural stop on the broken edge; stop past the far edge at 1.5R; stop past the far edge with a 1-box target; fade the edge). **Result on 44,982 bars (09-01 → 10-19 20:58 UTC): not one of 8 cells clears its reference.** 20-bar box (median $6.41 = 4.1 ATR, 648 breaks, 74% false): 42.1%/35.4%/56.8%/10.1% vs refs 40.0/40.0/55.1/10.3 → E −$0.49/−$1.70/−$0.34/−$0.63. 60-bar box (median $11.56 = 7.7 ATR, 315 breaks, 75% false): 37.8%/26.4%/55.3%/10.4% vs refs 40.0/40.0/53.0/5.8 → E −$1.03/−$5.02/+$0.14/−$0.09; G2 is **BELOW ref** in London and NY. Verdict: **boxes are a place to put a stop, not a place to read a prediction**; the only near-break-even geometry is the stop outside the **whole** box (cost 2.2% of risk vs 16% when the stop hugs the broken edge — the same inert-level finding as 2026-10-05). Live read (20:58 UTC, close $4140.20, ATR $0.59): 20-bar level 4140.57/4137.51 with a BUY's cost at **46.6% of risk**, 1h 4142.48/4137.51, 4h 4149.25/4136.57, prior trading day 10-16 4198.85/4147.17. Manual rules documented (§4): H1/H4 boxes only, box = where not when, stop outside the far edge, target the measured move, no BE before 0.75R, charge the real spread, skip the 20:58–22:00 break, no re-entry within 10–15 min, log every trade; bar = n≥100 and positive after spread. **`engine.py`, `trade_filter.py`, every gate/param/exit and the deploy path untouched**; struct-stop window and its 10-19 judgement untouched. Suite: box tests 14/14, `check_data.py` 0 fail, `smoke_test.py` PASSED, `handoff_check.py` FRESH, `py_compile` clean.
- **[2026-10-19 21:19 → structural-stop time-gate judgement (docs-only; runtime unchanged)]** Evaluated the latest available synced snapshot (log through 18:10 UTC): 636 closes, struct-stop n=139. `check_data.py` 0 fail/8 warn; structural geometry PASS; replay calibration 99.8%/99.7%; registered B/C screen MET, but PASS not met (n<150, Wilson LB 28.8% ≤32.1%). The explicit scheduled-closure counting rule yields **2/2** rides, firing the extra §7 REVERT trigger despite no realized gap damage. The registered sequence requires a gap guard first, but its cutoff and open-position policy are not defined/approved; no strategy change, revert, 0.25 ATR test or deployment was made. Quote sample remains 5/14 days, 1/2 weekends, $0.55 first-look median; keep $0.40. Review: `docs/REVIEW-2026-10-19-struct-stop-judgement.md`; plan and HANDOFF updated. `engine.py`, `trade_filter.py` and data files untouched.
- **[2026-10-17 → repeatable session execution plan (docs only; no strategy/runtime change)]** Owner observation: pressure-guided manual management has sometimes stayed in positions the bot would stop out of, and they may later recover; these cases are not yet matched to bot entries or systematically logged. Added `docs/EXECUTION-PLAN.md` with the next-session prompt **“Execute the plan.”**, a gated timeline, and a prospective/private observation protocol so recoveries are recorded without survivorship bias. README and HANDOFF now point to the plan. Current data is still paper-only: at n=127 the structural-stop screen is **not met** because SL share is 47.24% vs ≤47.0%; geometry remains valid (0 post-cutover stops inside the level). Quote logger is collecting but has only 3.7 days/0 complete weekends. Data integrity: 0 fail/8 warn; structural-stop guard PASS; handoff snapshot fresh; smoke PASSED. `engine.py` and `trade_filter.py` unchanged.
- **[2026-10-16 → dashboard market-context layer: buy/sell pressure, gate read, §7 era card, calibration (DISPLAY-ONLY; NO runtime change)]** Owner ask: *"i need to add an indicator in dashboard buy/sell pressure so i can make an informed decision on daily trade… if there's other information that will be helpful please add this in"*. Shipped **`pressure.py`** (new read-only, stdlib-only module), **`tools/pressure_report.py`** (new CLI: `--root`/`--era`/`--json`), **`dashboard.py`** panels + a read-only context layer, **`tools/smoke_test.py` Scenario U** (45 checks), `docs/ANALYSIS-2026-10-16-dashboard-pressure.md`, README/§-docs. Panels: 🌡️ tape pressure (60-bar composite: volume flow .30 / 60-bar momentum .20 / EMA50−EMA200 .20 / EMA50 slope .15 / RSI .15), 🎯 setup read (the engine's **own logged flags** where they exist, recomputed with the engine's rules for the SELL side/slope/proximity gates — PASS/FAIL per gate + the first miss), 📍 location in the 20-bar range + 🧮 hypothetical structural stop/TP, 🧪 live struct-stop era card against the §7 bar, 📅 today + last-20 exits with the base rate, 📡 feed health (gaps in **open-market minutes**, weekends/daily break excluded — the live log reproduces the 09-29 stall as 284 open min). **Honesty:** the composite was calibrated before being trusted — joined to every entry (last bar **strictly before** the entry minute, §8), one pre-specified split per side, struct-stop era n=120 and max-hold era n=347 both return **"collinear with side — not separable within-side"** (no `against` bucket on either side, ever; buy-pressure spans BUY 49–81, SELL 14–42), so the dial is context and the panel prints that verdict from a live re-join (10-min cache). Scenario U pins **every mirrored threshold** to `engine.py`/`trade_filter.py` and the §7 thresholds to the 10-05 doc (the dashboard may not import the engine — it also may not drift from it), pins `STRUCT_STOP_CUTOVER == strategy_lab.LIVE_CUTOVER`, proves read-only + stdlib-only by AST, and asserts the previous-20-bars level rule, reward-leg risk, weekend-vs-outage gaps, cooldown escalation, direction-aware blackout and the §7 SCREEN/PASS/REVERT logic. Panel R/trade reproduces `win_rate_report.py --spread`'s cost view to the digit (era −0.053R = $/trade ÷ mean 1R $5.74). **`engine.py`, `trade_filter.py`, every gate/param/exit and the deploy path: untouched** — autosync treats this as `DASH_CHANGED` (dashboard restart only). Struct-stop window un-stacked; era at n=120 **SCREEN MET — 30 short of PASS**, B2 with 0.3 pp of headroom, 10-19 21:00 review unchanged. Suite green: smoke PASSED A–U, `check_data.py` 0 fail / 8 warn, py_compile clean, `check_structural_stop.py` PASS (0 inside), `strategy_lab --calib-only` recall 100.0/100.0, `handoff_check.py` FRESH (0 drift).
- **[2026-10-15 → HANDOFF.md restored after a machine truncation, then consolidated (§1 history split out; the gate now checks structure)]** The daily doc job rewrote `docs/HANDOFF.md` twice in one minute: `43884e1` (14:06 UTC) replaced all 886 lines with the single line `PLACEHOLDER - will replace`, and `072459d` (14:07 UTC) put back the front matter + §1 only — **§2–§11 gone** (the gates, the evidence base, next steps, the verification ritual, the data gotchas, the architecture map, the deploy runbook and the §11 protocol itself), plus the §1 history blocks, `Definitions` and the §1a feed-outage record. **`tools/handoff_check.py` reported FRESH throughout**, because it reads only the snapshot block: a perfect block on a corpse reads as healthy. Owner ask: *"I believe we have to consolidate docs/HANDOFF.md maybe it's getting huge ... please analyze if we need to make improvements."* **Restored** from `712d106` (the 10-13 version) with the 10-15 data-refresh block kept at the top; **consolidated**: the dated §1 blocks (10-13 tooling, 10-05 state, the 09-29 outage, the superseded stances) moved to **`docs/HANDOFF-HISTORY.md`** (new, append-only, newest first) — 223 of the 886 lines were §1 and 92% of that was history no session had pruned, so the truncation was a *size* symptom, not just bad luck. HANDOFF is now **738 lines**, all 11 sections intact. **Hardened:** `handoff_check.py` gained `doc_structure()` — §1–§11 must exist with their headings intact (a rename is flagged, since a rename is how the restore smuggled the sections out), no bare placeholder markers (scanned outside code spans, case-sensitively — the first draft's case-insensitive scan tripped on the docs' own lowercase prose), and every `§N` reference must resolve to a section; `--update` **refuses to stamp a structurally broken doc**, so a truncation cannot be quietly re-verified. Smoke **Scenario P** grew 23 → 28 checks: the truncation fixture keeps a *perfect* snapshot block so only structure can fail it (proving the old gate called the 10-15 file fresh), `--update` refusal, the rename case, and "the real repo's HANDOFF.md is structurally whole". New **HANDOFF §11 rule 5**: §1 is current-state only. Suite green: smoke **A–T PASSED (320 checks, ~12 s)**, `check_data.py` 0 fail / 8 warn, `handoff_check.py` FRESH, `check_structural_stop.py` PASS. **No runtime change** — the struct-stop window is untouched (era n=109, judged at the 10-19 21:00 review).
- **[2026-10-13 → BTC-port assessment + struct-stop guard repair (tools/docs only; NO runtime change)]** Owner ask: *"given what we did for our bitcoin trading bot updates in docs/HANDOFF.MD, do you think we can have some improvements on my gold trading bot as well … dont create a PR until we can finalise everything."* Compared gold with `bitcoin-trading-bot` (HANDOFF + PRs #1–#20) → **`docs/ANALYSIS-2026-10-13-btc-port-assessment.md`** (12-item verdict table: done / needs owner / after the window / not for gold). **Found and fixed:** (1) the struct-stop cutover was **2026-10-06 03:00:04 UTC** (autosync deploy of PR #28, merged 00:31:53), not the planned 10-05 21:00 — `check_structural_stop.py` was **FAILing** on #495–#498 (old rule; #495/#497/#498 carry exactly 2.00 ATR of risk with the level 2.3–2.9 ATR away). `strategy_lab.LIVE_CUTOVER` corrected, era n 82 → **78**; the tool now **proves the boundary from the ledger** (OLD/NEW/BOTH rule classification, last-OLD → first-NEW bracket #498 02:39:09 → #499 03:33:05, BOUNDARY-ERROR vs REGRESSION diagnosis); erratum at the top of ANALYSIS-2026-10-05, §7 thresholds untouched; moving the four trades out **flatters the era by $9.90** (−$10.60 → −$0.70 gross) — disclosed. (2) `strategy_lab.Lab` took the 20-bar level over **19** prior bars; the engine uses 20 (matches its logged `Dynamic_Floor` 99.96% vs 85.97%) → fixed; funnel recall 99.8/99.7 → **100/100**; stop-inside-level 63.8% → 66.4%; master-era replay structstop −0.101R → −0.076R at $0.20/side; "better in 3 of 4 eras" unchanged. **Added:** `tools/handoff_check.py` (machine-checked HANDOFF snapshot, tolerance 30 trades / 48 h re-calibrated from BTC's 5; autosync digest line `📝 handoff:`, advisory), `docs/AUTOSYNC.md` (the script header had pointed at a missing file; records "deploy time = cutover"), smoke **Scenarios O** (guard + harness fidelity vs the engine's own logged floor; end-to-end clean/boundary/regression/early cases) and **P** (handoff policy, 23 checks), both hermetic and mutation-checked; HANDOFF §1/§4/§6/§7/§9/§10/§11 + era table refreshed (§1 had been **8 days / 82 trades stale**; last daily-job refresh was PR #22 on 09-25). **Also found, NOT changed (gate/exit behaviour inside the open window):** the daily-loss breaker counts SLs among the last 30 ledger rows (34 entries under-counted, never silently off; BTC fixed it with `DAY_WINDOW=400`); `mt5_history_dump.py` labels broker-server time as UTC (+3 h today, flips at DST) and a naive port of BTC's UTC `ts` fix would make the engine's dedup drop ~3 h of candles. **Waiting on the owner:** `NOTIFY=alerts`, `win_rate_report --spread`, the GOLD XM quote/spec logger, one history dump for the large-N path. Ledger at data collection 226: **575 closed / 1 active**, 110W/248L/215BE/2TIME = 30.7% dec [26.2–35.7], −$319.51 → $180.49 gross (−$549.51 at the assumed $0.20/side), engine $197.46, drift +$16.97; integrity 0 fail / 8 warn; smoke A–P passed. Struct-stop era first look (n=78, **descriptive only, below the n=100 screen**): 25W/37L/15BE/1TIME, 40.3% dec [29.0–52.7], gross −$0.70 (+0.007R/trade), SL 5.1/calendar day, scratch 19.2%, avg SL 1.42× pre-change, drawdown $13.77, 0 closure-gap rides. Branch `arena/3f12a4a6-gold-trading-bot`; **no PR** (owner asked to finalise first).
- **[2026-10-13 (later, same session) → the three BTC ports the owner approved: cost view, GOLD quote/spec logger, large-N history path (tools/docs/ops only; NO runtime change)]** Owner decisions via ask: leave `NOTIFY` alone; build the logger; build the large-N path; add `--spread`. **Built (all on the branch, no PR yet):** (1) `win_rate_report.py --spread X` — net view + cost view; default output byte-identical; ties to the snapshot (−$549.51 at $0.40 a round trip). (2) **The GOLD quote + contract-spec logger** — `tools/mt5_quotes.py`, `deploy/mt5quotes.service` (installs as `mt5quotes-gold`), `tools/xm_quote_report.py`, `tools/broker_time.py` (the EU/US DST rule, verified only by observed offsets), `docs/XM-LOGGER.md`. Read-only (AST-checked: no trading API name), privacy allow-lists (public repo: never `account_info()`/`terminal_info()`), `order_calc_profit` probe (0.01 lot × $1 must be $1.00), spec-change history. Ported for a market that **closes**: a frozen tick is a `STALE` row (not an outage, never trips its own watchdog, never moves the learned server offset — the trap is that a tick exactly N hours old looks like a fresh tick on a server N hours behind, which every weekend would trigger), a DST change needs 2 consecutive agreeing fresh ticks (also while gold is shut), the report separates scheduled closures / feed stalls / logger outages. Autosync: `xm_data` in `DATA_FILES`, `xm_data/*` conflicts server-wins, phase 4d (digest `📡` line; a ⚠️ only when the newest row is > 15 min old; a crashed report is reported, not pasted). (3) **The large-N path** — `tools/history_to_log.py`, `strategy_lab.py --bars` / `--ratchet`, `docs/ACCELERATE-TESTING.md`, `mt5_history_dump.py` docs, `.gitignore`. The dump writes broker-server time labelled UTC, stamped at bar OPEN, with the forming bar last; the converter **proves the clock** with an exact four-column OHLC match against the log's MT5 era (the log is the same terminal's closed M1 bars from 2026-09-10; before that it is Twelve Data's), per UTC day, so the 2026-10-25 DST change will be **observed**; it refuses rather than guesses; the lab mode is read-only, ledger-free, splits out-of-sample (< 09-04) from in-sample and prints monthly windows + cost sensitivity. **Verification:** smoke **A–T, 315 checks, ~10 s, hermetic** (Q logger, R report + broker_time, S converter, T lab history mode); 62 mutations of the new code all killed; every existing `strategy_lab` mode byte-identical; the real MT5-era log round-trips through the converter (29,912 bars, 100.0% exact vs 0.0% at wrong offsets); autosync exercised in a sandbox incl. the **old script merging its own new version mid-run (safe)**. **Found on the way:** `forward_test_log.csv` before 2026-09-10 is Twelve Data's bars (half the stamps at `:00`, weekend rows) — the MT5-era proof window starts 09-11; the dump's last row is the still-forming bar; a single global-best-offset gate would have refused a legitimate DST change inside the overlap (the proof is per day). **Not verified:** neither the logger nor the dump has run against a real terminal (none in the sandbox) — the first run on the box is the real validation. **Waiting on the box:** install `mt5quotes-gold` before Sunday 2026-10-25; one history dump → convert → replay. Branch `arena/3f12a4a6-gold-trading-bot`; **no PR** (owner asked to finalise first).
- **[2026-10-05 (2nd session) — STOP-LOSS GEOMETRY: root cause found, `SL_CLEAR_ATR` shipped, step-2 and the session band closed]** Owner ask: *"rethink new strategy as there's a lot of stop loss"*. Built the missing prerequisite first — **`tools/strategy_lab.py`**, a **costed, stateful, era-matched full-strategy replay** (regenerates the funnel from the 1-min log with engine-faithful SMA-seeded EMA50/200, simple-mean RSI/ATR-14, 20-bar floor/ceiling excluding the current bar, decision-time indicator convention; then the whole cascade: direction-aware blackouts, daily breaker by `Exit_Time`, production SL-cooldown semantics, one-position occupancy with same-bar re-entry, cost on every exit incl. BE, era-correct ratchet trigger, engine intra-bar ordering arm→stop→target→TIME). Funnel **recall 100.0/99.7/99.6%** on the 0.30R / 0.75R-master / max-hold eras (68.9% pre-09-10 as expected, the gate stack itself changed mid-era); taken-set overlap 77% after fixing **two harness bugs** (a BE/TIME scratch must switch the cooldown block *off*; the breaker counts SLs by exit time) — that overlap limit is cascade timing, not a gate difference. Ledger at judgement: **493 closed / 0 active**, 84W/208L/200BE/1TIME, **28.8% dec** [23.9–34.2], **−$308.91 → $208.05**, −0.163R/trade; master n=318 −$0.581/t; max-hold n=223 −$0.646/t (−$11.08/day, 17.2/day). **Root cause (mechanical, not statistical):** `FLOOR_BUFFER_PCT = 0.0020` is a **price-%** tolerance — $8.30 on a $4,150 metal = **4.5× the median ATR (1.83)** — while every other threshold in the funnel is ATR-scaled, so "price tested the 20-bar floor" is TRUE on **86.9%** of logged bars (89.1% recomputed; `status.json` agrees: 936/1031 candidate bars) and 44.5% of passers close >2 ATR from the level. Consequence: median |entry − level| **2.42 ATR** → a 2·ATR stop sits **inside** the range (median 0.42 ATR short) on **203/318 = 63.8%** of master trades and **95/149 = 63.8% of its SL exits** — no structural break needed; median SL lifetime **7.2 min** (46% ≤7, 97.6% ≤30 of a 240-min budget), only 22.3% touched +1·ATR first. (The 68.6%/69.1% figures used in chat/earlier drafts double-counted BE-ratcheted rows' overwritten stop; `tools/check_structural_stop.py` recovers risk from the reward leg and is now the authority.) **SHIPPED (one variable, `engine.py`):** `SL_CLEAR_ATR = 0.5` + `RR_TARGET = ATR_TP_MULT/ATR_SL_MULT` → `risk = max(2·ATR, |entry−level| + 0.5·ATR)`, `TP = 1.5 × actual risk`; 0% stops inside the level by construction (replay 0/217 vs 210/326 before), **80.2%** of trades level-bound, median risk 2.00 → 3.07 ATR ($3.75 → $6.27), zero change when the level does not bind or `level is None`. Live+paper paths both wired (`execute_live_trade` measures from the order price); `status.json` restart keeps the wider stop. **Evidence (costed, era-matched, `--table`):** master era n 326 → 217, decisive 32.1 → **37.4%**, −0.217 → **−0.106R**/trade, −$13.90 → **−$5.83**/calendar day, SL/day 8.2 → 5.4, scratches 33 → 25%, replay maxDD $255 → **$175**, hold 10 → 22 min, TIME 1 → 7; improvement is cost-insensitive (+0.083R gross → +0.148R at $0.35/side) and **better in 3 of 4 eras** (worse pre-ratchet: −0.084 → −0.192R, because with no ratchet a wider stop is only bigger losses); 4/5 chronological chunks better (+0.058/+0.044/+0.260/+0.276/**−0.031**); leave-one-day-out R/trade ∈ [−0.173,−0.100] (baseline ∈ [−0.289,−0.19]); both sides improve (BUY −0.290 → −0.194, SELL −0.198 → −0.052); not an ATR-mix artifact (+0.198 / +0.165 / **+0.008** by ATR bucket — it is a quiet-tape fix). **Honest limits: expectancy stays negative at every cost tested** (costed breakeven decisive WR ≈42.2% vs 37.4%), the **SL dollar bill does not fall** (−$621.61 → −$659.43; −$4.20 → −$6.80 per stop, max single loss −$8.82 → −$12.22), volume −33% via occupancy/cooldown with no entry change, and longer holds raise closure-gap exposure while the SL-count-based daily breaker bites less. **Rejected with numbers (do not re-derive):** level-test re-scale (0.15/0.25/0.5/1.0 ATR or force a pierce — best pooled cell in the repo, +0.091R for `sweep`, but era-unstable: tol0.15 = 0 winners of 21 decisive in the 0.30R slice and −0.273 vs −0.154R in 0.75R-pre-maxhold; near-miss bucket is the *worst* class at 14.3% dec / −0.409R; `validate_gates.py` PROX0.5/1.0 = 28%/33% dec), stop-only widening that degrades the ratio (49.1% WR but −0.107R), min-SL 2.5/3.0/3.5 with RR held (WR up to 50.7%, −0.107/−0.134R — the §5.6 trap), min-SL 1.5/1.0 (−0.257/−0.425R), tightening anything, and stacking the tolerance on the stop fix (≡ stop fix). **Step-2 (ratchet-off) CLOSED without an isolation slot:** ≈breakeven gross (−0.052R), buys its R gain by deleting the scratch bucket (**61.7%** of trades end as full stop-outs vs 45.4%), and is **redundant** on top of the shipped stop (−0.131R vs −0.124R). **Session-band candidate DOWNGRADED:** measured costed+cascade-aware for the first time, the Asia-vs-London/NY gap collapses from **0.268R to 0.085R** under the structural stop → it was a proxy for stop geometry and fails REVIEW-2026-10-05 §5a's own independence clause (b). **Pre-registered bar written before any post-cutover trade exists** (`docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` §7): era = entries ≥ 2026-10-05 21:00 UTC; **invariant checks first** (stop-inside-level must be 0, clearance ≥ 0, recall still ~100%, level-bound share 70–90%); then **n≥100** (n<60 is not a result) = **SCREEN** R/trade ≥ −0.10R + decisive WR ≥ 36% + SL/day ≤ 6.5 + scratch ≤ 35%, and **PASS needs n≥150 with the WR's Wilson 95% LB > 32.1%** (≈40% WR = the uncosted 1:1.5 breakeven); REVERT = R/trade ≤ −0.20R, or avg SL > 2.2× pre-change, or era drawdown > $250, or 2+ trades riding a closure gap; re-review 2026-10-19 or n=150. **Docs/tooling hygiene:** `tools/win_rate_report.py` now recovers risk from the **TP leg** (`|TP−Entry|/1.5`) — exact in both regimes, `2·ATR` would understate level-bound risk — Definitions updated (R/trade = actual risk; new **level-bound** / **clearance** / **struct-stop era** terms), README tool list + cascade-ignorant warning, `tools/smoke_test.py` **Scenario N** (16 checks: geometry, retest survival, ratchet arms at 0.75R of the *new* risk, restart keeps the wide stop, `level=None`/hugging entries byte-identical) and Scenario **L pinned** (it read the real wall clock and went red at 00:09 UTC on a *clean* checkout — pre-existing, not caused by this change). Suite green: smoke **A–N PASSED**, `check_data.py` 0 fail / 8 warn, `--calib-only` recall unchanged, `check_structural_stop.py` PASS (pre-cutover it correctly reports 63.8% inside). `TRADING_MODE` stays `FORWARD_TEST`, lot 0.01, max-hold 240, no new gate. HANDOFF §0/§1/§2/§4/§5z/§6/§7/§8/§9/§11 + era table + Definitions refreshed.
- **[2026-10-05 → scheduled max-hold re-review: isolation closed, `H-side-awareness` DROPPED, step-2 trigger MET (docs + two tool-label fixes; no runtime change)]** `docs/REVIEW-2026-10-05.md` on the data collection 172 snapshot (commit `304551b`, last candle 2026-10-05 02:59:08 UTC, **479 closed / 0 active**, 83W/200L/195BE/**1TIME** = 29.3% dec [24.3–34.9], true P&L −$284.01 → **$215.99**, engine $232.96, drift +$16.97; integrity 0 fail / 8 warn, smoke A–M passed). **Max-hold isolation closed** (deploy + 14 d, **n=209**, 45W/100L/63BE/1TIME, 31.0% dec, **−$0.570/trade, −$8.64/calendar day**, 16.1 entries/day): the 240-min cap **never bound an in-session trade** (longest non-TIME hold 68.0 min) — the one TIME exit is **#476**, a SELL held **49.1 h wall-clock across the 10-02→10-04 weekly close** (−$1.52), because the cap cannot fire while the market is closed and the stop is unenforceable across a gap in LIVE; keep the cap (cheap insurance, not the SL-cluster cause), new named candidate = pre-close/flat-before-close guard. **Fallback step-2 trigger MET** (post-deploy P&L/trade ≤ −$0.40 at n ≥ 200) → ratchet-off **eligible but NOT approved**: blocked on the ANALYSIS-2026-10-01 §4 costed/stateful harness + an explicit pre-registration/sign-off; never back to 0.30R. Master 0.75R book **n=304** (65W/141L/97BE/1TIME, 31.6% dec [25.6–38.2], −$0.526/trade = −0.145R, bar still tripped); 0.30R era n=130 unchanged (−$0.321/t), 0.75R pre-maxhold n=95 (−$0.427/t), pre-ratchet n=45 (−$1.834/t). **`H-side-awareness` formally scored against its own 5-part bar → DROPPED**: (a) 27 decisive counter-trend ✔ (17 BUY-falling + 10 SELL-rising; 36 at 240 min); **(b) FAIL** — 60-min aligned BUY +8.1 pp but **aligned SELL −6.4 pp**, and at 240 min the failing side flips (BUY −3.4 pp, SELL +13.6 pp); **(c) FAIL** — no rising-gold sub-period supplies the comparison (09-17/09-18 up-leg aligned BUY 45.0% with zero decisive counter-trend BUYs; 09-29 inverts BUY −25 pp; 10-01 inverts SELL −10 pp); (d) ✔, (e) this doc. No BUY ban / SELL-only / momentum gate. **Candidate refresh era-correct + risk-normalized (R = Profit ÷ 2·ATR):** RSI≥45 **still dropped** (keep −0.151R vs skip −0.135R; max-hold −0.175R vs −0.135R); **MAX_ATR 4.50→2.50 NORMALIZED-REJECTED** (ATR<2.5 −0.146R vs ATR≥2.5 −0.143R — the dollar gap was position risk; ATR≥2.0 even beats ATR<2.0, −0.063R vs −0.197R); ATR<2.0 rejected; post-BE <5-min same-side re-entry **strongest queued** (master −0.325R vs −0.104R, n=57; max-hold −0.389R vs −0.111R, n=36) but still observational (needs cascade replay + pre-registered bar); BUY-side bleed observation only (max-hold BUY 24.6% dec, −$1.306/t vs SELL 35.7%, +$0.008, Fisher p=0.2031 — weaker than 10-01's 0.1137). **NEW named candidate (NOT adopted): London/NY session-band bleed** — master book entries 23:00–06:59 UTC 39.8% dec / +$0.258/t / −0.004R (n=125) vs 07:00–22:59 25.4% / −$1.073 / −0.244R (n=179), pooled Fisher **p=0.034** (max-hold p=0.045, 40.7% vs 24.4%); holds within both sides and every ATR bucket, not a side/tape mix, consistent 4/4 eras and 5/5 chunks, worst hours 15:00–17:59 — but post-hoc hour scan, uncorrected p, per-side p≈0.10–0.26, no cost/cascade model; proposed 6-part bar in REVIEW-10-05 §5a (4/6 standing), **proposed not registered**; one isolation slot — sequence against ratchet-off. **Tooling fixes (labels only, no math):** `tools/check_data.py` long-hold warning no longer claims "survivors are pre-deploy rows" (false since #476) and prints the Exit_Reason + the cannot-fire-while-closed caveat; `tools/win_rate_report.py` no longer labels +0.30R "LIVE SINCE 09-10" (historical, live = +0.75R since 09-15), explains that ACTUAL mixes both ratchet levels, and §2/§6 print explicit **0.75R-master** and **max-hold-era** lines. Remaining 10-01 §4 items (cost model on all exits, SL-streak/wall-clock cascade, direction-aware NOH8, MFE/MAE alignment, pathwalk/phantom labels) stay open as prerequisites. Ops: feed advances to 10-05 02:59 with only the normal daily-break/8-min/weekly-close gaps (no new outage signature); host hardening still unverified. HANDOFF §1/§4/§5/§6/§8/§11 + definitions + start-here + timeline refreshed. Suite green: smoke PASSED A–M, `check_data.py` 0 fail / 8 warn, py_compile clean, `win_rate_report.py` / `momentum_regime.py` / `analyze_losers.py` / `phantom_trades.py` / `validate_gates.py` end-to-end. No engine/strategy/param/data/deploy change.
- **[2026-10-01 analysis only]** High stop-loss verification (`docs/ANALYSIS-2026-10-01-stop-loss-rate.md`): 448 closed, 77W/184L/187BE, SL/all 41.1% vs SL/decisive 70.5%; paper P&L −$251.69, 0.75R master n=273 / −$0.467 per trade, max-hold n=178 / −$0.488 / 0 TIME. Current-rule geometry/labels and matched baseline verified; integrity 0 fail / 8 warn, smoke A–M passed. No bot/parameter/data/deploy change. Next session: host/feed verification, correct era/cooldown/alignment/cost analysis tooling, formal ~10-05/n≈200 review; ratchet-off only as a costed isolated candidate (current observed-entry gross replay +$1.45/191), post-BE pause separate; no RSI/ATR/side-ban adoption. Handoff refreshed; 09-29 freeze is historical, CSVs now advance through 10-01.
- **[2026-09-29 → feed outage: 6 h silent starvation + detection fix (engine/tooling; no strategy change)]** The user reported the dashboard showing **STALE**; the repo confirmed it (`status.json`/`forward_test_log.csv` frozen at **08:29:19 UTC**, last commit `data collection 141` 08:34:01, ~6 h of nothing while 09:00/12:00/15:00 autosync digests said `no new data` and looked green). Root cause from the server evidence: **the host rebooted at 08:29:15** (journal `-- Boot c22469d0… --`), all units restarted 08:29:18, but **`mt5.service` never came back — stuck in `deactivating (stop-sigterm)`** for 6 h, so the terminal published no bars and `mt5_last_candle.json` froze at `ts=1790681280` (11:28 server = 08:28 UTC; mtime 08:29). The engine stayed `active (running)` and looped on the *deduped* frozen candle: that `continue` jumped **over** the stale-feed guard, and `feed_stale_seconds()` reads `_last_price_mono` — never set after a restart — so it returned `0.0` ("fresh") the whole time → **no journal line, no Telegram alert** (the STALE badge was the only detector that worked). Also found an **undocumented precursor**: a 9.7-h stall 09-28 17:50:05 → 09-29 03:33:37 (~283 open-market minutes), same signature — twice in 24 h. **Impact:** ~6 h of London/NY missing (no backfill; the engine logs one row per closed minute) + ~283 open minutes on 09-28; **no position open across either gap** (#397 exit 09-28 17:40:02, #403 exit 09-29 07:51:03, `trade_active: false`) → no phantom P&L; ledger frozen at **402 closed, 64W/166L/172BE/0TIME, 27.8% dec [22.4–33.9], true P&L −$254.99 → $245.01, engine $261.98** (0.75R era n=227 30.1% −$0.576/t; max-hold era n=132 28.3% −$0.683/t, still 0 TIME fires). **Fixes (detection only, `docs/REVIEW-2026-09-29-feed-outage.md`):** `feed_publisher_age_seconds()` (sidecar heartbeat — the file is rewritten every 5 s even on a closed market, so a stale mtime means the *publisher* died), `mt5_feed_problem()` (missing/corrupt file, stale heartbeat, market-hours candle stall; `is_market_quiet()` keeps weekends silent), `report_mt5_feed_problem()`/`_recovered()` (5-min journal print, 30-min Telegram cooldown with MT5 wording, one recovery line), all evaluated **before** the dedup `continue`; `smoke_test.py` **Scenario L** (missing/frozen/corrupt/quiet-market/alert-limit/recovery); `tools/autosync.sh` phase 4b digest backstop (`📈 candles: ok|STALE N open min`, open-market minutes computed with the weekend/daily break excluded — dry-run flags today at the 12:00 run, silent on Sat/Sun). **No strategy/param change; max-hold isolation window undisturbed.** Suite green: smoke PASSED A–L, `check_data.py` 0 fail / 8 warn, py_compile clean, `win_rate_report.py` end-to-end, `bash -n tools/autosync.sh` clean. Ops follow-ups (server): harden `mt5.service` (`Restart=always`, `TimeoutStopSec=30`, `KillMode=control-group`, `enable`), use the recovery runbook (stop/kill the stuck terminal → start it → `systemctl restart mt5feed` → verify `updated_at` advancing).
- **[2026-09-28 → "WR improves when gold falls?" analysis: real pattern, wrong cause (docs + tool only)]** User observed the win ratio improving while gold falls. New read-only tool **`tools/momentum_regime.py`** (8 sections: day-level, pre-entry momentum 30/60/120/240 min measured at entry−1 min for the feed lag, side decomposition per era, within-side refutation, 240-min trend alignment, up-day counter-cases, 5-day chunk stability, pre-registered bar printout) + **`docs/ANALYSIS-2026-09-28-falling-gold-win-rate.md`** on 380 closed trades (61W/157L/162BE/0TIME, 28.0% dec [22.4–34.3], −$238.19 true → $261.81; engine $278.78, drift +$16.97 unchanged). **Findings:** the pooled falling-tape gap is real but insignificant (60-min 30.7% vs 25.0%, p=0.37; 240-min 33.6% vs 22.5%, p=0.072) and structurally confounded with side — 94% of falling-60m entries are SELLs and 96% of rising-60m are BUYs, so "falling tape" mostly means "the SELL side" (all data 34.0% vs 22.3%, p=0.070; max-hold era 36.5% vs 14.3%, p=0.041 → p=0.16 with 09-28 removed). Three refutations: (1) day-level null — down days 27.9% dec / −$0.59 per trade vs up days 28.1% / −$0.72; (2) within-side, falling tape is the WORST BUY bucket (13 trades, 2W/11L, 15.4% dec, −$2.12/trade) so "favour falling tape" is direction-blind nonsense; (3) unstable — the whole gap is 3 trading days old (09-24→09-28: 52.2% vs 7.7%; 09-14→09-18 dead heat 36.1% vs 36.8%) and **inverts in the book's only up-leg** (09-17/09-18: BUY 45.0% dec / +$10.01 vs SELL 12.5% / −$21.37). What survives: the 09-22→09-25 bleed was the **BUY side** (max-hold era BUY 4W/24L, 14.3% dec, −$84.07 vs SELL 19W/33L, 36.5%, +$10.69) — consistent across eras but never significant (pooled p=0.070, p→0.16 ex-09-28) and possibly just the −6.7% slide the book happens to live in. **Registered `H-side-awareness` + a 5-part pre-registered bar** (≥25 decisive counter-trend outcomes; ≥5 pp gap within BOTH sides separately; must also hold in a rising-gold sub-period; P&L/trade no worse than −$0.10; doc + isolation first) — current scoreboard fails (a)(b)(c), so **nothing adopted, no engine/param change, max-hold isolation window undisturbed**. HANDOFF §1/§2/§5/§6/§7/§8 + cheat sheet + start-here updated; README tools list + new-session note updated. Ledger refresh: 0.75R era n=205 → 30.5% dec [23.5–38.5], −$0.556/trade (was −$0.78 at 09-25; still below the −$0.40 bar); max-hold era n=110 → 28.8% dec [20.0–39.5], −$0.667/trade, still 0 TIME fires. Suite green: smoke PASSED, `check_data.py` 0 fail / 9 warn, py_compile clean.
- **[2026-09-21 → revert-or-maintain check: MAINTAIN (docs-only)]** User asked for a comparison of the whole trade book before vs after the recent parameter changes, and whether to revert or maintain (`docs/ANALYSIS-2026-09-21-revert-or-maintain.md`; 281 closed trades, data collection 92, ledger 40W/107L/134BE/0TIME = 27.2% dec [20.7–34.9], −$186.88 true, engine $337.82, drift +$24.70 unchanged). Partitioned into non-overlapping books: pre-ratchet n=45 (17.8% dec, **−$1.834/trade**), 0.30R era n=130 (31.2%, −$0.321), master 0.75R book **n=106 (31.4% dec [21.8–43.0], −$62.68 = −$0.591/trade — bar still tripped; worsened from −$0.471 by today's bleed)**, of which "0.75R-only" (closed at deploy) n=95, −$0.427 and **max-hold era n=11 (2W/7L/2BE, −$22.07)**. Verdicts: (1) new-regime stack 09-10 — MAINTAIN, bleed cut 5.7×; (2) ratchet 0.30→0.75 — MAINTAIN, live has no edge but 0.30R replay −$116.30 vs 0.75R +$28.74, and the correct forward step is pre-registered fallback step 2 (ratchet-off, replay 44.3% dec / +$119), never back to 0.30R; (3) max-hold 240 min — MAINTAIN, **exonerated by construction: 0 TIME fires and today's 11 holds ran 1.0–24.9 min**, nowhere near the cap. Today's red day explained without any param break: −51-pt gold trend day, 9 of 11 trades SELLs chopped inside the sell-off (documented stop-inside-chop pattern), daily breaker tripped (11 SLs ≥ 10 → trend-side-only), cooldown leak recurring (+$258.67 sequential phantom); P(≤2 wins in 9 decisive) ≈ 41% at the era base rate. **Why maintain is protocol-mandated:** the falsification bar's pre-registered fallback (max-hold in isolation) is judged at deploy + ~2 weeks / n ≈ 200 on P&L/day + bleed/trade — today is hour ~12 of that window. Watch item for the same re-review (not adopted — one change at a time): RSI≥45 ∧ ATR<2.5 combo (new-regime keep 37.0% dec / −$9.91 vs skip 25.0% / −$94.46). No engine/strategy/param change; max-hold isolation window undisturbed. Suite green: smoke PASSED A–K, `check_data.py` 0 fail / 8 warn, `win_rate_report.py` + `phantom_trades.py` re-ran end-to-end.
- **[2026-09-21 → §2b era table + no-reset decision (docs-only)]** The previous session's final commit (`295687e`, "the §2b era table and the no-reset decision") was **local-only** — its ephemeral workspace died before the push, so the commit object itself is unrecoverable; this is a faithful reconstruction from the docs' context, recomputed on the data collection 86 snapshot (271 trades; no new trades since the 07:08 drop, so every 09-21 figure unchanged). `docs/ANALYSIS-2026-09-21-win-rate-drop-check.md` **§2b** now partitions the ledger into non-overlapping books: **all/era-blind (what the tile shows) n=271, 27.3% dec, −$0.625/trade**; **pre-ratchet n=45, 17.8%, −$1.834**; **0.30R era n=130, 31.2%, −$0.321**; **master 0.75R ratchet book n=96, 32.3% dec (CI 22.0–44.6), −$45.20 (−$0.471/trade — falsification bar tripped 09-17 16:17 UTC, still breached)**; of which **pre-deploy "0.75R-only" n=95, 32.8%, −$0.427** (closed at the ~09-21 06:00 deploy restart; last pre-deploy entry #269 05:18:05) and **max-hold era n=1** (#270 SELL 06:31:03 → SL −$4.59). Rows partition: 45+130+95+1=271, P&Ls sum to −$169.40. **No-reset decision (binding for future sessions):** the max-hold deploy resets nothing — (1) no counter reset: the 0.75R book keeps accumulating from 09-15 06:00 and the falsification bar stays judged on the whole book (a reset would have manufactured an un-pre-registered pass/fail window and orphaned the trip record); (2) "closes at deploy" = the sub-period stopped receiving trades, not re-zeroed stats; (3) the max-hold era is a *sub-period* of the same ratchet book (still 0.75R) for the step-1 isolation read, judged at deploy + ~2 weeks / n≈200; (4) no engine-state reset — stats restore from `trades.csv` on the restart (brief 0.0% tile = known restore artifact), Trade_Num not renumbered, ledger never zeroed. Era-terminology pointer added in `docs/REVIEW-2026-09-21.md` §3; `docs/HANDOFF.md` §1/§5/§11 updated (branch/PR state, era-book pointer, latest-doc line). No engine/strategy/param change (`engine.py`/`trade_filter.py`/`dashboard.py` untouched — the max-hold isolation window is undisturbed; merge only advances the box's docs on the next autosync). Suite green: smoke PASSED A–K, `check_data.py` 0 fail / 8 warn, py_compile clean.
- **[2026-09-21 → win-rate drop check: NO drop + dashboard tile clarity]** User asked whether the win rate had collapsed after the last change (max-hold time stop, PR #15 merged 04:50:49Z), right after a manual autosync at 06:59 — the number on screen was the **dashboard Win-Rate tile (27.3%)** (`docs/ANALYSIS-2026-09-21-win-rate-drop-check.md`, 271 trades). **Answer: no.** Pooled decisive WR **27.3%** at n=271 (was 27.6% at n=265, 07:00 earlier today); 0.75R era **32.3%** at n=96 (was 33.3% at n=90) — both moves inside the ±11 pp CI; new regime 31.9% at n=226; last 30 trades 40.0%. **The tile is era-blind** (mixes the retired pre-ratchet 17.8%/n=45 and 0.30R 31.2%/n=130 books with the current era), which is what made a stable number read as a collapse → tile now labelled **"Win Rate (decisive) · all eras · excl. BE/TIME · all-in 14.0%"** (`dashboard.py`, display-only, no engine/strategy/param change; verified by rendering with real, partial and absent `status.json`). **The change is exonerated by construction: `MAX_HOLD_MINUTES = 240` has fired 0 times** (`time_exits: 0`; the key only exists in the PR #15 engine, so its presence in the engine's 06:59:06 `status.json` also **confirms the ~06:00 autosync deploy**) and TIME exits are excluded from decisive WR math anyway. Max-hold era sample = **1 trade** (#270 SELL 06:31 → SL, −$4.59); since the merge only 2 closed trades, both losers (−$7.15) — that is the entire basis of the impression. The recent window is noise + known mechanics: last 5 closed trades 0W/4L/1BE (**P(0 of 4 decisive) = 20%, P(≤1 of 5) = 47% at a 33% base rate**), 4-SL run → 60-min cooldown state, and the cooldown blocked a cluster of *winning* SELLs at 05:30–06:17 (9 of 13 blocked would have TP'd; +$281.83 sequential phantom) while the live book sold a −$35 move and got stopped by 2.6–4.6 point bounces — 4 of the 5 latest exits were in the bot's favour 30–60 min later (direction right, timing wrong). Independent live-engine verification from the price log: every BE exit of the era reached **MFE ≥ 0.76R** (min 0.76R, median 1.10R; none below 0.70R) → the deployed ratchet is genuinely at 0.75R, geometry (2·ATR / 3·ATR) intact, no schema drift. Pre-registered bar status unchanged (era P&L/trade −$0.471 at n=96, still below −$0.40: a P&L bar, not a WR bar); judge max-hold at deploy + ~2 weeks / n ≈ 200. Suite green: smoke PASSED A–K, `check_data.py` 0 fail / 8 warn, py_compile clean.
- **[2026-09-21 → max-hold time stop SHIPPED (fallback step 1)]** Implemented `MAX_HOLD_MINUTES = 240` in `engine.py` (`docs/REVIEW-2026-09-21.md`): any open trade older than 4 h closes at market with `Exit_Reason TIME` — price exits take priority, enforced on tick + MT5 candle paths, wall-clock (gap rides exit on the first candle/tick back), engine-side only (LIVE broker-side stop is future work). TIME accounting: own `time_exits` counter (in `total_trades`), P&L-signed into balance and era P&L/trade, but excluded from decisive WR math and ignored by the SL streak / daily breaker, like BE. All tools TIME-aware (`win_rate_report`, `analyze_losers`, `validate_gates`, `pathwalk_sims` count TIME explicitly; `check_data` accepts the domain + early-fire tripwire; dashboard gains a Time Stops tile) with byte-identical output on pre-TIME data; `smoke_test.py` Scenario K covers tick + candle paths, price priority, SELL sign, armed-but-expired, restart restore. Era snapshot at ship: 265 closed (+1 active), 0.75R era n=90 → 19W/38L/33BE, 33.3% dec (CI 22.5–46.3), −$0.412/trade (bar still breached); 09-18 full day +$3.38 (first positive era day); weekend thin (Sat dark, Sun 2 trades). 0.75R-only era closes at deploy (merge → autosync ≤ 3 h); max-hold era re-baselines at the restart — pin the exact boundary from the autosync log / Telegram digest. Queue unchanged (RSI≥45 ~dropped, MAX_ATR held, BE-resets-streak down-graded); isolation starts at deploy, re-review ≈ deploy + 2 weeks. Suite green: smoke PASSED A–K, `check_data.py` 0 fail / 8 warn, py_compile clean.
- **[2026-09-18 review → falsification bar formally TRIPPED; fallback starts]** Data review only, no code/param changes (`docs/REVIEW-2026-09-18.md`; 250 trades, 75 at +0.75R → 16W/32L/27BE, 33.3% decisive CI 21.7–47.5, **−$0.443/trade** — the pre-registered bar (P&L/trade ≤ −$0.40 at n≥60) **formally tripped 2026-09-17 16:17 UTC (−$0.595/trade at n=60)** and remains breached at n=75 (CI [−1.29, +0.40]); true equity $342.57, engine ledger $367.27, drift +$24.70 unchanged). 09-18 partial day = first positive era day (+$5.50, 12 trades, 50% dec) — noted, not over-read (against −1.07/−22.92/−14.74). **Fallback now active per pre-registration: ~4 h max-hold time stop first, measured in isolation (next code session; era re-baselines at deploy via autosync ≤ 3 h), ratchet-off second (replay +$0.40–0.52/trade), never back to 0.30R.** Queue otherwise unchanged: BE-resets-streak still down-graded; MAX_ATR 4.5→2.5 still held (era ATR≥2.5 unchanged at n=9, 1W/4L/4BE, −$12.35); RSI≥45 still ~dropped; scheduled-news gate named-only. **Realistic auto-trade timeline recorded (REVIEW-2026-09-18 §5):** at ~24–25 trades/day trade count is cheap — binding constraints are (1) a config with demonstrated positive expectancy in isolation, (2) regime coverage (one FOMC in 14 trading days; trend flip may be months away), (3) costs (forward-test P&L = price delta only, zero commission/spread — real account must clear broker costs), (4) unimplemented LIVE-mode broker-side BE modify. Phase gates: max-hold deploy now → in-isolation check ~2 wks → edge confirmation ~8 wks (n≈1,300 era trades, CI ±$0.20/trade) → multi-regime 3–4 mo → micro live pilot Q1 2027 → **auto-trade decision 6–12 mo (Mar–Sep 2027)**. Bot is not income until then. Suite green: smoke PASSED A–J, `check_data.py` 0 fail / 8 warn, py_compile clean.
- **[2026-09-17 review → FOMC + falsification]** Data review only, no code/param changes (`docs/REVIEW-2026-09-17.md`; 233 trades, 58 at +0.75R → 11W/25L/22BE, 30.6% dec CI 18–47, **−$0.557/trade — below the −$0.40 falsification bar**, n=58 < 60 so not yet formal; true equity $343.50, engine ledger $368.20, drift +$24.70). **FOMC 09-16 raised 25bp to 3.75–4.00% at 18:00 UTC**; gold cascaded −$118.3 (−2.7%) in ~70 min (spike 4367 → low 4235) into **no open trade** — defense-in-depth (escalated SL cooldown 17:28–18:28 → MAX_ATR>4.50 wall 18:02–20:01), not luck. But 09-16 was already a bleed day pre-release (4W/11L/8BE, −$18.45 by 18:00; daily breaker hit 10 SLs at 16:06), so the bar breach is **not** a news fluke. Queue re-ranked: **RSI ≥ 45 ~DROPPED** (skip 36.0% dec / −$18.79 vs keep 27.9%); **~4h max-hold time stop PROMOTED to #1** (only two >60-min holds, expresses close-before-scheduled-macro without a news feed); **BE-resets-streak DOWN-GRADED** (still +$206 sequential phantom leak, but escalation just proved it pays for itself on FOMC day); MAX_ATR 4.50→2.50 held (ATR≥2.5: 1W/4L/4BE, −$1.37/trade, n=9). Next trigger: P&L/trade ≤ −$0.40 at n≥60 → max-hold first, ratchet-off second (never 0.30R). Suite green: smoke PASSED A–J, `check_data.py` 0 fail / 8 warn.
- **[2026-09-15 docs]** Session & Push Protocol added to `docs/HANDOFF.md` (new §11 "How to keep this file honest", ported from bitcoin-trading-bot PR #5): one session = one scope = one PR at the end (merge → `origin/main` → the next `tools/autosync.sh` run, ≤ 3 h, deploys to the live box — so merging stays the last click); push after every logical step — the sandbox filesystem is ephemeral and unpushed commits are unrecoverable (no cherry-picking from dead workspaces); the session PR stays open as a draft until the agent reports all tasks complete + `tools/smoke_test.py` SMOKE TEST PASSED + `tools/check_data.py` 0 fail **and** the user confirms; hand off via `docs/HANDOFF.md` + this changelog, not chat. Also: per-session update ritual written down (§11) and the current work branch recorded in §1's header. Docs-only — no code, params, or strategy logic touched; nothing to re-run.
- **[2026-09-15 review → rule change]** 164-trade review (`docs/REVIEW-2026-09-15.md`; ledger 14W/58L/92BE = 19.4% decisive, CI 12.0–30.0, true P&L −$140.94 → equity $359.06, drift +$24.72; new regime #46–164 = 119 trades, 6W/21L/92BE, −$58.43 = −0.123R/trade vs −0.649R pre-ratchet). **Finding: the win rate was an exit problem.** `BE_TRIGGER_R = 0.30` is 0.6·ATR ≈ $1.2 on a $4300 market — one noisy minute; median scratch lifetime 1.5 min and 77% of new-regime trades ended as $0 scratches (09-14 alone: 62 trades, 49 of them scratches, 9 entries in 43 min because a BE exit triggers no cooldown). Re-walking the SAME 119 entries with an explicit 240-min horizon (replay validated: at +0.30R it reproduces 6W/21L/92BE, −$57.55 vs −$58.43 actual) gives: +0.30R 22.2% dec −$0.49/trade (live) | +0.75R **44.7% dec +$0.40/trade** | ratchet off 41.0% dec +$0.52/trade, cascade-aware. The 92 scratches alone would have replayed 55W/36L for +$221.74. **Adopted: `BE_TRIGGER_R` 0.30 → 0.75** (only strategy change; engine restart via autosync). Queue: (a) RSI≥45 MET its adoption bar (new regime: 47 skip-bucket trades at 10.0% dec / −$32.22 vs 29.4% kept) — adopt next cycle; (b) BE resets the SL streak — supported (cooldown-blocked phantoms 48W/28L +$163 sequential; 17 of 21 SLs escalate because scratches don't break the streak); (c) RISE120 — **REJECTED** (135 kept, 18% dec, −$123.40); (d) MAX_ATR 4.5→2.5 — eligible (ATR≥2.5: 0W/4L/13BE, −$27.11), parked one cycle to avoid confounding. BUY side: 0W/5L/26BE in the new regime (0% decisive in 31 trades). Phantom total still says the risk layer adversely selects: 99 sequential blocked signals → 63W/36L (64%), +$198.20 vs 19.4% taken. **Tooling bug hunt**: 3 of 5 analysis tools were broken on this data — `pathwalk_sims.py` had SELL bar extremes inverted (`hi_r = d*(h-e)/risk` is the favourable side only for BUYs) so it under-detected every short's TP/BE arm and *looked* self-validating by falling back to actual; ratcheted-stop rows (`Stop_Loss == Entry_Price`, 98 of them — 92 BE **plus 6 TP winners**) divided by zero in `analyze_losers.py`/`exit_sims.py`/`pathwalk_sims.py`; `analyze_losers.py`'s naive §4 exit table (which cannot see past a 2-min window) was deleted in favour of horizon-aware replay. All fixed, plus `check_data.py` gap-span bounds (`<` → `<=`, it had missed a trade held 49.1 h across the weekend: #95 Fri 20:57 → Sun 22:01) and two new tripwires (ratcheted-stop rows = INFO, >60-min holds = WARN). New read-only tool **`tools/win_rate_report.py`** (win-rate decomposition with Wilson CIs, era/side/day/hour splits, hold-time table, ratchet counterfactual, cascade-aware trigger grid, queued filters by era). `smoke_test.py` Scenario I now derives its labels from `BE_TRIGGER_R` and gained a **"must NOT arm below the trigger"** assertion. Suite green: smoke PASSED (A–J), `check_data.py` 0 fail / 8 warn.
- **[2026-09-10 PM review]** First 15 trades on the merged PR #7 stack (`docs/REVIEW-2026-09-10-PM.md`, 60 trades total: 8W/39L/13BE, −$92.05 true, equity $407.95). BE ratchet live: 13/15 scratches (−$9.54, −65% bleed vs pre-BE); counterfactual says it saved ~$30 of SLs and killed 5 trend TPs (~$34) — P&L-neutral, variance-reducing. ATR>4.5 bound validated live (12 blocked, all would-be SL); London direction-aware fix not yet live-tested (deployed 12:34, after the window). RSI<45 deepens to 1W/15L/3BE (6% dec, −$44.01) — queued as change candidate #1 behind the 30-new-regime-trade bar (15/30). **Strategy unchanged.** Tooling-only cycle: all `tools/` made BE-aware (BE rows reconstruct 2×/3×ATR geometry from `ATR_At_Entry` since logged SL==entry), `check_data.py` gains same-minute INFO check (part-2 to-do, done: 18 min / 19 extra rows, benign) + BE tripwires, dashboard gains BE tile + TREND-ONLY badge. Suite green (smoke A–J, 0 fail). Also rescued `docs/REVIEW-2026-09-10-part2.md` from stale PR #5 (closed as included). No engine restart required.
- **[2026-09-10]** Data review part 2 (`docs/REVIEW-2026-09-10-part2.md`, "data collection 11", rescued from PR #5): 79 new log rows, trade #42 (BUY SL −$3.33, passes all gates incl. rejected PROX pair), true equity $422.35. Stall recovered as one 293.5-min hole (00:47→05:41, no trade open across it); drift fix survived the ~06:33 restart (`daily_losses: 2` correct).
- **[2026-09-10 analysis → rules]** Losing-trade study (`docs/ANALYSIS-2026-09-10-losing-trades.md`, tools: `analyze_losers.py` / `exit_sims.py` / `pathwalk_sims.py`) on 45 trades (8W/37L, −$82.51): expectancy ≈ −0.5R at every TP placement (exits can't create edge), but **blocked signals replayed 47.5–65% WR (+41 phantom raw) while taken signals went 17.8%** — the risk layer was adversely selecting. Adopted (smoke A–J green):
  - **Breakeven stop ratchet** `BE_TRIGGER_R = 0.30` in engine.py (tick + candle paths, status.json persistence, exit reason `BE` = scratch, new `be_exits` counter; replay −82.51 → −62.36). LIVE-mode broker-side SL modify is still future work.
  - **Direction-aware London blackout**: 07:55–09:00 UTC blocks BUYs only — SELL phantoms there went 5W/1L (+20.09) since the SELL side went live; other windows unchanged.
  - **Daily-loss breaker degrades to trend-side-only** instead of halting: after `MAX_DAILY_LOSSES` (kept at 10; the live "(11/3)" rows were from the older 3-limit build), entries must agree with 60-min momentum from the price log (15-min staleness guard, legacy hard-halt fallback). Post-halt phantoms had gone 7W/0L (+27.71).
- **[2026-09-10]** `DATA_SOURCE=MT5` feed option for forward testing. After the Twelve Data WebSocket began refusing connections (handshake OK, immediate close — WS-trial expiry on the free plan suspected), the engine can now source closed M1 GOLD candles from the local Wine MT5 terminal (broker feed, no plan limits). `MetaTrader5` has no Linux wheels, so the Linux engine never imports it: a sidecar `tools/mt5_feed.py` runs under the Wine Python in the same prefix as the terminal (same pattern as the `mt5-balance` alias: `WINEPREFIX=~/.mt5 xvfb-run wine C:/Python312/python.exe Z:/opt/gold/tools/mt5_feed.py`) and atomically publishes the latest closed candle to `/opt/gold/mt5_last_candle.json`; `run_mt5_test()` reads that file — one row per closed minute, deduped by candle timestamp (a restart never re-logs the boundary candle; worst case one minute lost), same stale-feed guard + Telegram alerts. Trading stays simulated. Default remains `TWELVEDATA` — switch by adding `DATA_SOURCE=MT5` to `/opt/gold/.env` + installing `deploy/mt5feed.service` (`systemctl enable --now mt5feed`) + restarting the engine. `smoke_test.py` Scenario H covers file read/normalization/dedup.
- **[2026-09-10]** Stale-feed guard for the Twelve Data WebSocket: the feed stalled silently at 00:47 and again after the 02:05 restart (2.5h+ of missing candles, zero alerts) — a zombie WebSocket delivers no events and `heartbeat()` never raises, so the engine idled forever. `run_forward_test()` now force-reconnects when no price event arrives for `STALE_FEED_SECONDS` (10 min) and sends a rate-limited Telegram alert (30-min cooldown, suppressed during the broker daily break ~21:00-02:00 UTC and weekends via `is_market_quiet()`). `smoke_test.py` Scenario G covers detection, quiet-hour classification, and alert rate-limiting. **Deploy note**: add `Environment=PYTHONUNBUFFERED=1` to `goldbot.service` (`sudo systemctl edit goldbot.service`) so engine prints reach the journal unbuffered — the 02:05 stall was invisible in `journalctl` because Python block-buffers stdout.
- **[2026-09-10 post-review]** trades.csv schema-drift fix + learning tooling (see `docs/REVIEW-2026-09-10.md`):
  - **Critical**: SELL rows were appended under the pre-SELL 15-field header, misaligning every field (`Exit_Reason` read as a price) and silently disabling the daily-loss breaker, cooldowns and stat reload for SELL trades. `engine.migrate_trades_csv()` now self-heals the file on startup and before every append (backup kept); `trade_filter` has a loud drift tripwire; repo data migrated (raw copy: `archive/trades.csv.bak.20260910_pre_schema_fix`).
  - **New tools**: `tools/check_data.py` (integrity gate: schema/ledger/gaps/cross-file), `tools/phantom_trades.py` (replays blocked skip-log signals as phantom trades — reconstruction validated 99–100% vs logged indicators), `tools/validate_gates.py` now direction-aware (SELL mirrors, both schemas).
  - `tools/smoke_test.py` Scenario F: regression test reproducing the drift incident.
- **[2026-09-10]** Bidirectional Trading + Capital Protection Upgrade:
  - **Added Short-Selling (SELL) Funnel**: Symmetric Bearish setup when `EMA50 < EMA200`, testing 20-bar ceiling, upper-wick rejection $\ge 38\%$, holding resistance, falling EMA50 slope, and close near EMA50.
  - **Added Daily Loss Circuit Breaker (`MAX_DAILY_LOSSES = 3`)**: Automatically halts trading for the rest of the UTC day upon reaching 3 Stop Losses to prevent drawdown spirals during trend days / chop.
  - **Added Escalating SL Cooldowns**: 30 min cooldown after 1 SL, escalating to 60 min after 2 consecutive SLs, and halting on 3 SLs.
  - **Expanded High-Impact Blackout Windows**: London Open (07:55–09:00 UTC), NY Open & US Macro Data (13:25–15:15 UTC), and Daily Rollover Spread Spikes (21:45–22:30 UTC).
  - **Updated Web Dashboard**: Dual Long/Short funnel telemetry, active trade direction badges, and real-time daily loss tracking.
- **[2026-09-09]** Added regime gates from win-rate review: EMA50 slope lookback (30 candles) and max distance below EMA50 ($0.3 \times \text{ATR}$).
- **[2026-09-04]** Removed restrictive `MIN_EMA_GAP` filter from `trade_filter.py`. It was blocking valid pullbacks because the EMA gap naturally shrinks during pullbacks.
- **[2026-09-04]** Aligned ATR thresholds. `engine.py` `MIN_ATR` changed from 0.70 to 1.10 to match `trade_filter.py`.
- **[2026-09-04]** Fixed funnel diagnostics in `engine.py`. Added `self.hit_... += 1` counters so `status.json` accurately tracks where signals drop off.
- **[2026-09-04]** Updated `datetime.utcnow()` to `datetime.now(timezone.utc)` in `trade_filter.py` to prevent Python 3.12+ deprecation warnings.

## 📊 Forward Test Observations (Sep 4–17, 2026)
- **Ledger at 2026-09-15**: 164 trades, 14W/58L/92BE → **19.4% decisive** (8.5% all-in), true P&L −$140.94 ($500 → $359.06). Needs 40% decisive to break even at 1:1.5. New regime since the 09-10 stack: 119 trades, −0.123R/trade (was −0.649R pre-ratchet).
- **FOMC day 2026-09-16**: Fed **raised 25bp to 3.75–4.00%** at 18:00 UTC; gold fell −$118 (−2.7%) in ~70 min. Bot had **no open trade** and entered nothing 17:19–20:36 UTC — covered by escalated SL cooldown (17:28–18:28) then the MAX_ATR>4.50 wall (18:02–20:01), not luck. 09-16 was still a bleed day pre-release (4W/11L/8BE by 18:00, daily breaker hit 10 SLs at 16:06).
- **Interim 2026-09-17**: 233 trades; 58 at +0.75R → 11W/25L/22BE, 30.6% dec (CI 18–47), **−$0.557/trade — falsification bar breached** (n=58<60, formal at next drop). Scratch rate 37.9%, median BE hold 8.5 min (mechanism ok); edge not materialising. RSI≥45 ~dropped; max-hold ~4h promoted to #1; BE-resets-streak down-graded; MAX_ATR tightening held. Fallback plan if the bar holds: max-hold stop first, ratchet-off second.
- **Win-rate diagnosis (09-15)**: the decisive rate is low mostly because the +0.30R breakeven ratchet harvested 77% of new-regime trades into $0 scratches — the entry stream itself replays near 50/50. Raised the trigger to 0.75R.
- **Blocked > taken, still**: the risk layer replayed its own rejects at 64% decisive (+$198.20 sequential across 99 deduped signals) while taken trades won 19.4%. Cooldown escalation is the biggest leak (+$163).
- **Review Findings**: Without daily circuit breakers, bad days (Sept 8 grind-down and Sept 9 afternoon news dump) resulted in 20 Stop Losses across 2 days. The new daily cap and US macro blackout directly protect against these scenarios.
- **Funnel Stats**: System now monitors both dynamic floor (Long) and dynamic ceiling (Short) with slope and proximity confirmation.

## 🚀 Future Tweaks / To-Do
- [x] Add Short-Selling logic for when `EMA50 < EMA200`.
- [x] Add Daily Loss limit (`MAX_DAILY_LOSSES = 3`) to `trade_filter.py`.
- [x] Implement escalating SL cooldown (30 min -> 60 min on consecutive SLs).
- [x] Judge the +0.75R ratchet after ~2 weeks — DONE 09-21: bar tripped 09-17 (−$0.595/trade at n=60), still breached at n=90 (−$0.412); fallback step 1 shipped.
- [x] **~4h max-hold time stop** — SHIPPED 09-21 (`MAX_HOLD_MINUTES = 240`, reason TIME). Isolation from deploy; re-review ≈ deploy + 2 weeks.
- [x] Confirm the fallback-step-2 bar at the re-review — **DONE 10-05: MET** (n=209, −$0.570/trade), harness delivered the same day, **step 2 then CLOSED as not worth a slot** (see the 2026-10-05 stop-geometry entry). Never back to 0.30R.
- [x] Score registered **`H-side-awareness`** at the ~10-05 re-review — **DONE 10-05: DROPPED** (fails (b) within-SELL 60-min and (c) rising-gold; see `docs/REVIEW-2026-10-05.md` §3). Do not re-slice.
- [x] Pre-register + sign off **one** experiment — **DONE 2026-10-05 (2nd session), and it went a third way**: the costed/stateful/era-matched harness (`tools/strategy_lab.py`) was built first, which let the *root cause* be measured (inert level test → non-structural stop). The shipped experiment is the **structural stop** with a pre-registered bar (`docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` §7, judge at n≥100 ≈ 2026-10-19). **Ratchet-off closed without spending a slot** (≈breakeven gross, 61.7% full stop-outs, redundant next to the stop fix: −0.131R vs −0.124R). **Session-band gate downgraded** (gap collapses 0.268R → 0.085R under the new stop — it was a proxy for stop geometry).
- [x] Finish the remaining ANALYSIS-2026-10-01 §4 tooling: **cost model on all exits incl. BE ✓, SL-streak + wall-clock cascade ✓, direction-aware/era-correct gate replay ✓** (all in `tools/strategy_lab.py`, funnel recall 99.6–100% per era); MFE/MAE alignment in `analyze_losers.py` and decisive-WR labels in `pathwalk_sims.py`/`phantom_trades.py` **still open** (those tools are descriptive only).
- [ ] New named candidate (not adopted): **pre-close entry guard / flat-before-close** for the daily/weekly closure gap (#476 rode 49.1 h) — pair with LIVE-mode broker-side work.
- [ ] Cooldown semantics: BE should reset the SL streak (still queued, down-graded post-FOMC); consider a ~5-min post-scratch pause to stop same-move re-entry churn (47% of 0.75R entries still <10 min after prev exit).
- [ ] ~~Adopt RSI ≥ 45 entry gate~~ — **~dropped 2026-09-17** (reversal confirmed; was a ratchet-era artifact).
- [ ] Scheduled-news gate (optionally) — named candidate after the 09-16 FOMC passed without one; the MAX_ATR wall is what actually covered it.
- [ ] Multi-Timeframe (15m/1h) higher-timeframe trend integration.
- [ ] Live spread filter check before order dispatch.

## 2026-10-17 — PR #34 corrected: sizer is LIVE-only, skips arm nothing, FOMC window reverted
- PR #34 (%-risk sizer + min-spread filter + FOMC 18:00 blackout) **deployed 2026-10-16 23:01:54 UTC** via autosync `d5b81151`, into a **closed market** (gold shut 20:57 UTC) — ledger 624 closed, struct-stop era n=127, no trade affected.
- Measuring the deployed code against its own claim found three defects. (1) `size_lots` sized off the **paper ledger** ($150.69), not a broker account: replayed on the era's 127 entries it skips 76.4% (rolling balance) and 84–91% ($180/$151); at the $500 ledger start it would have picked **0.02** lots on 16/127 — a flow stop and an entry-stream confound for the open struct-stop window, not the R-invariant no-op the PR claimed. (2) `execute_simulated_trade` armed the position **before** the sizer check and the refuse branch returned without clearing it, so the next candle **logged a phantom trade** (previous SL/TP vs the new entry price) — reproduced hermetically. (3) LIVE fell back to the paper ledger when `account_info()` was unavailable, and logged `LOT_SIZE` instead of the sized volume.
- Fix (one commit, no strategy/param change): `size_lots` returns `LOT_SIZE` in paper (book byte-identical to pre-PR-34), the trade commits atomically after the sizer accepts, LIVE refuses to size without an account, and the **FOMC 17:55–18:30 window is reverted** (blackouts frozen by §6.1; it blocked 3 of 127 era entries, +$15.80, ~0.023R of era R/trade ≈ a quarter of the headroom to the −0.10R bar) — to be re-registered after 2026-10-19.
- Coverage: `tools/smoke_test.py` **Scenario V** (paper lot parity, LIVE sizing arithmetic, skip-path invariant, frozen blackout list + positive controls) — PR #34 had **zero** smoke coverage of its own code. Bars: paper identical to pre-PR-34; `SMOKE TEST PASSED`; `check_structural_stop.py` PASS.
- Docs: `docs/PREREG-2026-10-17-risk-sizer.md` erratum (skip table + deploy cutover + defect), HANDOFF §1/§4/§6.8, era timeline. The struct-stop window is the only live experiment again.

## 2026-10-16 — dashboard market-context layer (display-only, no runtime change)
- Owner ask: a buy/sell pressure indicator on the dashboard, plus anything else useful for a daily decision.
- Added `pressure.py` (read-only, stdlib-only) + panels in `dashboard.py` + `tools/pressure_report.py` (CLI) + smoke Scenario U (45 checks) + `docs/ANALYSIS-2026-10-16-dashboard-pressure.md`.
- The pressure composite is 60-bar, weighted, and **auditable** (every component prints raw value, unit, weight and buy-share). Calibration on the live book: **collinear with side** (BUY 49–81, SELL 14–42 at entry; zero `against` buckets in either era) → shown as **context**, and the panel says so in its own words.
- The decision-useful part is the gate read: the engine's own flags (`Tested_Floor`, `Valid_Rejection`, `Held_Floor`, `Trend_Confirmed`, wick, RSI, ATR) with the SELL side, EMA slope and proximity buffer recomputed by the engine's rules, plus the portfolio state (blackout/cooldown/breaker/skips), the 20-bar location and the live structural risk.
- Invariants: mirrored thresholds pinned by Scenario U to `engine.py`/`trade_filter.py`; `pressure.py` proven read-only and stdlib-only by AST; feed gaps counted in open-market minutes (weekly close excluded); R/trade on `win_rate_report.py`'s scale ($/trade ÷ mean 1R rebuilt from the reward leg).
- No engine/filter/param change; autosync restarts the dashboard only; the struct-stop window is undisturbed.

## 2026-10-15 — stop-loss rate: harness fix + pre-registration (no runtime change)
- Question: "too many stop losses". Live struct-stop book (n=111): 39.1% decisive vs 42.0% breakeven at the live payoff; gross −$0.32/trade.
- Found and fixed a replay bug: `strategy_lab.py` blackout end boundary was inclusive by minute; live is `<=` on the full timestamp. Replay now matches live on the struct-stop era (39.3% vs 39.1% decisive).
- Level-test re-scale (0.25 ATR) is the strongest queued lever; pre-registered on paper in `docs/PREREG-2026-10-15-level-test-0.25.md`. Not deployed; judged only after the 10-19 review.
- Docs: `docs/ANALYSIS-2026-10-15-stop-loss-rate.md`, `docs/HANDOFF.md` §1/§5/§6/§8.

## 2026-10-19 — negative-balance investigation

Confirmed ten malformed phantom TP rows (#626–635) booking −$41,806.88; raw paper
equity −$41,656.19 versus last valid $150.69. Checked-in correction passes smoke;
host process/deployment unverified. No ledger or runtime changes. Evidence and
recovery prerequisites: `docs/REVIEW-2026-10-19-negative-balance.md`.

Recovery PR follow-up: added paper-exit geometry guards, honest finite-negative
startup accounting and a strict dry-run/backup/quarantine repair CLI. Full smoke,
three hermetic recovery tests and compilation pass. Host apply remains operator-only;
no strategy changes and no production ledger edits.

## 2026-10-19 (early session, ~05:20–06:30 UTC) — struct-stop interim screen n=127 + the §7 closure-gap trigger (docs/tools only, no runtime change)
- Session: "Execute the plan." First eligible step only — every-session verification plus the complete registered screen on the checked-in data (collection 279, log to 2026-10-19 02:59 UTC). **No runtime rule changed, nothing deployed, `engine.py`/`trade_filter.py` untouched.**
- Verification: `check_data.py` 0 fail / 8 warn (the documented historical warnings) · `handoff_check.py` FRESH · `check_structural_stop.py` **PASS** (0 stops inside the level, median clearance +0.50 ATR, boundary #498 old -> #499 new) · `strategy_lab --calib-only` recall **100.0/100.0** · `smoke_test.py` **PASSED** (now A-W) · `py_compile` clean.
- Screen at n=127 (37W/60L/29BE/1TIME, 10 entry dates, gross -$47.48): A1-A5 pass, B1 SL/day 6.00 pass, **B2 SL share 47.24% vs the strict <=47.0% bar FAILS**, B3 scratch 22.83% pass, C1 R/trade -0.065R pass, C2 decisive WR 38.14% [29.1-48.1] pass -> **SCREEN NOT MET** (same marginal miss as 10-17). PASS unreachable at n=127 (Wilson LB 29.1% < the required 32.1%). Revert triggers R4/R5/R7 clear (R -0.065 vs -0.20; avg SL $5.85 vs $8.60; era DD $93.38 vs $250). Costed: era -$98.30 / -0.135R at the assumed $0.40 round trip, -$117.35 / -0.161R at the logger's $0.55 median -> negative at every cost read. Replay cross-check (post-cutover, $0.20/side): baseline n=205 40.4% -0.120R vs structstop n=133 38.1% -0.116R (row-to-row deltas only).
- **New work — the §7 extra revert trigger (gap risk) is now measurable.** No tool had ever counted it ("2 or more post-cutover trades found open across a daily/weekly closure with an unenforceable stop"). New read-only `tools/check_gap_rides.py` (ride = open across a scheduled closure, counted from the cutover; a feed outage is not a closure) prints the count **and** the damage facts. **The count is 2 of a registered threshold of 2 -> the trigger is REACHED** (#595 10-14 and #610 10-15, both over the 20:58->22:00 daily break). Damage so far **$0.00**: no weekend closure ridden, neither reopen gapped through its stop (#610 reopened $4.15 above it, #595's stop was already ratcheted to entry), both exits printed at the stop or target price. The count was 0 at n=78 on 10-13.
- **No revert executed, deliberately:** the struct-stop window is open until it is judged (HANDOFF 6.1), the registered judgement point is 2026-10-19 21:00 UTC or n=150, a revert is a runtime change that reaches the host only through merge + autosync, and §7 registers a threshold but never a counting rule - the rule must be **stated in the judgement record**, not settled by which way a session happened to count. The review spells out the decision procedure; if the trigger is judged fired, the registered action is a single-commit revert of the structural stop **with the gap guard first**, and the 0.25 ATR level test does not proceed. Smoke **Scenario W** pins the counter (classification, the two mechanical gap facts, the threshold, and an end-to-end synthetic book).
- Parallel tracks: quote logger **5/14 complete days, 1/2 weekends** (median spread $0.55, 98.5% of samples above the assumed $0.40; the $0.40 assumption stays in force) · pressure composite still *collinear with side - not a signal* (BUY 43.4% / SELL 56.6% on the last bar) · the negative-balance incident is reconciled in the ledger but the **host-side verification is still operator-only** · the large-N history path is still a first-run-on-the-box task.
- Docs: new `docs/REVIEW-2026-10-19-struct-stop-screen.md`; HANDOFF §1 rewritten in place (current-state only) with the replaced block moved to `docs/HANDOFF-HISTORY.md` per §11 rule 5; era timeline, cheat sheet, §6.1, §7 and the §11 milestone table updated; this plan reconciled. An earlier 04:41 UTC draft of the review was **PR #38 — closed unmerged**, so none of it had reached `main`; this session re-derived every number from the data.

## 2026-10-19 — read-only dashboard context PR

Owner authorized risk/map/evidence upgrade and PR. Added labelled indicative closure
countdown/hold overlap, logged-spread freshness, complete-bucket M15/H1 momentum,
observed prior-day range and costed ALL/BUY/SELL evidence. No engine/filter changes.
Scope, deferred data-dependent additions and limitations:
`docs/ANALYSIS-2026-10-19-dashboard-context.md`. Refreshed snapshot to collection 282,
630 closes and struct-stop n=133; no judgement or deploy claimed. Integrity 0 fail,
smoke and four targeted tests (including Flask render) pass; compilation clean.

## 2026-10-19 — signal outlook (read-only, no runtime change)

Owner ask: manual direction-reading from 1-min candles is extremely hard — "could we
have a rough estimate where it's headed given very strong signal?" Measured forward
walks after every taken (8/8) signal in the bot's own ledger: direction at 15–60 min
is a coin flip (pooled 48.9% [41–57] the trade's way @30m, struct-stop era n=135;
median drift −0.02R), no better than a trend-anywhere baseline; target prints before
stop ~32–34% of decisive 30–60m races vs the 40% driftless reference for +1.5R/−1R
(~40% only over the full 240-min life); bigger rejection wicks did not follow through
better (exploratory). Shipped as cone + base rates, not an arrow: `pressure.py`
§5b (`signal_outlook`/`outlook_now`), `tools/signal_outlook.py`, dashboard 🧭 panel
(applied cone when the last bar is 8/8), 9 hermetic tests in
`tools/test_signal_outlook.py`. Full method/numbers/verdict:
`docs/ANALYSIS-2026-10-19-signal-outlook.md`. Struct-stop window and its 21:00
judgement untouched; no gate/sizing/hold use authorized. Verification: check_data
0 fail · smoke PASSED (Scenario U AST still clean) · 13 unit tests incl. Flask
render (venv flask in sandbox) · py_compile clean.

## 2026-10-19 (data refresh, checked-in log through 18:10 UTC) — handoff refresh (docs only, no runtime change)

The host-side `handoff_check.py --update` output supplied for this session reported
data collection 287, 636 closed trades, and a log through 18:15 UTC (44,819 bars).
The checked-in clone is five minutes behind on bars (18:10 UTC, 44,814 bars), but
its ledger/outcomes, balances, structural-stop sample, skips and open-trade state
match the host output. The handoff snapshot is kept aligned to the checkout's
verifiable 18:10 timestamp; the collection number 287 is carried from the host
report because this shallow checkout cannot derive that autosync commit number.

Current ledger: **636 closed, 124W/276L/234BE/2TIME**, 31.0% decisive; engine
ledger $142.16, true equity $125.18, net −$629.22 at the assumed $0.40 round trip.
The structural-stop era is **n=139** (39W/65L/34BE/1TIME, 11 entry dates).
`check_structural_stop.py` PASS (0 stops inside; 81.3% level-bound; median
clearance +0.50 ATR; median risk 3.27 ATR). The fresh interim screen is **MET**
(B1 5.91/day; B2 46.76%; B3 24.46%; C1 −0.071R; C2 37.50% [28.8–47.1]), but
this is not the scheduled judgement or PASS: 11 trades short of n=150 and Wilson
LB 28.8% < 32.1%. The §7 closure-gap count remains **2/2** (#595, #610), with no
weekend ride or realized gap damage. The 2026-10-19 21:00 UTC judgement (or n=150,
whichever comes first) remains pending; no strategy/risk rule was changed.

The quote logger is at 6.1 days, 5/14 complete UTC days and 1/2 weekends, median
$0.55; the $0.40 assumption stays. The pressure calibration re-join at n=139 is
still collinear with side; the signal-outlook re-read remains a coin flip at 30m
(50.4% [42–59], median +0.02R). Updated `docs/HANDOFF.md` §§1/4/5/6, the era
timeline and milestones; archived the replaced §1 in `docs/HANDOFF-HISTORY.md`;
reconciled `docs/EXECUTION-PLAN.md`.

Verification: `check_data.py` 0 fail / 8 documented warnings; `handoff_check.py`
FRESH (one advisory because this shallow clone cannot resolve collection #287);
structural-stop guard PASS; `check_gap_rides.py` still at the registered count
(its `--strict` exit 1 is expected because the threshold is reached); `pressure_report.py`
SCREEN MET; `strategy_lab.py --calib-only` recall 99.8% (0.75R master) / 99.7%
(max-hold); quote report 6.1 days; signal-outlook report n=139. No final judgement,
deployment, or production-host process verification is claimed.

## 2026-10-20 — "execute the plan": post-gate data refresh (docs only, no runtime change)

Ran the plan's every-session queue against the checked-in snapshot (collection 294, ledger
and log through 2026-10-20 08:59 UTC) and completed its refresh duties. No engine, filter,
parameter, gate, exit or deploy change: `engine.py` stays `TRADING_MODE = "FORWARD_TEST"`.

Current state: **644 closed** (128W/277L/237BE/2TIME, 31.6% decisive), engine ledger $174.73,
true equity $157.76, net **−$599.84** at the assumed $0.40 round trip; open paper trade
SELL #646 @ $4120.28. The eight post-judgement trades (#638–#645, 4TP/1SL/3BE, +$32.58 gross)
moved the structural-stop era from n=139 to **n=147** (43W/66L/37BE/1TIME) with the guard still
PASS (0 stops inside the level, 81.6% level-bound, +0.50 ATR median clearance, 3.29 ATR median
risk) and the §7 closure-gap count unchanged at **2/2**, so the REVERT trigger remains fired.

Ruling recorded (interpretation, not a new threshold): the n=150 confirmatory arm **lapsed**
when the 2026-10-19 21:00 UTC time gate came first, so growing past 150 must not be used to
re-judge SCREEN/PASS on a later snapshot; post-gate era numbers are observations only. A
re-opened arm would need a new dated pre-registration written before the data is used.

Quote logger 6.7 days, 6/14 complete UTC days, 1/2 weekends, median $0.55 — the $0.40 assumption
stays. Broker-clock DST still unverified (single +3 h offset); discriminating window opens
2026-10-25 01:00 UTC. Pressure composite still collinear with side at n=147 (display-only).

Verification: `check_data.py` 0 fail / 8 documented warnings; `handoff_check.py` FRESH before and
after `--update` (0 advisory drift after); `check_structural_stop.py` PASS; `check_gap_rides.py`
2/2 (threshold reached, as registered); `strategy_lab.py --calib-only` recall 99.8% / 99.7%;
`win_rate_report.py --spread 0.40` net −$599.84; `xm_quote_report.py` 6/14 days;
`pressure_report.py --root .` all screen bars inside their thresholds. Files: `docs/HANDOFF.md`,
`docs/HANDOFF-HISTORY.md`, `docs/EXECUTION-PLAN.md`, `docs/REVIEW-2026-10-20-post-gate-refresh.md`,
this log. No deployment, host-process verification or production conclusion is claimed.

**Addendum (same session): owner was asked for the gap-guard definition.** Three scoping questions
(guard scope, pre-close cutoff, closure schedule source) put to the owner; answers: scope "leave it
blocked for now", schedule source "not sure yet", cutoff 30 minutes *if* a window is ever adopted.
Recorded as **no rule approved** — the 30-minute answer is a preference attached to no adopted scope,
not a registered `N`, and nothing was implemented. Consequence: the structural stop stays in the
checked-in engine, the bot stays paper-only, and the prescribed "revert with the gap guard first"
remains blocked pending the owner's own dated pre-registration. Recorded in
`docs/REVIEW-2026-10-20-post-gate-refresh.md` §4 so the next session quotes it rather than re-asking.


## 2026-10-20 — manual dashboard watch cards

Added read-only BUY/SELL watch price cards to Boxes & Timing: buffered breakout
references, hypothetical invalidation/target, gross and costed payoff, stale/unknown
health overrides and a labelled >1 ATR chase heuristic. Retests are not tracked;
no engine or filter changes. See `docs/REVIEW-2026-10-20-box-watch-cards.md`.
Also recorded the requested live-readiness estimate separately; no go-live approval.

## 2026-10-21 — box chop read, retest tracking, optional Telegram notifier

Owner: the BUY/SELL watch cards look accurate but the market feels choppy; can anything be
improved, and can a Telegram message go out when the indicators line up?

**Display + tooling only.** No `engine.py` / `trade_filter.py` change, no parameter, gate or
exit change; the struct-stop window and its 2026-10-19 judgement are untouched.

1. **Chop read** (`pressure.box_chop`, dashboard "🌊 Is the tape choppy?", `box_report` §4b):
   the false-break share of the engine's own 20-bar box, recent 24 h vs the span in view, plus
   efficiency ratio and box-width-vs-median. At the 14:59 snapshot: 14/18 breaks closed back
   inside within 15 min (78%) vs a 74% baseline — chop is **normal** — while efficiency is
   0.04/0.02 and the box is 3.0 ATR vs a 4.7 median, i.e. range-bound and compressed.
2. **Retest tracking** (`pressure.box_retest`): the last break on a box **frozen at the break
   bar**, classified extended / retesting / held / failed, rendered on both watch cards. 94% of
   breaks are retested within 30 bars (median 3); 98% of touch-then-no-re-break were false
   breaks; entering the **held** retest measured 59.0% vs a 57.2% reference and the same
   −$0.31/trade as entering the break — a status read, **not** a filter. Supersedes the
   "retests are not tracked" line of 2026-10-20.
3. **Telegram notifier** (`tools/box_alert.py`, `deploy/boxalert.service`, optional): one
   rate-limited message when a fresh close beyond an edge lines up with every check, ≤10%-of-R
   geometry and no chase. Decision in `pressure.box_alert()`, limiter in
   `pressure.box_alert_suppressed/record` — pure, so the sidecar, the dashboard preview and the
   `box_report --alert-scan` replay share one implementation. Measured volume **5.1/day** over a
   7-day replay (30-min global spacing + 90-min per-edge cooldown + 6/day cap = spam control,
   not an expectancy claim). The dashboard previews the exact text and never sends it.

**Negative results recorded, including my own mistake:** a first pass on overlapping events
(6083) showed a clean 10 pp "chop filter" (62.9% vs a 54.6% reference, +$1.04/trade). Under the
repo's one-position convention (681 sequential breaks) it vanished and partly **reversed**
(choppy bucket 61.9% vs clean 60.0%), and the prior-trading-day version — which cannot
autocorrelate with its own outcome — pointed the wrong way too (51.1% vs a 55.1% reference).
Same trap as the 09-28 pooled-momentum error, so it is written down
(`docs/ANALYSIS-2026-10-21-box-chop-retest-alerts.md` §2).

Verification: `tools/test_box_alert.py` 22 pass (new); `test_box_watch.py` 6, `test_box_report.py`
14, `test_dashboard_context.py` 13 (Flask 3.1.3 in a local venv); `tools/smoke_test.py`
**SMOKE TEST PASSED** including Scenario U's `pressure.py` read-only AST check;
`box_report.py --alert-scan` runs clean on 47,379 bars (~22 s); `bash -n tools/autosync.sh` ok;
`handoff_check.py` FRESH, 0 advisory drift. **Not run:** a real Telegram send (no outbound
access to api.telegram.org in the sandbox) and nothing on the production host — installing the
sidecar and merging remain the owner's actions.

## 2026-10-21 (later) — `🔔 box alerts: not configured` was a wiring bug, not a missing pair

Owner: the 18:00 UTC digest said `🔔 box alerts: not configured (no TELEGRAM_BOT_TOKEN/CHAT_ID)` —
why?

**Ops/tooling fix only.** No `engine.py` / `trade_filter.py` / `pressure.py` / `dashboard.py` change,
no parameter, gate or exit change; the struct-stop window, its judgement and the gap-guard blocker
are untouched. Nothing was installed or changed on the host.

**Cause.** That digest was delivered *by* the Telegram pair it said was missing. `tools/autosync.sh`
reads the pair from `/opt/gold/.env` into its own **unexported** `TG_TOKEN`/`TG_CHAT` (enough for its
`curl`), then runs `python3 tools/box_alert.py --quiet` as a child — which inherited neither variable,
and `box_alert.py` (unlike `engine.py`, which `load_dotenv`s `/opt/gold/.env`) read only its
environment. 18:00 was the first run of the phase PR #49 added (merged 17:40, deployed 17:46; the
deploying run never runs a new phase, `docs/AUTOSYNC.md` §3). Reproduced with the real script in a
sandbox (cron-like empty environment, fake `.env`, stubbed `curl`/`systemctl`): the stub received the
digest *with the token*, and the digest's `🔔` line said `not configured`.

**Fix.**
1. `box_alert.py` reads its own keys (Telegram pair + `GOLD_BOX_ALERT*`) from `$GOLD_DATA_DIR/.env`
   (`GOLD_ENV_FILE` / `--env-file`), filling only what the environment lacks — never the feed's API
   key, never overriding a real variable. Autosync passes `GOLD_DATA_DIR=$GOLD_DIR`; no secret moves
   through argv or the child's environment.
2. The line now says whether the notifier is **running**: `--loop` stamps a heartbeat into its own
   `box_alert_state.json` each tick (not in `--dry-run`). Without this, the fixed line would have read
   `0 sent today · none sent yet` on a box with no unit installed — a healthy-looking notifier that
   does not exist. States: `Telegram pair found · notifier not running (optional: install
   deploy/boxalert.service)` / `running · …` / `notifier STOPPED (last heartbeat …)` / `disabled` /
   `not configured (… in the environment or /opt/gold/.env)` (`docs/AUTOSYNC.md` §3).
3. Found on the way: `GOLD_BOX_ALERT_GLOBAL_COOLDOWN_MIN` was documented (unit + docstring) but never
   read, and the message footer always quoted the default limits. Both now follow the knobs (the
   decision itself cannot change — the limits only ride along).
4. `DecideOnceTests.test_it_decides_without_sending_when_nothing_lines_up` was already failing before
   this change: it read the **checked-in** log and assumed it ended 14:59 UTC; three data commits later
   the day's breaker blocked first. Rewritten on a synthetic tape (HANDOFF §7: never the live CSVs).

Verification: `tools/test_box_alert.py` **34 pass** (12 new, incl. a subprocess run of `--quiet` exactly
as autosync calls it; the new tests fail on the old code with the owner's exact line); `smoke_test.py`
**SMOKE TEST PASSED**; `py_compile` all; `bash -n tools/autosync.sh`; `check_data.py` 0 fail / 8 warn;
`test_box_report` 14, `test_box_watch` 6, `test_dashboard_context` 13 (Flask in a temp venv),
`test_signal_outlook` 9, `test_repair_phantom_ledger` 7. Sandboxed real `autosync.sh` (fixed) printed
each state: pair-not-running, running (a real `--loop` reading `.env` with nothing exported), STOPPED,
disabled, not configured; the token appeared in no output. **Not run:** a real Telegram send and
anything on the production host. After merge, the next autosync deploys it (tools-only: smoke gate
runs, engine not restarted; an installed box-alert unit is restarted).

---

## 2026-10-23 — Telegram routing: indicator alerts only, trade news in a twice-daily digest

**Ask.** "Staring at the screen until we get a go ahead to trade… I have many telegram messages, I may
miss out on this… maybe we limit the telegram messages for the indicators only, the rest on the auto
trade I possibly don't need for now." (Owner also chose: trade messages off entirely; digest twice a
day plus a trade summary; a watch plan at both London and NY open.)

**Measured first.** 10 trading days to 10-23: **36.8 skip notices/day** (45% of all traffic, one per
blocked bar during a cooldown or blackout), 14 entries, 14 exits, 4.1 `BE STOP ARMED`, 8 autosync
digests, ≈5.1 box-watch notices → **≈82/day, worst day 101**. The wanted message was ~6% of the chat.

**Changed (message policy only — no strategy, gate, exit, sizing or ledger change).**
1. `engine.py`: `send_telegram(text, kind=...)` with `TELEGRAM_KINDS = (trade, exit, skip, risk, feed)`;
   `GOLD_TELEGRAM_KINDS` selects which are sent. Unset/blank = **every message, unchanged**; `none` =
   silent; a typo falls back to everything so a typo can never silently mute the bot. Filtering is
   silent (no print flood) and the CSVs/status/journal are written either way.
2. `tools/autosync.sh`: `GOLD_DIGEST_EVERY_HOURS` (default 12, `0` = old 3-hourly) with the last-sent
   epoch in `GOLD_DIGEST_STATE`; **an incident bypasses the clock** (any `$EXTRA`, a rollback/failed/
   skipped deploy, a failed push) and is never silenced; routine digests go out with
   `disable_notification=true` so only incidents buzz; new `🧾 trades: N closed (2W/3L/2BE) | net $…`
   line computed read-only from `trades.csv` since the last digest.
3. Watch plan: `pressure.box_plan_next/box_plan_text/box_context`, `tools/box_alert.py --plan` (and
   inside `--loop`). One message after 07:00 and 13:00 UTC: where price sits, the two prices at which
   the instant notice would fire, the costed levels, what is blocking, ATR-percentile + tick-volume
   **context** (the two 10-23 audit hints — neither cleared the adoption bar) and the **0-of-8 no-edge
   footer**. Deduped per (date, session); nothing sent if the box slept through the window or the
   market is shut; `--no-plan` disables it.

**Result.** ≈82 messages/day → **≈7–9/day**, at most four of them unsolicited (2 plans + the measured
≈5.1 notices), and the chat is quiet unless something is wrong.

**Verification.** `smoke_test.py` **SMOKE TEST PASSED** (new Scenario X: default-unchanged, `none`,
explicit list, typo fallback, a filtered kind sends nothing, digest blocks, anchor windows,
dedupe/re-send/failed-send-retry/dry-run/weekend, plan text content); `test_box_alert.py` 34 pass;
`test_box_watch` 6; `check_data` 0 fail / 8 warn; `handoff_check` FRESH; `py_compile tools/*.py`;
`bash -n tools/autosync.sh`; the digest trade-summary block re-run against the live ledger at 12 h /
48 h / 500 h windows. **Not run:** a real Telegram send, the production host, or the box notifier
(not installed). Deploy: `engine.py` changed → `goldbot` restarts; the plan needs
`deploy/boxalert.service`. Revert is `.env`-only.

## 2026-10-23 (later) — v1 post-mortem, scalper removal, and the `goldbot/` v2 harness

**Trigger:** owner asked whether the bot can work at all "given gold's volatility", then
gave a free hand to redesign and to drop the scalper tab.
**Full write-up:** `docs/REDESIGN-2026-10-23-v2-harness.md`. **No runtime change** —
`engine.py`, `trade_filter.py`, `pressure.py` and `tools/strategy_lab.py` are byte-identical.

### The post-mortem (recomputed this session, collection 326)

The owner's doubt is right but the diagnosis is wrong, and the difference decides what to fix:

- **Volatility is not the cause.** Bucketed by ATR at entry, the *quietest* bucket is the
  worst on the board (<1.2 ATR: 14.3% decisive, n=18) and the most volatile is tied with it
  (≥2.0: 23.7%). Fisher: quiet p=0.080, volatile p=0.051; the one significant bucket
  (1.2–1.4, p=0.013) fails the side split (BUY p=0.294, SELL p=0.373). BUY vs SELL p=0.492.
  With 199 trades there is no establishable volatility↔win-rate relationship either way.
- **Volatility is a geometry problem.** Median risk $3.94 on a $4,000 instrument; the $0.55
  round trip is 14.0% of it, lifting the break-even decisive WR at 1:1.5 from 40.0% to
  **43.2%**. The escape hatch is timeframe: 19.5% of R on a 20-bar M1 box vs 2.1% on a 4h box.
- **Direction is what is fatal.** 49% [41–57] at 30 min after an 8/8 signal, and no exit
  geometry rescues it — the best cell in `tools/pathwalk_sims.py` is +$2.93 over 696 trades
  *gross*. Era arithmetic: gross −61.13, cost −109.45, net −170.58; **cost is 1.8× the gross
  loss**, and the BE bucket booked $0.00 gross while paying $29.15.
- Corrected in-session: an MFE walk put the ratchet's cost at $237.70, which is unsafe
  (MFE cannot say whether the target printed before the stop returned). The sequence-aware
  figure is **$230.80**.

### Removed (owner request + the measured reason)

`manual_scalp.py`, `scalp_template.py`, `docs/MANUAL-SCALPING.md`, `tools/test_manual_scalp.py`,
`tools/test_scalp_dashboard.py`, the four `/scalp*` routes, the nav link, and
`GOLD_MANUAL_JOURNAL_FILE`. `dashboard.py` 2,298 → 2,178 lines and now has **no write route
at all**. `tools/autosync.sh` `DASH_CHANGED` updated to `dashboard.py pressure.py chart.py
goldbot/` (the old pathspec named files that no longer exist).

### Built: `goldbot/` (1,942 lines incl. 548 of tests)

Modular, **pure stdlib** (this sandbox has no requests/dotenv/flask/pandas, so v1 cannot even
be imported here), no engine import, no order path. Four decisions carry the analysis:
timeframe is the primary knob (default H4); an explicit **cost floor that refuses and counts**
setups whose risk is under 20× the round trip (v1 had no such rule); the structural stop kept,
with each trade recording whether the *level* or the *ATR floor* bound; and the entry is a
**named hypothesis** (`trend_pullback`), not a claim of edge.

Two bugs the tests caught that would have shipped: `warmup_bars()` ignored the ATR period, so
ATR was `None`, every entry was refused with "no ATR", and the replay reported **zero trades
with a straight face**; and the costed break-even formula returned 0.4558 where the ledger
says 43.2% — the correct form is `p = (risk + c)/(risk·(1+rr) + c)`, and the shortcuts move
the bar by 2.4pp. Both pinned.

### First result — the wall, not the verdict

`python3 -m goldbot --compare` on the 52-day log: **4 trades** (3 at M15, 0 at H1, 1 at H4).
The cost thesis holds mechanically (3.9% → 0.5% of R vs v1's 14.0–19.5%), but the binding
constraint on v2 is **sample size**, so the large-N path (`mt5_history_dump.py` →
`history_to_log.py` → `--bars`) is the next real step, not a nice-to-have. §6 of the doc
pre-registers the bar (n≥100 decisive, Wilson lower bound over the *costed* break-even,
cost ≤5% of R, same direction within each side, chronological holdout, net R>0) before any
further tuning.

**Verified:** 64 `goldbot` tests OK; `tools/smoke_test.py` PASSED; `check_data.py` 0 fail;
`test_manual_chart.py` 32 OK; `test_box_report.py` 14 OK; `test_signal_outlook.py` 9 OK;
`handoff_check.py` FRESH. **Not verified here:** the Flask dashboard routes (no Flask in this
sandbox) — the excision was checked by `py_compile` and a zero-hit grep for `/scalp`.

## 2026-10-25 — "execute the plan": session refresh + duplicate trade #697 found (docs only, no runtime change)

Ran the plan's session-start checks on the collection-334 snapshot (data through 2026-10-23 20:57
UTC): `check_data.py` 0 fail / 8 warn; `handoff_check.py` FRESH after `--update`;
`check_structural_stop.py` **PASS at n=200** (0 inside level, 83.5% level-bound, +0.50 ATR
clearance, median risk 3.33 ATR); `check_gap_rides.py` still **3/2** (#595/#610/#687 — no
gap-through, no worse exit); `pressure_report.py` SCREEN MET on all five checks (SL/day 6.00, SL
share 45.00%, scratch 26.50%, gross −0.052R, decisive 37.93% [30.4–46.0]); `xm_quote_report.py`
**10/14** complete days, 1/2 weekends, median $0.55 (newest synced row 10-24 14:59:30, Saturday
frozen tick; 10-21 tick stall up to ~1 h noted for the host health check). The DST discriminating
window opened 01:00 UTC; no post-transition offset observed yet — next sync decides the rule.

**New finding — duplicate `Trade_Num` #697.** The synced ledger has two rows numbered 697: the
10-23 11:17 BUY (SL −$8.70) and the 10-23 15:15 SELL (TIME −$0.36, should be #698). Root cause is a
latent engine bug: `trades.csv` rows are written only at close, while `restore_open_trade_from_status()`
restores `current_trade_num` but **not** `next_trade_num` — after any restart with an open trade, the
next trade reuses the open trade's number. Same pattern as the long-standing #1/#2/#3 (09-04) and
#171 (09-15) duplicates. No current metric or judgement is affected (every tool is row-based; the
balance chain 137.02 → 136.66 and `status.json` agree), but the key is non-unique and the bug is
live on the host at the next restart-with-open-trade. Proposed: two-line engine fix (restore
`next_trade_num` from status.json, max with the CSV-derived value), a hermetic smoke scenario, and an
optional renumber of the SELL row — **none applied**; owner review pending. Record:
`docs/REVIEW-2026-10-25-duplicate-trade-number.md`.

Handoff snapshot + §1/§4/§5/§6 refreshed, replaced §1 archived to `docs/HANDOFF-HISTORY.md`,
`docs/EXECUTION-PLAN.md` re-based. Gap-guard blocker, $0.40 cost assumption and all §4 thresholds
unchanged. No engine, filter, parameter, gate or deployment change; no ledger modification; no PR
merge (owner is finalising the session).

## 2026-10-25 (follow-up) — stop-hunt mark-outs + stop-clearance grid replay (evidence only, no runtime change)

Owner hypothesis (delegated the decision: "no vast experience with chart or gold instrument —
help me make the decisions u see best"): price hovers at the stop level, tags it, and bounces
back; some traders place their stop slightly past the level the instrument suggests, to avoid
exactly that.

**Built.** `tools/stop_hunt_markout.py` — reproducible bounded 24 h mark-outs (observed bars
only, gaps never bridged; ratchet-risk reconstruction for rows where `Stop_Loss == Entry`).
`structstop1.5` clearance variant added to `tools/strategy_lab.py` (one VARIANTS entry;
`--calib-only` recall 99.8% unchanged; `smoke_test.py` PASSED).

**Mark-outs (era n=200).** 84% of SLs hovered ≤0.25R of the stop before printing (TP wins 13%,
BE 17%); 27% of SLs back at entry ≤15 m, 31% by 1 h, 12% never within 24 h; median hunt before
a ≤15 m bounce ≈0.17R (≈1.1 ATR past the tested level; p75 ≈2.1 ATR); 21/90 (23%) carry the full
SL→entry→TP signature (88% of the fast bounces). Counterweight: **29% of TP wins survived ≥0.5R
adverse movement** — the same adversity threatens winners, so the pattern alone cannot justify a
stop change (base rate vs cost decides).

**Grid (costed stateful replay, post-cutover era).** Net R/t by cost: at every cost 1.5 > 1.0 >
live 0.5 > 0.25 > old geometry (reconfirms 10-06 was the right direction). **structstop1.5 =
−0.000R/trade at registered $0.20/side, −0.023R at measured $0.275** (live: −0.102/−0.132) —
breakeven at registered cost, first positive-slope point in project history; decWR 43.1% vs
38.7%. Pre-declared bar (≥+0.05R at both costs, WR no drop, DD within 25%, n within 15%): 1.5
passes 3 of 4 — n 163 vs 207 (−21.3%) misses, mechanism disclosed (longer holds, 5 TIME vs 2);
still 10.2 trades/day. 1.0 ATR fails bar 1 (+0.026R) — measured-and-insufficient.

**Verdict.** NO live change. `structstop1.5` = **pre-registration candidate, not registered**
(one variable: `SL_CLEAR_ATR` 0.5→1.5; TP stays 1.5× actual risk; 10-05-style SCREEN/PASS/REVERT
bars drafted in the analysis). Sequencing: the fired §7 gap trigger keeps the owner's gap-guard
decision first in the queue; this is the next single variable after it, not a stack. Owner is
asked to decide (1) gap-guard a/b/c, (2) register the 1.5 ATR arm or not, (3) the 2-line
duplicate-#697 engine fix — in one sitting if preferred. No engine, filter, gate or runtime
change; no ledger modification; nothing merged.

Record: `docs/ANALYSIS-2026-10-25-stop-hunt-markouts-and-clearance-grid.md`.

---

## 2026-10-25 (post-merge autosync) — PR #58 deployed (`71317da`), DST-responsive gap-guard fix + docs reconciliation

**Trigger.** User merged PR #58 (`d38117a` at `02:39:37 UTC`: `8d84dcf` `#697` duplicate-number restore fix + `4d911fa` 30-min entries-only daily-closure gap guard), `autosync.sh` synced `data collection 335` (`7b2e2ea` at `02:48:08 UTC`) and deployed `71317da` (`autosync: merge upstream` at `02:48:12 UTC`) into the closed weekend market, and user asked to pick up where we left off.

**Baseline verification (`71317da` / `data collection 335`).**
- `check_data.py`: `0 fail, 8 warn` — `697` closed trades (`140W/301L/253BE/3TIME`, `31.7%` decisive, engine ledger `$136.66`, true equity `$119.70`, net `−$659.10` at `$0.20/side`), `50,494` log bars ending `2026-10-23 20:57:08 UTC`, `0` open trades (`status.json` `next_trade_num: 698`).
- `check_structural_stop.py`: `PASS` at struct-stop era `n=200` (`55W/90L/53BE/2TIME`, `0` stops inside level, `83.5%` level-bound, median clearance `+0.50 ATR`, median risk `3.33 ATR`).
- `check_gap_rides.py`: `3/2` post-cutover daily-break rides (`#595`, `#610`, `#687`), `$0` realized gap damage; `0 / 200` struct-stop entries (`7 / 697` all-book) fell in `[20:28, 22:00)`.
- `xm_quote_report.py`: `STALE` (~11.3 h old at `02:48 UTC` autosync — `xm_data/quotes-2026-10-24.csv` stopped at `2026-10-24 15:34:30 UTC`, `10/14` complete days, `1/2` weekends, median `$0.55/oz`); flagged `mt5quotes-gold` for host restart before Sunday's reopen.

**Owner decisions.**
1. **Stop geometry (`hold_for_dst`):** Keep `SL_CLEAR_ATR = 0.5` + deployed gap guard through Sunday reopen / Monday until the real post-DST broker offset (`+2h` EU vs `+3h` US) is observed; do not stage `structstop1.5` or revert to `2·ATR` in this step.
2. **Gap-guard DST responsiveness (`fix_dst_lag`):** Fix the 30-day modal DST lag in `derive_daily_closure()` now with hermetic smoke tests.

**Runtime hygiene refinement (`1c02b2c` on `arena/c5824a9f-gold-trading-bot`).**
- Updated `derive_daily_closure()` in `engine.py` (`GUARD_RECENT_SAMPLES = 5`, `GUARD_WEEKEND_MIN = 24 * 60.0`, `GUARD_DST_TOL_MIN = 2`) so the modal `(close_tod, reopen_tod)` baseline uses the last 5 daily breaks (converging within 3 breaks for any schedule shift while ignoring isolated mid-day feed outages) and shifts immediately on **Day 1** across a `±60 min` (`±2 min` bar jitter) Sunday weekly reopen / post-weekend daily break when `< 5` post-weekend breaks exist. Non-`±60 min` reopens (e.g. Monday `07:15 UTC` outage recovery) are ignored so feed outages never synthesize a false closure window. Added `_guard_closure_path` cache invalidation in `GoldEngine.guard_closure()`.
- Expanded `tools/smoke_test.py` Scenario Z with 7 hermetic checks covering EU/US fall-back Day 1 (`+60m` → `21:58–23:00`), spring-forward Day 1 (`−60m` → `20:58–22:00`), Monday outage reopen + Day 2 recovery across a Tuesday mid-day outage, and 3-break non-DST schedule convergence. `py_compile` + full `smoke_test.py` (Scenarios A–Z) **PASSED**.

**Docs updated.** `docs/HANDOFF.md` (`handoff_check.py --update` to collection 335, start-here note, era-timeline row, rewritten §1, §4 live table, §5, §6 items 0/1/3(h)/3(j)/6, §11 milestones), `docs/HANDOFF-HISTORY.md` (archived collection-334 §1 verbatim), `docs/PREREG-2026-10-25-gap-guard-daily-closure.md` (status header + §9 deploy & DST-refinement record), `docs/EXECUTION-PLAN.md` (baseline + timeline queue), `archive/PROJECT_LOG.md` (this entry).


## 2026-10-26 (post-merge autosync) — PR #61 deployed (`d4686f8`); first attempt rolled back, push "failed" (incident review, docs only)

**Trigger.** The 15:38 UTC digest: `🚨 deploy rolled back` + `⚠️ push to origin failed` (`data collection 351`, `smoke=not run (no code change)`, handoff `STALE +66.7 h`). User asked whether it was all good.

**Finding.** Two forced autosync runs ~80 s apart. Run #1 (`fde881a`, 15:37:50): `git merge` of PR #61 (`0f7f71e`, merged 15:33:21) failed → rollback → the push was a non-fast-forward by construction. Run #2 (`fd2746e` 15:39:09 → merge **`d4686f8` 15:39:13 = the cutover**): merged, smoke passed, engine + dashboard restarted, everything pushed. **No data lost** (bar log 0 gaps > 90 s, quote logger unbroken, ledger #704–#711 contiguous, digest numbers reproduce to the cent), credentials fine, the stale-handoff line was a consequence of the rollback.

**Verification.** `d4686f8`'s tree equals a clean re-merge of `fd2746e` + `0f7f71e`; replaying run #1's merge on a clean tree exits 0 (not a textual conflict); `smoke_test.py` 484/0; 218 unit tests OK; `check_data` 0 fail/8 warn; `check_structural_stop` PASS (n=214); gap-ride 3/2 unchanged; live gate CLOSED 9/8/3. `engine.py` AST diff vs `dc330a5`: 103/112 definitions identical, paper path unchanged (only `__init__` + `save_status` touch it: a fail-open read and the new `live_last_candle_ts: null` key). Startup of the real engine on the real data is identical old vs new; every `status.json` consumer accepts the key.

**Open.** Why run #1's merge failed is unconfirmed — `autosync.sh` discards `git merge` output and the rollback's `git reset --hard` erases the evidence. Sandbox reproduction with the real script: an uncommitted edit to a tracked *doc* (the hand-edit guard covers code paths only) yields the exact digest and a succeeding retry. The engine after the restart is not yet visible in the repo (next data commit 18:00) and a dead engine after a successful merge is **silent** (not an incident). Seven `autosync.sh` defects (D1–D7: misleading smoke label, discarded merge/push output, destructive `reset --hard` rollback, guard ignores docs, silent engine-down, redundant restart, cosmetic redirect) are proposed in the review, **none applied**.

**Docs updated.** `docs/REVIEW-2026-10-26-autosync-rollback-push-failed.md` (new), `docs/AUTOSYNC.md` (rollback-without-smoke row, real meaning of `push FAILED`, `ENGINE SERVICE NOT ACTIVE` row, "not an incident" note), `docs/HANDOFF.md` era timeline. No code, parameter, ledger or deploy change.

## 2026-10-27 ~12:00 UTC — G1 made answerable: owner decision pack + collection-359 refresh (**docs/tools display layer only; no strategy change, no deploy, no order**)

**Trigger.** Owner: “follow execution plan, shall we enable G1 presentation”. Per §0 the lowest-numbered step is **A1**, which is gated on **G1 owner sign-off** — a decision no agent session may make. So this session did the part it is allowed to do: verify the state, refresh every number the decision rests on, and write the pack that makes the question answerable in one line.

**Refresh.** Collection 359 (722 closed, 143W/315L/261BE/3TIME, 31.2% decisive, engine ledger $92.38, true equity $75.44, net −$713.36 at $0.40 RT; BUY #723 open). Era n=212 → **225**: decisive 37.5% → **35.8% [28.8–43.4]**, gross −0.054R → **−0.081R**, guard still PASS (0 inside, 82.2% level-bound, +0.50 ATR, 3.31 ATR median risk). Gap rides unchanged 3/2 with 0 gap-through / 0 worse exits. Quotes 11/14 → **12/14** days, 1/2 weekends, $0.55 median (144 matched trades). `check_data` 0 fail/8 warn, `handoff_check` FRESH, `--calib-only` 99.8%, `live_readiness` 9/8/3 CLOSED.

**Finding (host blocker cleared from data).** The first post-DST **daily** break is in the log: `2026-10-26 20:58:09 → 22:00:04 UTC` (61.9 min) and `derive_daily_closure()` returns exactly `(20:58, 22:00)` — the deployed guard schedule is right in the new regime and the ±60-min DST adaptation correctly did *not* fire. It had nothing to fix: the closure is anchored in **UTC**, not broker time (quote-sidecar freeze `20:59 → 22:00 UTC` on 10-22 at +3h and on 10-26 at +2h). This completes PREREG §2.3, the one pre-deploy engineering item that did not need the signature. No bar hole at the 10-26 break; the 10-25 Sunday-reopen hole is still a host task.

**Replay for the decision** (`strategy_lab --table`, post-cutover era; R/t per side $0.20 / $0.275 / $0.35): live `0.5` **−0.141 / −0.171 / −0.202**; `1.0` −0.126 / −0.154 / −0.181; `1.5` **−0.046 / −0.069 / −0.092**; literal §7 revert −0.155 / −0.202 / −0.249 (worst cell at every cost, ~66% of stops back inside the level). `1.5` vs live = **+0.095 / +0.102 / +0.110R**, decWR 36.5% → 40.3%, maxDD 230.2 → 180.0, SL/day 5.61 → 3.94, median risk 3.31 → 4.35 ATR, avg SL −$6.28 → −$8.20, hold 23.5 → 37.0 min, TIME 2 → 5, n 232 → 182 (−21.6%, the bar point that fails; the registered 10-25 score stays frozen at 3/4). Stated plainly in the pack: PASS needs ≈**48%** decisive WR at n=150 (Wilson LB > 40%), the replay's ordering bias favours deeper stops, and `1.0` is not a cheaper middle option.

**Shipped (no runtime change).** New `docs/BRIEF-2026-10-27-g1-owner-decision.md` (the G1 pack + the sign-off block). `docs/EXECUTION-PLAN.md`: new §2b refresh, A1 row now names the pack and drops the completed DST task, §4 history row. `docs/HANDOFF.md`: §1 rewritten (old block moved to `docs/HANDOFF-HISTORY.md`), era-timeline row, §5 evidence entry, §6 next steps. `readiness.py`: post-DST blocker closed, G1 blocker + `g1`/`window_15` timeline rows point at the pack and the timing slack; new milestone row. README doc table row.

**Verification.** `smoke_test.py` PASSED (A–Z + AA), 64 `goldbot` tests OK, 18 `live_readiness` + 16 readiness-tab tests OK, `py_compile engine.py trade_filter.py` OK, `handoff_check` **FRESH** after `--update`. Note for future sandboxes: `test_readiness_tab.py` needs Flask installed, otherwise `DashboardWiringTests` errors on import — an environment gap, not a repo defect.

**Open.** **G1 is the only thing between the plan and step A2.** The owner answers A (sign `structstop1.5`) / B (run the literal §7 revert) / C (hold, recorded with a reason). Signing unlocks the rest of A1 (register the draft verbatim, `strategy_lab.CLEAR15_CUTOVER`, the 1.5-ATR era splits in `check_structural_stop` / `win_rate_report` / `pressure_report` / journal, the smoke geometry assertion), then A2 deploys the one line. Every week of delay erodes the n=150 arm against the 2026-12-01 21:00 UTC date gate. `SL_CLEAR_ATR` is still **0.5**.

## 2026-10-27 ~13:17 UTC — **G1 SIGNED (branch A) → step A1 complete** (`structstop1.5` registered; tool work landed; **no deploy, no engine change, no order**)

**Trigger.** Owner answered the pack written earlier the same day: **approve (A) — register `structstop1.5`** rather than execute the literal §7 revert, and finish **all of A1** in this session with **A2 (the deploy) left as its own later step**.

**What "registered" was allowed to mean.** The draft became binding by changing its *status lines only* — the title, the `**Status:**` line, the §1 sign-off line (dated, quoting the owner's answer and nothing more), and the §2 pre-deploy task list ticking to done. §3–§7, where the numbers live, are byte-identical to the draft: `n≥100` SCREEN / `n≥150` or `2026-12-01 21:00 UTC` PASS with Wilson LB > 40%, `A1 = 0` stops inside the level, `A2 = median clearance ≥ 1.5 ATR`, `A3 ≥ −0.05R` at the assumed cost, `A4 70–90%` level-bound, `A5 3.8–5.0 ATR` median risk, B1 ≤ 6.0 SL/day, B2 ≤ 40%, B3 ≤ 35%, and the four revert triggers. A sign-off is not a licence to improve a bar while signing it.

**Registration guardrail that mattered.** Sign-off preceded any post-change trade — the last ledger row at sign-off was **#723 (BUY, still open under 0.5 ATR)** — which is the condition §1 itself imposed. Had a 1.5 ATR trade already existed, the registration would have been retroactive and inadmissible.

**Engineering (A1).** `strategy_lab`: `CLEAR15_ATR/CUTOVER/ERA` + `clear15_eras()` feeding `--table`. `check_structural_stop`: `--era {auto,struct,clear15}`, `geometry_class()` now classifies against the **judged** era's clearance and its predecessor's (a post-deploy trade would otherwise land in `???`), a new `A2 clearance` row that hard-FAILs on any level-bound trade under the bar, and a `NOT STARTED`/exit-0 path while the cutover is `None`. `win_rate_report`: second era book + `ERAS` row, inside the existing lazy-import guard. `pressure`/`pressure_report`: `BAR15` = the registered §5 transcribed, `era_stats()` made bar-driven (cost-aware R/trade, C3 PASS-arm row, per-bar revert wording, geometry + PASS gates), `build()["era15"]`, `--era clear15` with a `5b` card. `journal`: `--era clear15`. `smoke_test`: **Scenario AB** — patch *only* `SL_CLEAR_ATR`, and on Scenario N's tape assert risk = distance + 1.5·ATR, ≥1.5 ATR clearance, TP still 1.5× the actual risk, ratchet at 0.75R of the **wider** risk, a dip that stops the 0.5 ATR trade out leaving the 1.5 ATR trade alive, and delta-vs-live = exactly one ATR; then pin the constant back to 0.5 and assert the three judging tools refuse the unstarted window.

**Two traps found and closed while doing it.** (1) Defaulting `check_structural_stop --since` to the judged cutover silently emptied the historical era rows and the OLD/NEW boundary evidence — a cutover selects *which era is judged*, it must never narrow a report. (2) The first `era_stats(bar=BAR15)` implementation fell back to the **0.5 ATR era's** boundary when `CLEAR15_CUTOVER` was `None`, i.e. it would have "failed" a window that had not started; it now returns `None`. Both are the same failure class as the 2026-10-13 `LIVE_CUTOVER` erratum and both are now Scenario AB assertions rather than reviewer vigilance.

**Invariant checked, not assumed.** No tool's default *judgement* changes pre-deploy: `pressure_report --root .` §5 card byte-identical, `check_structural_stop` still 720 joined rows / PASS (with the new `[OK ] A2 clearance: median +0.50 ATR; 0/185 below it` line appended), `win_rate_report` and `journal --era structstop` (n_era=225) unchanged; `strategy_lab --table` gains a
three-line footer stating the 1.5 window is registered but undeployed, and no cell moves. A judgement that closed on 2026-10-19 must not acquire a new sentence because a later window was registered — an earlier draft of the read layer tried to make the §7 card say "short of the screen n", and that edit was reverted rather than shipped.

**Verification.** `smoke_test.py` **PASSED** (A–AB); `python3 -m unittest discover -s . -p 'test_*.py'` from `tools/` → **154 OK**; `py_compile engine.py trade_filter.py` OK; `check_data` 0 fail/8 warn (unchanged); `handoff_check` **FRESH** with 0 advisory drift (the §1 snapshot needed no `--update`: the numbers did not move, only the prose did). Simulated a deploy in-review (`CLEAR15_CUTOVER = 2026-10-27 06:00`) to prove the `5b` card renders its own B/C/A/R rows, then discarded it — no repo file carries a deploy time.

**Docs.** `docs/REVIEW-2026-10-27-g1-decision.md` (decision, evidence, and the A2 contract), PREREG status/§1/§2, `docs/EXECUTION-PLAN.md` §1.3 gate + A1 row **DONE** + A2 row rewritten as the next eligible step + §4 history, `docs/HANDOFF.md` §1/era timeline/§5/§6, README PREREG row, `readiness.py` timeline (`g1` → done, new `a2` row, `window_15` clock starts at the deploy) with `tools/test_readiness_tab.py` moved to match (16 OK).

**Open.** **A2**: one line, in a window where the host shows no open position, and the deploy's own `autosync: merge upstream` commit time becomes `CLEAR15_CUTOVER` in the same change — nothing else in Track A can start before it. G2 (cost sample 12/14 days, 1/2 weekends at the time of writing) and the two host items (Sunday-reopen bar hole, DEMO evidence) are unaffected by this decision. `SL_CLEAR_ATR` is still **0.5**, and that is the intended state until A2 lands.

## 2026-10-28 — B2: the LIVE path gets the same exits as paper (broker-side BE ratchet + 240-min time stop)

**Session prompt:** “Follow execution plan.” Ritual run on **collection 370** (737 closes, era n=240):
`check_data` 0 fail/8 warn, `handoff_check` FRESH(2)→FRESH(0) after the refresh, `check_structural_stop` **PASS**
(0 stops inside the level, 82.5% level-bound, +0.50 ATR clearance, 3.33 ATR median risk), `check_gap_rides` 3/2
with 0 gapped through / 0 worse exits / 0 weekend rides, `pressure_report` era **35.5% [28.7–42.9] decisive,
−0.078R gross** (B1/B2/B3/A4/A5 OK, C1 OK, **C2 FAIL** vs its 36.0% baseline — recorded, never re-judged),
`xm_quote_report` **13/14 complete days + 1/2 weekends** at a $0.55 median round trip, `live_readiness`
**9 PASS / 8 TODO / 3 MANUAL**.

**A2 was correctly not run.** Its only remaining condition is a host action: the one line
`SL_CLEAR_ATR 0.5 → 1.5` must land while the host has **no open position**, and the era boundary is the host's own
`autosync: merge upstream` commit time. The 18:54:49 UTC snapshot is flat, but the deploy fires from the host's
`0 */3 * * *` cron, which this session can neither see at that minute, push `main` for, nor restart. Reported as a
blocker instead of faked; `SL_CLEAR_ATR` is still **0.5** and `CLEAR15_CUTOVER` is still `None`.

**B2 (Track B, explicitly parallel): decision recorded before coding.** `docs/DECISION-2026-10-28-b2-broker-be-and-time-stop.md`
applies the plan's default — implement the broker-side mirror rather than register a divergence, because
`BE_TRIGGER_R = 0.75` and `MAX_HOLD_MINUTES = 240` are frozen variables of the open experiment and a LIVE book
without them is a *different* strategy whose evidence can never transfer.

**What the gap actually was.** Both rules lived only in engine state: `_arm_breakeven()` mutated `self.stop_loss`
and sent a message but never touched the broker; `_maybe_time_stop()` was reachable only from `check_position()`
(ticks) and `resolve_open_trade_on_candle()` (MT5 paper feed), and `run_live()` calls neither. Worse, a confirmed
LIVE fill recorded only the trade number — not `trade_active`, entry, stop, target or time — so even a reachable
rule had no position to act on.

**Shipped (LIVE path only; paper byte-identical).** `execute_live_trade` now records the filled position (ticket,
sizing risk, entry/SL/TP, entry time and context) and persists it before the next loop pass; `run_live` calls
`live_manage_open_position()` on every 5-second pass, which (a) sends `TRADE_ACTION_SLTP` to move the stop **to
entry** once the trade is +0.75R ahead and (b) closes at market by ticket once it is 240 minutes old, booking the
exit through the **same** `_maybe_time_stop()` the paper path uses — one ledger row, one counter, one message.
Booked only after `TRADE_RETCODE_DONE`; one retry only for market-moved rejects (requote / price changed / price
off / timeout / connection), never for logic rejects; the stop can only tighten and only arms once; if the broker
already holds `sl == entry` after a restart it is adopted rather than re-sent; management still runs while the
process is **disarmed** (both actions reduce risk — a kill switch must not orphan a position); if the broker no
longer holds the ticket, **nothing is invented** (no exit price, no P&L — that is B3), one loud alert fires and
`live_reconcile_pending` blocks new LIVE entries until it is reconciled.

**The scorecard was also made honest.** `broker_be` / `broker_time_stop` were substring checks — a docstring could
have turned them green, and a helper `run_live` never calls would have passed. They are now **call-graph** checks
(`_reachable`, `_calls`, `_uses_attribute`, `_uses_name`, `_dict_has_key`): evidence must be real AST usage on the
LIVE path. A unit test pins both failure modes.

**Verification.** `smoke_test.py` **PASSED** (A–AB unchanged, new **Scenario AC** 12/12 driving the real fill →
ratchet → 240-min close against a fake broker); `tools/test_live_manage.py` **19 OK** (new); `test_live_readiness.py`
**20 OK**; `goldbot/tests` **64 OK**; `test_readiness_tab.py` **16 OK**; `py_compile` OK; `check_data` 0 fail/8 warn;
`handoff_check` **FRESH (0 advisory drift)**; `live_readiness` **11 PASS / 6 TODO / 3 MANUAL, gate CLOSED**.

**What it does not prove.** No demo-account evidence (B5) — every check is source inspection plus hermetic fakes;
no deal-level reconciliation (B3) — a broker SL/TP exit is still not booked, the new flag only makes that loud and
blocks new exposure; single position only; and if the process is down when +0.75R or 240 min is crossed, only the
broker's own SL/TP protects the trade. The gate stays CLOSED.

**Next.** A2 (owner/host: deploy at a flat moment, then record the cutover), then **B3** — reconciliation, which
closes the one gap B2 deliberately left open.

---

## 2026-10-30 ~03:00 UTC — "should we increase the simulated equity?" (docs + one read-only tool; NO ledger edit, NO strategy change)

Owner asked, in a "follow execution plan" session, whether the simulated equity should be raised now that
`status.json` reads **$52.98** (true equity **$36.05**). Ritual ran on collection **381** (758 closed,
era n=261, SELL #759 open): `check_data` 0 fail/8 warn, `handoff_check` FRESH, `check_structural_stop` PASS,
`check_gap_rides` 3/2 (0 damage), `live_readiness` 11 PASS / 6 TODO / 3 MANUAL CLOSED.

**Answer: no top-up.** The paper book trades a fixed 0.01 lot (`size_lots()` returns `LOT_SIZE` with no broker
account), so the ledger number cannot move an entry, an exit, a lot, a parameter, R/trade, era DD or any
registered bar — only `engine_ledger_usd`, which `handoff_check`'s money rule correctly treats as a ledger edit
(the 2026-09-09 reset erased $24.74 of real losses and left the $16.93 drift still visible today). Increasing it
buys no statistical power and hides the one number that is honest about a −0.170R/trade net era.

**What the question did expose:** there is **no balance floor** and, at −$0.94/closed trade and 13.1 trades per
active day, **≈38 trades ≈ 2.9 trading days** of runway (bootstrap 90%: 33–336 trades; 6% of draws have no burn
at all). Registered — before the event, so it cannot rescue a bar — a **rebaseline-at-zero** rule: no edit while
true equity > $0; at the first trade that leaves it ≤ $0, archive the book, keep every row and trade number,
rebase the ledger to $500, publish one marker + a dated REVIEW, and change **nothing** else (R/trade, era DD and
the PASS/REVERT bars are computed from per-trade P&L and are untouched; it is not a new era and must never be
called a fresh $500 test).

**Shipped:** `tools/equity_runway.py` (read-only: ledger vs true equity vs drift, era R/trade and $ burn,
runway + bootstrap, policy state; `--json`, `--strict`) and `tools/test_equity_runway.py` (**18 OK**, hermetic,
pins reward-leg risk recovery, drift reporting, no-write side effects and the exact fire point); decision doc
`docs/ANALYSIS-2026-10-30-simulated-equity-and-paper-runway.md`; plan §1 guardrail + §2d; handoff §1/§6 + snapshot.

**Unchanged:** `SL_CLEAR_ATR = 0.5`, every frozen constant, `TRADING_MODE = "FORWARD_TEST"`, the ledger, every
row of `trades.csv`, the deploy and the host. **No order, gate CLOSED.** **A2 remains the next eligible step and
is blocked right now by open SELL #759** (it needs a flat host); Track B is at **B3** (reconciliation).
