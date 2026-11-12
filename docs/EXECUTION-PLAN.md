# Gold bot execution plan — “follow execution plan”

**Status:** living session queue — re-based **2026-11-12** on collection 480 (data through `2026-11-11 23:59:05 UTC`);
§2/§2b refreshed 2026-10-27, §2c 2026-10-28, §2d 2026-10-30 (paper-ledger decision: **no top-up / no rebaseline**),
and §2e refreshed **2026-11-06**. **G1 is SIGNED (2026-10-27, branch A):** A1 is DONE; **A2 remains blocked on a
production-host flat-position check at deploy time**. This checkout's current ledger is flat, but it is not evidence
about the inaccessible host. **B2 (2026-10-28), B3 (2026-11-06) and B4 (2026-11-12) are DONE** in Track B; `live_readiness`
is **17 PASS / 0 TODO / 3 MANUAL**, gate still CLOSED — **no code TODO remains**. **B4 is DONE (2026-11-12)**; the
next Track-B step is **B5 (DEMO-account evidence), a host/operator action** that cannot be done from the checkout. The
feed is healthy at this snapshot (quotes continuous to `2026-11-11 23:59:30`, bars to `23:59:05`), so there is no §6
feed item outstanding. A6's sample gate is met and follows the preceding Track-B queue step. Evidence: `docs/REVIEW-2026-10-27-g1-decision.md`, `docs/REVIEW-2026-10-28-b2-broker-be-time-stop.md`,
`docs/REVIEW-2026-11-06-b3-position-deal-reconciliation.md`, `docs/ANALYSIS-2026-11-12-b4-live-order-safety.md`.
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
- **G1 (one time) — SIGNED 2026-10-27:** the owner approved branch **(A)**, `docs/PREREG-2026-10-26-structstop1.5.md` (`SL_CLEAR_ATR = 1.5`) instead of the literal §7 revert. A1 (registration + pre-deploy tool work) is done; the gate that remains on this track is **A2's own condition** — no open trade on the host when the one line lands. Signing G1 authorised the change, not a second variable, and it did not make PASS likely (§4 eligibility stays 3/4).
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
- **The simulated balance is a counter, not capital, and it is NEVER rebaselined (owner decision
  2026-10-30).** Paper always trades `LOT_SIZE` (0.01) — `size_lots()` returns it whenever there is no broker
  account — so the ledger number changes no trade, no R/trade, no era DD and no registered bar. Editing it
  mid-window is a **ledger edit**, not a risk decision: it is exactly what `tools/handoff_check.py`'s money
  rule calls tampering, and what erased $24.74 of real losses on 2026-09-09. The owner's signed answer is
  **"no rebaseline ever — let it go negative"**: no top-up, no reset, no edit to `trades.csv`/`status.json`,
  and the book is *expected* to trade through zero. The rebaseline-at-zero proposal it declined is preserved
  unsigned in `docs/ANALYSIS-2026-10-30-simulated-equity-and-paper-runway.md` (§5 declined, §8 the decision)
  and may not be cited as live policy. Check the decline with `python3 tools/equity_runway.py`.

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

### 2c. Refresh 2026-10-28 ~19:00 UTC (collection 370, log through `2026-10-28 17:59:05 UTC`)

Read with §2 and §2b; nothing below re-opens a closed judgement.

- **737 closed** (146W/322L/266BE/3TIME, decisive **31.2%**), engine ledger **$89.04**, true equity **$72.11**,
  net **−$722.69** at the registered $0.40 round trip. `next_trade_num: 738`, **no open trade** at the snapshot
  (`handoff_check open_trade: none`). `check_data` 0 fail/8 warn, `handoff_check` FRESH (2 advisory).
- **Era n=240** (61W/111L/66BE/2TIME): decisive **35.5% [28.7–42.9]**, gross **−0.078R/trade** ($−109.08;
  decisive-only denominator −0.113R), SL/day **6.17**, SL share **46.2%**, scratch 27.5%, avg SL **$5.73**,
  era DD **$154.98**. Geometry guard still **PASS** (0 stops inside the level, 82.5% level-bound,
  +0.50 ATR median clearance, **3.33 ATR** median risk). The bar card reads
  **B1/B2/B3/A4/A5 OK, C1 OK, C2 FAIL** (decisive WR 35.47% vs the 36.0% baseline) — the 10-19 judgement stays
  closed and the lapsed n=150 arm stays lapsed.
