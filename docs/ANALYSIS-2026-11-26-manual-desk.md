# ANALYSIS 2026-11-26 — “Follow execution plan”: ritual refresh, B5 feed precondition, and a Manual desk for the owner's own trading

**Status:** dated session record. **Paper-only; display-only.** No strategy variable, registered cost, ledger row, engine/trade_filter path, broker connection, host action, arming or real order. The phrase's authority (`docs/EXECUTION-PLAN.md` §0) covers analysis, tools, tests, docs, PRs and pre-registered merges — this session ships tools/docs/dashboard-only work and merges it with the owner's explicit “proceed to merge”.

**Owner ask (this session):** *“Please follow execution plan and proceed with improvements, if theres anything that can be helpful, when we ate also manually trading, please help include anything that can be helpful . Proceed to merge”*.

**Canonical queue:** `docs/EXECUTION-PLAN.md`. **Current state:** `docs/HANDOFF.md`. Dated pre-registrations/reviews still own every experiment threshold; nothing below re-opens a closed judgement.

---

## 0. Session ritual (§5), on collection 598 — log through `2026-11-26 14:59:08 UTC`

| Check | Result |
|---|---|
| `git status --short` / `git log --oneline -3` | clean branch `arena/2f8166e1-gold-trading-bot` at `1474cd0` (`main` base); no open PR at session start |
| `tools/check_data.py` | **0 fail / 9 documented warnings** (unchanged warning classes: duplicate Trade_Nums, balance continuity, long holds, ledger drift, 148 price-log gaps, 12 trades across a gap, 2 unjoinable entry rows) |
| `tools/handoff_check.py` | **STALE by 66 closed trades / +137 h** → `--update`; the machine snapshot is now FRESH at 1,064 closes, era n=567, 81,815 bars |
| `tools/check_structural_stop.py` | **PASS**: struct-stop era n=567, **0** stops inside the level, 81.7% level-bound, +0.50 ATR median clearance, 3.10 ATR median risk; deploy boundary still bracketed by #498 (OLD) / #499 (NEW) around `2026-10-06 03:00 UTC` |
| `tools/check_gap_rides.py` | **9** post-cutover scheduled-closure rides (threshold 2): 1 reopen gapped through the stop, **0** exits worse than the stop, 4 scratch stops, 0 weekend rides. Recorded, not re-judged |
| `tools/pressure_report.py --root .` | era n=567, decisive **36.8% [32.3–41.6]**, gross **−0.034R/trade**, SL/day 6.02, SL share 45.68%, scratch 27.16%, avg SL $6.20, era DD $207.87; bar card B1/B2/B3/C1/C2/A4/A5 **OK**, R4/R5 clear. Grown-sample observation only — the 10-19 judgement stays closed and the lapsed n=150 arm stays lapsed |
| `tools/xm_quote_report.py` | **41/14 complete UTC days, 5/2 weekends**; 486 matched trades, measured round trip mean/median **$0.55**, p90 $0.57, max $1.66; offsets +2h/+3h, EU rule fits 100.00% of 85,694 rows; spec captured `2026-11-26 13:57:01 UTC`: **REAL**, 1:1000, build 6230, **IOC only**, volume min 0.01 / step 0.001 / max 50, spread 56 pts |
| `tools/live_readiness.py` | **17 PASS / 0 TODO / 3 MANUAL — LIVE GATE CLOSED** (cost model, DEMO evidence, independent edge) |
| `tools/cost_model.py` | all-in default re-cost: whole book net **−$1,048.14** vs **−$867.35** at the registered $0.40; **the book is negative before costs** (gross −$441.75). Diagnostic only — no registered bar re-read |
| `tools/equity_runway.py` | true equity **$58.25**, era burn −$0.74/closed trade at $0.40, 13.2 trades/active day → ≈79 trades / ~6.0 trading days to $0.00 (bootstrap 90% 74–1038). Signed **“no rebaseline ever”** policy unchanged; the ledger is a counter, not capital |
| `tools/feed_forensics.py --days 14` | **no hole of 10+ expected-open minutes in the trailing 14 days** — see §2 |
| `readiness.py` | gate CLOSED; cost-basis row binding $0.40, $0.57 from 2026-12-01 |

**The book:** **1,064 closed** (236W/470L/354BE/4TIME; **33.4% decisive [30.0–37.0]**), engine ledger **$75.18**, true equity **$58.25**, net **−$867.35** at the registered $0.40 round trip. No open trade (`next_trade_num: 1065`). **No demonstrated edge after costs.**

