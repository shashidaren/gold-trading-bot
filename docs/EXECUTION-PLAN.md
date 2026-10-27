# Gold bot execution plan — “follow execution plan”

**Status:** living session queue — re-based **2026-10-26 ~14:15 UTC** on collection 349 (data through `2026-10-26 11:59:07 UTC`);
§2 numbers refreshed **2026-10-27 ~12:00 UTC** on collection 359. **G1 is now an answerable question:** the
approve / reject / hold pack the owner needs is `docs/BRIEF-2026-10-27-g1-owner-decision.md` (still unsigned).
**Purpose:** make progress consistent across sessions while the bot stays in paper/forward-test mode, until there is — or is not — something genuinely workable for live trade.
**Canonical prompt:** **“Follow execution plan.”** (The older “Execute the plan.” remains an exact alias; README/HANDOFF point here.)

Full audit of the current state: **`docs/REVIEW-2026-10-26-full-system-audit.md`**.
Current state + operating rules: **`docs/HANDOFF.md`**. Exact experiment thresholds stay in their dated pre-registrations/reviews; this plan must never replace or relax them.

**Owner's quick view (display-only):** the dashboard's 🚦 **Readiness** tab (`?tab=readiness`) or
`python3 readiness.py` renders §3's queue as a **timeline in days**, §4's completed milestones and the
**pending** owner/host blockers, alongside the live `tools/live_readiness.py` scorecard. It mirrors this
plan — this file stays canonical. Day counts are conditional estimates, **not deadlines**, not a profit
forecast, and never a gate: the tab writes no state and cannot authorise or place a live trade.

---

## 0. What the phrase means (binding)

In any new session, the owner says **“Follow execution plan.”** That means:

1. Read this file and `docs/HANDOFF.md`; verify the repository/data with the **session ritual** (§5). Do not ask the owner to restate the project context.
2. Select the **lowest-numbered eligible step** in §3. A step is eligible only if its gate is met, its pre-registration exists where required, and it has no unresolved blocker. **Do one step per session** (plus the ritual and doc updates). Never stack two strategy variables.
3. Do the safe work that is possible. If a step needs a production-host action, a missing trading-rule definition, or a new risk approval, report the **exact blocker** rather than pretending the step was completed.
4. Land every conclusion in a dated `REVIEW`/`ANALYSIS`/`PREREG` doc, update this plan's status/queue, refresh `docs/HANDOFF.md` (§1/§4/§5/§6 + `handoff_check.py --update`), and add a line to `archive/PROJECT_LOG.md`.
5. End with: what changed, what the tests said, the single next eligible step, and any blocker.

**The phrase authorises (paper-only):** analysis, tools, tests, docs, pre-registrations, PRs, and — **only for a change whose dated pre-registration is already signed off and whose own gates pass** — merging that one pre-registered paper-trading change to `main` (autosync deploys it into the **paper** engine). It does **not** authorise a second variable on the same window.

**The phrase NEVER authorises:** real orders; setting `TRADING_MODE = "LIVE"`; arming `GOLD_LIVE_ARMED`; bypassing or retro-editing a pre-registration; stacking strategy changes; hand-editing `/opt/gold`; committing credentials, account identifiers or an unredacted manual journal. Those need a separate, explicit, informed owner decision.

**Two approval gates remain in the whole plan:**
- **G1 (one time, now):** sign off `docs/PREREG-2026-10-26-structstop1.5.md` — i.e. approve branch (A) over the literal §7 revert. Until G1, step A1 is blocked and every other step is still eligible.
- **G2 (at the end):** any real-money trading. Never delegated to the phrase.

If the owner wants per-change sign-off instead of the phrase acting as sign-off for pre-registered paper changes, say **“hold merges”** once; it will be recorded here.

---

## 1. Guardrails (unchanged, still binding)

