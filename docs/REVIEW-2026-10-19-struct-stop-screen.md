# REVIEW 2026-10-19 — structural-stop interim screen at n=127, and the §7 closure-gap trigger

**This is not the scheduled judgement.** The pre-registered confirmatory point is
**2026-10-19 21:00 UTC or n=150, whichever comes first**
(`docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` §7). This session ran at
~05:20–06:30 UTC on 2026-10-19 with the checked-in data (collection 279, log to
2026-10-19 02:59:06 UTC): the struct-stop era is **n=127 closed**, so neither arm
of the gate had been reached. Per `docs/EXECUTION-PLAN.md` this session executed
the first eligible step only — the every-session verification plus the complete
registered screen on current rows. **No runtime rule was changed, nothing was
deployed, and the 0.25 ATR level test remains blocked behind the judgement.**

Paper only: `engine.py` remains `TRADING_MODE = "FORWARD_TEST"`.

> **Housekeeping.** An earlier session on this date (≈04:41 UTC) opened PR #38 with a
> draft of this file; it was **closed without merging**, so none of it reached `main`.
> Everything below was re-derived from the data by this session. The one addition is
> `tools/check_gap_rides.py` (§3): the §7 gap trigger had never been counted by any
> tool, and it is the only registered condition that is currently in question.

---

## 1. Session-start verification (all green)

