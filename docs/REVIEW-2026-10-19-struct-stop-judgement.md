# REVIEW 2026-10-19 — structural-stop time-gate judgement at n=139

**Judgement recorded:** 2026-10-19 21:19 UTC, after the registered 21:00 UTC time gate.  
**Data actually available:** latest checked-in log/quote data ends at 18:10 UTC; ledger has 636 closes, of which 139 are in the structural-stop era. `git ls-remote origin main` still pointed at the checked-in base commit, so no newer main snapshot was available. This is a judgement on the latest available synced rows, not a claim about unsynced host activity after 18:10. The n=150 arm had not been reached in that snapshot.

**Decision:** the §7 extra gap-risk **REVERT trigger is FIRED** under the counting rule recorded below (2 rides, threshold 2). The ordinary screen is MET, but this does not override the separate trigger; PASS is not available. The registered action says to revert the structural stop **with the gap guard first**. That guard is only a named candidate in the repository, with no approved cutoff or open-position policy. Therefore this review completes the evidence judgement and records the trigger, but **does not implement the guard, revert the stop, deploy anything, or start the 0.25 ATR test**. This is a documented blocker, not a re-interpretation or waiver of the trigger. `engine.py` remains paper-only (`TRADING_MODE = "FORWARD_TEST"`) and unchanged.

---

## 1. Session-start checks

| Check | Result |
|---|---|
| Branch/worktree before review | `arena/f140154e-gold-trading-bot`, clean at `5f957eb` |
| `python3 tools/check_data.py` | **0 fail, 8 documented warnings**; 636 ledger rows; latest log bar 2026-10-19 18:10:05 UTC |
| `python3 tools/handoff_check.py` | **FRESH**, one advisory (`data_collection` is unavailable from the data files); snapshot and row counts otherwise match |
| `python3 tools/check_structural_stop.py` | **PASS**, n=139; 0 post-cutover stops inside the level; 81.3% level-bound; median clearance +0.50 ATR; median risk 3.27 ATR. Boundary still brackets the deploy: last old-rule #498 at 02:39 UTC, first new-rule #499 at 03:33 UTC |
| `python3 tools/strategy_lab.py --calib-only` | Recall **99.8%** on the 0.75R master and **99.7%** on max-hold; A3 is within the registered range |
| `python3 tools/check_gap_rides.py` | **2 scheduled-closure rides / threshold 2**; 0 reopened through a stop, 0 exits worse than stop/target, 1 ratcheted scratch, 0 weekend rides |
| `python3 tools/pressure_report.py --root .` | Struct-stop n=139; all five B/C screen bars inside their thresholds |
| `python3 tools/win_rate_report.py --spread 0.40` | Costed ledger report completed; `$0.40` remains the registered round-trip assumption |
| `python3 tools/strategy_lab.py --table --only baseline,structstop` | Costed stateful replay table completed at $0.00, $0.30, $0.40 and $0.70 round trip |
| `python3 tools/xm_quote_report.py` | 6.1 days, 5/14 complete UTC days, 1/2 complete weekends; sample target **not met**, median spread $0.55 first look |

The quote logger has not earned a cost-assumption change: keep $0.40 round trip. The 18:10 data tail is about three hours before this review; production process identity and any later host rows remain operator-only and unverified from this checkout.

## 2. Registered screen and other revert bars

The evaluated window is the existing structural-stop era, entries at/after 2026-10-06 03:00 UTC. No re-slicing was done.

| Bar | Current result | Registered threshold | Verdict |
|---|---:|---:|---|
| A1 — stops inside level | 0 / 139 | 0 | PASS |
| A2 — clearance | median +0.50 ATR; no inside-level stops | ≥0, and ≥0.5 ATR when level-bound | PASS |
| A3 — replay recall | 99.8% / 99.7% (master / max-hold) | 99.6–100% | PASS |
| A4 — level-bound share | 81.3% | 70–90% | PASS |
| A5 — median risk | 3.27 ATR | 2.7–3.5 ATR | PASS |
| B1 — SL events / calendar day | 5.91 | ≤6.5 | PASS |
| B2 — SL share of closed | 65/139 = 46.76% | ≤47.0% | PASS |
| B3 — scratch share | 34/139 = 24.46% | ≤35% | PASS |
| C1 — gross R / trade, registered ledger scale | −0.071R | ≥−0.10R | PASS |
| C2 — decisive WR | 39/104 = 37.50%; Wilson 95% [28.8%, 47.1%] | ≥36% for SCREEN | PASS for SCREEN |