- **Tape:** SELL-dominated (BUY 29% / SELL 71% over the last 60 closed bars), 60-bar momentum −2.01 ATR,
  EMA50−EMA200 −2.32 ATR, RSI 85.1, ATR 0.77 (below the 1.10 floor), daily SLs 5/10, 38 setups blocked in 24 h.
- **Cost sample 13/14 complete UTC days, 1/2 weekends** (159 matched trades, measured round trip mean/median
  **$0.55**, p90 $0.56, max $0.68) — still short of the target, so **$0.40 stays registered**. Broker offset
  **+2h** confirmed on 7 919 post-DST rows (EU rule fits 100% of 30 621). Captured spec (17:42:06 UTC):
  REAL/RETAIL_HEDGING 1:1000, build 6230, filling **IOC only**, spread 55 pts, volume 0.01/0.01/50,
  contract 100.
- **LIVE gate CLOSED: 11 PASS / 6 TODO / 3 MANUAL** after B2 (was 9/8/3). Remaining TODOs are exactly
  B3 (position/deal reconciliation) and B4 (disconnect safety, sizing limits, cost guard); the three MANUAL
  items are unchanged (cost model, demo evidence, edge evidence).
- **Verdict unchanged: no demonstrated edge after costs.** Nothing in this refresh is permission to trade.

### 2d. Refresh 2026-10-30 ~03:00 UTC (collection 381, log through `2026-10-30 02:59:04 UTC`)

Read with §2/§2b/§2c; nothing below re-opens a closed judgement.

- **758 closed** (150W/334L/271BE/3TIME, decisive **31.0% [27.0–35.2]**), engine ledger **$52.98**,
  true equity **$36.05**, net **−$767.15** at the registered $0.40 round trip. **SELL #759 open** at the
  snapshot (`next_trade_num: 760`) — which is why **A2 is blocked again**: it needs a flat host.
  `check_data` 0 fail/8 warn, `handoff_check` FRESH (2 advisory), `check_structural_stop` PASS
  (0 inside level, 82.4% level-bound, +0.50 ATR, 3.32 ATR median risk), `check_gap_rides` 3/2 with 0 damage.
- **Era n=261** (65W/123L/71BE/2TIME): decisive **34.6% [28.1–41.6]**, gross **−0.098R/trade**
  ($−145.14; decisive-only −0.136R), SL/day **6.15**, SL share **47.1%**, scratch 27.2%, avg SL **$5.80**,
  era DD **$191.04**. Bar card now reads **B1/B2*/B3/A4/A5** with **B2 a fresh FAIL** (SL share 47.13% vs the
  47.0% bar) and C2 still FAIL; the 10-19 judgement stays closed and the lapsed n=150 arm stays lapsed.
- **Cost sample 15/14 complete UTC days, 1/2 weekends** (still short of *two weekends*), measured round trip
  mean/median **$0.55**, p90 $0.56, max $0.68 — **$0.40 stays registered**.
- **Paper ledger runway (NEW, `python3 tools/equity_runway.py`):** true equity $36.05 against a net burn of
  **−$0.94/closed trade** (era, $0.40 RT) at **13.1 trades/active day** is **≈38 closed trades ≈ 2.9 trading
  days** to zero, bootstrap 90% range **33–336 trades** (6% of draws have no burn at all — n=261 cannot
  separate the era from break-even). The engine has **no balance floor** and keeps trading on a negative
  ledger (a supported, tested state). **The simulated balance is a counter, not capital**: paper always
  trades 0.01 lot (`size_lots()` returns `LOT_SIZE` with no broker account), so a top-up moves no trade, no
  R/trade, no era DD and no registered bar — only `engine_ledger_usd`, which is exactly what
  `handoff_check`'s money rule treats as a ledger edit. **Owner question answered NO to a top-up**, and then
  **NO to ever rebaselining either** — signed **"no rebaseline ever — let it go negative"** (§8 of
  `docs/ANALYSIS-2026-10-30-simulated-equity-and-paper-runway.md`), which declines the §5 rebaseline-at-zero
  proposal; it stays on the record, unsigned and unadopted. Expectations written down with the decision: a
  negative `equity` on the dashboard will *look* like the 2026-10-19 phantom incident and is not it (a real book
  loses ~$1/trade), and `handoff_check`'s money rule stays armed against a silent ledger edit.
- **LIVE gate CLOSED: 11 PASS / 6 TODO / 3 MANUAL** (unchanged since B2). Next Track-B step **B3** (reconciliation).
- **Verdict unchanged: no demonstrated edge after costs.** Nothing in this refresh is permission to trade.

