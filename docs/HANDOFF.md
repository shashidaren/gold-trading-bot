# HANDOFF — current state and operating rules

**One-line prompt for a new session:** **“Follow execution plan.”** (“Execute the plan.”
is the exact older alias.) Read `docs/EXECUTION-PLAN.md` first — its opening section states exactly
what the phrase authorizes, the two hard approval gates (G1 = pre-registration sign-off,
G2 = real money) and the session ritual. Then use this file and the live repository data to
verify the current state before acting. The phrase never authorizes real orders, a switch to
LIVE, bypassing a pre-registration or stacking strategy changes. Exact experiment thresholds
remain in their dated pre-registration/review documents; this handoff or the plan must never
replace or relax them.

Keep it current: every session that changes code, params, or conclusions must
update §1, §4/§5 and §6 before it ends (see §11 "How to keep this file
honest"). §11 also carries the **Session & Push Protocol** — push every commit
immediately and keep the session PR open until the user signs off. Follow it
from the first commit.

### Snapshot (machine-checked)

<!-- HANDOFF-SNAPSHOT machine-checked by tools/handoff_check.py; refresh with --update -->
| key | value |
|---|---|
| as_of_utc | 2026-10-30 02:59 |
| data_collection | 381 |
| closed_trades | 758 |
| outcomes | 150W/334L/271BE/3TIME |
| decisive_wr_pct | 31.0 |
| engine_ledger_usd | 52.98 |
| true_equity_usd | 36.05 |
| cost_usd_per_side | 0.20 |
| net_pnl_usd_at_cost | -767.15 |
| cutover_utc | 2026-10-06 03:00 |
| structstop_era_trades | 261 |
| structstop_era_outcomes | 65W/123L/71BE/2TIME |
| log_bars | 56190 |
| log_last_bar_utc | 2026-10-30 02:59 |
| skip_rows | 1793 |
| open_trade | SELL #759 @ 4001.31 |
<!-- /HANDOFF-SNAPSHOT -->

This block is the **only machine-checked part of the file**: `python3 tools/handoff_check.py`
recomputes every key from `trades.csv` / `forward_test_log.csv` / `status.json` and says
**FRESH** or **STALE** (tolerance 30 closed trades / 48 h — about two trading days at gold's
10–18 trades a weekday). Autosync prints the verdict in every digest (`📝 handoff:`), advisory only.
`python3 tools/handoff_check.py --update` rewrites the block and nothing else; the prose numbers in
§1/§4/§5/§6 still have to be rewritten by hand (§11). **Numbers convention:** the ledger and every
P/L in the prose are **gross of costs** unless the line says `net` — the paper engine books no
spread. `net_pnl_usd_at_cost` charges the assumed `cost_usd_per_side` on every trade, scratches
included (the same model as `strategy_lab.py`); that cost is **assumed pending a sufficient measured sample** — the active quote logger (`docs/XM-LOGGER.md`) must meet its 14-day/two-weekend sample target before it can inform a replacement (§6).
`cutover_utc` must equal `strategy_lab.LIVE_CUTOVER` — the check fails if the doc and the tool
disagree about when the structural stop went live.
**The check now covers the file's structure too (2026-10-15):** every `## 1.`–`## 11.` section must be
present, no placeholder markers are allowed, and every `§N` reference must resolve to a section — because on
10-15 the daily doc job truncated the file to its front matter and the freshness check, reading only the
snapshot block, still said FRESH.

### Start here (30 seconds)

The canonical session queue and its ritual are in `docs/EXECUTION-PLAN.md`
(“Session ritual”). The owner's one-line prompt is **“Follow execution plan.”**; run that
ritual before drawing any conclusion. The list below is the detailed version.

1. Read **§1** (stance + numbers) and **Definitions** below it.
2. Run integrity + era report:
   ```bash
   python3 tools/check_data.py          # expect "0 fail"
   python3 tools/handoff_check.py       # is THIS file still true AND still whole? STALE -> `--update`, then rewrite §1/§4/§5/§6 (§11)
   python3 tools/win_rate_report.py
   python3 tools/momentum_regime.py     # regime/side + the 09-28 hypothesis & its bar
   python3 tools/check_structural_stop.py   # struct-stop guard: must PASS (it also proves the deploy boundary)
   python3 tools/check_gap_rides.py     # §7 closure-gap revert trigger: the count + the damage facts
   ```
   **Read §1 first**: the structural-stop time gate was judged at **2026-10-19 21:00 UTC** using the
   latest then-available snapshot (through 18:10 UTC, n=139). Geometry and SCREEN pass, but PASS does not
   (n<150; Wilson LB 28.8% ≤32.1%). The **§7 closure-gap trigger FIRED at 2/2** under the counting
   rule in `docs/REVIEW-2026-10-19-struct-stop-judgement.md` §3 (**now 3/2** after #687; the registered
   judgement and response are unchanged). Its registered response is REVERT with the gap guard first;
   **PR #58 (`d38117a`) registered and implemented the 30-min entries-only gap guard + `#697` duplicate-number fix,
   and `autosync` (`71317da`, 2026-10-25 02:48:12 UTC) deployed both into the closed weekend market**
   (`docs/PREREG-2026-10-25-gap-guard-daily-closure.md`). **Owner decision (2026-10-25 post-merge):**
   hold stop geometry on `SL_CLEAR_ATR = 0.5` + gap guard through Sunday reopen / Monday until the
   post-DST broker offset (`+2h` EU vs `+3h` US) is observed in real rows, and ship the DST-responsive
   `derive_daily_closure()` fix (`1c02b2c`, smoke Scenario Z) so a 1 h DST shift adapts immediately
   instead of lagging behind a 30-day mode; only after offset verification choose between the `structstop1.5`
   pre-registration candidate (`docs/ANALYSIS-2026-10-25-stop-hunt-markouts-and-clearance-grid.md`) and
   the literal §7 revert. The **2026-10-20 refresh** (`docs/REVIEW-2026-10-20-post-gate-refresh.md`)
   re-ran every check on the 08:59 UTC snapshot, moved the era to n=147 and recorded that the n=150
   arm **lapsed with the time gate** — do not re-judge PASS on the grown sample. The n=127 file
   `docs/REVIEW-2026-10-19-struct-stop-screen.md` is the earlier interim record. The BTC-port verdicts
   are in `docs/ANALYSIS-2026-10-13-btc-port-assessment.md` §3 (context: the 10-13 block in
   `docs/HANDOFF-HISTORY.md`). The quote logger has **10/14 complete UTC days and 1/2 weekends**,
   median $0.55, **currently STALE (~11.3 h old at collection 335 — newest row 2026-10-24 15:34:30 UTC;
   restart `mt5quotes-gold` on the host before Sunday reopen)**; retain the registered $0.40 round trip
   until the full sample target and process health are verified.
  The large-N history dump/convert/replay is still a first-run-on-the-box task:
  `docs/ACCELERATE-TESTING.md` §2. The dashboard's pressure/setup/location/feed panels are
  **display-only** (`docs/ANALYSIS-2026-10-16-dashboard-pressure.md`); since 2026-10-23 no dashboard
  page writes anything at all. Dashboard/helper changes restart only the dashboard, never the engine
  (`docs/AUTOSYNC.md`).

3. **10-05 re-review is DONE:** `docs/REVIEW-2026-10-05.md`. Max-hold isolation
   closed (n=209, 1 TIME exit, cap never bound in-session); fallback step-2
   trigger **MET** (−$0.570/trade at n=209) → ratchet-off is **eligible to be
   pre-registered, but blocked on the costed harness + user sign-off**;
   `H-side-awareness` **DROPPED** (bar (b) and (c) fail). New named candidate:
   London/NY session-band bleed (§5a) — not adopted. No runtime change.
4. Never change `BE_TRIGGER_R` / `MAX_HOLD_MINUTES` / ATR bounds / blackouts /
   session windows without a pre-registered bar + REVIEW/ANALYSIS doc.

### Command cheat sheet

| Goal | Command |
|------|---------|
| Integrity first | `python3 tools/check_data.py` |
| Era / WR / ratchet grid | `python3 tools/win_rate_report.py` |
| Falling-gold / side regime check | `python3 tools/momentum_regime.py` |
| Blocked-signal phantoms | `python3 tools/phantom_trades.py` |
| Gate replay (ledger-side, cascade-ignorant — descriptive only) | `python3 tools/validate_gates.py` |
| **Any exit/gate/param counterfactual** | `python3 tools/strategy_lab.py --table --only baseline,<variant>` |
| Replay-vs-production recall | `python3 tools/strategy_lab.py --calib-only` |
| Stop-vs-level invariant (+ deploy-boundary evidence) | `python3 tools/check_structural_stop.py` |
| **§7 closure-gap revert trigger (count + damage)** | `python3 tools/check_gap_rides.py` (`--root DIR`, `--since`, `--json`, `--strict` → exit 1 at the trigger) |
| **Is this handoff stale?** | `python3 tools/handoff_check.py` (`--update` rewrites only the snapshot block) |
| **How much paper runway is left?** | `python3 tools/equity_runway.py` (`--cost 0.275`, `--json`, `--strict` = exit 1 at the rebaseline floor) — read-only; ledger vs true equity vs drift, era $ burn, runway + bootstrap. `docs/ANALYSIS-2026-10-30-simulated-equity-and-paper-runway.md` |
| Net-of-cost view of the ledger | `python3 tools/win_rate_report.py --spread 0.40` (round-trip $; the default output is unchanged without it) |
| **Measured spreads / cost / server clock / contract spec** (once `mt5quotes-gold` runs) | `python3 tools/xm_quote_report.py` (`--quiet` = the digest line) |
| **Large-N replay over broker M1 history** | `python3 tools/history_to_log.py mt5_history.csv --out history_utc.csv`, then `python3 tools/strategy_lab.py --bars history_utc.csv` |
| **Boxes now + does box theory pay?** | `python3 tools/box_report.py` (`--root DIR`, `--spread $`, `--json`) — live 20-bar/1h/4h/prior-day boxes with structural stop/TP per edge, plus the measured breakout/fade verdict. In the browser: the dashboard's **📦 Boxes & Timing** tab (`?tab=boxes`) renders the same read plus the condition checklist. Read-only, display-only (`docs/ANALYSIS-2026-10-20-box-theory-manual-trading.md` §6) |
| **Box chop + retest + how loud the alert is** | `python3 tools/box_report.py --alert-scan` — the live boxes, the measured "is it choppy?" read (recent 24 h vs the span in view), the frozen-box retest state, and a replay of how many Telegram notices the current rule would have sent (`--alert-days N`). Read-only, ~25 s. `docs/ANALYSIS-2026-10-21-box-chop-retest-alerts.md` |
| **Session watch plan (07:00 / 13:00 UTC)** | `python3 tools/box_alert.py --plan --dry-run` (the exact message, nothing sent) · `--plan` (send if an anchor is due; `--loop` runs it automatically) · `--no-plan` (break notices only). Display-only: no order, no gate; deduped per date+session in the notifier's state file. `docs/PROPOSAL-2026-10-23-telegram-routing.md` |
| **Box-watch Telegram notice (optional sidecar)** | `python3 tools/box_alert.py --once --dry-run` (the decision + the exact text, nothing sent) · `--test` (prove the bot/chat) · `--quiet` (the autosync `🔔` line: `disabled` / `not configured` / `Telegram pair found · notifier not running` / `running` / `notifier STOPPED`, states in `docs/AUTOSYNC.md` §3) · `--loop` (what `deploy/boxalert.service` runs). Reads the pair and its knobs from `/opt/gold/.env` itself, so no `set -a` step. Display-only: no order, and the only file it writes is its own state (dedupe + heartbeat) |
| **Market context (tape / gates / §7 era / calibration)** | `python3 tools/pressure_report.py` (`--root DIR`, `--era structstop|maxhold|075|all`, `--json`) — the same read-only layer the dashboard renders |
| **Where did strong (8/8) signals head? (rough estimate)** | `python3 tools/signal_outlook.py --root .` (`--era structstop|075|all`, `--json`) — forward-walk cone + base rates per side/era; display-only, `docs/ANALYSIS-2026-10-19-signal-outlook.md` |
| Chart & Placement tab read layer | `python3 tools/test_manual_chart.py` (32 hermetic tests; the tab itself is `?tab=chart`, `?tf=1\|5\|15`) |
| v2 harness (goldbot/) | `python3 -m unittest discover -s goldbot/tests -t .` (64 hermetic tests) then `python3 -m goldbot --compare`. Read-only; no orders. `docs/REDESIGN-2026-10-23-v2-harness.md` |
| Loser features | `python3 tools/analyze_losers.py` |
| Engine regression | `python3 tools/smoke_test.py` (A–Z + AA) |
| **LIVE execution gate scorecard** | `python3 tools/live_readiness.py` (`--json`, `--strict` → exit 1 while closed) — 20 checks; a PASS is a code check, not a demo test |
| LIVE-path unit tests | `python3 tools/test_live_readiness.py` (20) + `python3 tools/test_live_manage.py` (19, broker-side management) |
| **How many days to live? what's done / pending?** | `python3 readiness.py` (`--json`) — the same read the dashboard's **🚦 Readiness** tab renders (`?tab=readiness`, `?readiness=refresh`); `python3 tools/test_readiness_tab.py` (16). Estimates, never deadlines or a profit forecast |
| Force autosync now | `sudo /opt/gold/tools/autosync.sh` |
| Live state | `cat /opt/gold/status.json` |
| Engine service | `systemctl status goldbot` (or unit that runs `engine.py` under `/opt/gold`) |
| Autosync log | `tail -80 /var/log/gold_autosync.log` |

### Do not

- Pool **decisive WR** across the 09-15 ratchet change without naming the era.
- Key BE reconstruction only on `Exit_Reason == "BE"` — use **geometry**
  (`Stop_Loss == Entry_Price`), and recover the pre-ratchet risk from the **reward leg**
  (`|TP − Entry| ÷ 1.5`), **not** from `ATR_At_Entry`: since 2026-10-05 the stop is
  structural, so `2·ATR` understates risk on level-bound trades (§8).
- Decide an exit/ratchet/stop change from `exit_sims.py`, `pathwalk_sims.py` or
  `phantom_trades.py` — they are **cascade-ignorant** (one position,
  cooldown and breaker state are not modelled). Use `tools/strategy_lab.py` (§7).
- Stack a second runtime change on the open **struct-stop window** (entries ≥ **2026-10-06
  03:00 UTC**, the deploy time — planned 10-05 21:00): one variable at a time, and its bar is
  already written (§6 item 1).
- Date a cutover from the **plan** or the **PR merge**. Take it from the host's
  `autosync: merge upstream` commit time (`docs/AUTOSYNC.md` §2) and confirm it from the ledger —
  the struct-stop cutover was dated 6 h early and only a failing guard exposed it.
- Hand-edit code on `/opt/gold` (autosync will refuse deploy).
- Feed a raw `mt5_history_dump.py` file to anything UTC-aware: its `Timestamp` is **broker-server time labelled
  UTC** (+3 h now) stamped at bar *open*, and its last row is the still-forming bar. Convert with
  `tools/history_to_log.py`, which proves the clock against the live log and refuses rather than guesses
  (`strategy_lab --bars` refuses a raw dump). Never write history pulls into `xm_data/` (autosync commits it).
- Ship param/strategy changes without a pre-registered bar + REVIEW/ANALYSIS doc.
- Quote replay numbers from before 2026-10-15 without noting the harness fix (blackout end boundary, §8).
- Treat the bot as income, or go LIVE without broker-side BE + a costs model.
- Read falling-vs-rising (or "gold is down") stats pooled across sides — split
  by BUY/SELL first (they are ~collinear with direction, §2).

### Env (names only — never commit values)

`/opt/gold/.env`:
- `DATA_SOURCE` = `MT5` (live) or `TWELVEDATA`
- `TWELVE_DATA_API_KEY`
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`
- `MT5_FEED_FILE` (optional; default `/opt/gold/mt5_last_candle.json`)
- `GOLD_TELEGRAM_KINDS` (optional; `trade,exit,skip,risk,feed` subset, `none` = engine silent;
  **unset = every message, unchanged**) — see `docs/PROPOSAL-2026-10-23-telegram-routing.md`
- `GOLD_BOX_ALERTS` / `GOLD_BOX_ALERT_DAILY_CAP` / `GOLD_BOX_ALERT_*_COOLDOWN_MIN` (optional
  box notifier; `0` disables it)
- *(removed 2026-10-23)* `GOLD_MANUAL_JOURNAL_FILE` went with the `/scalp` page; nothing reads it now

### Era timeline (UTC)

| When | What |
|------|------|
| 2026-10-28 ~19:15 UTC (**B2 complete — LIVE path only; NO deploy to the host / NO engine strategy change / NO order**) | **“Follow execution plan” session.** Ritual on collection 370 (737 closes, era n=240): `check_data` 0 fail/8 warn, `handoff_check` FRESH(2), `check_structural_stop` PASS (0 inside, 82.5% level-bound, +0.50 ATR, 3.33 ATR risk), `check_gap_rides` 3/2 with 0 damage, `pressure_report` era 35.5% dec / −0.078R gross (C2 FAIL vs its 36.0% baseline, recorded not re-judged), `xm_quote_report` 13/14 days + 1/2 weekends at $0.55, `live_readiness` 9 PASS / 8 TODO / 3 MANUAL. **A2 was not run:** its only remaining gate is a host action (the line must land while the host has no open position, and the cutover is the host's own `autosync: merge upstream` commit time) — reported blocked, not faked. **Track B B2 shipped instead** (decision recorded before the code): the LIVE path records the filled position and now mirrors the paper exits at the broker — `TRADE_ACTION_SLTP` to entry at +0.75R and a 240-min market close, both booked through the same `_maybe_time_stop()` row; confirm-before-book, one retry only on market-moved rejects, stop can only tighten, management still runs while disarmed, a broker-closed position books nothing and blocks new entries. `broker_be` + `broker_time_stop` PASS with **call-graph** evidence (no docstring credit, unreachable helpers no longer count) → **11 PASS / 6 TODO / 3 MANUAL, gate CLOSED**. Tests: 18 new `tools/test_live_manage.py`, smoke **Scenario AC** (12 checks), 20 + 64 + 16 existing green, smoke A–AB unchanged. Records: `docs/DECISION-2026-10-28-b2-broker-be-and-time-stop.md`, `docs/REVIEW-2026-10-28-b2-broker-be-time-stop.md`. **`SL_CLEAR_ATR` is still 0.5; `TRADING_MODE` still FORWARD_TEST.** |
| 2026-10-27 ~13:17 UTC (**G1 signed → step A1 complete; NO deploy / NO engine change / NO order**) | **The owner answered the pack: branch (A).** `docs/PREREG-2026-10-26-structstop1.5.md` is now the *registered* bar for the `structstop1.5` window (`SL_CLEAR_ATR 0.5 → 1.5`) — status lines and the dated sign-off only, §3–§7 byte-identical — and it was signed **before** any post-change trade existed (#723 was open under 0.5 ATR at sign-off). A1's pre-deploy tool work landed: `strategy_lab` (`CLEAR15_ATR/CUTOVER/ERA` + `--table` era row), `check_structural_stop --era clear15` (era-aware classification + an `A2 clearance` hard check + `NOT STARTED` while the cutover is None), `win_rate_report` era rows, `pressure.BAR15` + `pressure_report --era clear15` (§5b card), `journal --era clear15`, and smoke **Scenario AB** (patch *only* the constant: risk = distance + 1.5·ATR, TP still 1.5×real risk, ratchet at 0.75R of the wider risk, delta = exactly one ATR; plus the three tools refusing to judge an unstarted window). `CLEAR15_CUTOVER` is deliberately **None**: the window's boundary is the host's `autosync: merge upstream` commit time of the **A2** deploy (10-13 erratum), so every clear15 path is inert and each tool's default verdict is unchanged (`--table` gains only a "registered but not deployed" footer note). `readiness.py`: `g1` → done, new `a2` row, `window_15` clock starts at the deploy. Smoke A–AB PASSED, 154 `tools/` tests OK, `check_data` 0 fail/8 warn, `handoff_check` FRESH. Record: `docs/REVIEW-2026-10-27-g1-decision.md`. **`SL_CLEAR_ATR` is still 0.5 — A2 is a separate step, gated on no open position.** |
| 2026-10-27 ~12:00 UTC (**"follow execution plan" session; G1 pack + evidence refresh; NO strategy change / deploy / order**) | Ran the ritual on collection 359 (722 closes, era n=225): `check_data` 0 fail/8 warn, `handoff_check` FRESH, `check_structural_stop` PASS (0 inside, 82.2% level-bound, +0.50 ATR), `check_gap_rides` 3/2 reached with 0 damage, `strategy_lab --calib-only` 99.8%, `pressure_report` era card 35.8% dec / −0.081R gross, `xm_quote_report` 12/14 days + 1/2 weekends at $0.55, `live_readiness` 9 PASS / 8 TODO / 3 MANUAL CLOSED. **Cleared a host blocker with data:** the first post-DST daily break (`2026-10-26 20:58:09 → 22:00:04`) matches `derive_daily_closure()` = `(20:58, 22:00)` exactly, and the quote sidecar shows the break is fixed in **UTC** across the offset change (freeze 20:59→22:00 on 10-22 at +3h and on 10-26 at +2h) — so PREREG §2.3 is satisfied ahead of any deploy and no ±60-min adaptation was needed. Refreshed the costed replay for `0.5 / 1.0 / 1.5 / revert` at $0.20/$0.275/$0.35 and wrote the owner decision pack `docs/BRIEF-2026-10-27-g1-owner-decision.md` (A sign `structstop1.5` / B literal §7 revert / C hold with a reason; PASS feasibility 48% at n=150 stated as the headwind it is). **No parameter change: `SL_CLEAR_ATR` is still 0.5 and G1 stays unsigned.** |
| 2026-10-26 **15:39:13 UTC (`d4686f8`)** (**deploy record + incident review, docs only; no strategy change**) | **PR #61 (`0f7f71e`) deployed by the `autosync` merge `d4686f8`** — the 14:15 row's "no deploy" meant no *strategy* deploy: `engine.py` (LIVE-path hardening; paper path AST-identical, 103/112 definitions unchanged) and the dashboard Readiness tab did go live. A forced run at 15:37:50 (`data collection 351`, trade #711) **rolled back** — `git merge` itself failed, so `smoke=not run`; its push was rejected as a *consequence* (origin ahead), not a credentials fault — and the retry at 15:39:09 (`352`) deployed cleanly; every data row is on `origin/main`, no bar gap. Engine restarted ≈15:39:24 (inferred) with no open trade; `status.json` gains `live_last_candle_ts: null`; **no era boundary moved** (struct-stop n=214). Cause of the failed first merge **unconfirmed** (the script discards merge output; best-fitting class: an uncommitted tracked doc on the box); a dead engine after a successful merge is silent; `autosync.sh` defects D1–D7 proposed, not applied. `docs/REVIEW-2026-10-26-autosync-rollback-push-failed.md`. |
| 2026-10-26 ~14:15 UTC (**full-system review; LIVE-path hardening only; NO strategy change / deploy / order**) | Owner asked to review everything, finalise the engine and make progress drivable by **“Follow execution plan.”** Re-ran every check on collection 349 (709 closes, era n=212): `check_data` 0 fail/8 warn, `handoff_check` STALE→FRESH (old §1 archived), `check_structural_stop` PASS (0 inside, 83.0% level-bound, +0.50 ATR), `check_gap_rides` 3/2 (0 gap-through), `pressure_report` SCREEN MET (37.5% [30.2–45.4], −0.054R), `--calib-only` 99.8%, `xm_quote_report` **11/14 days, 1/2 weekends, $0.55**, **DST gate MET: +2h from 10-25 22:00:30 UTC, EU rule 100%**. New findings: ~2 h of open-market M1 bars missing at the Sunday reopen on the price path (quote sidecar was fresh), `derive_daily_closure()` still `(20:58, 22:00)` until the first post-DST daily break, captured spec `filling_mode=2` (IOC only) while `run_live` hard-coded FOK. **Shipped (LIVE path only, zero paper change):** `live_armed()` + `LIVE_HALT`, `resolve_order_filling()` from the symbol bitmask, closed-bar/dedup `run_live` with its own `live_last_candle_ts` watermark; new `tools/live_readiness.py` (9 PASS / 8 TODO / 3 MANUAL, gate CLOSED) + `tools/test_live_readiness.py` (18) + smoke **Scenario AA**. Refreshed clearance grid: 1.5 ATR −0.024R/t at $0.20/side vs live −0.110 (3/4 pre-declared bar). Wrote `docs/PREREG-2026-10-26-structstop1.5.md` as a **DRAFT pending G1 owner sign-off** and rebuilt `docs/EXECUTION-PLAN.md` around the new prompt with Tracks A/B/C. Full record: `docs/REVIEW-2026-10-26-full-system-audit.md`. |
| 2026-10-25 **02:48:12 UTC (`71317da`)** + post-merge follow-up | **PR #58 (`d38117a`) deployed into the closed weekend market** via `autosync` (`7b2e2ea` `data collection 335` + `71317da` `autosync: merge upstream`; 697 closed, 0 open, no bars during weekend): (1) `#697` duplicate-number restore fix (`8d84dcf`, Scenario Y) and (2) **daily-closure gap guard live** (`4d911fa`, `GUARD_CUTOFF_MIN = 30`, entries only, derived from observed price-log breaks, Scenario Z; `docs/PREREG-2026-10-25-gap-guard-daily-closure.md`). **Post-merge session (`arena/c5824a9f-gold-trading-bot`):** verified `71317da` + collection 335 (`smoke_test.py` PASSED, `check_data.py` 0 fail/8 warn, `check_structural_stop.py` PASS at n=200, `check_gap_rides.py` 3/2); flagged **`mt5quotes-gold` STALE (~11.3 h old, stopped 2026-10-24 15:34:30 UTC)** for host restart before Sunday reopen; **owner decided to hold stop geometry (`SL_CLEAR_ATR = 0.5`) until the post-DST broker offset (`+2h` EU vs `+3h` US) is observed tonight/Monday**, and approved making **`derive_daily_closure()` DST-responsive (`1c02b2c`)** — baseline over recent 5 breaks + immediate Day-1/Day-2 `±60 min` Sunday-reopen / post-weekend break shift adaptation (immune to feed outages; +7 hermetic Scenario Z checks) so a 1 h DST transition never lags 10+ trading days behind a 30-day mode. |
| 2026-10-25 (same session, follow-up to the ~01:45 refresh, **evidence + replay only; no runtime change**) | Owner hypothesis (price hovers at stops, tags them, bounces; traders stop deeper than the level suggests) + delegated decision. New `tools/stop_hunt_markout.py` (bounded 24 h mark-outs, observed bars only) + `structstop1.5` clearance variant in `tools/strategy_lab.py` (one VARIANTS entry; calib recall 99.8% re-verified; `smoke_test.py` PASSED). Mark-outs (era n=200): 84% of SLs hovered ≤0.25R of the stop before printing vs 13% of wins; 27% back at entry ≤15 m, 12% never in 24 h; median hunt ≈0.17R (≈1.1 ATR past the tested level, p75 ≈2.1 ATR); 21/90 full signature; **29% of TP wins had ≥0.5R MAE** (why the pattern alone cannot justify a stop change). **Costed grid replay (post-cutover era, stateful):** at every cost, 1.5 ATR > 1.0 > live 0.5 > 0.25 > old geometry; **structstop1.5 = −0.000R/trade net at registered $0.20/side and −0.023R at measured $0.275** (live: −0.102/−0.132), breakeven at registered cost, +0.10R delta vs live at both costs, decWR 43.1% vs 38.7%; pre-declared bar passed 3 of 4 (n 163 vs 207 = −21.3% misses; mechanism disclosed: longer holds, 5 TIME vs 2). **Verdict: NO live change — `structstop1.5` recorded as a pre-registration candidate, not registered; `structstop1.0` measured-and-insufficient (+0.026R < +0.05R bar).** Dated evidence + drafted (unregistered) SCREEN/PASS/REVERT bars: `docs/ANALYSIS-2026-10-25-stop-hunt-markouts-and-clearance-grid.md`. |
| 2026-10-25 ~01:45 UTC ("execute the plan" session refresh, **docs only; no runtime change**) | Re-ran every session check on the collection-334 snapshot (data through 2026-10-23 20:57 UTC): `check_data.py` 0 fail / 8 warn; `handoff_check.py` FRESH after `--update`; `check_structural_stop.py` **PASS at n=200** (0 inside level, 83.5% level-bound, +0.50 ATR clearance); `check_gap_rides.py` still **3/2** (no gap-through, no worse exit); `pressure_report.py` SCREEN MET on all five checks (SL/day 6.00, SL share 45.00%, scratch 26.50%, gross −0.052R, decisive 37.93% [30.4–46.0]); `xm_quote_report.py` **10/14** complete days, 1/2 weekends, median $0.55, newest synced row 10-24 14:59:30 (Saturday, market-closed frozen tick); DST window opened 01:00 UTC with **no observed offset yet** (next sync decides the rule). **New finding:** duplicate `Trade_Num` **#697** in the synced ledger (the 10-23 15:15 SELL should have been #698) — latent engine bug: `restore_open_trade_from_status()` restores `current_trade_num` but not `next_trade_num`, so a restart-with-open-trade makes the next trade reuse the number (same pattern as the long-standing #1/#2/#3, #171 duplicates). No metric or judgement affected (row-based tools; balance chain + status.json agree); two-line fix + smoke scenario proposed, **not applied** — owner review pending. `docs/REVIEW-2026-10-25-duplicate-trade-number.md`. Gap-guard blocker, quote-cost target and all §4 thresholds unchanged; no guard, revert, test, or deploy. |
| 2026-10-21 ~23:00 UTC (**ops/tooling fix, no runtime change**) | **`🔔 box alerts: not configured` was false.** The 18:00 digest, the first to run the phase PR #49 added (deployed 17:46), reported no `TELEGRAM_BOT_TOKEN/CHAT_ID` in the very message that pair had delivered. `autosync.sh` keeps the pair in its own unexported `TG_TOKEN`/`TG_CHAT`, and `box_alert.py` read only its inherited environment. Fix: the tool reads its own keys from `$GOLD_DATA_DIR/.env` (environment wins, like the engine's `load_dotenv`), and autosync passes `GOLD_DATA_DIR=$GOLD_DIR`. The line now also says whether the notifier is **running** (a `--loop` heartbeat in its own state file); otherwise "pair found" would have read as a healthy notifier. Also fixed: the documented `GOLD_BOX_ALERT_GLOBAL_COOLDOWN_MIN` was never read, and the message footer ignored the knobs. A pre-existing failing test that read the live CSVs was made hermetic. `test_box_alert.py` 34 pass, smoke PASSED, sandboxed real `autosync.sh` shows every state. `engine.py`/`trade_filter.py`/`pressure.py`/`dashboard.py` untouched; the notifier remains **not installed** unless the owner installs it. |
| 2026-10-21 11:59 UTC (session refresh, **docs only; no runtime change**) | Re-ran every session check on the 11:59 UTC snapshot (collection 303): `check_data.py` 0 fail / 8 warn; `handoff_check.py` FRESH after snapshot + §1 refresh; `check_structural_stop.py` PASS at n=160 (0 inside level); `check_gap_rides.py` still 2/2, 0 gapped through, 0 worse exit; `pressure_report.py` SCREEN MET on all five checks, era n=160 (44W/74L/41BE/1TIME), decisive WR 37.3% [29.1–46.3], R/trade −0.065; `xm_quote_report.py` 7.8 days (7/14 complete, 1/2 weekends), median spread $0.55 vs the $0.40 assumption. Snapshot block + §1 refreshed, old §1 archived to `docs/HANDOFF-HISTORY.md`. No guard, revert, test, or deploy. |
| 2026-10-19 (dashboard PR) | Read-only risk/map/costed-evidence panels; no runtime change or deploy claimed. |
| 2026-10-19 (dashboard) | **Simple Summary tab + Volatility Guard (display-only, no runtime change):** `pressure.py` `volatility_guard`/`simple_summary` (ATR/spread/blackout/cooldown/breaker/closure/trend/gaps/range checklist, verdict green/amber/red), `dashboard.py` tab switch (Simple ↔ Full, localStorage + `?tab=`), preview with `GOLD_DATA_DIR=.`. No engine/filter/gate change. |
| 2026-09-10 ~12:34 | BE ratchet 0.30R + London BUY-only + trend-side daily breaker (PR #7) |
| 2026-09-15 ~06:00 | `BE_TRIGGER_R` → **0.75** (PR #9 deploy) |
| 2026-09-17 | Falsification bar tripped (−$0.40/trade at n≥60) |
| 2026-09-21 ~06:00 | `MAX_HOLD_MINUTES=240` live (PR #15); **no era counter reset** |
| 2026-10-05 (1st) | Scheduled max-hold re-review (`docs/REVIEW-2026-10-05.md`): isolation closed at n=209, fallback step-2 trigger met, `H-side-awareness` dropped, session-band candidate named. **No runtime change** |
| 2026-10-05 21:00 (planned) → **2026-10-06 03:00:04 (actual)** | **STRUCTURAL STOP live**: `SL_CLEAR_ATR = 0.5` + TP = 1.5 × actual risk (`engine.py`). One variable; **new isolation window** (entries ≥ **2026-10-06 03:00 UTC**). PR #28 merged 10-06 00:31:53; autosync deployed it at 03:00:04 (`2f4f4c6`); #495–#498 ran the old rule. Evidence + pre-registered bar: `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` (erratum at the top) |
| 2026-10-13 | **Tooling/docs session (no runtime change):** cutover corrected, replay level window 19→20 bars, `handoff_check.py` + `docs/AUTOSYNC.md`, `win_rate_report.py --spread`, the **GOLD quote + contract-spec logger** (`docs/XM-LOGGER.md`, install pending) and the **large-N history path** (`docs/ACCELERATE-TESTING.md`, first dump pending), BTC-port assessment (`docs/ANALYSIS-2026-10-13-btc-port-assessment.md`). On a branch, **no PR yet** (owner asked to finalise first) |
| 2026-10-15 | **Data refresh (no runtime change):** struct-stop era n=109 (past n=100 screen); metrics still inside most bars (SL share marginal); quote logger collecting (median spread $0.55); handoff snapshot + §1 updated. Scheduled 10-19 review next. |
| 2026-10-15 (tooling) | **Replay-vs-live gap fixed** (`strategy_lab.py` blackout end boundary, end exclusive; the live check is on the full timestamp). Struct-stop era: replay 39.3% decisive vs live 39.1%. Older replay numbers move by ~0.02–0.1R/trade. **Level-test 0.25 ATR pre-registered on paper** (`PREREG-2026-10-15-level-test-0.25.md`), not deployed. No runtime change |
| 2026-10-15 (docs) | **HANDOFF restored + consolidated** (no runtime change): the daily doc job truncated the file at 14:06 UTC (`43884e1` wrote `PLACEHOLDER - will replace`), losing **§2–§11**; content recovered from `712d106`, §1 history split out to `docs/HANDOFF-HISTORY.md`, `handoff_check.py` now checks section structure, not just freshness. |
| 2026-10-16 | **Dashboard market-context layer (display-only, no runtime change):** `pressure.py` + `tools/pressure_report.py` + `smoke_test.py` Scenario U; buy/sell pressure gauge, the engine's gates read back on the last bar, location/risk, §7 era card, feed health. Calibration says the composite is **collinear with side — not a signal**. `engine.py`/`trade_filter.py`/deploy path untouched; autosync restarts the dashboard only |
| 2026-10-17 (merge 10-16 22:54:47; **deploy 10-16 23:01:54**) | **Risk sizer + gates (PR #34) deployed into a closed market** (624 closed, no trade affected), then **corrected in place the same session**: `size_lots` is LIVE-only (the ledger-based version skipped 76–91% of M1 setups and would have sized 0.02 lots at the $500 start), the trade is committed atomically after the sizer accepts (the old order logged phantom trades), LIVE never sizes off the paper ledger, and the **FOMC 17:55–18:30 blackout is reverted** (blackouts frozen, §6.1; it moved era R/trade by ~0.023R). Struct-stop window un-stacked; smoke Scenario V added |
| 2026-10-19 (docs/tools only, **no runtime change**) | **Struct-stop interim screen at n=127** (`docs/REVIEW-2026-10-19-struct-stop-screen.md`): A1–A5, B1, B3, C1, C2 pass, **B2 47.24% vs ≤47.0% fails → SCREEN NOT MET**; era −$47.48 gross / −$98.30 at $0.40. **The §7 closure-gap revert trigger is AT its threshold (2 of 2 post-cutover rides over a daily closure: #595, #610)** — first item of the 21:00 judgement. New read-only `tools/check_gap_rides.py` makes that trigger measurable (count + damage facts) + smoke **Scenario W**. Quote logger 5/14 days, 1/2 weekends (median $0.55). An earlier 04:41 UTC draft of the review was PR #38 — **closed unmerged**, so nothing of it reached `main` |
| 2026-10-19 18:10 UTC (data refresh, **no runtime change**) | Checked-in book 636 closes; struct-stop n=139 (39W/65L/34BE/1TIME), mechanical guard PASS, interim §7 SCREEN MET (SL share 46.76%, gross −0.071R, 37.50% decisive). PASS still needs n≥150 + Wilson LB >32.1%; 11 trades remain and current LB is 28.8%. Gap-ride count remains at threshold 2/2 (#595/#610); no gap-through or damage. Quote logger 6.1 days, 5/14 complete days, 1/2 weekends, median $0.55. Scheduled 21:00 judgement pending. |
| 2026-10-19 21:00 UTC (struct-stop time-gate judgement, **docs only; no runtime change**) | Judged the latest available synced snapshot at 18:10: n=139, geometry PASS, SCREEN MET, PASS not met. Recorded the explicit gap-ride counting rule; 2/2 scheduled-closure rides fire the pre-registered REVERT trigger despite $0 realized gap damage. The prescribed gap guard is not operationally defined (cutoff/open-position policy missing), and host data/executable are unverified, so no revert, guard, deployment, or 0.25 ATR test was made. New evidence/blocker: `docs/REVIEW-2026-10-19-struct-stop-judgement.md`. |
| 2026-10-20 08:59 UTC (post-gate data refresh, **docs only; no runtime change**) | Checked-in book 644 closes (128W/277L/237BE/2TIME); struct-stop era grown to n=147 (43W/66L/37BE/1TIME), guard still PASS (0 inside level, 81.6% level-bound, +0.50 ATR clearance, 3.29 ATR risk). The n=150 arm **lapsed with the 10-19 time gate** and is not re-opened by the grown sample; the recorded judgement (SCREEN MET at n=139, PASS unavailable, gap trigger fired) stands. Post-gate readings: SL/day 5.50, SL share 44.90%, scratch 25.17%, gross −0.028R, decisive 39.45% [30.8–48.8]; gross era −$23.43. Gap rides unchanged at 2/2; quote logger 6.7 days, 6/14 complete, 1/2 weekends, $0.55 median. No guard, revert, test, or deploy. Evidence: `docs/REVIEW-2026-10-20-post-gate-refresh.md`. |
| 2026-10-23 (Telegram routing + watch plan, **message policy only; no runtime/strategy change**) | Owner: the box-watch notice is buried in ~82 messages/day and staring at the screen for it is a long wait. Measured 10 trading days to 10-23: **36.8 skip notices/day (45% of the traffic)**, 14 entries, 14 exits, 4.1 BE-armed, 8 digests, ≈5.1 box notices (worst day 101). **Shipped:** `engine.py` tags every message with a kind (`trade/exit/skip/risk/feed`) and `GOLD_TELEGRAM_KINDS` selects which are sent — unset = today's behaviour byte for byte, `none` = silent, a typo falls back to everything; the filter never touches the trading path or the CSVs. `tools/autosync.sh` digest is rate-limited by `GOLD_DIGEST_EVERY_HOURS` (default 12, `0` = old 3-hourly) with an **incident bypass that always sends at once**, routine digests delivered silently, and a new `🧾 trades:` line summarising closes since the last digest. `pressure.box_plan_next/box_plan_text` + `tools/box_alert.py --plan` (also run inside `--loop`) send **one session watch plan at 07:00 and 13:00 UTC** — levels, both alert prices, what is blocking, ATR-percentile/tick-volume *context* and the 0-of-8 no-edge footer — deduped per (date, session), nothing sent if the box slept through the window or the market is shut. Traffic ≈82 → ≈7–9/day. Smoke **Scenario X** (routing, digest blocks, anchors, dedupe, failed-send retry). `engine.py`/`pressure.py` change means the engine restarts on deploy; the plan needs `deploy/boxalert.service` installed (still optional). Evidence: `docs/PROPOSAL-2026-10-23-telegram-routing.md`. Nothing in §4 moves; the §7 gap trigger and gap-guard blocker are untouched. |
| 2026-10-23 11:59 UTC (journal + indicator audit, **display-only; no runtime change**) | **695 closed** (140W/300L/253BE/2TIME, 31.8% dec [27.6–36.3], net −$649.24 at $0.40), **198 in struct-stop era** (55W/89L/53BE/1TIME, 38.2% [30.7–46.3], net −$131.63), BUY #697 open @ $4 027.91. `check_data` 0 fail/8 warn, `handoff_check` FRESH, `check_structural_stop` PASS (0 inside), `check_gap_rides` **3/2 REACHED** (+#687 SELL 2026-10-22, no gap-through). New `tools/journal.py` self-journal (BUY vs SELL, ATR/session/hour buckets, 11 lab indicators with Fisher p) + `docs/INDICATOR-AUDIT-2026-10-23.md` — no extra indicator clears the 5 pp + side-split bar; strongest hints ATR-percentile quiet 55.6% vs volatile 31.5% (p=0.014) and volume spike 45% vs thin 20.5% (p=0.031 whole book) are context only. Dashboard Journal tab added (`pressure.journal_read` + `_extra_indicators_series`, `?tab=journal`), like Simple/Boxes/Chart it restarts the dashboard only (`docs/AUTOSYNC.md`). No engine/filter/gate/exit/sizing change; gap-guard blocker unchanged. |
| 2026-10-23 14:59 UTC (Manual Scalping workspace + refresh, **dashboard/journal-only; no runtime change**) | Owner approved a separate manual page. Built `/scalp` with the shared M1/M5/M15 chart, health context, costed risk/size calculator and a separate atomic self-reported JSON journal (`manual_scalp_journal.json`, git-ignored); no order route and no bot-ledger/state writes. Added `manual_scalp.py`, `scalp_template.py`, routes, operating guide and pure/Flask tests; autosync now restarts the dashboard for its helper modules too, never the engine. Snapshot refreshed to **696 closed**, **199 struct-stop-era trades** (55W/90L/53BE/1TIME), no open trade; guard PASS (0 inside), gap count **3/2**, handoff FRESH. Recorded n=139 judgement and gap-guard blocker unchanged. Pure calculator/journal, chart, existing-dashboard and route tests pass; full `tools/smoke_test.py` PASSED. |

## 1. Where things stand (as of **2026-10-30 — data collection 381; bar log through 02:59 UTC; sim ledger $52.98 / true equity $36.05 with ≈38 trades of runway, no top-up — see `docs/ANALYSIS-2026-10-30-simulated-equity-and-paper-runway.md`**)

**Stance:** paper-only. `TRADING_MODE = "FORWARD_TEST"` and no real order is possible without two independent gates (`docs/EXECUTION-PLAN.md`, “What the phrase means”). Stop geometry is still **`SL_CLEAR_ATR = 0.5`** — registered on 2026-10-27, **not yet deployed**; `RR_TARGET = 1.5`, `BE_TRIGGER_R = 0.75`, `MAX_HOLD_MINUTES = 240`, the 30-min entries-only closure guard (`71317da`) and the 10-26 LIVE-path hardening are frozen — one variable per window. **B2 (2026-10-28) touched the LIVE path only:** the broker now holds the +0.75R ratchet and the 240-min time stop, so paper and LIVE are the *same* strategy; the paper engine, its ledger and every frozen constant are unchanged.

**The book:** **758 closed** (150W/334L/271BE/3TIME; **31.0%** decisive [27.0–35.2]), engine ledger **$52.98**, true equity **$36.05**, net **−$767.15** at the registered $0.40 round trip. Log 56 190 bars to `2026-10-30 02:59:04 UTC`; `check_data.py` 0 fail/8 warn; `handoff_check.py` FRESH (2 advisory); **SELL #759 open** (`next_trade_num: 760`).

**Open experiment:** struct-stop era **n=261** (65W/123L/71BE/2TIME), decisive **34.6% [28.1–41.6]**, gross **−0.098R/trade** ($−145.14; decisive-only denominator −0.136R), SL/day 6.15, SL share **47.1%**, scratch 27.2%, avg SL $5.80, era DD **$191.04**; geometry guard **PASS** (0 stops inside the level, 82.4% level-bound, +0.50 ATR clearance, 3.32 ATR median risk). The bar card reads **B1/B2/B3/A4/A5**, with **B2 a fresh FAIL** (SL share 47.13% vs the 47.0% bar) and C2 still FAIL. The **10-19 judgement is closed** (SCREEN MET at n=139, n=150 PASS arm lapsed with its time gate) — the numbers above are grown-sample observations, never a re-judgement. **No demonstrated edge after cost.**

**The paper ledger is a counter, not capital — and it is running out (2026-10-30 answer: no top-up).** Paper always trades `LOT_SIZE` (0.01): `size_lots()` returns it whenever there is no broker account, by the 10-17 correction that stopped the paper book being sized off its own balance. So the ledger number moves no entry, exit, lot, parameter, R/trade, era DD or registered bar — only `engine_ledger_usd`, i.e. a **ledger edit**, which is what `handoff_check`'s money rule calls tampering and what erased $24.74 of real losses on 2026-09-09 (the $16.93 drift still in these numbers is its signature). What is real is the **runway**: **−$0.94/closed trade** net (era, $0.40 RT) at **13.1 trades/active day** against $36.05 is **≈38 closed trades ≈ 2.9 trading days** to zero, bootstrap 90% **33–336 trades** (6% of draws have no burn at all — n=261 cannot separate the era from break-even), and there is **no balance floor** (a negative ledger is a supported, tested state). **Registered instead of a top-up — a rebaseline-at-zero rule** (`docs/ANALYSIS-2026-10-30-simulated-equity-and-paper-runway.md` §5): no edit while true equity > $0; at the first trade leaving it ≤ $0, archive the book, keep every row and trade number, rebase to $500 with one published marker + a dated REVIEW, and change nothing else — it is **not** a new era and must never be described as a fresh $500 test. Check with `python3 tools/equity_runway.py` (`--strict` exits 1 at the fire point).

**G1 is SIGNED (2026-10-27, branch A) — `structstop1.5` is the registered window and A2 (the deploy) is still next:** the §7 closure-gap REVERT trigger had fired (3 rides vs threshold 2, 0 gap-through, 0 worse exits, 0 weekend rides) and its literal response was a revert to `2·ATR / 3·ATR`; the owner chose the pack's option **(A)** instead — one further step, `SL_CLEAR_ATR 0.5 → 1.5`, so `docs/PREREG-2026-10-26-structstop1.5.md` is the binding bar for one window (**registered, not deployed**; its §3–§7 numbers may not be edited after outcomes are seen). The registered eligibility bar is **3/4** (trade count −21.9%), the costed replay puts `1.5` at **−0.046R/t** at $0.20/side vs live **−0.141** and the literal revert **−0.155**, and PASS needs ≈**48%** decisive WR at n=150 against a 34.6% reading — **KEEP-with-no-edge or REVERT remain the likely readings**: this is a stop-hunt defect fix, not a claim of edge. **A2's only remaining condition is a host action**: the one line must land while no position is open — **it is blocked right now by open SELL #759** (and the host deploys from its own `0 */3 * * *` cron, which this repo session cannot see or drive); the cutover is the host's `autosync: merge upstream` commit time. Decision records: `docs/REVIEW-2026-10-27-g1-decision.md`, `docs/BRIEF-2026-10-27-g1-owner-decision.md`.

**B2 DONE (2026-10-28) — the LIVE path now runs the same exits as paper:** `execute_live_trade` records the position the broker holds (ticket, sizing risk, entry/SL/TP/time, entry context) and persists it; `run_live` calls `live_manage_open_position()` every 5 s pass, which sends `TRADE_ACTION_SLTP` to move the stop **to entry** at +0.75R and a market close by ticket at 240 min, booking the exit through the **same** `_maybe_time_stop()` the paper path uses (one ledger row, one counter). Rejections are retried once only when the *market* moved (requote/price changed/off/timeout/connection), never on a logic reject; an action is booked only after `TRADE_RETCODE_DONE`; the stop can only tighten and only fires once; management still runs while the process is **disarmed** because both actions reduce risk; a position the broker closed behind the engine books **nothing** (no invented exit price — that is B3), raises one loud alert and **blocks new LIVE entries** until reconciled. Scorecard **11 PASS / 6 TODO / 3 MANUAL, gate CLOSED**; the two checks were made **call-graph** checks (a helper `run_live` cannot reach no longer passes, and no comment/docstring can satisfy a check). Evidence: `docs/DECISION-2026-10-28-b2-broker-be-and-time-stop.md`, `docs/REVIEW-2026-10-28-b2-broker-be-time-stop.md`. **What it does not prove:** no demo-account evidence (B5), no deal-level reconciliation (B3), single position only, and if the process is down when +0.75R or 240 min is crossed only the broker's own SL/TP protects the trade.

**Cost and clock:** quote logger **15/14 complete UTC days, 1/2 weekends** (measured round trip mean/median **$0.55**, p90 $0.56, max $0.68) vs the registered $0.40 — $0.40 stays registered until 14 days **and two weekends** (`tools/xm_quote_report.py`, A6). Broker offset **+2h** since `2026-10-25 22:00:30 UTC`, EU rule fits 100% of 34 343 observed rows; the first post-DST daily break `2026-10-26 20:58:09 → 22:00:04` matches `derive_daily_closure()` exactly. Spec `filling_mode = 2` = **IOC only**; account kind **REAL** (a live pilot needs a DEMO account + separate data dir).

**Engine + live gate:** the paper path is stable (`smoke_test.py` A–Z + **AA** + **AB** + **AC** PASSED, 19 `test_live_manage` tests, 20 `live_readiness` tests, 64 `goldbot` tests, 16 readiness-tab tests, 18 new `test_equity_runway` tests, `py_compile` OK). `python3 tools/live_readiness.py` = **11 PASS / 6 TODO / 3 MANUAL → LIVE GATE CLOSED**; the six TODOs are exactly Track B3 (reconciliation: 2 checks) and B4 (disconnect, sizing, cost: 3 checks) plus `quote_sample` (data, waiting on the logger), and the three MANUAL items are operator/evidence items. None of them is permission to trade.

**Pressure:** composite still collinear with side — context, never a signal or a gate. The owner's manual pressure/hold hypothesis remains unmeasured; the private observation-log template is the “Manual observation record” appendix of `docs/EXECUTION-PLAN.md`.

**One-line prompt:** **“Follow execution plan.”** — `docs/EXECUTION-PLAN.md` (“What the phrase means”) states exactly what it authorizes and the two approval gates.

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

## 2. Bot in one paragraph

Simulated XAUUSD scalper on 1-min candles. BUY at the 20-bar floor /
SELL at the 20-bar ceiling after a ≥38% wick rejection, trend-gated by
EMA50 vs EMA200 (+30-bar slope, one-sided 0.3·ATR EMA50 buffer),
RSI BUY 30–68 / SELL 32–70, ATR 1.10–4.50.
Exits: SL = entry ∓ **max(2·ATR, distance to the tested level + 0.5·ATR)**, TP = entry ∓
1.5 × that risk (1:1.5 held against the *actual* stop; identical to the old 3·ATR whenever the
level does not bind — 2026-10-05, §4/§5), plus a breakeven ratchet
that moves SL to entry once the trade is +0.75R ahead (`BE_TRIGGER_R`, 0.30R
from 09-10 to 09-15 — see §4). `engine.py` = signals +
execution/state; `trade_filter.py` = portfolio risk gates; `dashboard.py` =
Flask status page. Trading is FORWARD-TEST simulated (no real orders);
`TRADING_MODE=LIVE` path exists but the BE stop (below) is engine-side only there.
Because the trend gate keys side on EMA50 vs EMA200, **direction and side are
nearly collinear in the data** (94% of falling-60m entries are SELLs, 96% of
rising-60m are BUYs) — never read a "momentum" claim without splitting by side
(ANALYSIS-2026-09-28).

## 3. Data feed: Twelve Data → MT5 sidecar (configured 2026-09-10)

`DATA_SOURCE` env var in `/opt/gold/.env` picks the feed; default in code is
`TWELVEDATA`. **The deployed engine runs `DATA_SOURCE=MT5`**.

How MT5 works (feed-only, trading stays simulated):
- MT5 terminal runs **under Wine** in prefix `~/.mt5`, logged in.
- Sidecar `tools/mt5_feed.py` runs under the **Wine** Python and atomically
  publishes the latest **closed** M1 GOLD candle to `/opt/gold/mt5_last_candle.json`.
- Engine reads that file each poll, dedupes by candle timestamp.

**Tool (2026-09-11):** `tools/mt5_history_dump.py`
- Pulls historical bars (M1/M5/H1/etc.) from the same MT5 connection.
- Useful later for faster offline filter research / walk-forward tests.
- Does **not** affect the live engine.
- Example:
  ```bash
  export WINEPREFIX=~/.mt5
  xvfb-run --auto-servernum \
    wine C:/Python312/python.exe Z:/opt/gold/tools/mt5_history_dump.py \
      --days 365 --timeframe M1 --out Z:/opt/gold/history_m1.csv
  ```
- Remember: broker history ≠ live feed. Live forward-test remains the authority.

Stale-feed guard still active. Feed price scale is the **broker demo GOLD
feed** (~4.4k), not spot XAUUSD.

## 4. Current risk gates (trade_filter.py)

**LIVE execution parity (2026-10-28, B2) — no gate, threshold, sizing rule or cost assumption changed.**
The LIVE path now mirrors the two engine-side exit rules **at the broker**: the +0.75R ratchet as
`TRADE_ACTION_SLTP` to entry (only after `TRADE_RETCODE_DONE`, only ever tighter, only once) and the 240-min
time stop as a market close by ticket, booked through the same paper `TIME` path. This was needed because the
broker holds the stop/target and `run_live` never ran the paper exit code — without it LIVE would have been a
different strategy. Both actions only reduce risk and still run while disarmed; a broker-closed position books
nothing and blocks new exposure until reconciled. Full rules, reject/retry semantics and gaps:
`docs/REVIEW-2026-10-28-b2-broker-be-time-stop.md`. `TRADING_MODE` stays `FORWARD_TEST`.

Dashboard + Manual Scalping workspace: no risk gates, parameters, engine sizing or registered cost
assumptions changed. The `/scalp` calculator is manual arithmetic only; its editable inputs never drive
`trade_filter.py` or `engine.py`, and its journal is not portfolio state.

**Recovery PR (2026-10-19):** candle/tick paper exits reject invalid/nonfinite/zero
position geometry before booking P&L; startup retains finite negative/zero balances
honestly. Backup-first `tools/repair_phantom_ledger.py` is dry-run by default and
requires stopped engine/autosync before apply. No strategy thresholds changed.

**2026-10-19 incident:** no gates or parameters changed. Invalid zero-target TP rows
evade the SL-based breaker; that breaker is not a data-integrity safeguard.

**Source of truth for live params** (do not change without a pre-registered bar + REVIEW/ANALYSIS doc):

| Param | Value | File |
|-------|-------|------|
| `BE_TRIGGER_R` | 0.75 | `engine.py` |
| `MAX_HOLD_MINUTES` | 240 | `engine.py` |
| `ATR_SL_MULT` / `ATR_TP_MULT` | 2.0 / 3.0 (TP = `RR_TARGET` × **actual** risk) | `engine.py` |
| `SL_CLEAR_ATR` / `RR_TARGET` | **0.5 / 1.5** (live **2026-10-06 03:00** UTC — planned 10-05 21:00; pre-cutover books have neither) | `engine.py` |
| `GUARD_CUTOFF_MIN` | **30 min** (entries only, derived from observed price-log daily breaks + DST-responsive shift adaptation; live **2026-10-25 02:48:12** UTC via `71317da` — `docs/PREREG-2026-10-25-gap-guard-daily-closure.md`) | `engine.py` |
| `RSI_MIN` / `RSI_MAX` | BUY 30 / 68; SELL mirrored 32 / 70 | `engine.py` |
| `MIN_ATR` (engine) | 1.10 | `engine.py` |
| `MIN_ATR_TO_TRADE` / `MAX_ATR_TO_TRADE` | 1.10 / 4.50 | `trade_filter.py` |
| `MAX_DAILY_LOSSES` | 10 | `trade_filter.py` |
| `SL_COOLDOWN_BASE/ESCALATED` | 30 / 60 min | `trade_filter.py` |
| London blackout | 07:55–09:00 UTC, **BUY only** | `trade_filter.py` `BLACKOUT_WINDOWS` |
| NY / rollover blackouts | both sides | `trade_filter.py` `BLACKOUT_WINDOWS` |

**Current mechanical check (latest checked-in snapshot, 2026-10-23 20:57 UTC):** `tools/check_structural_stop.py` PASS at n=200, with zero post-cutover stops inside the level, 83.5% level-bound, median clearance +0.50 ATR and median risk 3.33 ATR. This verifies geometry only. The time-gate judgement (recorded at n=139) is in §1/§6 and `docs/REVIEW-2026-10-19-struct-stop-judgement.md`: SCREEN MET, PASS not met, and the separate closure-gap REVERT trigger fired (now 3/2); the required gap guard deployed at `2026-10-25 02:48:12 UTC` (`71317da`) into the closed weekend market, and stop geometry is held on `SL_CLEAR_ATR = 0.5` until the post-DST broker offset is observed. The grown n=200 sample is an observation, not a re-judgement (`docs/REVIEW-2026-10-20-post-gate-refresh.md` §3).

**Mirrored, and pinned:** the read-only dashboard layer needs some of these thresholds, so it keeps its own
copies in `pressure.py` (`docs/ANALYSIS-2026-10-16-dashboard-pressure.md`) — it must not import the engine, and
it must not drift from it either: `tools/smoke_test.py` Scenario U asserts every mirror **equals** the
`engine.py`/`trade_filter.py` value, so a param change here has to move the mirror in the same commit or the
deploy gate goes red. Nothing in the dashboard can change trading behaviour.

- SL cooldown: 30 min, escalating to 60 min after 2 consecutive SLs (BE
  scratches neither count toward nor break the streak — see the engine note
  below and §6 item 2b).
- Daily breaker: after `MAX_DAILY_LOSSES = 10` SLs → trend-side-only mode.
- Blackouts (UTC): London 07:55–09:00 **blocks BUYs only**; NY windows and
  rollover block both sides.
- ATR bounds: <1.10 or >4.50 → skip (high-ATR bound validated live).

Engine: **BE stop ratchet** at +`BE_TRIGGER_R = 0.75`·risk → SL moves to entry
(raised from 0.30 on 2026-09-15: at 0.30R = 0.6·ATR the trigger was one noisy
1-min bar, 77% of new-regime trades scratched with a median lifetime of 1.5 min
and the ratchet was converting +$222 of runs into $0 — docs/REVIEW-2026-09-15.md).
Exit reason `BE` = scratch (excluded from wins/losses/cooldown/daily tally).
Still true after the change: **a BE exit neither triggers nor breaks the SL
streak** (`get_consecutive_sl_count` breaks on TP, counts SL, ignores BE), so
escalation to 60 min is the norm and a scratch can be followed by an instant
re-entry into the same dying setup (27 of 58 0.75R-era entries came <10 min
after the previous exit). Both are open items in §6. Note the counterweight
that FOMC day surfaced: escalating cooldown is what kept 17:28–18:28 UTC dark
on 09-16, so it is no longer an unambiguous leak.

Engine: **structural stop** (live **2026-10-06 03:00 UTC**, planned 10-05 21:00 — `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md`, erratum at its top).
`risk = max(ATR_SL_MULT·ATR, |entry − level| + SL_CLEAR_ATR·ATR)` where `level` is the same
20-bar floor/ceiling the rejection gate was measured against; `take_profit = RR_TARGET·risk`.
Why: the level test's tolerance is price-% (`FLOOR_BUFFER_PCT = 0.0020` ≈ $8.30 ≈ **4.5×** the
median ATR) so it passes on 86.9% of bars, entries fill a median **2.42 ATR** from the level,
and a plain 2·ATR stop therefore sat **inside** the range on **63.8%** of the 0.75R master book
— 63.8% of SL exits needed no structural break at all (median SL lifetime 7.2 min). Guarded by
`tools/smoke_test.py` Scenario N and checkable on any era with
`python3 tools/check_structural_stop.py` (**post-cutover it must print 0** — and it now prints the boundary evidence that dates
the deploy from the ledger). Costed, era-matched
replay (10-05 figures, harness since corrected to the 20-bar level — see the erratum): master era n 326→217, 32.1→37.4% decisive, −0.217→−0.106R/trade, −$13.90→−$5.83/day at
$0.15/side, SL/day 8.2→5.4, maxDD $255→$175; **better in 3 of 4 eras** (worse pre-ratchet — it
needs the ratchet), and **still negative at every cost tested**. §7 of that doc is the
pre-registered bar (judge at n≥100, ~2026-10-19).

Engine: **max-hold time stop** (deployed 2026-09-21, fallback step 1 —
`docs/REVIEW-2026-09-21.md` §2): any open trade older than
`MAX_HOLD_MINUTES = 240` closes at market with reason `TIME`, whatever the
P&L. Price exits take priority (a simultaneous TP/SL wins); checked on both
the tick path and the MT5 candle path (at close); wall-clock, so across a
closure the trade exits on the first candle/tick back. TIME is a **neutral
bucket like BE**: own `time_exits` counter (in `total_trades`), P&L-signed
into the balance and era P&L/trade, but **excluded from decisive WR math and
ignored by the SL streak / daily breaker**. Engine-side only (LIVE caveat as
for the ratchet).
**Post-10-05 re-review:** the cap never bound an in-session trade in its first
14 days (longest non-TIME hold 68.0 min; n=209). It **cannot fire while the
market is closed**, so a position opened before a closure rides it — the only
TIME exit so far is #476, held 49.1 h across the 10-02→10-04 weekly close.
In LIVE mode that stop is not broker-protected across the gap; a pre-close
entry guard / flat-before-close policy is a named candidate (§5a/REVIEW-10-05
§5b), not adopted.

- **Engine: risk sizer (2026-10-17, deployed then corrected — LIVE-only).** `size_lots(stop_usd)`
  enforces `RISK_PCT = 1.0` of the **broker** balance and skips the trade when the sized lot is
  below `volume_min`. `CONTRACT_SIZE=100` (GOLD Standard; `1` for GOLDmicro) and `VOLUME_STEP=0.01`
  are explicit constants. **Paper returns `LOT_SIZE`** (no broker account to size off — the
  ledger-based version skipped 76–91% of M1 setups, see `docs/PREREG-2026-10-17-risk-sizer.md`), so the
  forward-test book and the open struct-stop window are unchanged. The trade is committed **after** the sizer accepts, so a skip
  leaves no armed state (the old order logged phantom trades on the next candle). LIVE sizes off
  `account_info().balance`, refuses when that is unavailable, and logs the sized volume.
  See `docs/PREREG-2026-10-17-risk-sizer.md` (erratum at the top).


## 5. Evidence base (don't re-derive)

Key documents:
- **`docs/REVIEW-2026-10-28-b2-broker-be-time-stop.md` (B2 completion) + `docs/DECISION-2026-10-28-b2-broker-be-and-time-stop.md`
  (the choice, recorded before the code):** why LIVE had to mirror the +0.75R ratchet and the 240-min time stop instead of
  registering a divergence; the exact request/confirm/retry semantics; what is booked and what deliberately is **not**
  (a broker-closed position invents nothing — B3 supplies deal P&L); the restart and disarmed behaviour; the call-graph
  scorecard change (a helper `run_live` cannot reach no longer passes, and no comment or docstring can satisfy a check);
  and the six explicit gaps (no demo evidence, no reconciliation, single position, downtime blind spot, 5 s cadence,
  gate still CLOSED at 11 PASS / 6 TODO / 3 MANUAL).
- **`docs/REVIEW-2026-10-27-g1-decision.md` (G1 decision record + A1 completion):** what the owner actually chose
  (branch A, before any post-change trade existed), what the sign-off does **not** authorise (no engine edit today, no
  second variable, no implied edge), the book as it stood at sign-off (era n=225, 35.8% decisive, −0.081R, guard PASS),
  each A1 tool task with the command that verified it, the two traps hit and closed (`--since` must not default to the
  judged cutover; `era_stats(bar=BAR15)` must return `None` rather than fall back to the 0.5 ATR era), and the **A2
  contract** in five steps. Read it before touching any `clear15` code path.
- **`docs/BRIEF-2026-10-27-g1-owner-decision.md` (G1 decision pack):** the owner-facing one-gate brief — what A/B/hold each mean,
  the refreshed costed replay for `0.5 / 1.0 / 1.5 / revert` at $0.20 / $0.275 / $0.35 per side, the per-trade consequences of `1.5`
  (+31% risk and per-stop cost, −21.6% trade count, longer holds, 22% lower modelled drawdown, SL/day 5.61 → 3.94), the frozen 3/4
  eligibility bar, **why PASS is the unlikely outcome** (Wilson LB > 40% at n=150 needs ≈48% decisive WR vs 35.8% observed / 40.3% best
  replay reading), the timing slack against the 2026-12-01 date gate, and the post-DST daily-break verification (PREREG §2.3). Records the
  gate decision once the owner signs; changes nothing by itself.
- **`docs/REVIEW-2026-10-26-full-system-audit.md` (latest full-system review):** collection 349 / 709 closes / era n=212; all session checks re-run; DST gate MET (**+2h**, EU rule 100%); refreshed clearance grid (1.5 ATR −0.024R/t at $0.20/side, −0.047R at $0.275/side vs live −0.110/−0.140, 3/4 of the pre-declared bar); **LIVE-path audit** (8 open gaps) and the 10-26 hardening; honest live-readiness verdict (two tracks + hard gate). Its companion `docs/PREREG-2026-10-26-structstop1.5.md` is a **DRAFT, not registered** pending G1.
- `docs/REDESIGN-2026-10-23-v2-harness.md`: the v2 post-mortem and redesign — what the v1 ledger says
  is actually wrong (cost/risk, not volatility), what was deleted, what `goldbot/` is, and the
  pre-registration bar a v2 hypothesis has to clear before it means anything.
- **Structural-stop time-gate judgement (recorded 2026-10-19 21:19 UTC; checked-in data through 18:10 UTC on that day, n=139):** `tools/pressure_report.py --root . --era structstop` at the judgement reported all five §7 SCREEN checks inside their bars (B1 5.91 SL/day, B2 46.76% SL share, B3 24.46% scratch share, C1 −0.071R gross, C2 37.50% decisive [28.8–47.1]); **SCREEN MET, PASS NOT MET** (n<150; Wilson LB 28.8% is not >32.1%). Gross era P&L there was −$56.01; at the assumed $0.40 round trip, net −$111.61 (−0.142R/trade); at the quote logger's $0.55 first-look median, −$132.46 (−0.168R/trade). The §7 gap count was **2/2 and the REVERT trigger FIRED**, despite no gap-through or realized gap damage. Full judgement: `docs/REVIEW-2026-10-19-struct-stop-judgement.md`. **Post-gate refresh (2026-10-20 08:59 UTC, docs only):** era n=147 (43W/66L/37BE/1TIME), guard still PASS (0 inside level, 81.6% level-bound, +0.50 ATR median clearance, 3.29 ATR median risk), gap count still **2/2**, logger 6/14 complete days; those are observations on a grown sample (`docs/REVIEW-2026-10-20-post-gate-refresh.md` §3). **Gap-guard resolution (2026-10-25):** registered (`docs/PREREG-2026-10-25-gap-guard-daily-closure.md`) and deployed via PR #58 / `autosync` `71317da` (`02:48:12 UTC`, closed weekend market), with DST-responsive `derive_daily_closure()` (`1c02b2c`); stop geometry held pending observed post-DST offset.
- `docs/ANALYSIS-2026-10-16-dashboard-pressure.md` (**latest, display-only**): documents the dashboard's
  market-context layer (`pressure.py`, `tools/pressure_report.py`) and composite weights. Its dated
  calibration (n=120 struct-stop + n=347 max-hold) found the composite *collinear with side — not
  separable within-side*; the current re-join at n=200 confirms the same verdict (BUY 76 aligned / 5
  mixed, SELL 114 aligned / 5 mixed, no `against` bucket on either side). The other panels provide setup/location/risk context;
  none authorizes a gate, a change to the judged stop experiment, or the still-blocked gap-guard action.
- `docs/PREREG-2026-10-15-level-test-0.25.md` (**pre-registration, not deployed**): the 0.25 ATR level test, its bars and REVERT rules. It is **blocked by the fired 10-19 closure-gap trigger** and is not the next eligible change.
- `docs/ANALYSIS-2026-10-15-stop-loss-rate.md` (**analysis, no runtime change**): "too many stop losses" —
  its publication-snapshot struct-stop book was 39.1% decisive vs 42.0% breakeven at the live payoff; the 10-19 judgement and current figures are recorded above; the replay-vs-live gap is **found and fixed**
  (a blackout end-minute bug in `strategy_lab.py`, tooling only). `tol0.25` remains a pre-registered candidate, but the §7 trigger currently blocks it.
- `docs/REVIEW-2026-10-05.md` (**latest, analysis-only — the scheduled formal
  re-review**): max-hold isolation closed (n=209, 1 TIME, cap never bound
  in-session, −$0.570/trade) → **fallback step-2 trigger MET** (eligible, not
  approved: needs the costed harness + pre-registration + sign-off);
  `H-side-awareness` **DROPPED** (27 decisive counter-trend ✔ but within-SELL
  60-min gap −6.4 pp and the failing side flips at 240 min; no rising-gold
  sub-period supports it); candidate refresh era-correct + risk-normalized
  (RSI≥45 dropped; MAX_ATR tighten normalized-rejected; post-BE fast re-entry
  −0.325R vs −0.104R remains the strongest queued, still observational);
  **new named candidate: London/NY session-band bleed** (39.8% vs 25.4% dec,
  p=0.034, holds in-side/in-ATR/in-era/5-of-5 chunks; proposed bar 4/6, not
  registered); #476 weekend-gap finding; two analysis-tool labels corrected.
- `docs/ANALYSIS-2026-10-01-stop-loss-rate.md` (still the **cost/tooling
  reference**; its ledger numbers are that snapshot's — current numbers are §1):
  448 closed; SL/all 41.1% versus SL/decisive 70.5%; current 0.75R n=273,
  −$0.467/trade, max-hold n=178, −$0.488/trade / 0 TIME. Geometry/labels and
  current-rule replay verified; smoke A–M passed, integrity 0 fail / 8 warn.
  **No bot change justified by the percentage alone.** Next-session queue:
  verify host/feed, repair/calibrate research tools, formal isolation review,
  costed stateful ratchet-off only if approved, separate post-BE-pause test.
  Replaces stale candidate headlines, not historical review records.
- `docs/REVIEW-2026-09-29-feed-outage.md` (6-h silent starvation after
  the 08:29 reboot: evidence chain, the guard bug that hid it, the undocumented
  09-28 precursor, detection fix + ops runbook)
- `docs/ANALYSIS-2026-09-28-falling-gold-win-rate.md` ("WR improves
  when gold falls?" → **wrong cause, no adoption**: real 30.7% vs 25.0% pooled
  gap but day-level null (27.9% vs 28.1%), side-coupled (94/96%), within-BUY
  refuted (13 falling-tape BUYs = worst bucket, 15.4%), whole gap 3 days old and
  inverted in the 09-17/09-18 up-leg (BUY 45.0% vs SELL 12.5%). Registered
  `H-side-awareness` + pre-registered bar — **scored at the 10-05 re-review:
  DROPPED** (fails bar (b) within-SELL and (c) rising-gold).
  Tool: `tools/momentum_regime.py`)
- `docs/ANALYSIS-2026-09-21-revert-or-maintain.md` (whole book before
  vs after the recent parameter changes on 281 trades → **MAINTAIN, revert
  nothing**: new-regime stack −5.7× bleed, 0.30R→0.75R replay −$116 → +$29
  (never back), max-hold exonerated by 0 fires at longest hold 24.9 min;
  today's −$22 trend-day bleed is noise within the pre-registered fallback)
- `docs/ANALYSIS-2026-09-21-win-rate-drop-check.md` ("did the win rate
  just drop?" → **no**: pooled 27.3% at n=271, era 32.3% at n=96, 0 TIME exits,
  ratchet verified firing at ≥0.76R; the recent 0W/4L run is sampled noise +
  the known cooldown leak. Also relabels the dashboard Win-Rate tile
  "**(decisive)** — all eras · excl. BE/TIME · all-in 14.0%", because the bare
  27.3% tile is era-blind and reads like a collapse; the era rate is 32.3%.
  **§2b: the era table** — 271 trades partitioned into 4 non-overlapping books
  (all 27.3%/−$0.625, pre-ratchet n=45 17.8%/−$1.834, 0.30R era n=130
  31.2%/−$0.321, master 0.75R book n=96 32.3%/−$0.471, of which max-hold era
  n=1) — **plus the no-reset decision (binding):** the max-hold deploy resets
  nothing; "closes at deploy" = the sub-period stops receiving trades; the
  falsification bar stays judged on the whole 0.75R book)
- `docs/REVIEW-2026-09-21.md` (max-hold time stop deployment record
  + 90-trade 0.75R close-out)
- `docs/REVIEW-2026-09-18.md` (falsification bar formally tripped; fallback
  starts; auto-trade timeline framework in §5)
- `docs/REVIEW-2026-09-15.md` (last full review — 164 trades; read it for
  the ratchet rationale, it supersedes several older conclusions below)
- `docs/ANALYSIS-2026-09-10-losing-trades.md`
- `docs/REVIEW-2026-09-10-PM.md`

Historical headlines (2026-09-15, 164 trades / 119 new-regime; superseded
for current decisions by the dated reviews above and §6):
- 19.4% decisive (14/72), CI 12.0–30.0; 56% of all trades are $0 scratches.
  Needs 40% decisive to break even at 1:1.5.
- **The ratchet, not the entries, was crushing the win rate.** Same 119 entries
  re-walked at +0.75R: ~45% decisive, +$0.40/trade (cascade-aware). At 0.30R the
  replay reproduces live exactly, which is what makes that comparison valid.
- "Expectancy ≈ −0.5R at every TP placement — entries are the problem" (09-10)
  no longer holds as stated: with the looser ratchet the entry stream replays
  ~50/50. Blocked signals replay 64% decisive (+$198 sequential) vs 19.4%
  taken — cooldown escalation + ratchet explain both sides of that gap.
- RSI < 45 **now meets its pre-registered adoption bar** (new regime: 47 trades,
  10.0% decisive, −$32.22 vs 29.4% for the rest) — candidate #1, adopt next
  cycle.
- ATR ≥ 2.5 (new regime): 0W/4L/13BE, −$27.11 — MAX_ATR tightening is eligible
  but held one cycle so it isn't confounded with the ratchet change.
- ⚠️ Sequence-aware numbers in `docs/REVIEW-2026-09-10-PM.md` §3 used
  `pathwalk_sims.py`, which had its SELL bar extremes inverted (fixed 09-15).
  Anything pathwalk said about SELL trades before this cycle is unreliable.
- **Interim 2026-09-17** (`docs/REVIEW-2026-09-17.md`, 58 trades at +0.75R):
  30.6% dec (CI 18–47), −$0.557/trade — **falsification bar (−$0.40)
  breached in P&L, n=58 < 60**. FOMC 09-16 (+25bp → 3.75–4.00%, 18:00 UTC)
  produced a −$118 (−2.7%) cascade that hit no open trade (escalated cooldown
  17:28–18:28 → MAX_ATR wall 18:02–20:01); 09-16 was already a bleed day
  pre-release, so the breach is not a news fluke. RSI ≥ 45 now ~dropped
  (skip bucket 36.0% dec, −$18.79 vs 27.9% kept); BE-resets-streak
  down-graded (escalation just protected the FOMC hour); ~4h max-hold time
  stop promoted to front of queue. Next check: if P&L/trade ≤ −$0.40 at
  n ≥ 60 → max-hold first, ratchet-off second. Era boundary unchanged:
  09-15 06:00 UTC (PR #9 merged 03:00:23Z, deployed by the 06:00 run).
- **2026-09-28 (380 trades) — "gold falls → WR improves?"** (see the
  ANALYSIS-2026-09-28 doc): the pooled falling-tape gap is real but small and
  insignificant (30.7% vs 25.0%, p=0.37; 240-min p=0.072) and structurally
  confounded with side. Day-level null; within-BUY refuted (falling-tape BUYs
  15.4% vs 23.2% — the worst bucket); the whole gap is 3 trading days old and
  inverts in the 09-17/09-18 up-leg (BUY 45.0% / SELL 12.5%). What survives: the
  recent bleed is the BUY side (max-hold era BUY 14.3% dec / −$84.07 vs SELL
  36.5% / +$10.69), consistent across eras but only nominal (pooled p=0.070,
  p→0.16 without 09-28) and possibly just the −6.7% slide we happen to be in.
  Registered hypothesis + bar; **no gate adopted**.

### 5z. `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` — why the SL rate is high, and the one change that fixes it

**Read this before touching any exit parameter.** Headline findings (all reproducible, §10 of
that doc):

- The level test is **inert**: `FLOOR_BUFFER_PCT = 0.0020` is a *price-%* tolerance, ≈ $8.30 on
  a $4,150 market ≈ **4.5× the median ATR (1.83)**. `Tested_Floor` is true on 86.9% of logged
  bars and 44.5% of the bars that pass it close >2 ATR *above* the level.
- Therefore the stop is **not structural**: median |entry − level| = **2.42 ATR**, so a 2·ATR
  stop sits inside the range (median 0.42 ATR short of it) on **63.8%** of the 0.75R master
  book, and **63.8% of its SL exits** were that class. Median SL lifetime **7.2 min**
  (46% ≤ 7 min, 97.6% ≤ 30 min of a 240-min budget); only 22.3% of trades touched +1·ATR first.
- **Shipped:** stop must clear the level (`SL_CLEAR_ATR = 0.5`), TP = 1.5 × the actual risk.
  Costed replay (master era, $0.15/side): −0.217 → **−0.106R**/trade, −$13.90 → −$5.83/day,
  decisive 32.1 → 37.4%, SL/day 8.2 → 5.4, scratches 33 → 25%, maxDD $255 → $175, 3 of 4 eras
  better (worse pre-ratchet: it needs the ratchet). 0 of 217 post-change trades have a stop
  inside their level (210 of 326 before).
- **Costs of it:** −33% trade flow (occupancy/cooldown, not a gate change), avg SL −$4.20 →
  −$6.80, holds 10 → 22 min (TIME 1 → 7, so more closure-gap exposure), the daily-loss breaker
  fires less (it counts SLs), and expectancy is **still negative at every cost level tested**.
- **Rejected on this data (do not re-derive):** ATR-rescaling the level test (era-unstable,
  0 winners of 21 decisive in the 0.30R slice; and the near-miss bucket is the *worst* of all at
  14.3% dec / −0.409R), stop-only widening that degrades the ratio (49.1% WR but −0.107R),
  min-SL 2.5/3.0/3.5 ATR with RR held (WR up to 50.7%, expectancy flat-to-worse), min-SL
  1.5/1.0 (−0.257/−0.425R), ratchet-off (≈breakeven gross, 61.7% SL share, redundant next to
  the stop fix), the session band (§1), and stacking the entry tolerance on top (≡ the stop fix
  alone).

## 6. Next steps (in order)

**2026-10-30 — canonical queue is `docs/EXECUTION-PLAN.md`; this section is the evidence/backlog.**
**New this session: the paper-ledger runway decision (no top-up) + a registered rebaseline-at-zero rule**
(`docs/ANALYSIS-2026-10-30-simulated-equity-and-paper-runway.md`, `tools/equity_runway.py`). It changes no
parameter and adds no queue step: the ledger stays unbroken and everything keeps being judged in **R**. Re-check
it with `python3 tools/equity_runway.py` (≈38 trades / ≈2.9 trading days at the point estimate, bootstrap 90%
33–336; `--strict` exits 1 at the fire point). **Do not "helpfully" top up the balance** — see §1.
The owner's prompt is **“Follow execution plan.”** — lowest-numbered eligible step only.
**A2 is still the next Track-A step and it is blocked on the host, not on the repo:** G1 is SIGNED and A1 is DONE,
so the one line `SL_CLEAR_ATR = 0.5 → 1.5` may land — but only in a moment when the host has **no open position**,
with `strategy_lab.CLEAR15_CUTOVER` (and `pressure.CLEAR15_CUTOVER`) set to that deploy's
`autosync: merge upstream` commit time, then confirmed by `check_structural_stop.py --era clear15` (it prints
`NOT STARTED` until then, and the OLD/NEW bracket after). As of 2026-10-30 02:59 UTC the host is **not** flat
(**SELL #759 open**), and the host deploys from its own `0 */3 * * *` cron, so this session cannot see the next
flat moment, cannot push `main`, and cannot restart the engine — the step is reported blocked, never faked. Nothing in Track A (A3–A5) may be judged
before that boundary exists.
**Track B is now the runnable track, and (B3) is next:** adoption of an existing broker position on startup,
duplicate-order refusal, realised P&L from `history_deals_get`, and ticket↔trade-number persistence — it closes the
one gap B2 deliberately left open (a broker-closed position currently books nothing and blocks new entries).
**(B4)** disconnect safety, live volume/stops limits and a spread-as-%-of-R veto come after it. **(A6)** the
14-day/two-weekend cost sample is **1 complete day + 1 weekend short** (13/14, 1/2; measured round trip $0.55).
**Host:** verify `mt5feed` / the `goldbot` restart for the 10-25 ~2 h Sunday-reopen bar hole (the **post-DST daily break is
confirmed** against `derive_daily_closure()` — that item is closed).
`python3 tools/live_readiness.py` currently reports **11 PASS / 6 TODO / 3 MANUAL → LIVE GATE CLOSED**;
every Track B step must turn one check green with a hermetic test. No real orders, no LIVE,
no `GOLD_LIVE_ARMED`, no second strategy variable.

**Telegram routing + session watch plan (2026-10-23): owner sign-off, then a normal deploy.**
The engine change (`GOLD_TELEGRAM_KINDS`) means **`goldbot` restarts** on deploy; it is a message
filter, not a strategy change, and with the knob unset the behaviour is identical. To actually
get the intended chat (≈7–9 messages/day instead of ≈82) the owner must, after sign-off, put
`GOLD_TELEGRAM_KINDS=none` (or `feed,risk` to keep ops alerts) and optionally
`GOLD_DIGEST_EVERY_HOURS=12` in `/opt/gold/.env` — no code deploy is needed for those two
values, but nothing changes without them. **The twice-daily watch plan (07:00 / 13:00 UTC) needs
`deploy/boxalert.service` installed**; the unit is still optional and not installed by this
change, so without it neither the plan nor the instant notice is sent (the digest would say
`box alerts: Telegram pair found · notifier not running`). Prove it first with
`python3 tools/box_alert.py --plan --dry-run` and `--test`. Revert is `.env`-only:
unset the knob, `GOLD_DIGEST_EVERY_HOURS=0`, `--no-plan`. Full record + measured volume table:
`docs/PROPOSAL-2026-10-23-telegram-routing.md`. **If the unit is never installed**, the plan can
still be driven from cron (`*/5 7,13 * * * cd /opt/gold && GOLD_DATA_DIR=/opt/gold python3
tools/box_alert.py --plan`), because it needs no daemon — only a run inside the 15-minute anchor
window, and its dedupe makes extra runs harmless; the instant break notice is the part that needs
`--loop`. The digest's `🔔` line now ends with `last plan … · next … UTC`, so a plan that never
fires is visible without checking the box. This changes nothing in the struct-stop window,
the fired §7 closure-gap trigger, or the still-blocked gap guard.

**Redesign + scalper removal (2026-10-23): dashboard-only deploy; the engine is untouched.**
The Manual Scalping page was **removed** at the owner's request, superseding the build note above: the
routes, modules, guide and tests are deleted and `GOLD_MANUAL_JOURNAL_FILE` is read by nothing. In the
same session the v1 post-mortem was written up and the v2 harness (`goldbot/`) was added — a separate,
pure-stdlib package with no engine import and no order path, so it cannot affect the forward test.
`DASH_CHANGED` restarts the dashboard for `dashboard.py`, `pressure.py`, `chart.py` or `goldbot/`; the
engine unit does not restart. Local render: `GOLD_DATA_DIR=. python3 dashboard.py`.
Refresh follow-up (2026-10-23): main-dashboard tab switches now update `?tab=` with
`history.replaceState` as well as localStorage, so the 15-second meta-refresh cannot replay an old
`?tab=chart` deep link and pull the operator away from Journal, Boxes, Simple, or Full. Explicit
deep links still win on first load, and chart `tf` is preserved. No engine behavior changes.
Next evidence action is operational, not a strategy change: accumulate and review ≥100 closed manual rows
with positive expectancy after measured costs before believing a method. Still open from the Chart tab:
whether to draw the bot's open paper trade (entry/SL/TP/ratchet) on the chart. No engine/gate/exit work is
authorized by this dashboard feature.

Dashboard + notifier PR: review the read-only panels and the alert rule, then deploy
**dashboard-only** after sign-off; no engine restart. The 2026-10-20 manual watch cards
(BUY/SELL price references, hypothetical stop/target, costed payoff, stale/chase warnings)
are unchanged, and the 2026-10-21 session supersedes exactly one line of
`docs/REVIEW-2026-10-20-box-watch-cards.md`: retests **are** now tracked, on a box frozen at
the break, with the measured verdict that waiting for the held retest showed no edge
(`docs/ANALYSIS-2026-10-21-box-chop-retest-alerts.md`). The Telegram notifier is **optional
and not installed by this change**; installing it is the owner's action, and `GOLD_BOX_ALERTS=0`
disables it. **Digest-line fix (later 10-21):** the 18:00 digest's `🔔 box alerts: not configured`
was a wiring bug (autosync never hands its Telegram pair to a child), not a missing pair. After the
fix merges, expect `🔔 box alerts: Telegram pair found · notifier not running (optional: install
deploy/boxalert.service)` until the owner installs the unit, then `running · …`
(`docs/AUTOSYNC.md` §3). The current machine snapshot is the marked block at the top of this file;
the earlier 08:59/11:59 narratives remain dated assessments, not new experiment judgements.
**The gap-guard blocker is unchanged** — no runtime change was made.

**Ledger numbering finding (2026-10-25): duplicate `Trade_Num` #697 — FIXED & DEPLOYED (`8d84dcf` via `71317da`).** The ledger
has two rows numbered 697 (the 10-23 11:17 BUY, SL; the 10-23 15:15 SELL, TIME — should be #698).
Root cause: on restart while a trade is open, `restore_open_trade_from_status()` restored
`current_trade_num` but not `next_trade_num`, and CSV rows are written only at close — so the next
trade reused the number (same pattern as the long-standing #1/#2/#3 and #171 duplicates). No metric
or judgement is affected (row-based tools; balance chain and `status.json` agree; `next_trade_num: 698`).
Fixed in `8d84dcf` + smoke Scenario Y and deployed at `2026-10-25 02:48:12 UTC` (`71317da`); the historical
duplicate row was deliberately left un-renumbered (`docs/REVIEW-2026-10-25-duplicate-trade-number.md`).

**Priority incident blocker (2026-10-19):** recovery tool and safeguards are prepared
for owner merge; full smoke + repair tests pass. Merge alone does not repair the host.
 operator should pause the paper engine,
preserve host CSV/status/journal and verify the running executable/revision before
restarting corrected code. Reconcile/quarantine invalid rows only from backed-up evidence;
do not reset to $500 or interpret raw negative equity as a broker loss. No live files
were repaired in this session. See `docs/REVIEW-2026-10-19-negative-balance.md`.

**Session execution queue:** `docs/EXECUTION-PLAN.md` is the concise, chronological
sequence to follow when the owner says **“Follow execution plan.”** (alias “Execute the plan.”).
Its opening section defines the phrase's authority and two approval gates. This section retains
the detailed evidence and backlog. Dated pre-registrations/reviews are the source
of truth for experiment thresholds; always refresh from current data.

0. **Ops verification first (updated 2026-10-26):** the quote logger is healthy again
   (11/14 days, 1/2 weekends, newest row `2026-10-26 11:59:30 UTC`) and the DST offset is
   **observed** (+2h, EU rule). Two host checks remain: (a) the **price-bar** log resumes only at
   `2026-10-25 23:59:24 UTC` while quotes were fresh from 22:00 UTC — ~2 h of open-market M1 bars
   are missing, so verify `mt5feed` / the `goldbot` restart; (b) confirm the first **post-DST daily
   break** (due 10-26 evening) against `derive_daily_closure()`, which still returns `(20:58, 22:00)`.
   Runbook + drop-in in `docs/REVIEW-2026-09-29-feed-outage.md` §7
   (`Restart=always`, `TimeoutStopSec=30`, `KillMode=control-group`, `systemctl enable`).
   Recover the terminal only if it is stalled; do not infer a fresh outage from a
   cloned snapshot's age. Check `mt5_last_candle.json` mtime/`updated_at`, live
   status/log progression, `📈 candles: ok` and journal recovery/health lines.
   Host-side process/deployment verification and any later unsynced data remain operator-only.
   **Research prerequisite (DELIVERED 10-05):** `tools/strategy_lab.py` is the costed,
   stateful, era-matched, direction-aware replay the 10-01 §4 list demanded (funnel recall
   99.7–100% per era; cost on every exit incl. BE; production cooldown/breaker semantics).
   Era/pooling labels in `win_rate_report.py` and the false long-hold warning in `check_data.py`
   were fixed earlier the same day. Remaining §4 items are cosmetic-for-decisions (MFE/MAE
   alignment in `analyze_losers.py`, decisive-WR labels in `pathwalk_sims.py`/`phantom_trades.py`)
   but those tools stay **descriptive only**.
   Calibrate each era's actual rule before trusting any hypothetical P&L.
   Tools-only validation does not authorise runtime/strategy changes.
1. **STRUCT-STOP TIME-GATE JUDGED 2026-10-19 21:00 UTC; GAP GUARD DEPLOYED 2026-10-25 02:48:12 UTC (`71317da`)**
   (judgement evidence in `docs/REVIEW-2026-10-19-struct-stop-judgement.md`; guard pre-registration in
   `docs/PREREG-2026-10-25-gap-guard-daily-closure.md`).
   The structural-stop rule remains in the checked-in engine: entries ≥ **2026-10-06 03:00 UTC** use
   `SL_CLEAR_ATR = 0.5` + `RR_TARGET` TP. At the judged **n=139** the geometry guard and A1–A5 pass; the
   registered **SCREEN MET** (SL/day 5.91, SL share 46.76%, scratch 24.46%, gross −0.071R/trade, decisive
   WR 37.50% [28.8–47.1]). **PASS NOT MET**: n<150 and Wilson LB 28.8% is not >32.1%.
   The era has since grown to **n=200** with all bars still inside their thresholds (SL/day 6.00, SL share
   45.00%, scratch 26.50%, gross −0.052R, decisive 37.93% [30.4–46.0]; gross −$61.49). Those are
   **post-gate observations, not a re-judgement**: the n=150 confirmatory arm lapsed when the time gate
   came first (`docs/REVIEW-2026-10-20-post-gate-refresh.md` §3).
   `check_gap_rides.py` reports **3/2** (#595/#610/#687; $0 realized gap damage), firing the §7 extra
   REVERT trigger ("revert and take the gap guard first"; the 0.25 ATR test does not proceed).
   **PR #58 (`d38117a`) registered and implemented the 30-min entries-only daily-closure gap guard, and
   `autosync` (`71317da`, 2026-10-25 02:48:12 UTC) deployed it into the closed weekend market.** On this
   branch (`1c02b2c`), `derive_daily_closure()` is made DST-responsive (recent 5-break modal baseline +
   immediate Day-1/Day-2 `±60 min` Sunday-reopen / post-weekend shift adaptation) so EU/US DST transitions
   never lag 10+ trading days behind a 30-day mode. **Owner decision (2026-10-25 post-merge):** hold
   `SL_CLEAR_ATR = 0.5` + gap guard through Sunday reopen / Monday until the post-DST broker offset
   (`+2h` EU vs `+3h` US) is observed, then decide between pre-registering **`structstop1.5`**
   (`docs/ANALYSIS-2026-10-25-stop-hunt-markouts-and-clearance-grid.md`) or executing the literal §7
   structural-stop revert. Keep the bot paper-only. Original SCREEN/PASS/REVERT thresholds in the 10-05
   analysis remain binding.
2. **Max-hold isolation: CLOSED 10-05** (`docs/REVIEW-2026-10-05.md`). Verdict:
   n=209, 1 TIME exit (the 49.1-h weekend-gap hold #476), **the cap never bound
   an in-session trade** (longest non-TIME hold 68.0 min) → keep it as cheap
   insurance, it is **not** the cause of the SL cluster. Era result −$0.570/trade,
   −$8.64/calendar day.
   **Fallback step-2 (ratchet-off): trigger was MET (n=223, −$0.646/trade), the harness
   prerequisite is now delivered, and the measured answer is NO.** It is *not* worse than the
   live baseline in isolation (−0.162R vs −0.245R pooled master, $0.20/side) — but it buys
   that only by **deleting the scratch bucket: 61.7% of trades become full stop-outs** (45.4%
   today), its gross expectancy is ≈ breakeven (−0.052R), and **stacked on the shipped
   structural stop it adds nothing: −0.131R vs −0.124R** (`--only structstop,structstop+nord`).
   Spending an isolation slot on a variant that is redundant once the stop is fixed is not
   worth 2+ weeks. **Recommendation: close step 2.** Owner may override with a pre-registered
   bar; **never** back to 0.30R either way.
3. **Queued strategy changes** — refreshed 10-05; candidates only, no adoption
   (all numbers 0.75R master / max-hold era; `R` = Profit ÷ 2·ATR, which equals actual risk
   on every pre-2026-10-05 row — see Definitions):
   - (a) **RSI ≥45 — remains DROPPED.** keep 31.0% dec / −0.151R vs skip
     32.5% / −0.135R (max-hold: −0.175R vs −0.135R). The skip bucket is better
     in both books. Do not reopen without a new era-correct pre-registration.
   - (b) **BE resets the SL streak** (cooldown de-escalation) — still queued,
     still **down-graded** (FOMC escalation covered 17:28–18:28 UTC). Needs the
     calibrated cascade tool first; do not combine with a post-BE pause.
   - (c) **RISE120 entry gate — REJECTED / dropped.**
   - (d) **MAX_ATR 4.50→2.50 — NORMALIZED-REJECTED 10-05.** ATR<2.5 −0.146R vs
     ATR≥2.5 −0.143R (max-hold: −0.174R vs −0.092R); the dollar gap was
     position risk. ATR<2.0 also loses (keep −0.197R vs skip −0.063R). Drop
     unless a costed harness says otherwise.
   - (e) **Momentum / `H-side-awareness` — DROPPED 10-05** (fails bar (b) and
     (c); see REVIEW-2026-10-05 §3). No BUY ban / SELL-only / momentum gate.
     The BUY-side bleed is observation only (max-hold BUY −$1.306/trade,
     p=0.2031 — weaker than the 10-01 p=0.1137).
   - (f) **Session-band gate (London/NY bleed) — DOWNGRADED 10-05 (same day), do not
     adopt or stack.** Measured with the costed stateful harness: baseline Asia +0.022R vs
     London/NY −0.246R (gap 0.268R), but under the shipped structural stop the same split is
     +0.001R vs −0.084R (**gap 0.085R**) — the band was largely a **proxy for the stop-geometry
     defect**, so it fails REVIEW-2026-10-05 §5a's independence clause (b). Ledger-only
     description (39.8% vs 25.4% dec, pooled p=0.034) stands as history, not as a gate.
   - (g) **Post-BE <5-min same-side re-entry pause — strongest queued
     entry candidate.** master −0.325R vs −0.104R (n=57); max-hold −0.389R vs
     −0.111R (n=36). Observational only: needs the stateful cascade replay and
     a pre-registered bar; separate from the SL-streak change.
   - (i) **Level-test re-scale to 0.25 ATR — pre-registered 10-15 and owner-approved, NOT deployed**
     (`docs/PREREG-2026-10-15-level-test-0.25.md`). **Blocked by the 2026-10-19 §7 gap-risk REVERT
     trigger; do not run or deploy it.** The dated pre-registration still owns its bars if it becomes
     eligible in a later, separately authorised window. It predicts a borderline master-book result
     at the assumed $0.20/side (−0.062R/trade), is era-unstable, and expects about 6.3 trades/day
     (~16 trading days to n=100; ~24 to n=150). It is an experiment, not a claim of profitability.
     Reproduce with `tools/strategy_lab.py --grid level`; do not re-register or tune it after seeing data.
   - (h) **Pre-close entry guard — REGISTERED & DEPLOYED 2026-10-25 (`71317da`)**
     (`docs/PREREG-2026-10-25-gap-guard-daily-closure.md`). Named 10-05 from the #476 weekend hold
     (`docs/REVIEW-2026-10-05.md` §5b); owner-approved 2026-10-25 as **30-minute cutoff, entries only**
     (no flattening of open positions), derived from observed price-log daily breaks (`20:58 → 22:00 UTC`
     under `+3h`), fail-open below 3 breaks, wired ahead of trade-number assignment (Scenario Z), with
     DST-responsive adaptation (`1c02b2c`). Flattening open positions before close and a **scheduled-news
     gate** remain separate, unadopted candidates.
   - (j) **Stop-clearance 0.5 → 1.5 ATR — pre-registration candidate, NOT registered (replayed
     2026-10-25, `docs/ANALYSIS-2026-10-25-stop-hunt-markouts-and-clearance-grid.md`).** Costed
     stateful replay (post-cutover era): −0.000R/trade net at $0.20/side, −0.023R at measured
     $0.275 vs live −0.102/−0.132; passes 3 of 4 pre-declared bars (n −21.3% misses, mechanism
     disclosed); 1.0 ATR fails bar 1 (+0.026R < +0.05R) and is measured-and-insufficient. One
     variable (`SL_CLEAR_ATR`, TP stays 1.5× actual risk); drafted SCREEN/PASS/REVERT bars mirror
     the 2026-10-05 registration. **Held until the post-DST broker offset (`+2h` vs `+3h`) is observed
     after Sunday's reopen** (owner decision 2026-10-25; gap guard is now deployed), with no further
     point-tuning (2.0 ATR needs its own registration).
   - Ratchet falsification: **TRIPPED** (09-17, −$0.595 at n=60; now −$0.581 at
     n=318 master). Max-hold fallback delivered **no** improvement to blame or
     credit (§1). Step 2 (ratchet-off) measured 10-05 and **rejected** — see above.

4. Historical research — **path BUILT 2026-10-13, first run on the box pending** (`docs/ACCELERATE-TESTING.md`):
   dump M1 with `tools/mt5_history_dump.py`, convert with `tools/history_to_log.py` (it **proves** the
   server-time → UTC conversion against the live log's MT5 era, picks the DST rule from the data, drops the
   forming bar and refuses rather than guesses), then `python3 tools/strategy_lab.py --bars history_utc.csv`
   (today's rules, constant 0.75R ratchet by default, OOS vs in-sample split at 2026-09-04, monthly windows, cost
   sensitivity). It buys ~14.5 weeks of replay (100k bars), ~9 of them out-of-sample for the rules. A result there is
   a **hypothesis to pre-register**, never a reason to change anything inside an open window; the live forward
   test stays the authority. **Two traps, both handled by the converter:** the dump's `Timestamp` is the broker-server
   epoch labelled UTC (+3 h today, flips on the broker's DST — Sunday 2026-10-25) and its last row is the
   still-forming bar. Do **not** port BTC's UTC `ts` change into the live `mt5_feed.py`: the persisted
   `mt5_last_candle_ts` watermark would make the engine's dedup drop ~3 h of candles (assessment F4).

5. LIVE-mode broker-side BE modify — only if/when switching to real orders.
   Note the ratchet level is now +0.75R, and the engine-side-only caveat still
   applies.

6. **BTC-port queue (assessed 2026-10-13, `docs/ANALYSIS-2026-10-13-btc-port-assessment.md` §3–§4).**
   *Done (on the branch):* machine-checked handoff + digest line, `docs/AUTOSYNC.md`, the guard/harness fixes,
   `win_rate_report.py --spread`, the GOLD quote + spec logger and report, the large-N history path.
   *Owner decided:* leave `NOTIFY` as it is.
   *Quote logger in progress (checked 2026-10-25 on collection 335):* `python3 tools/xm_quote_report.py`
   reports **10/14 complete UTC days** and 1/2 complete weekends (31 653 rows); median spread/round trip is
   about $0.55. **Currently STALE (~11.3 h old at the 02:48 UTC autosync):** the newest synced row is
   `2026-10-24 15:34:30 UTC` (Saturday — no `quotes-2026-10-25.csv`), plus the earlier 10-21 ~1 h tick stall;
   restart/verify `mt5quotes-gold` on the host before Sunday reopen so weekend #2 and the post-DST tick offset
   are captured. Keep the $0.40 assumption until the report reaches 14 complete days including 2 weekends, then
   re-cost with `win_rate_report.py --spread` / `strategy_lab.py --cost`. Spread alone does not measure all
   slippage/commission. Verify the observed server offset around the 2026-10-25 DST change; do not guess — the
   data so far shows a single **+3 h** offset, and the EU rule (**2026-10-25 01:00 UTC**) and US rule
   (**2026-11-01 06:00 UTC**) disagree between those dates, so that window identifies the rule.
   *Still pending on the box (tooling only):* one history dump → convert → replay (`docs/ACCELERATE-TESTING.md` §2).
   *After the struct-stop judgement, later runtime candidates still need separate pre-registration:* gap-aware stop fills (BTC PR #14: fill at the candle open if the bar opens through the stop) and the whole-day daily-breaker window (`load_recent_trades(n=400)`; latent, never bitten) remain deferred. The **pre-close entry guard (item 3(h)) is now registered and deployed (`71317da`)**, with DST-responsive adaptation (`1c02b2c`).
   *Not for gold now:* `live_readiness` / `live_path_probe` / order executor / GO-LIVE window (no positive point
   estimate to stage), `reconcile_stale_trade` (no stuck trade; #577 verified).

7. **Dashboard market read layer (2026-10-16) — display-only, keep it that way.** `pressure.py` mirrors
   `engine.py`/`trade_filter.py` constants instead of importing them, and **Scenario U pins every
   mirror** (plus the §7 thresholds and `LIVE_CUTOVER`) so a change to either side fails the deploy gate
   — if a threshold moves, move it in both places in the same commit. The panel's era card reports the
   §7 bar; it never judges it, and its R/trade is `win_rate_report.py`'s cost-view scale
   ($/trade ÷ mean 1R, rebuilt from the reward leg) so the two cannot disagree. Refreshing the printed
   calibration is `python3 tools/pressure_report.py`; the dashboard re-joins the ledger itself every
   10 min. **No dashboard number may become an entry condition without a pre-registered bar (§11).**

8. **Risk sizer + gates (2026-10-17) — deployed, corrected the same session; paper-inert now.**
   The sizer is **LIVE-only** (`size_lots` returns `LOT_SIZE` with no broker account), the trade is
   committed atomically after the sizer accepts, LIVE refuses to size without `account_info()`, and
   the **FOMC 17:55–18:30 window is reverted** (blackouts frozen by §6.1; it moved era R/trade by
   ~0.023R on 3 entries — re-register after 10-19). `MIN_SPREAD_POINTS` stays, LIVE-only.
   Pre-registration + erratum: `docs/PREREG-2026-10-17-risk-sizer.md`; deploy gate: smoke
   **Scenario V**. **Weekend / flat-before-close stays deferred** to a separate PR after 10-19
   (§6.3(h) — it reads the wall clock, so it is not hermetic). The **1:2 target (SL 1.5× / TP 3.0×
   ATR)** stays blocked until the 2026-10-19 judgement (§6.1) — nothing here touches
   `ATR_SL_MULT` / `RR_TARGET` / `SL_CLEAR_ATR`.


## 7. How to verify code changes (always)

```bash
python3 tools/smoke_test.py          # must print "SMOKE TEST PASSED"
python3 -m py_compile engine.py trade_filter.py
python3 tools/check_data.py          # expect "0 fail"
python3 -m py_compile tools/*.py     # analysis tools must at least import
python3 tools/win_rate_report.py     # must run end-to-end on current data
python3 tools/momentum_regime.py     # same, plus prints the registered bar
python3 tools/strategy_lab.py --calib-only        # funnel recall must stay ~100% per era
python3 tools/check_structural_stop.py            # stop-vs-level invariant (post-cutover: 0, PASS) + boundary evidence
python3 tools/check_gap_rides.py                   # §7 closure-gap trigger: rides over a closure + the damage facts
python3 tools/handoff_check.py                    # this file vs the data (FRESH); --update after a refresh
python3 tools/xm_quote_report.py --quiet          # "not collecting yet" until mt5quotes-gold is installed; never errors
GOLD_DATA_DIR=. python3 tools/box_alert.py --plan --dry-run  # the 07:00/13:00 watch-plan message, sent to nobody
python3 tools/box_alert.py --quiet                # the digest's 🔔 line, now ending with the plan state
python3 tools/pressure_report.py                 # dashboard read layer end to end (tape/gates/§7 era/calibration)
                                                  #   smoke Scenario U pins its mirrors to engine/trade_filter
python3 tools/strategy_lab.py --bars forward_test_log.csv > /dev/null   # history mode still runs end to end on real bars
```

Note: `tools/` scripts are NOT covered by smoke_test.py and several of them
have historically crashed or lied on new data shapes (2026-09-15: ZeroDivision
on ratcheted-stop rows, inverted SELL bars in pathwalk). Run them after every
data drop, not just after code changes.

- **Exit / stop / TP geometry changes** must additionally (a) be replayed costed and stateful
  with `python3 tools/strategy_lab.py --table --only baseline,<new-variant>` across **all four
  parameter eras** — a variant that wins in one era is noise, and `exit_sims.py` /
  `pathwalk_sims.py` / `phantom_trades.py` are cascade-ignorant and must not
  decide them; (b) carry a mechanical invariant checkable from the ledger alone
  (`tools/check_structural_stop.py` for stop-vs-level) — a code fact is a far stronger early
  signal than expectancy at n=20; and (c) be mirrored in a smoke Scenario. Bar shape:
  `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` §7.
- **A runtime change's cutover is its deploy time, not its plan.** Read it from the host's
  `autosync: merge upstream` commit (`git log --grep 'autosync: merge upstream' --format='%H %cI'`;
  `docs/AUTOSYNC.md` §2), set the era constant from that, and let the invariant check confirm it from the
  ledger *before* anyone reads a P&L row (10-13: the struct-stop cutover was dated 6 h early). Build the
  boundary evidence into the invariant check of any new runtime change.
- **Smoke scenarios are the deploy gate (autosync rolls back on a red one) — keep them hermetic.** Synthetic data
  in a temp dir, never the live CSVs (they change every 3 h), no wall clock, no dependence on a constant that a
  later legitimate change will move (Scenario O pins `LIVE_CUTOVER` for this reason).
- **Smoke tests must not read the wall clock.** Scenario L (`mt5_feed_problem` quiet-hours) did;
  it passed in market hours and failed at 00:09 UTC on 10-05 on a *clean* checkout. It is now
  pinned inside the scenario. If a scenario goes red only between 21:00–01:59 UTC or at a
  weekend, suspect the test before the code.

## 8. Data gotchas (hard-won)

- `trades.csv` has historical Trade_Num resets — dedupe by timestamp.
- **Ratcheted rows** log the *live* stop: at the 10-01 snapshot,
  `Stop_Loss == Entry_Price` on **256 rows: 187 BE + 69 TP**. Reconstruct the original
  geometry from the **reward leg**, not from the ATR multiple: `risk = |TP − Entry| ÷ 1.5`
  (the ratchet never touches TP). That is exact in **both** regimes — pre-2026-10-05 it
  reproduces risk = 2·ATR, after it the level-bound risk (median 3.07 ATR) — whereas
  `entry ∓ 2·ATR` silently *understates* risk on every level-bound trade and would inflate
  apparent R. `win_rate_report.py`, `check_structural_stop.py` and `strategy_lab.py` all use the
  TP-leg rule. For exact baseline calibration, preserve the logged target and account for
  ATR/price rounding; see ANALYSIS-2026-10-01 §4.
- **A %-expressed price tolerance is not a constant in ATR terms.** `FLOOR_BUFFER_PCT = 0.0020`
  looked like "0.2%, basically at the level" but on a $4,150 metal that is ~$8.30 ≈ 4.5× the
  median ATR, and it silently disabled the entry gate (86.9% of bars pass) — see
  ANALYSIS-2026-10-05 §2. Every threshold in this funnel must be ATR-scaled; the corollary is
  that a change whose *benefit* comes from an ATR-relative distance will read differently as
  the metal's price drifts, so re-check these numbers after a large regime/price move.
- `status.json` `win_rate` is decisive (TP/(TP+SL)); dashboard tile now labels it.
- Balance vs sum(Profit) drift is known (~$10–25); order of magnitude is the authority.
- Entry times are UTC; local session labels (London/NY) use UTC windows in code.
- **Momentum at entry must be measured strictly before the entry bar** (the
  price log lags `trades.csv` by ~1 min — `tools/momentum_regime.py` uses
  `entry − 1 min` for "now" and the same offset for the window start). Never
  include the entry minute's close in a pre-entry feature.
- **A frozen `mt5_last_candle.json` is not a quiet market.** The sidecar
  rewrites the file every 5 s even when the market is closed, so a stale mtime
  means the *publisher* died (terminal logged out/stuck) — the only reliable
  signal, because with a frozen file no candle is ever accepted and
  `feed_stale_seconds()` stays `0.0` (2026-09-29). The engine now checks the
  heartbeat before the dedup; see `mt5_feed_problem()`. Full incident record (6 h of silent
  starvation, the invisible `0.0` staleness, the ~283-minute precursor) in
  `docs/HANDOFF-HISTORY.md` and `docs/REVIEW-2026-09-29-feed-outage.md`.
- **Never read a momentum/regime claim without a side split**: the trend gate
  makes falling tape ≈ SELL and rising tape ≈ BUY (94%/96% in the book), so
  pooled momentum numbers are side numbers in disguise (2026-09-28).
- **Dollars measure position size, not signal.** ATR varies 1.10–4.50, so a
  $/trade gap can be pure risk-sizing (the MAX_ATR candidate died exactly this
  way on 10-05). Normalize: `R = Profit ÷ (2·ATR_At_Entry)` before comparing
  buckets, and still cost the result.
- **The 240-min TIME stop cannot fire while the market is closed** and closes
  on the first candle/tick back: a position can ride a daily/weekly closure
  (#476: 49.1 h wall-clock, −$1.52 on the Sunday reopen). Do not read a long
  hold as "the cap failed", and do not assume the stop is enforceable across a
  gap in LIVE.
- `tools/analyze_losers.py` prints "Skip 23:00-06:59 UTC (Asia/rollover)" with
  keep = the **London/NY** book. Read keep/skip labels carefully — the *skipped*
  199-trade bucket was the better one (10-05 §5a).

- **Blackout end boundary (fixed in the replay 2026-10-15).** `trade_filter.is_in_blackout` is `start <= now.time() <= end`
  on the full timestamp. A bar stamped HH:MM is evaluated seconds after the minute opens, so the end minute is **not**
  blocked. `strategy_lab.py` used an inclusive minute and blocked 09:00 and 15:15 wrongly; that alone made the
  struct-stop era look 4–5 pp too good. Replays from before 10-15 carry that error.

## 9. Architecture quick map

```
engine.py          signals + structural stop + BE ratchet + max-hold TIME + state machine
trade_filter.py    portfolio gates (cooldown, daily breaker, blackouts, ATR)
dashboard.py       Flask status page; every panel read-only (the /scalp write routes are gone)
pressure.py        read-only market-context layer for the dashboard (tape pressure, engine-gate read,
                   location/risk, portfolio state, §7 era card, feed health, box geometry/chop/retest
                   and the pure box-alert decision + rate limiter) — stdlib only, no writes
chart.py           read-only chart + placement layer for the Chart & Placement tab:
                   M1->M5/M15 aggregation, pixel-space chart primitives (candles/levels/session bands),
                   cost ruler, entry/stop/target cards — stdlib only, no writes, no engine import
goldbot/           the v2 harness (config/data/indicators/signal/risk/portfolio/replay + CLI). Pure
                   stdlib, no engine import, no order path. Not a service; run by hand.
tools/strategy_lab.py   canonical costed/stateful/era-matched replay (exit+gate decisions)
tools/check_structural_stop.py  ledger-side invariant guard for the 2026-10-05 change (+ deploy-boundary evidence)
tools/handoff_check.py  machine-checks the snapshot block at the top of THIS file (autosync digest: 📝 handoff)
tools/pressure_report.py  what the dashboard shows, printed (--root/--era/--json): tape, gates, location,
                   portfolio, §7 verdict, CALIBRATION (does the pressure composite separate outcomes?)
tools/mt5_quotes.py     read-only Wine sidecar: 30 s XM quotes + contract spec -> xm_data/ (deploy/mt5quotes.service)
tools/xm_quote_report.py  what the logger measured: spreads, cost vs the assumed $0.40, server clock, spec (digest: 📡)
tools/equity_runway.py  paper-ledger runway: ledger vs true equity vs drift, era $ burn, trades/days to $0, and the
                   registered rebaseline-at-zero state (read-only; no engine import)
tools/broker_time.py    the EU/US DST rule for XM's server clock (verified only by observed offsets)
tools/box_report.py   live boxes + the measured box verdict, the chop/retest read and `--alert-scan`
                   (how many Telegram notices the current rule would have sent)
tools/box_alert.py    OPTIONAL display-only Telegram notifier: the same pressure.box_alert() decision
                   the dashboard previews, rate-limited, PLUS the 07:00/13:00 UTC session watch
                   plan (--plan, also run by --loop); writes only its own state (deploy/boxalert.service)
tools/history_to_log.py broker-history (server time) -> validated UTC bars for `strategy_lab --bars`
tools/             other analysis / integrity / report scripts (not on the hot path)
/opt/gold/         live deploy root (autosync from main; never hand-edit)
```

## 10. Deploy & ops

- **Source of truth for live code:** `main` on GitHub.
- Autosync: every 3 h from `/opt/gold` (`tools/autosync.sh`); refuses if local
  dirty. Force: `sudo /opt/gold/tools/autosync.sh`.
- A "daily Grok job" is documented to refresh `docs/HANDOFF.md` §1 from `status.json` + `trades.csv`; the last
  refresh PR is **#22 (2026-09-25)** and §1 was 8 days stale on 10-13 — do not rely on it. The snapshot block
  is machine-checked instead (`tools/handoff_check.py`; the digest line `📝 handoff:` is advisory and never
  blocks a deploy), and `--update` is the deterministic way for any job or session to refresh it.
- Full autosync runbook, digest legend and the "deploy time = cutover" rule: **`docs/AUTOSYNC.md`**.
- Autosync digest now carries `📈 candles: ok (N open min) | STALE N open min`
  (phase 4b, added 2026-09-29): open-market minutes since the last logged candle,
  weekend/daily break excluded, shouts at > 90. A green digest with `no new
  data` no longer means "all fine" on its own.
- Services: `goldbot.service` (engine), `mt5feed.service` (Wine MT5 sidecar), and — once installed per
  `docs/XM-LOGGER.md` — `mt5quotes-gold.service` (read-only quote/spec logger; autosync commits its `xm_data/` and
  the digest shows `📡 xm logger: …`; a ⚠️ means the logger is down, not that gold is shut).
- **Optional** `boxalert-gold.service` (`deploy/boxalert.service`, added 2026-10-21): the box-watch Telegram
  notifier. It is a *notification*, not part of the trading path — it places no order, imports no engine module
  and writes only `box_alert_state.json` (git-ignored). Not installed by default; `GOLD_BOX_ALERTS=0` disables it
  without uninstalling. Autosync restarts it when `tools/box_alert.py` **or** `pressure.py` changes and shows an
  advisory `🔔 box alerts: …` line that never blocks a deploy. That line reads the pair and the knobs from
  `/opt/gold/.env` (put overrides there, not in the unit), and says `running` only while the loop's heartbeat
  is fresh: `Telegram pair found · notifier not running` = not installed, `notifier STOPPED` = it died (states:
  `docs/AUTOSYNC.md` §3). Test before installing:
  `python3 tools/box_alert.py --once --dry-run`, then `--test` (no `set -a; . ./.env` needed). Since
  2026-10-23 the unit has **two jobs**: the rate-limited break notice and the twice-daily session
  watch plan (07:00 / 13:00 UTC; `--no-plan` drops the second). Volume measured at **5.1 messages/day**
  (`tools/box_report.py --alert-scan`); `GOLD_BOX_ALERT_DAILY_CAP` is the knob that binds.
- A `dashboard.py` / `pressure.py` / `chart.py` / `readiness.py` / `tools/live_readiness.py` /
  `goldbot/` change is a **dashboard-only** deploy
  (`DASH_CHANGED`): the dashboard service restarts, the `goldbot` engine unit does not. Main tabs are
  `Simple`, `Journal`, `Chart & Placement`, `Boxes & Timing`, **`Readiness`** and `Full`; there is no separate
  manual workspace any more. Tab preference uses `localStorage` + `?tab=`; `?tf=1|5|15` picks the chart
  timeframe. For a local render: `GOLD_DATA_DIR=. python3 dashboard.py` (also `GOLD_LOG_FILE`,
  `GOLD_TRADES_FILE`, `GOLD_SKIP_FILE`, `GOLD_STATUS_FILE`); defaults stay `/opt/gold/*`.
  `goldbot/` is never deployed as a service — it has no daemon and no order path.
- **🚦 Readiness tab (2026-10-26, `?tab=readiness`, display-only):** the owner's *when* reference. It shows
  elapsed forward-test / structural-stop-era days, days left to the cost sample, US DST cross-check and
  pre-registered window, plus the conditional 2–4 month edge review and 6–12 month G2 review; a dated
  **completed** milestone list and the **pending** owner/host blockers; and the live 20-check
  `tools/live_readiness.py` scorecard. `readiness.py` is stdlib-only, imports no engine module, writes
  nothing and cannot open the LIVE gate. Its view is cached 5 min (`?readiness=refresh` forces a new read);
  same read in the terminal: `python3 readiness.py` / `--json`. Tests: `tools/test_readiness_tab.py` (16).
- Logs: `journalctl -u goldbot -f`; autosync log `/var/log/gold_autosync.log`.

## 11. How to keep this file honest

**Session & Push Protocol**
1. Push every commit immediately (do not batch).
2. Keep a session PR open until the user signs off.
3. Before ending: run `python3 tools/handoff_check.py --update`, then update §1 numbers, §4/§5 if
   params/evidence moved, §6 next steps, the
   era-timeline table (top of file) and `archive/PROJECT_LOG.md`. A runtime change is not
   "done" until its **pre-registered bar exists in a dated doc** — write the bar before any
   post-change trade can be judged, and never re-slice eras afterwards to rescue it.
4. Never leave conclusions in chat only — land them in this file or a dated REVIEW.
5. **§1 is current-state only — never prepend a new dated block to it.** Rewrite §1 in place and move the
   block it replaced to `docs/HANDOFF-HISTORY.md` (append-only, newest first). The 10-15 truncation began as
   §1 bloat: 223 of the file's 886 lines were §1, 92% of it history no session had pruned — and this file is
   rewritten by an automated daily job, so size is a reliability risk, not just a reading chore. If a required
   section goes missing, `python3 tools/handoff_check.py` now says STALE (and `--update` refuses to run).

**Forward-test milestones (canonical session queue: `docs/EXECUTION-PLAN.md`)**

| Gate | Action |
|---|---|
| Now (2026-10-28) | Edge not confirmed — remain paper-only. **“Follow execution plan.”** drives `docs/EXECUTION-PLAN.md`: **G1 SIGNED, A2 (the `SL_CLEAR_ATR 0.5 → 1.5` deploy) still pending a host window with no open position**, Track B now at **B3** (reconciliation), cost sample 13/14 days + 1/2 weekends. LIVE gate CLOSED (**11 PASS / 6 TODO / 3 MANUAL**). |
| **DONE 2026-10-28 (B2 — LIVE broker-side exits)** | `docs/REVIEW-2026-10-28-b2-broker-be-time-stop.md` + `docs/DECISION-2026-10-28-b2-broker-be-and-time-stop.md`: the broker now holds the +0.75R ratchet (`TRADE_ACTION_SLTP` to entry, confirm-before-book, retry only on market moves) and the 240-min time stop (market close by ticket, booked through the paper `TIME` path); LIVE fill state recorded/persisted; a broker-closed position books nothing and blocks new entries. `broker_be` + `broker_time_stop` PASS via call-graph checks; 18 fake-MT5 tests + smoke **Scenario AC**; paper path unchanged. **No order, no arming, no strategy change.** |
| **DONE 2026-10-26 (full audit + LIVE hardening)** | `docs/REVIEW-2026-10-26-full-system-audit.md`: DST gate MET (+2h EU), 11/14 quote days, arm/kill-switch + IOC filling + closed-bar/dedup `run_live` (LIVE path only), `tools/live_readiness.py` scorecard + Scenario AA + 18 tests, `structstop1.5` prereg **draft**. **No strategy parameter changed; no deploy; no order.** |
| **Judged 2026-10-19 21:00 UTC (latest checked-in rows through 18:10; n=139)** | `docs/REVIEW-2026-10-19-struct-stop-judgement.md`: geometry PASS; SCREEN MET; PASS not met. The closure-gap count is 2/2 under the documented rule, so the extra §7 REVERT trigger FIRED. No runtime change was made because the required gap guard has no owner-approved cutoff or open-position policy; the checked-in engine remains on the structural stop, paper-only. |
| **Post-gate refresh (2026-10-20 08:59 UTC; era n=147)** | `docs/REVIEW-2026-10-20-post-gate-refresh.md`: all session checks pass, era grew to n=147 with bars inside their thresholds and the gap count still 2/2. The n=150 arm **lapsed with the time gate** — do not re-judge PASS on the grown sample; a re-opened arm needs a new dated pre-registration. Blocker unchanged: owner-defined gap guard, then the prescribed revert. |
| **Gap guard DEPLOYED (2026-10-25 02:48:12 UTC, `71317da`) + DST-responsive fix (`1c02b2c`)** | `docs/PREREG-2026-10-25-gap-guard-daily-closure.md`: 30-min entries-only daily-closure guard + `#697` duplicate-number fix deployed into the closed weekend market; `derive_daily_closure()` made DST-responsive (`1c02b2c`). **Owner decision:** hold `SL_CLEAR_ATR = 0.5` until Sunday reopen / Monday confirms the post-DST broker offset (`+2h` EU vs `+3h` US), then decide between pre-registering `structstop1.5` (`docs/ANALYSIS-2026-10-25-stop-hunt-markouts-and-clearance-grid.md`) or executing the literal §7 revert. The 0.25 ATR level-test remains ineligible. |
| ~2–4 months | Seek 100+ trades across multiple regimes for the first serious edge assessment. |
| 6–12 months | Consider a separate live-readiness review only if durable positive expectancy after realistic costs is demonstrated and the owner explicitly approves. |

Do **not** treat the bot as supplementary income until positive expectancy
after realistic costs is clearly demonstrated on a meaningful live sample.