**SCREEN MET. PASS NOT MET:** the time gate elapsed with n=139 (<150), and the Wilson lower bound 28.8% is not greater than 32.1%. The result is not evidence of a profitable strategy: gross era P&L is **−$56.01**; at the registered $0.40 round trip, net is **−$111.61 (−0.142R/trade)**. The first-look $0.55 quote median would put the era at −$132.46 (−0.168R/trade), but the logger sample is too short to replace the registered assumption.

The other numeric revert conditions do not fire on these rows: gross R/trade −0.071R is above the −0.20R trigger; average SL loss $5.78 is below 2.2 × the $3.91 pre-change loss ($8.60); era drawdown $112.87 is below $250. These clearances do **not** cancel the distinct closure-gap trigger.

As a separate replay cross-check, `strategy_lab.py --table --only baseline,structstop` at $0.20/side reports the post-cutover `structstop` replay row as n=148, 38.2% decisive, −0.113R/trade, −$0.800/trade, −$9.86/day, 12.3 trades/day, 24.4-minute median hold and $156.9 max drawdown. This is the stateful counterfactual replay, not the 139-row ledger verdict; it is not substituted for the registered B/C screen.

## 3. Closure-gap trigger — counting rule and judgement

To make the registered count reproducible, this review uses the read-only tool's explicit rule:

- A ride is a post-cutover ledger trade whose hold interval spans a price-log hole longer than five minutes.
- Count only holes classified as scheduled market closures: the daily break (starts 20:00–22:00 UTC and lasts 30–180 minutes) or the weekly close (>24 hours). Feed outages are excluded.
- Count every qualifying ride, whether or not a later gap loss occurred; the registered wording is about an unenforceable stop while the market is shut, not only about a stop fill that missed its price.

`tools/check_gap_rides.py` reports **2**, exactly the registered threshold:

| Trade | Closure and reopen | Stop / reopen headroom | Recorded exit | Gap damage |
|---|---|---|---|---|
| #595 BUY | Daily break, 2026-10-14; reopen 22:00 UTC | Stop was ratcheted to entry; reopen $11.43 above it | TP +$14.45 | No gap-through; no worse fill |
| #610 BUY | Daily break, 2026-10-15; reopen 22:00 UTC | Reopen $4.15 above stop | SL −$6.95 at the stop | No gap-through; no worse fill |

No post-cutover weekend closure was ridden. Both rides qualify under the stated rule even though neither caused gap loss; the damage facts are recorded, not used to add an unregistered qualifier. Therefore **the extra REVERT trigger is fired**.

## 4. Required action and blocker

The controlling text is `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` §7: if the extra gap-risk trigger is met, **revert and take the gap guard first**. The already-approved 0.25 ATR level test is not eligible after this verdict.

The guard itself is not yet an operationally defined rule. `docs/REVIEW-2026-10-05.md` §5b names (but does not adopt) a pre-close entry guard with an unspecified `N` minutes and/or a broker-side flat-before-close policy; HANDOFF §6.3(h) likewise leaves it unadopted. The repository does not define an owner-approved cutoff, whether it blocks entries only or also closes open paper positions, a verified holiday/DST schedule, or the treatment of the daily versus weekly closure. The broker-clock transition around 2026-10-25 is still unverified. The existing rollover blackout is not a substitute: it is an entry gate, not an open-position close policy, and its window is not registered as the closure guard.

Accordingly, **no runtime change is made in this review**. Do not silently choose `N`, invent a flatten rule, apply only half of the “guard first” action, or proceed to the level-test experiment. The next step is an owner-defined and dated pre-registration for the gap guard, followed by its separate reviewed implementation; only then can the prescribed structural-stop revert be prepared and the host operator verify/deploy it. Production process/revision and any data newer than 18:10 must also be checked on the host before operational conclusions. Until then the checked-in engine remains in `FORWARD_TEST` with the structural stop still present; no real orders or deployment are authorized.

## 5. Reproduction

```bash
python3 tools/check_data.py
python3 tools/handoff_check.py
python3 tools/check_structural_stop.py
python3 tools/strategy_lab.py --calib-only
python3 tools/check_gap_rides.py
python3 tools/pressure_report.py --root .
python3 tools/win_rate_report.py --spread 0.40
python3 tools/strategy_lab.py --table --only baseline,structstop
python3 tools/xm_quote_report.py
```

**Files changed for this judgement:** this review, `docs/EXECUTION-PLAN.md`, `docs/HANDOFF.md`, `docs/HANDOFF-HISTORY.md`, and `archive/PROJECT_LOG.md`. `engine.py`, `trade_filter.py`, all CSVs, parameters and deployment files are unchanged.