### 2e. Refresh 2026-11-06 (collection 435, log through `2026-11-06 08:59:02 UTC`)

Read with §2/§2b/§2c/§2d; this is a current-state refresh, not a re-judgement of any closed experiment.

- **840 closed** (175W/370L/292BE/3TIME, decisive **32.1% [28.3–36.1]**), engine ledger **$73.70**, true equity
  **$56.75**, net **−$779.25** at the registered $0.40 round trip. No open trade (`next_trade_num: 841`).
  `check_data`: 0 fail / 9 documented warnings; `handoff_check` snapshot refreshed; `check_structural_stop` PASS
  (0 inside level, 82.5% level-bound, +0.50 ATR median clearance, 3.27 ATR median risk).
- **Structural-stop era n=343** (90W/159L/92BE/2TIME), decisive **36.1% [30.4–42.3]**, gross **−0.060R/trade**
  on the pressure-report reward-risk scale, SL/day **6.12**, SL share **46.36%**, scratch **26.82%**, average SL
  **$6.01**, era DD **$200.06**. These are grown-sample observations only; the 10-19 judgement is closed and the
  lapsed n=150 arm is not reopened. **No demonstrated edge after costs.**
- **Gap rides:** 5 post-cutover scheduled-closure rides vs the registered threshold 2; 1 reopened through the stop,
  0 exits worse than the stop, 0 weekend rides. Record the count and damage separately; this refresh does not reopen
  the old judgement or alter the entries-only gap guard.
- **Quotes:** 21 complete UTC days / 2 weekends; target met. Spread-only median **$0.55**, p90 **$0.57**;
  measured round trip on 262 matched trades mean/median **$0.55**, p90 **$0.57**. This is not the all-in cost
  model (slippage/commission/swap still need evidence), so `$0.40` remains registered until the dated A6 analysis.
  The final digest reports the logger **STALE** (newest row ≈0.6 h old, market open); verify `mt5quotes-gold` on
  the host before using the sample further. Broker offsets +2h/+3h remain EU-rule consistent; captured spec is REAL, IOC-only.
- **Paper runway:** true equity **$56.75**, net era burn **−$0.80/closed trade** at the registered $0.40 RT and
  13.2 trades/active day: ≈**71 trades / 5.4 trading days** to zero; bootstrap 90% **60–834 trades** (10% of draws
  do not show burn). Owner's never-rebaseline decision is unchanged; this is a counter, not capital.
- **B3 DONE:** startup adopts one magic-filtered position only when entry/SL/TP are valid; ticket↔trade number is
  persisted; order attempts reconcile first; broker closing deals book actual profit + commission + swap + fee and
  are idempotent across a crash. Ambiguous/multiple positions and unrecognized close reasons remain blocked for
  operator review. Fake-MT5 restart tests and call-graph readiness checks pass. **14 PASS / 3 TODO / 3 MANUAL**;
  B4's disconnect/sizing/cost guards are the remaining code TODOs. No broker connection or order was used here.
- **A2 remains host-blocked:** the local paper ledger is flat, but no host position check or autosync cutover can be
  verified from this checkout. Do not infer host flatness from the local ledger.
- **Verdict:** paper-only; no strategy or cost assumption change, no real order, no live authorization.

### 2f. Refresh 2026-11-12 ~03:00 UTC (collection 480, log through `2026-11-11 23:59:05 UTC`)

Read with §2–§2e; a current-state refresh, not a re-judgement of any closed experiment.

- **887 closed** (191W/388L/305BE/3TIME, decisive **33.0% [29.3–36.9]**), engine ledger **$130.70**, true equity
  **$113.76**, net **−$741.04** at the registered $0.40 round trip. No open trade (`next_trade_num: 888`).
  `check_data` 0 fail / 9 documented warnings; `handoff_check` FRESH after refresh; `check_structural_stop` PASS.
- **Era n=390** (106W/177L/105BE/2TIME): decisive **37.5% [32.0–43.2]**, gross **−0.028R/trade** (pressure-report
  scale), SL/day **5.90**, SL share **45.4%**, scratch **26.9%**, avg SL **$6.01**, era DD **$200.06**. Bar card
  B1/B2/B3/C1/C2/A4/A5 **OK**. Grown-sample observation only — the 10-19 judgement stays closed and the lapsed
  n=150 arm stays lapsed.