- Preserve the open experiment and its original, dated decision bars. **One runtime variable per forward-test window.**
- Use the costed, stateful `tools/strategy_lab.py` replay for exit/gate ideas; `exit_sims.py` / `pathwalk_sims.py` / `phantom_trades.py` are descriptive only.
- Keep rejected candidates rejected unless **new, dated, pre-registered evidence** justifies reopening them. Never tune a threshold after seeing the outcome.
- Judge net R/trade, payoff, drawdown, SL severity, sample size **and** uncertainty — not win rate alone.
- Pressure composite = context only (collinear with side). The owner's manual pressure method is a separate, unmeasured hypothesis. Never widen or remove a live stop because selected examples later recovered.
- Cutover dates come from the host's `autosync: merge upstream` commit time, confirmed from the ledger — never from the plan or the PR merge.
- No account identifiers, credentials, personal balances or unredacted manual journals in Git.
- **`TRADING_MODE` stays `FORWARD_TEST`** until G2. `python3 tools/live_readiness.py --strict` must be green before G2 is even discussed, and a green scorecard is **not** itself permission.

---

## 2. Baseline (re-based 2026-10-26 — always refresh before relying on it)

- **709 closed paper trades** — 142W/306L/258BE/3TIME, decisive WR **31.7%**; engine ledger **$131.30**, true equity **$114.34**, **net −$669.26** at the registered $0.40 round trip. No open trade (`next_trade_num: 710`). Log 51 215 bars through `2026-10-26 11:59:07 UTC`.
- **Structural-stop era n=212** (57W/95L/58BE/2TIME): decisive WR **37.5% [30.2–45.4]**, gross **−0.054R/trade**, SCREEN MET on all five registered checks. The **n=150 PASS arm lapsed with the 10-19 time gate** — the grown sample is an observation, not a re-judgement. Geometry guard **PASS**: 0 stops inside the level, 83.0% level-bound, +0.50 ATR clearance, 3.32 ATR median risk.
- **§7 closure-gap revert trigger FIRED at 3/2** (#595/#610/#687; 0 gapped through, 0 worse exits, no weekend ride). The **30-min entries-only gap guard is deployed** (`71317da`, 10-25 02:48:12 UTC) and `derive_daily_closure()` is DST-responsive.
- **DST gate MET:** observed broker offset `+3h` → **`+2h` from 2026-10-25 22:00:30 UTC**; the EU DST rule fits 100% of 24 379 rows. `history_to_log.py --dst eu` is now evidence-backed. No post-DST **daily** break has been logged yet (first due 10-26 evening), so the derived guard schedule is still `(20:58, 22:00)` — verify after that break.
- **Quote logger healthy again:** 14 files / 35 571 rows, **11/14 complete UTC days, 1/2 weekends**, median spread **$0.55** (measured round trip $0.55 on 131 matched trades) vs the registered $0.40. Spec `filling_mode = 2` → **IOC only**; account kind **REAL** (a live pilot must use a DEMO account + separate data dir).
- **New host action:** the quote sidecar was fresh from Sunday 22:00 UTC but the **price-bar log resumes only at 23:59:24 UTC** (~2 h of open-market M1 bars missing at the reopen). Verify `mt5feed` / `goldbot` restart on the host.
- **Replay calibration:** `--calib-only` recall **99.8%**. Post-cutover net R/trade at $0.20/side: old geometry −0.137, **live 0.5 ATR −0.110**, 1.0 ATR −0.099, **1.5 ATR −0.024** (at $0.275/side: −0.184 / −0.140 / −0.126 / **−0.047**). 1.5 ATR passes 3 of 4 pre-declared bar points; the 4th (trade count −21.9%) fails and is disclosed.
- **Live gate CLOSED:** `tools/live_readiness.py` = **9 PASS / 8 TODO / 3 MANUAL**. Paper engine fully tested (`smoke_test.py` A–Z + AA PASSED, 64 `goldbot` tests, 18 `live_readiness` tests, `check_data.py` 0 fail/8 warn).
- **Verdict: no demonstrated edge after costs.** Whole book and live era both net negative after cost. Nothing here is permission to trade real money.

### 2b. Refresh 2026-10-27 ~12:00 UTC (collection 359, log through `2026-10-27 11:59:06 UTC`)

Read with §2; nothing below re-opens a closed judgement.

- **722 closed** (143W/315L/261BE/3TIME, decisive 31.2%), engine ledger **$92.38**, true equity **$75.44**, net **−$713.36**
  at the registered $0.40 round trip. BUY #723 open at the snapshot. `check_data` 0 fail/8 warn, `handoff_check` FRESH.
- **Era n=225** (58W/104L/61BE/2TIME): decisive **35.8% [28.8–43.4]**, gross **−0.081R/trade** (was −0.054R at the
  registered 10-19 gate), SL/day 6.12, SL share 46.2%, avg SL $5.80, era DD $151.65. Geometry guard still **PASS**
  (0 stops inside the level, 82.2% level-bound, +0.50 ATR clearance, 3.31 ATR median risk). This is a grown-sample
  observation — the 10-19 judgement is closed and the lapsed n=150 arm stays lapsed.
- **Post-DST daily break: VERIFIED, host blocker cleared from data.** First post-DST break `2026-10-26 20:58:09 →
  22:00:04 UTC` and `derive_daily_closure()` returns exactly `(20:58, 22:00)`; the break is fixed in **UTC** across the
  offset change (quote-sidecar freeze 20:59→22:00 UTC on both 10-22 at +3h and 10-26 at +2h), so the deployed
  gap-guard schedule is right and its ±60-min adaptation correctly did not fire. This completes PREREG §2.3 — the
  pre-deploy engineering item that did not need a signature. No reopen hole on 10-26; the 10-25 one is still a host item.
- **Replay refreshed** (post-cutover era, `strategy_lab --table`): live 0.5 ATR **−0.141R/t** at $0.20/side
  (−0.171 at $0.275, −0.202 at $0.35), `structstop1.5` **−0.046 / −0.069 / −0.092** → Δ **+0.095 / +0.102 / +0.110R/t**;
  the literal §7 revert is the **worst** cell at every cost (−0.155 / −0.202 / −0.249). `1.0 ATR` buys only +0.015R.
  Registered eligibility bar unchanged at **3/4** (trade count −21.9% then, −21.6% now — recorded, not re-scored).
- **PASS-arm feasibility, stated plainly:** Wilson LB > 40% at n=150 needs ≈**48%** decisive WR (72/150); the live era
  reads 35.8% and the best replay reading of `1.5` is 40.3% [32.0–49.3]. The likely outcomes are KEEP-no-edge or REVERT.
- **Cost sample 12/14 complete UTC days, 1/2 weekends** (38 451 rows, median spread $0.55, measured round trip $0.55
  on 144 matched trades) — still short of the target, so **$0.40 stays registered**. `live_readiness` unchanged at
  **9 PASS / 8 TODO / 3 MANUAL, gate CLOSED**.

---

## 3. The queue

**Selection rule:** ritual first (§5), then the lowest-numbered step whose gate is met. Tracks A (strategy evidence) and B (execution engineering) run in parallel; a blocked step never blocks the other track. Track C is the final go/no-go.

### Step 0 — DONE 2026-10-26 (this session)

| | |
|---|---|
| Work | Full-system audit, DST-gate verification, handoff refresh, LIVE-path hardening (arm gate + kill switch, IOC filling from spec, closed-bar/dedup `run_live`), `tools/live_readiness.py` scorecard, Scenario AA + 18 unit tests, `structstop1.5` pre-registration draft. |
| Completion test | `docs/REVIEW-2026-10-26-full-system-audit.md` exists; `smoke_test.py` PASSED; `test_live_readiness.py` 18 OK; `live_readiness.py --strict` exits 1 (gate closed); no strategy parameter changed. |
| Result | All met. **No runtime strategy change, no deploy, no real order.** |

### Track A — evidence and the open strategy experiment

| ID | Gate / when | Work | Completion test | Blocker |
|---|---|---|---|---|
| **A1** | **G1 now** | Owner signs (or rejects) `docs/PREREG-2026-10-26-structstop1.5.md`. **Prepared for the owner 2026-10-27: `docs/BRIEF-2026-10-27-g1-owner-decision.md`** (options A/B/hold, refreshed costed replay, what a PASS would actually require, timing slack, risks). If signed: register it verbatim (dated, before any post-change trade), do the §2 pre-deploy tool work (new era cutover in `strategy_lab` / `check_structural_stop` / `win_rate_report` / `pressure_report` / journal; smoke assertion for 1.5 ATR clearance); the post-DST daily-break signature is **already confirmed** (§2b). If rejected: execute the literal §7 revert instead, with its own dated REVIEW. | signed + dated PREREG; `strategy_lab.CLEAR15_CUTOVER` exists with the deploy date **unknown until deploy**; all tests pass; a REVIEW records the gate decision. | **G1 owner sign-off** (deviation from the literal §7 revert). The pack is written; only the signature is missing. |
| **A2** | A1 done, no open trade | Single-variable change `SL_CLEAR_ATR = 0.5 → 1.5` in one commit + PR; merge (the phrase is the sign-off **only** because A1's registration exists). Record the real cutover from the host's `autosync: merge upstream` commit, confirm from the ledger boundary. | one-line diff; `smoke_test.py` PASSED; `check_structural_stop.py` shows the OLD/NEW boundary at the recorded cutover; dated REVIEW with the cutover time. | Host autosync (3 h cycle); never hand-edit `/opt/gold`. |
| **A3** | A2 + 10–20 new-era trades | Judge **A1–A5** of the registered bar (geometry + calibration). | dated REVIEW: 0 stops inside level, ≥1.5 ATR clearance, recall 99.6–100%, level-bound 70–90%, median risk 3.8–5.0 ATR. A failure = REVERT, no P&L reading. | none |
| **A4** | n=100 in the new era | **SCREEN** judgement (net R/trade ≥ −0.05R at $0.20/side, decisive WR ≥ 40%, B1–B3, A still passes). | dated REVIEW with Wilson CIs, per-day columns, cost sensitivity. | none |
| **A5** | n=150 or 2026-12-01 21:00 UTC, whichever comes first | **PASS/FAIL/REVERT** judgement exactly as registered. | dated REVIEW; PASS requires Wilson LB > 40%, net ≥ 0.00R at $0.20/side, ≥ −0.05R at $0.275/side, era DD ≤ $200. | none |
| **A6** | in parallel, when the quote logger reaches **14 complete days + 2 weekends** (~end of October) | Complete the cost model: measured all-in round trip (spread + slippage + commission + swap), re-cost the ledger and canonical replay with a sensitivity range, write a dated cost doc. Keep $0.40 registered until then. | `xm_quote_report.py` target met; `live_readiness.py` `quote_sample` + `cost_model` turn PASS; dated `ANALYSIS` doc. | logger uptime (host). |
| **A7** | after A5, only if PASS | **Independent** forward window on the **same unchanged strategy** — 2–4 months, multiple regimes, chronological holdout. This, not a replay, is the edge test. | dated pre-registration before the window; positive net expectancy after measured cost with acceptable drawdown and uncertainty. | time; a FAIL/REVERT ends this track. |
| **A8** | research only, parallel | Private manual observation log (§7) for the owner's pressure/hold hypothesis. No bot behaviour change. ≥100 matched post-stop observations before any exploratory screen; then a new dated pre-registration, never an engine gate. | private log (outside Git) + optional dated ANALYSIS. | the manual rule is still undefined — ask the owner for the definition before coding it. |

### Track B — LIVE execution engineering (all paper-safe; none places an order)

Every step must move at least one `live_readiness.py` check from TODO to PASS **and** add a hermetic test. The gate stays CLOSED until all of them plus the MANUAL items are PASS.

| ID | Gate / when | Work | Completion test | Blocker |
|---|---|---|---|---|
| **B1** | DONE 10-26 | `tools/live_readiness.py` scorecard + arm/filling/closed-bar hardening. | 9 PASS / 8 TODO / 3 MANUAL. | — |
| **B2** | any session | Broker-side **BE ratchet** (`TRADE_ACTION_SLTP` at +0.75R) **and** the 240-min **time stop**, or a dated registration of the explicit divergence (paper and LIVE would otherwise be different strategies). Decide first, then implement once. | `live_readiness.py` `broker_be` + `broker_time_stop` PASS; fake-MT5 tests for modify/close/rejection/retry. | choice must be recorded before coding (default: implement, do not diverge). |
| **B3** | any session | **Reconciliation:** adopt an existing broker position on startup (magic filter), refuse a duplicate order, read realised P&L from `history_deals_get`, persist ticket↔trade number, and prove restart recovery. | `position_reconcile` + `deal_reconcile` PASS; fake-MT5 restart tests. | none |
| **B4** | any session | **Pre-order safety:** `terminal_info().connected`, `volume_max`/step/stops/freeze levels from the live spec, and a **spread-as-%-of-R** veto (measured $0.55 is ~10% of 1R; `MIN_SPREAD_POINTS=60` is too loose). | `disconnect_safety`, `sizing_limits`, `cost_guard` PASS; unit tests with a fake spec. | none |
| **B5** | B2–B4 done | **DEMO-account** evidence on the host: fill (IOC), SL/TP, BE/time management, rejection handling, disconnect, restart, reconciliation, kill switch, and 48 h of stable running. Use a DEMO account and a separate data dir — the captured spec says REAL. | `docs/DEMO-EVIDENCE.md` (**new file to be created**, redacted) exists; `live_readiness.py` `demo_evidence` PASS. | **HOST/operator action** — cannot be done from the repo checkout. |
| **B6** | B5 done | Ops runbook: `GOLD_LIVE_ARMED=1`, `LIVE_HALT` kill-switch drill, service/user separation, monitoring/alerts, rollback, and a written “who can arm it” rule. | dated `docs/RUNBOOK-LIVE.md` (**new file to be created**) + a drill log; no credential in Git. | none |

### Track C — the only path to a live pilot

| ID | Gate | Work | Completion test |
|---|---|---|---|
| **C1** | A7 (edge) + B1–B6 (all PASS) + A6 (cost) | Separate **live-readiness review**: independent sample, measured costs, drawdown, operational evidence, worst-case loss, position sizing, and a **tightly capped pilot** plan. | dated `REVIEW` with an explicit GO/NO-GO, plus **G2** — the owner's separate, explicit, informed approval. No automatic go-live. |

**“Workable for live trade” is defined as:** (1) one unchanged strategy with positive net expectancy after **measured** costs on an independent forward sample across multiple regimes; (2) acceptable drawdown and tail risk with uncertainty bounds; (3) every blocking `live_readiness.py` check PASS; (4) a dated DEMO test report; (5) a cost model, kill switch, reconciliation and monitoring that have survived an outage; (6) G2. Anything less stays paper. **No date can be promised for profitable live trading** — failed gates extend the horizon indefinitely (current conditional estimate: strategy reassessment Dec 2026–Feb 2027; separate live-readiness review Apr–Oct 2027; `docs/REVIEW-2026-10-20-live-readiness-timeline.md`).

---

## 4. Compact history (completed queue items — do not re-do)

| When | What |
|---|---|
| 2026-10-19 21:00 UTC | Structural-stop time gate judged: geometry PASS, **SCREEN MET**, **PASS unavailable** (n=139 < 150; Wilson LB 28.8%). §7 closure-gap trigger fired 2/2. `docs/REVIEW-2026-10-19-struct-stop-judgement.md`. |
| 2026-10-20 | Post-gate refresh: n=150 arm **lapsed with the time gate**; no re-judgement on a grown sample. `docs/REVIEW-2026-10-20-post-gate-refresh.md`. |
| 2026-10-25 ~03:30 UTC | Owner stop-hunt hypothesis → `tools/stop_hunt_markout.py` + `structstop1.5` replay variant. Deeper stops monotone-better at every cost; 1.5 ATR passes 3/4 of a **pre-declared** bar; **NO live change**, candidate only. `docs/ANALYSIS-2026-10-25-stop-hunt-markouts-and-clearance-grid.md`. |
| 2026-10-25 02:48:12 UTC | PR #58 deployed: 30-min **entries-only** gap guard + `#697` duplicate-number fix, into the closed weekend market. Owner chose `hold_for_dst`. `docs/PREREG-2026-10-25-gap-guard-daily-closure.md`, `docs/REVIEW-2026-10-25-duplicate-trade-number.md`. |
| 2026-10-25 (post-merge) | `derive_daily_closure()` made DST-responsive (5-break baseline + Day-1/Day-2 ±60 min adaptation; +7 Scenario Z checks). Deployment of that commit is part of the same safe-work backlog if it is not already on `main`. |
| 2026-10-26 | Full audit, DST gate verified, LIVE-path hardening + readiness scorecard, pre-registration draft, this rewritten queue. `docs/REVIEW-2026-10-26-full-system-audit.md`. |
| 2026-10-27 | **G1 made answerable + ritual refresh (no strategy step run).** Wrote the owner decision pack `docs/BRIEF-2026-10-27-g1-owner-decision.md`; refreshed §2/§2b on collection 359 (era 212→225, gross −0.054R→−0.081R); re-ran the costed replay for 0.5/1.0/1.5/revert at $0.20/$0.275/$0.35; **verified the post-DST daily break against `derive_daily_closure()`** (PREREG §2.3 done, host blocker closed). No parameter change, no registration, no deploy, no order — **A1 is still waiting on the owner's line.** |

---

## 5. Session ritual (every “follow execution plan” session)

```bash
git status --short && git log --oneline -3
python3 tools/check_data.py                 # 0 fail; warnings are documented
python3 tools/handoff_check.py             # STALE -> --update, then rewrite §1/§4/§5/§6 prose
python3 tools/check_structural_stop.py     # PASS (0 inside level)
python3 tools/check_gap_rides.py           # registered closure count + damage facts
python3 tools/pressure_report.py --root .  # era verdict + calibration
python3 tools/xm_quote_report.py           # cost sample + DST offsets
python3 tools/live_readiness.py            # live gate scorecard
python3 tools/strategy_lab.py --calib-only # only when a replay/param idea is in play
python3 tools/handoff_check.py --update    # after checking the underlying files
```
If code changed, also: `python3 tools/smoke_test.py`, `python3 tools/test_live_readiness.py`,
`python3 -m unittest discover -s goldbot/tests -t .`,
`python3 -m py_compile engine.py trade_filter.py`, and the relevant replay/calibration checks.

**End-of-session checklist**
1. Mark the completed step and its evidence in §3; leave future gates untouched.
2. Refresh the handoff snapshot and prose; append the replaced §1 block to `docs/HANDOFF-HISTORY.md` (never prepend history to §1).
3. Land conclusions in a dated doc — never in chat only.
4. Push every commit immediately; keep the session PR open until sign-off (or use the phrase's pre-registered-merge authority, §0).
5. Report the next eligible step and any owner/host blocker.

---

## 6. Precedence when several steps look eligible

1. A data-integrity failure or a feed outage — fix/report first; no judgement on bad data.
2. Any expired **time gate** — judge it on the latest available snapshot, exactly as registered, before any new change.
3. Track A in order (A1 → A5), unless blocked by G1 or a host action.
4. Track B in order (B2 → B6), one `live_readiness.py` check at a time.
5. A6/A8 (cost sample, private observation log) whenever their data arrives.
6. C1 only when everything above is complete.

Never start a step whose pre-registration does not exist. Never re-open a lapsed arm because the sample later grew.

---

## 7. Manual observation record (private; do not commit filled rows)

One row per eligible signal/stop event, including cases where the owner does **not** override the stop and cases that lose. Keep bot and manual entries separate; do not call them matched unless timestamps and setup actually match. Minimum fields:

`timestamp_utc, bot_trade_id, side, bot_entry, bot_sl, bot_tp, manual_entry, manual_exit, pressure_source, pressure_metric, pressure_timeframe, pressure_value_at_entry, pressure_value_at_stop_touch, last_closed_bar_utc, contemporaneous_action, reason_code, max_hold_or_exit_rule, post_stop_markout_horizons, mfe, mae, hypothetical_exit, estimated_cost, notes_without_account_identifiers`

A trade that later touches its former target after the bot's stop is a **counterfactual mark-out**, not a win under the bot's rules. The entry, stop event and decision must be timestamped **before** looking at the recovery path. This phase changes no bot behaviour.