| Check | Result |
|---|---|
| Branch / worktree | `arena/8f3ca0a8-gold-trading-bot`, clean at `be447a5` (data collection 279) |
| `tools/check_data.py` | **0 fail, 8 warn** (the documented historical warnings) on the reconciled 624-row ledger |
| `tools/handoff_check.py` | **FRESH** (2 advisory drift: snapshot 02:33 vs newest data 02:59; open SELL #626) |
| `tools/check_structural_stop.py` | **PASS** — era n=127, **0 stops inside their level**, median clearance +0.50 ATR; boundary #498 (old rule) → #499 (new rule) confirms `LIVE_CUTOVER 2026-10-06 03:00 UTC` |
| `tools/strategy_lab.py --calib-only` | Recall **100.0% / 100.0%** (0.75R master, max-hold) — harness and engine agree; **A3 holds** |
| `tools/smoke_test.py` | **SMOKE TEST PASSED** (A–W; W is new this session and pins the gap-ride counter) |
| `python3 -m py_compile engine.py trade_filter.py tools/*.py` | clean |
| Ledger | 624 closed, 122W/271L/229BE/2TIME, 31.0% decisive, engine ledger $150.69, true equity $133.71; reconciled state from the 10-19 phantom-row incident holds (`docs/REVIEW-2026-10-19-negative-balance.md`) |
| Open position | SELL #626 @ $4175.02 (2026-10-19 02:57:06 UTC), SL $4179.89 / TP $4167.71 — valid geometry, post-repair numbering, **not in the ledger**, so era closed n is still 127 |

**Blocker that the repo cannot close:** the production host's running executable /
deploy identity is still unverified (`docs/REVIEW-2026-10-19-negative-balance.md`
steps 1–5). Every statement below is about the *checked-in* data, not about the
health of the live box.

---

## 2. The registered screen at n=127 (§7, judged A → B → C)

Era: entries ≥ 2026-10-06 03:00 UTC — 127 closed trades over **10 entry dates**
(2026-10-06 → 2026-10-16), 37W/60L/29BE/1TIME, gross **−$47.48** (−$0.374/trade),
median hold 26 min (p90 84, max 240 = the one TIME exit).

**A. Is the code doing what the model says?**

| # | Metric | Value | Bar | |
|---|---|---|---|---|
| A1 | Stops inside their level (post-cutover) | **0 / 127** | must be 0 | ✔ |
| A2 | Median clearance | **+0.50 ATR** | ≥ 0 (≥ 0.5 level-bound) | ✔ |
| A3 | Replay funnel recall | **100.0%** | 99.6–100% | ✔ |
| A4 | Level-bound share | **83.5%** | 70–90% | ✔ |
| A5 | Median risk | **3.32 ATR** | 2.7–3.5 | ✔ |

**B/C. Screen (the n ≥ 100 arm is met; the verdict is still interim):**

| # | Metric | Value | Bar | |
|---|---|---|---|---|
| B1 | SL events / day | **6.00** (60 SL over 10 entry dates; 5.45 over the 11-calendar-day span) | ≤ 6.5 | ✔ |
| B2 | SL share of closed | **47.24%** (60/127) | ≤ 47.0% strict | ✘ |
| B3 | Scratch (BE) share | **22.83%** (29/127) | ≤ 35% | ✔ |
| C1 | R/trade, gross (win-rate scale) | **−0.065R** ($/trade ÷ mean 1R $5.75) | ≥ −0.10R | ✔ |
| C2 | Decisive WR | **38.14%** (37/97), Wilson 95% [29.1, 48.1] | ≥ 36% | ✔ |

**SCREEN: NOT MET** — on B2 alone, by 0.24 pp. Do not round this up: as written,
47.24% > 47.0% fails. (One trade either way would flip it: 59/127 = 46.46% passes,
60/128 = 46.88% passes.) This is the same marginal miss recorded on 2026-10-17;
era P&L has not moved since the last era close (#625, 2026-10-16 19:45 UTC).

**PASS is not reachable at this n on two independent grounds:** n=127 < 150, and
the Wilson lower bound is **29.1%**, below the required > 32.1% (at n=150 that
bound needs ≈ 40% decisive WR). 23 more closes are needed for n=150; at the era's
~12.7 trades/day the 21:00 UTC timestamp arrives first.

**Costed reads** (the screen itself is on the cost-0 ledger scale, per §7):

| Cost assumption | Era net | Era net R/trade | Source |
|---|---|---|---|
| $0.00 (ledger, no spread) | −$47.48 | **−0.065R** | `win_rate_report.py` |
| **$0.40 round trip (registered assumption)** | **−$98.30** | **−0.135R** | `win_rate_report.py --spread 0.40` |
| $0.55 round trip (quote logger median, first look) | −$117.35 | **−0.161R** | `xm_quote_report.py` median spread |
| $0.60 round trip (sensitivity) | −$123.85 | −0.169R | `win_rate_report.py --spread 0.40` |
| $0.70 round trip (sensitivity) | −$135.85 | −0.186R | `strategy_lab.py --cost 0.35` |

Whole book at $0.40: **−$615.89** net. The era is **negative after realistic
costs under every cost read** — no edge is claimed under any verdict available
tonight.

**Replay cross-check** (§7 reporting row: `strategy_lab --table --only
baseline,structstop`, post-cutover window; row-to-row deltas only, the replay is
not the ledger):

| Cost/side | variant | n | decWR | SL% | R/t | $/t | maxDD | avgSL | hold |
|---|---|---|---|---|---|---|---|---|---|
| $0.15 | baseline | 205 | 40.4% | 41.0% | −0.088 | −0.297 | 87.2 | −3.71 | 10.0 m |
| $0.15 | structstop | 133 | 38.1% | 45.1% | −0.095 | −0.673 | 126.2 | −6.12 | 25.0 m |
| **$0.20** | baseline | 205 | 40.4% | 41.0% | −0.120 | −0.397 | 101.8 | −3.81 | 10.0 m |
| **$0.20** | structstop | 133 | 38.1% | 45.1% | −0.116 | −0.773 | 137.0 | −6.22 | 25.0 m |
| $0.35 | baseline | 205 | 40.4% | 41.0% | −0.216 | −0.697 | 148.1 | −4.11 | 10.0 m |
| $0.35 | structstop | 133 | 38.1% | 45.1% | −0.177 | −1.073 | 169.7 | −6.52 | 25.0 m |

The sign of the change against baseline flips with the cost assumption
(−0.007R at $0.20/side, +0.007R at $0.15, +0.039R at $0.35): at the registered
cost the structural stop is a hair better than the old geometry in this window,
at every cost it is still negative. Consistent with the parent analysis
(§5 of 2026-10-05: better in 3 of 4 parameter eras, never positive).

**Revert triggers R4/R5/R7: all clear.** R/trade −0.065R (revert ≤ −0.20R);
avg SL $5.85 vs the $8.60 trigger (2.2 × $3.91 pre-change; ≈ 1.5×); era
peak-to-trough drawdown $93.38 gross ($131.04 net at $0.40) vs $250. **The fifth
condition — the closure-gap trigger — does not read clear. See §3.**

Side split (descriptive): BUY n=63, 36.7% dec, −$24.67; SELL n=64, 39.6% dec,
−$22.81. No side action is registered or taken.

---

## 3. The one condition that is in question: §7's closure-gap revert trigger

### 3.1 The registered text

> | **Extra revert trigger (gap risk)** | 2 or more post-cutover trades found
> open across a daily/weekly closure with an unenforceable stop — that is the §6
> cost of longer holds materialising; revert and take the gap guard first |

Why it exists (§6 of the parent analysis, REVIEW-2026-10-05 §2a/§5b): the
structural stop made holds ~2× longer, so a position can still be open when the
broker shuts the market. While it is shut **the stop cannot be enforced**, and
in LIVE a stop is not broker-protected across a gap — it fills at the open, not
at the stop price (the reference case is the weekend hold #476, 49.1 h).

### 3.2 The count, and how it is counted

No tool counted this. `tools/check_gap_rides.py` (new, read-only) now does, with
the counting rule written down in the tool:

* a **ride** = a trade open across a hole in the price log (the same inclusive
  span test as `check_data.py`, > 5 min);
* a hole is a **scheduled closure** when it is the weekly close (> 24 h) or the
  broker's daily break (starts 20:00–22:00 UTC, lasts 30–180 min). A feed outage
  is a *different* risk (stale price, not a shut market) and is not counted;
* the era is the struct-stop window, entries ≥ 2026-10-06 03:00 UTC.

```
$ python3 tools/check_gap_rides.py
  post-cutover rides over a scheduled daily/weekly closure : 2   (threshold 2)  -> REACHED
     of which the reopen gapped THROUGH the stop          : 0
     of which the exit printed worse than the stop         : 0
     of which the stop sat at entry (scratch, $0 exposure) : 1
     of which a WEEKEND closure (the #476 failure mode)   : 0
     tightest reopen (least headroom over the stop)       : #610 BUY $+4.15
```

**The registered count is 2 of a registered threshold of 2 — the trigger is
REACHED.** It was 0 at n=78 (2026-10-13), when the same span test was applied
by hand; the two rides appeared on 10-14 and 10-15.

### 3.3 The evidence for each ride (and the whole-book history)

| Trade | Window (UTC) | Closure | Exit | Reopen open | Stop | Headroom at the reopen | Gap through the stop? | Exit worse than the stop? |
|---|---|---|---|---|---|---|---|---|
| **#595** BUY | 10-14 18:28:04 → 22:21:03 | daily break 20:58:02 → 22:00:08 (62 min) | TP 4107.24, **+$14.45** | 4104.22 | 4092.79 (= entry, ratcheted scratch) | +$11.43 | no | no |
| **#610** BUY | 10-15 20:05:05 → 22:48:07 | daily break 20:58:06 → 22:00:07 (62 min) | SL 4165.95, **−$6.95** | 4170.10 | 4165.95 | +$4.15 | no | no |

Pre-cutover, for contrast: **#95** SELL rode the 10-11 → 10-13 weekend closure
(2943 min) and **#409** BUY rode the 09-29 daily break. Both are *pre*-cutover
and neither counts toward the trigger, but both are the shape of ride that the
§7 sentence is about. No post-cutover trade rode a **weekend** closure: the
10-09→10-11 and 10-16→10-18 weekend gaps were both clear.

### 3.4 What this session concludes, and what it does not

Two different questions are hiding inside the registered sentence, and the tool
prints both so the judgement cannot settle one by omission:

1. **The trigger count** — post-cutover trades open across a scheduled
   daily/weekly closure = **2**, threshold **2**. Read literally, the stop of
   such a position is unenforceable *while the market is shut*, so both rides
   qualify. **The count is at the threshold.**
2. **The damage** — did the unenforceable stop actually cost anything? **No.**
   Neither reopen gapped through its stop (#610 reopened $4.15 *above* its stop;
   #595 $11.43 above a stop that had already been ratcheted to entry, i.e. a
   scratch with $0 exposure), and both exits printed at the stop or target
   price with no slippage. No ride has yet cost a cent of gap loss.

**The count is at the registered threshold and this session does not re-interpret
it away.** `docs/EXECUTION-PLAN.md` is explicit — *"If a registered revert
condition is actually met, document it and follow that pre-registered rule; do
not invent a replacement threshold"* — and the era's own §7 trigger was written
precisely to stop a later session from explaining away an inconvenient number
with a narrower definition chosen after the fact.

**This session nevertheless does not execute the revert, for three reasons that
are about process, not about the number:**

1. **The window is open until it is judged** (`docs/HANDOFF.md` §6.1: *"STRUCT-STOP
   WINDOW IS OPEN — do not touch exits until it is judged"*). The registered
   judgement point is **21:00 UTC today or n=150**; it is 05:20 UTC and n=127.
   A revert is a runtime change, and this repository's own protocol is that
   changes wait for the owner's sign-off (`docs/HANDOFF.md` §11 rule 2) and reach
   the host only through merge + autosync.
2. **The counting rule was never operationalised.** §7 registers a *threshold*
   (2) but not a *definition* of what counts. The 10-13 "0 rides" note used the
   span test, which is what the tool now uses. That this session is the first to
   put a rule in writing — 16 hours before the judgement — is exactly why the
   rule must be **stated in the judgement record**, not settled by which way a
   session happened to count.
3. **The trigger is a risk trigger, and the risk has not materialised.** The
   §7 sentence is about the *cost of longer holds*; here both rides cost $0.00
   of gap damage, one of them was a scratch, and no weekend closure has been
   ridden. That is evidence for the judgement, not a replacement count.

**Therefore the 21:00 judgement must resolve this first, explicitly, in this
order:**

1. **State the counting rule used** (the tool's: a ride = open across a
   scheduled daily/weekly closure, counted from the cutover) and confirm the
   count. If the count is ≥ 2, the trigger is fired — §7's thresholds may not
   be edited or relaxed to make it go away.
2. **If the trigger is judged fired**, the registered action is the pre-registered
   one: a **single-commit `git revert`** of the structural stop, **gap guard
   first** (§6.3(h) flat-before-close / pre-close entry guard — note it reads the
   wall clock, so it is not hermetic and needs its own PR and pre-registration),
   and the **0.25 ATR level test does not proceed**.
3. **If the trigger is judged not fired**, the judgement must record the rule it
   applied and why (e.g. only fills that missed the stop count; only weekly
   closures count) so the count is reproducible from tonight onward — and
   `tools/check_gap_rides.py` is then the thing that keeps it honest.
4. Either way, the **SCREEN verdict** is still **NOT MET** (B2, 47.24% vs ≤47.0%)
   and the era is negative after costs, so a PASS is not available tonight at
   n=127 under any reading.

---

## 4. Parallel tracks (no action taken)

- **Quote logger** (`tools/xm_quote_report.py`): 2026-10-13 15:48:30 → 2026-10-19
  02:59:30 UTC (5.5 days) — **5/14 complete UTC days, 1/2 complete weekends**;
  target **NOT met**, so the **$0.40 round-trip assumption stays in force**.
  First-look median spread **$0.55** (p90 $0.57, p95 $0.58, p99 $0.82, max $2.00);
  **98.5%** of usable samples are above the assumed $0.40, and the median spread
  is **10.5% of the era's median 1R ($5.26)** — the assumption is, if anything,
  optimistic. 4 scheduled closures (52.0 h) kept, 0 stalls outside them. Server
  offset still only +3 h observed; the **2026-10-25 DST transition** remains the
  verification point — do not guess it.
- **Pressure composite** (`tools/pressure_report.py`): last bar *balanced*,
  BUY 43.4% / SELL 56.6%. Calibration on the era (n=127 joined) still returns
  *collinear with side — not separable within-side* (the `against` bucket is
  empty on both sides). Context only; no hold/exit inference is drawn from it,
  and the owner's manual pressure method remains unspecified and unlogged
  (EXECUTION-PLAN research track unchanged).
- **Incident recovery** (`docs/REVIEW-2026-10-19-negative-balance.md`): the
  reconciled ledger passes integrity, but the host-side steps (pause the engine,
  preserve host CSV/status/journal, verify the running executable and revision,
  then restart corrected code) are **operator-only** and remain open.
- **Large-N history path** (`docs/ACCELERATE-TESTING.md` §2): the first
  dump → convert → replay on the box is still pending; tooling only.

---

## 5. Decision and next eligible action

- **Decision: none.** SCREEN **NOT MET** at n=127 (B2 only). No PASS, KEEP or
  REVERT verdict is available before the registered point, and **no parameter,
  gate, stop, target, ratchet or blackout was changed**. The §7 gap trigger is
  **recorded at its threshold** (§3) and is the first item of the judgement.
- **Next eligible action:** the confirmatory judgement session at
  **2026-10-19 21:00 UTC** (or on the close that takes the era to n=150, if
  earlier), in §7 order: **(0)** resolve the §3 gap trigger and record the
  counting rule; **(a)** re-run `tools/check_structural_stop.py` +
  `tools/strategy_lab.py --calib-only` + `tools/check_gap_rides.py`; **(b)** judge
  B/C on the then-current rows; **(c)** only if that judgement permits, consider
  the already-registered 0.25 ATR level test
  (`docs/PREREG-2026-10-15-level-test-0.25.md`) as the single next variable,
  with its cutover taken from the host deploy time — never the plan or merge time.
- **Blockers:** production-host verification (incident + deploy identity) is
  operator-only; the quote-cost sample needs 9 more complete days and 1 more
  weekend; the manual pressure hypothesis needs the owner's explicit
  source/timeframe/rule definition before any log or test exists; a revert, if
  the gap trigger is judged fired, needs the owner's authorisation and a host
  deploy.

**Reproduce** (all run 2026-10-19 ~05:20–06:30 UTC on collection 279):

```bash
python3 tools/check_data.py                 # 0 fail, 8 warn
python3 tools/handoff_check.py              # FRESH
python3 tools/check_structural_stop.py      # PASS, 0 inside the level
python3 tools/strategy_lab.py --calib-only  # recall 100.0 / 100.0
python3 tools/smoke_test.py                 # SMOKE TEST PASSED (A-W)
python3 tools/check_gap_rides.py            # §3: trigger count 2 of 2
python3 tools/pressure_report.py --root .   # tape + era card + calibration
python3 tools/win_rate_report.py --spread 0.40            # cost view (1b)
python3 tools/strategy_lab.py --table --only baseline,structstop   # replay rows
python3 tools/xm_quote_report.py            # 5/14 days, 1/2 weekends, $0.55 median
```

**Files changed by this session:** `tools/check_gap_rides.py` (new, read-only),
`tools/smoke_test.py` (Scenario W), `docs/REVIEW-2026-10-19-struct-stop-screen.md`
(this file), `docs/HANDOFF.md`, `docs/HANDOFF-HISTORY.md`, `docs/EXECUTION-PLAN.md`,
`archive/PROJECT_LOG.md`. **`engine.py` and `trade_filter.py` are untouched.**