- **Gap rides: 6** (threshold 2), 1 reopen through the stop, 0 worse exits, 3 scratch stops, 0 weekend rides.
  **New, recorded not judged:** the broker moved the daily break `20:58→22:00` → **`21:58→23:00` UTC from
  2026-11-02 with the server offset unchanged (`+7200 s` both sides)** — a schedule change, not DST.
  `derive_daily_closure()` now returns exactly `((21,58),(23,0))` from the price log, so the deployed guard
  follows it by itself; trade #887 was entered 76 min before the new close, outside the 30-min window.
- **Cost sample 27/14 complete UTC days, 3/2 weekends** (81 727 quote rows). Spread-only median **$0.55**,
  p90 $0.57; matched-trade round trip mean/median **$0.55** on **309** trades. Still spread-only, so **$0.40
  stays registered** pending A6. Offsets +2h/+3h, EU rule fits 100.00% of 56 304 rows. Spec re-captured
  2026-11-11 19:54:21 UTC: REAL, 1:1000, build 6230, IOC only, 0.01/0.01/50 volumes, stops 0 pts.
- **Feed healthy — no §6 item:** quotes continuous to `23:59:30`, bars to `23:59:05`; the 2026-11-06 "STALE"
  flag was the previous snapshot's collection boundary, not a dead logger.
- **B4 DONE:** connection (`connected` + `trade_allowed`), broker volume/stops limits, leverage-aware margin via
  `order_calc_margin()`, and a measured round-trip veto above **20% of 1R**. **17 PASS / 0 TODO / 3 MANUAL — no
  code TODO remains.** 28 hermetic tests, smoke Scenario AD, call-graph-pinned. Paper path byte-identical.
- **Verdict unchanged: no demonstrated edge after costs.** Paper-only; no strategy or cost change, no real
  order, no live authorization.

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
| **A1** | **DONE 2026-10-27** | Owner signed branch (A); the draft was registered verbatim (`docs/PREREG-2026-10-26-structstop1.5.md`, status line + dated sign-off only — §3–§7 untouched), and its three pre-deploy tool tasks were completed: era plumbing in `strategy_lab` (`CLEAR15_ATR/CUTOVER/ERA`), `check_structural_stop.py --era clear15` (clearance-aware classification, `NOT STARTED` while the cutover is None), `win_rate_report.py` era rows, `pressure.py BAR15` + `pressure_report.py --era clear15` (§5b card), `journal.py --era clear15`, and **smoke Scenario AB** (one-dial geometry proof + the refusal guards). `docs/REVIEW-2026-10-27-g1-decision.md` records the decision and every verification. | signed + dated PREREG; `strategy_lab.CLEAR15_CUTOVER` **exists and is `None`** by design (the deploy date is unknowable until the deploy); 154 tool tests OK; smoke A–AB PASSED; live-era tool output byte-identical. | — (closed; **A2 still gated on no open trade**) |
| **A2** | A1 done; deploy only in a verified **flat-host** window (not eligible from this checkout alone) | Exactly one line in `engine.py`: `SL_CLEAR_ATR = 0.5 → 1.5`. Nothing else (PREREG §2 freeze). Set `strategy_lab.CLEAR15_CUTOVER` (and `pressure.CLEAR15_CUTOVER`) to the host's `autosync: merge upstream` commit **time** for the deploy. | one-line diff; smoke Scenario AB; `check_structural_stop.py --era clear15` prints the OLD/NEW bracket; dated REVIEW with cutover. | **Host unavailable.** Repository has no open trade on 2026-11-06; that does not prove the host is flat. Re-confirm host position at deploy time; never hand-edit `/opt/gold`. |
| **A3** | A2 + 10–20 new-era trades | Judge **A1–A5** of the registered bar (geometry + calibration). | dated REVIEW: 0 stops inside level, ≥1.5 ATR clearance, recall 99.6–100%, level-bound 70–90%, median risk 3.8–5.0 ATR. A failure = REVERT, no P&L reading. | none |
| **A4** | n=100 in the new era | **SCREEN** judgement (net R/trade ≥ −0.05R at $0.20/side, decisive WR ≥ 40%, B1–B3, A still passes). | dated REVIEW with Wilson CIs, per-day columns, cost sensitivity. | none |
| **A5** | n=150 or 2026-12-01 21:00 UTC, whichever comes first | **PASS/FAIL/REVERT** judgement exactly as registered. | dated REVIEW; PASS requires Wilson LB > 40%, net ≥ 0.00R at $0.20/side, ≥ −0.05R at $0.275/side, era DD ≤ $200. | none |
| **A6** | quote sample gate **MET 2026-11-06** (proceed after the preceding Track-B queue step B4) | Complete the cost model: measured all-in round trip (spread + slippage + commission + swap), re-cost the ledger and canonical replay with a sensitivity range, write a dated cost doc. Keep $0.40 registered until that analysis is complete. | `xm_quote_report.py` target met; `live_readiness.py` `quote_sample` PASS; `cost_model` evidence resolved by dated `ANALYSIS` doc. | Spread-only evidence is complete; slippage/commission/swap all-in evidence still needed. |
| **A7** | after A5, only if PASS | **Independent** forward window on the **same unchanged strategy** — 2–4 months, multiple regimes, chronological holdout. This, not a replay, is the edge test. | dated pre-registration before the window; positive net expectancy after measured cost with acceptable drawdown and uncertainty. | time; a FAIL/REVERT ends this track. |
| **A8** | research only, parallel | Private manual observation log (§7) for the owner's pressure/hold hypothesis. No bot behaviour change. ≥100 matched post-stop observations before any exploratory screen; then a new dated pre-registration, never an engine gate. | private log (outside Git) + optional dated ANALYSIS. | the manual rule is still undefined — ask the owner for the definition before coding it. |