**Snapshot caveat, stated rather than smoothed:** the checked-in data ends at `14:59 UTC` while the session ran at ~15:30–16:00 UTC, so a freshness check on this clone prints `STALE ~55 min` and the Manual desk's feed row reads **BLOCK**. That is the **collection boundary**, not a host outage — the exact mistake `docs/ANALYSIS-2026-11-12-b4-live-order-safety.md` made from a logger row count and that `docs/ANALYSIS-2026-11-22-feed-holes-november.md` corrected. `feed_forensics.py` uses the *other* feed as the witness and never treats a snapshot's age as an outage.

---

## 1. Step selection — why this work, and what was NOT done

§6 precedence: **rule 1 (data integrity / feed outage) comes first**. The 45-day `feed_forensics.py` still shows the three November `BOTH FEEDS DOWN` outages (11-04 676 open min, 11-05 26 min with **#819 open**, 11-06 425 min) plus two Sunday `PRICE-FEED ONLY` holes; #819 stays **not judgeable** on bar data. None of them is new, and no expired time gate exists (the registered date gate is 2026-12-01 21:00 UTC).

Then the lowest-numbered eligible queue steps:

- **A2** (`SL_CLEAR_ATR 0.5 → 1.5`, G1 signed 2026-10-27) is still blocked on a **production-host flat-position check at deploy time**. The local book is flat, which is explicitly *not* host evidence. **Not done; not faked.**
- **B5** (DEMO-account evidence) is a **host/operator action**: `docs/DEMO-EVIDENCE.md` does not exist and cannot be produced from this checkout. **Not done; exact blocker reported.**
- **A6** is DONE (analysis 11-22, owner decision 11-22). Its only remaining action — writing $0.57 into the *next* window's pre-registration — cannot happen before 2026-12-01.
- **A8** is research-only, parallel, and explicitly *“No bot behaviour change”*: a private manual observation log for the owner's pressure/hold hypothesis. Its stated blocker is that **the manual rule is still undefined** — ask the owner before coding it.

So the safe work that *is* possible from this checkout, and which the owner explicitly asked for (“when we are also manually trading … include anything that can be helpful”), is **A8-supporting tooling**: surface the repo's measured placement/risk context in one display-only screen, ship the private §7 observation template, and finally close the deferred Chart-tab item (draw the bot's open paper trade). **No manual rule is implemented, judged or registered** — the A8 blocker is preserved and named in the tool's own output.

**One step, one variable:** no strategy variable was touched. This is not a second variable stacked on the open `structstop1.5` window.

---

## 2. §6 finding — B5's feed precondition is now MET on checked-in data

`docs/EXECUTION-PLAN.md` §2g / `docs/HANDOFF.md` §6 added a precondition to B5: *“a 48 h run needs a feed that survives 48 h … `python3 tools/feed_forensics.py` is the acceptance test”*; the HANDOFF wording is *“no `BOTH FEEDS DOWN` row in the trailing 14 days”*.

On this snapshot:

```
python3 tools/feed_forensics.py --days 14
  → no hole of 10+ expected-open minutes in this window
```

The three November outages are now **older than 14 days** (11-04/05/06 vs 11-26), and no new hole appeared from 11-12 → 11-26. Price bars run to `14:59:08`, fresh quotes to `14:59:30`, lag 0.4 min. Therefore **the registered data precondition for B5 is MET on the checked-in window**. This is a *data* fact, **not host proof**: restart durability must still be verified by the operator, and the 48 h DEMO run is the real test. B5 remains blocked on the host/operator action; `live_readiness.demo_evidence` stays MANUAL. `readiness.py`'s blockers and the `demo` timeline row were updated to say exactly this, so the display does not imply either that the host is fixed or that the precondition is still failing.

---

## 3. What shipped — a display-only “Manual desk”

### 3.1 `manual_desk.py` (new, stdlib-only, read-only)

Same contract as `pressure.py` / `chart.py` / `readiness.py`: **no engine import, no file write, no order path, no wall-clock-dependent test, no strategy variable**. It takes the dashboard's existing `ctx` (pressure read) and `status.json` and returns one JSON-safe brief:

1. **The bot's open PAPER position** — side, trade number, entry / stop / target, risk, reward, R:R, ratchet (`SL == entry`) state, age, minutes left on the 240-min TIME stop, and the registered cost as a share of 1R. Half-written/malformed `status.json` rows are reported unusable rather than coerced into plausible levels. A ratcheted stop is folded into the entry label so two labels never share a price.
2. **A conditions checklist** read back from the engine's own gates: fresh feed, ATR band 1.10–4.50, direction-aware blackouts (London BUY-only is a WARN, not a both-sides BLOCK), escalating SL cooldown, daily-loss breaker, closed market / daily break, spread as a share of the tighter structural stop's R (≤10% OK, >20% mirrors B4's veto as *advice*), and the manual one-position rule when the bot is already in a paper trade. Missing reads are `unknown`, **never green**. The verdict is only about conditions — `SIT OUT` / `CAUTION` / `CONDITIONS READ OK — still no demonstrated edge` — and **never says buy or sell**.
3. **Cost & break-even arithmetic**: decisive break-even WR at 1:1.5 is 40% uncosted, **42.67%** at the $0.40 registered round trip on a $6 stop, **43.65%** with the book's ~27% scratch share (cost is charged on *every* entry, including scratches), 43.8% at $0.57. The cost ruler shows spread-as-%-of-R for 1–4 ATR stops (at ATR $2.43, a 1-ATR stop pays 23.5% of R at the all-in figure — “too tight”).
4. **The registered-cost freeze is enforced in code**: `cost_basis()` keeps **$0.40 binding now** and **$0.57 deferred to the NEXT window from 2026-12-01 21:00 UTC**, even when the injected clock is past that date — the next window's pre-registration must state the number before its first trade. No net figure is re-stated at $0.57 as if it were the bar (§2h).
5. **The private §7 observation template**: all 23 fields verbatim from `docs/EXECUTION-PLAN.md` §7, plus the seven rules (one row per event including losses and non-overrides; keep bot/manual separate; timestamp before looking at recovery; a later target touch is a **counterfactual mark-out, not a win**; ≥100 matched post-stop observations before any exploratory screen; then a NEW dated pre-registration, never an engine gate; keep the file outside Git with no identifiers). **Header only** — the module contains no journal reader or writer, and `manual_observations*.csv` is git-ignored.

### 3.2 `tools/manual_desk_report.py` (new CLI, read-only)

`--root DIR`, `--json`, `--template`. `--template` prints the header and rules only, with no data read. Named `*_report.py` (like `pressure_report.py` / `box_report.py`) deliberately: a `tools/manual_desk.py` would shadow the root module whenever a tools script imports the dashboard — that shadowing bug was found and fixed during this session's dashboard render test.

### 3.3 Dashboard: 🧾 **Manual desk** tab (`?tab=manual`)

One screen, display-only: verdict card → the bot's open paper position → 8-row checklist → cost/break-even + cost ruler → private observation header → measured context + honesty footer. Deep links (`?tab=manual`) work; the 15-second meta-refresh keeps the selected tab (TABS array updated and pinned by `tools/test_dashboard_context.py`). The nav hint and JS tab list were updated.

### 3.4 The deferred Chart-tab item is closed

`chart.view(..., extra_levels=...)` now draws the bot's **open paper trade** as three labelled lines: white entry, rose stop, emerald target; off-range prices are pinned to the edge rather than dropped; open-trade lines are never merged by price with box levels (an entry on a box edge is two facts). `dashboard.chart_context()` passes `manual_desk.open_levels(status)` and includes the open-trade signature in its cache key, so a fresh open/close rebuilds the chart without waiting for a new log row. This was the open item in `docs/HANDOFF.md` §6 (“whether to draw the bot's open paper trade … on the chart”) and the deferred row in `docs/PROPOSAL-2026-10-23-manual-chart-tab.md` §0. The current book is flat, so synthetic statuses prove the overlay; nothing is drawn on a flat book.

### 3.5 Ops + hygiene

- `tools/autosync.sh`: `manual_desk.py` added to the dirty-tree guard and to `DASH_CHANGED`, so a future edit restarts **the dashboard only** — never the engine. `engine.py` / `trade_filter.py` are untouched, so this merge triggers no engine restart.
- `.gitignore`: `manual_observations*.csv` — filled manual rows can never be committed.
- `readiness.py`: dated 2026-11-26 milestone + the B5/feed blocker wording from §2.

### 3.6 What was deliberately NOT shipped