### Track B — LIVE execution engineering (all paper-safe; none places an order)

Every step must move at least one `live_readiness.py` check from TODO to PASS **and** add a hermetic test. The gate stays CLOSED until all of them plus the MANUAL items are PASS.

| ID | Gate / when | Work | Completion test | Blocker |
|---|---|---|---|---|
| **B1** | DONE 10-26 | `tools/live_readiness.py` scorecard + arm/filling/closed-bar hardening. | 9 PASS / 8 TODO / 3 MANUAL. | — |
| **B2** | **DONE 2026-10-28** | Choice recorded first (**implement, no divergence**): `docs/DECISION-2026-10-28-b2-broker-be-and-time-stop.md`. Broker-side **BE ratchet** (`TRADE_ACTION_SLTP` at +0.75R, stop to entry, only after `DONE`) **and** the 240-min **time stop** (market close by ticket), plus the LIVE fill state both rules need, restart persistence and a reconcile-pending block on new exposure. B3 later replaced quote-based time-stop booking with actual deal-history accounting. | **MET:** `live_readiness.py` `broker_be` + `broker_time_stop` PASS (now call-graph checks, not substring checks); **19** fake-MT5 tests in `tools/test_live_manage.py`; **Scenario AC** (12 checks) in `smoke_test.py`; smoke A–AB unchanged; scorecard **11 PASS / 6 TODO / 3 MANUAL**, gate CLOSED. Evidence: `docs/REVIEW-2026-10-28-b2-broker-be-time-stop.md`. | — (closed; followed by B3, now done) |
| **B3** | **DONE 2026-11-06** | Startup adopts one valid strategy position by magic; order path reconciles before exposure; realized P&L comes from broker `history_deals_get`; ticket↔trade number persists; ambiguous states fail closed. | **MET:** `position_reconcile` + `deal_reconcile` PASS through the LIVE call graph; 25 fake-MT5 tests (including query-failure, restart, and idempotency); smoke Scenario AC uses actual deal accounting. | — |
| **B4** | **DONE 2026-11-12** | **Pre-order safety:** `terminal_info().connected` **+** `trade_allowed`; `volume_min`/`volume_step`/**`volume_max`** and `trade_stops_level`/`freeze_level` from the live spec; leverage-aware free-margin check via `order_calc_margin()`; and a **spread-as-%-of-R** veto (measured $0.55 is ~9% of median 1R, up to 24.5% of the smallest). | **MET:** `disconnect_safety`, `sizing_limits`, `cost_guard` PASS through the call graph; **28** hermetic tests (`tools/test_live_safety.py`); **smoke Scenario AD** (11 checks, every refusal sends nothing); every guard re-pinned to go red if disconnected; paper path byte-identical. Scorecard **17 PASS / 0 TODO / 3 MANUAL**, gate CLOSED. Evidence: `docs/ANALYSIS-2026-11-12-b4-live-order-safety.md`. | — (closed; followed by B5, host-only) |
| **B5** | **B2–B4 DONE → next open step** | **DEMO-account** evidence on the host: fill (IOC), SL/TP, BE/time management, rejection handling, disconnect, restart, reconciliation, kill switch, and 48 h of stable running. Use a DEMO account and a separate data dir — the captured spec says REAL. | `docs/DEMO-EVIDENCE.md` (**new file to be created**, redacted) exists; `live_readiness.py` `demo_evidence` PASS. | **HOST/operator action** — cannot be done from the repo checkout. |
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
| 2026-10-27 (later) | **G1 SIGNED (branch A) → A1 DONE. No deploy, no engine change.** `docs/PREREG-2026-10-26-structstop1.5.md` registered verbatim with the dated owner sign-off; the §2 pre-deploy tool work landed (strategy_lab / check_structural_stop / win_rate_report / pressure + pressure_report / journal all era-aware, `CLEAR15_CUTOVER = None` so every clear15 path is inert); new **smoke Scenario AB** pins the one-dial geometry and the "refuse to judge an unstarted window" guards; readiness timeline moved G1 → done and added the A2 row. Evidence: `docs/REVIEW-2026-10-27-g1-decision.md`. **A2 is the next step and it is gated on there being no open trade.** |
| 2026-10-28 | **B2 DONE (Track B, parallel to the blocked A2).** Decision recorded before coding (implement, no divergence); the LIVE path now mirrors the +0.75R BE ratchet (`TRADE_ACTION_SLTP`) and the 240-min time stop (market close), records the fill state both rules need, persists ticket/risk across restarts, refuses new exposure while a broker-closed position is unreconciled, and runs management even while disarmed (risk-reducing only). Scorecard **9→11 PASS, 8→6 TODO, gate CLOSED**; the two checks were also made semantic (call-graph + AST, no docstring credit). Tests: 19 new fake-MT5, Scenario AC (12 checks), smoke A–AB unchanged, 20 + 64 existing green. **No order, no arming, no strategy change.** `docs/REVIEW-2026-10-28-b2-broker-be-time-stop.md`. |
| 2026-11-06 | **B3 DONE (Track B; A2 remains host-blocked).** LIVE startup/order attempts reconcile magic-filtered broker positions, adopt one valid orphan, persist ticket↔trade number, and book actual realized deal P&L (profit/commission/swap/fee) idempotently. Ambiguous position/deal state stays fail-closed. Readiness **12→14 PASS, 5→3 TODO, gate CLOSED**; 25 fake-MT5 tests + Scenario AC's broker-deal time-stop accounting; no broker connection/order, no strategy change. `docs/REVIEW-2026-11-06-b3-position-deal-reconciliation.md`. |
| 2026-11-12 | **B4 DONE (Track B; A2 remains host-blocked).** The LIVE order path now refuses to send without a connected, trade-permitted terminal; a lot size on the broker's own min/step/**max** grid with SL/TP outside its stops level; a leverage-aware free-margin check; and a **measured** round trip ≤ 20% of 1R. Readiness **14→17 PASS, 3→0 TODO**, gate CLOSED — **no code TODO left**. 28 hermetic tests + smoke Scenario AD; two defects caught (zero-spread fail-open; notional margin ignoring 1:1000). Paper path byte-identical, no order, no strategy change. `docs/ANALYSIS-2026-11-12-b4-live-order-safety.md`. |
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
`python3 tools/test_live_manage.py`, `python3 tools/test_live_safety.py`,
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
4. Track B in order (B2 → B6), one `live_readiness.py` check at a time. B2–B4 are done; **B5 is a host/operator
   action** (DEMO account + separate data dir) and must be reported as the exact blocker, not simulated.
5. A6/A8 (cost sample, private observation log) whenever their data arrives.
6. C1 only when everything above is complete.

Never start a step whose pre-registration does not exist. Never re-open a lapsed arm because the sample later grew.

---

## 7. Manual observation record (private; do not commit filled rows)

One row per eligible signal/stop event, including cases where the owner does **not** override the stop and cases that lose. Keep bot and manual entries separate; do not call them matched unless timestamps and setup actually match. Minimum fields:

`timestamp_utc, bot_trade_id, side, bot_entry, bot_sl, bot_tp, manual_entry, manual_exit, pressure_source, pressure_metric, pressure_timeframe, pressure_value_at_entry, pressure_value_at_stop_touch, last_closed_bar_utc, contemporaneous_action, reason_code, max_hold_or_exit_rule, post_stop_markout_horizons, mfe, mae, hypothetical_exit, estimated_cost, notes_without_account_identifiers`

A trade that later touches its former target after the bot's stop is a **counterfactual mark-out**, not a win under the bot's rules. The entry, stop event and decision must be timestamped **before** looking at the recovery path. This phase changes no bot behaviour.