- **No manual rule.** The owner's pressure/hold hypothesis is still undefined; A8's blocker is stated in the tool's own rules, not resolved. No screen, no gate, no pre-registration.
- **No journal writer, no write route, no unredacted rows in Git** (the `/scalp` workspace was removed at the owner's request on 2026-10-23; this does not bring it back).
- **No signal, no forecast, no “buy/sell”, no score.** The verdict is conditions only, and the footer repeats that the book is negative even at $0.00 cost, that the 8/8 signal is a coin flip, that 0 of 8 box geometries cleared the driftless reference, and that the pressure gauge is collinear with side.
- **No `SL_CLEAR_ATR` change, no `TRADING_MODE` change, no `GOLD_LIVE_ARMED`, no ledger edit, no cost re-basing, no second strategy variable, no host edit, no real order.**

**One historical-doc correction:** `docs/ANALYSIS-2026-10-20-box-theory-manual-trading.md` §4 rule 7 and `docs/PROPOSAL-2026-10-23-manual-chart-tab.md` still told a manual trader to skip `20:58–22:00 UTC`; the observed broker break has been `21:58→23:00 UTC` since 2026-11-02. Both dated docs were annotated with the current schedule and directed to `engine.derive_daily_closure()` rather than silently rewriting their historical measurement context. The Manual desk itself reads the display layer's blackout window / closed-market row and never hard-codes a stale break.

---

## 4. Verification (all hermetic unless noted)

| Test / check | Result |
|---|---|
| `tools/test_manual_desk.py` | **29 OK** — mirrors pinned to `pressure.py`, no engine import / no `open(` in the module, geometry/ratchet/time-stop, malformed status, $0.40 freeze past 12-01, break-even + scratch arithmetic, all 8 checklist states, JSON-serialisable brief, §7 fields/rules, CLI template/text |
| `tools/test_manual_chart.py` | **35 OK** (+3: extra levels get pixel `y`, no merge with box levels, off-range pinned, invalid prices dropped, flat book draws nothing) |
| `tools/smoke_test.py` | **A–AD + new Scenario AE PASSED** (10 checks: mirrors vs engine/trade_filter, no writer, conditions-only verdict, cost freeze, break-even, stale feed blocks, 23 §7 fields, open-trade overlay, flat book, no strategy change) |
| `tools/test_dashboard_context.py` | **19 OK** (+2: `?tab=manual` render, open-trade overlay in `chart_context`) — Flask installed into a local, git-ignored `.venv` for this checkout |
| `tools/test_readiness_tab.py` | **16 OK** (with Flask) |
| `tools/test_live_readiness.py`, `test_live_manage.py`, `test_live_safety.py`, `test_cost_model.py`, `test_feed_forensics.py`, `test_box_report.py`, `test_box_alert.py`, `test_manual_chart.py`, `goldbot/tests` | **25 / 25 / 28 / 19 / 13 / 14 / 35 / 35 / 64 OK** — full re-run after all edits; see §7 of `docs/HANDOFF.md` |
| `python3 -m py_compile engine.py trade_filter.py chart.py manual_desk.py dashboard.py readiness.py tools/*.py` | OK |
| `tools/check_data.py` after the code change | 0 fail / 9 documented warnings |
| `tools/live_readiness.py` after the code change | **17 PASS / 0 TODO / 3 MANUAL, CLOSED** — no check changed status |
| `tools/handoff_check.py` after `--update` + prose | FRESH |

**AST fact:** no function in `engine.py`, `trade_filter.py`, the paper path or the LIVE order path changed. The only runtime-adjacent edits are `dashboard.py`, `chart.py`, `readiness.py`, `manual_desk.py`, `tools/autosync.sh` (display restart list) and `.gitignore` — all display/ops, none on a trading path.

---

## 5. Next eligible step and the exact blockers

1. **B5 (DEMO-account evidence)** remains the lowest-numbered open Track-B step and is **host/operator only**: a DEMO account + separate data dir, fill/SL/TP/BE/time/rejection/disconnect/restart/reconciliation, and a 48 h stable run written to `docs/DEMO-EVIDENCE.md` (file does not exist). **New this session:** its feed precondition is MET on the checked-in 14-day window (§2); that does not replace host restart verification or the 48 h run.
2. **A2** independently awaits a verified flat **host** at deploy time; the local flat ledger is not that evidence. At deploy, set `CLEAR15_CUTOVER` from the host's `autosync: merge upstream` commit time.
3. **A6's next action** (write $0.57 into the next window's pre-registration, before its first trade) cannot happen before **2026-12-01 21:00 UTC**.
4. **A8's owner question is still open:** define the manual pressure/hold rule (what counts as an eligible signal/stop event, what the manual entry/exit decision is, and the contemporaneous reason codes) before any rule is coded or judged. The desk implements the *record*, not the rule.
5. **G2** (real money) is never delegated to “Follow execution plan”.

**Verdict unchanged: no demonstrated edge after costs — the book is negative before costs.** Remain paper-only.

---

## 6. Files changed this session

`manual_desk.py`, `tools/manual_desk_report.py`, `tools/test_manual_desk.py`, `chart.py`, `tools/test_manual_chart.py`, `dashboard.py`, `tools/test_dashboard_context.py`, `tools/test_readiness_tab.py` (unchanged; run), `tools/smoke_test.py` (Scenario AE), `readiness.py`, `tools/autosync.sh`, `.gitignore`, `README.md`, `docs/EXECUTION-PLAN.md` (§2i + queue/ritual/§7), `docs/HANDOFF.md` (snapshot + §1/§4/§5/§6/§7/§9/§10/§11 + era timeline), `docs/HANDOFF-HISTORY.md` (superseded §1), `docs/ANALYSIS-2026-10-20-box-theory-manual-trading.md` and `docs/PROPOSAL-2026-10-23-manual-chart-tab.md` (dated daily-break wording annotated as pre-DST; no historical conclusion rewritten), `archive/PROJECT_LOG.md`, this doc.
