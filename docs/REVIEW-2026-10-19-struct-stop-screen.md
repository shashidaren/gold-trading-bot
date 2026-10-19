# REVIEW 2026-10-19 (early session) — structural-stop interim screen at n=127

**This is not the scheduled judgement.** The pre-registered confirmatory point is
**2026-10-19 21:00 UTC or n=150, whichever comes first**
(`docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` §7). This session ran at
~04:41 UTC on 2026-10-19 with the checked-in data (collection 279, log to
2026-10-19 02:59 UTC): struct-stop era **n=127 closed**, so neither arm of the
gate had been reached. Per `docs/EXECUTION-PLAN.md` this session executed the
first eligible step only — the every-session verification plus the complete
registered screen on current rows. **No runtime rule was changed, nothing was
deployed, and the 0.25 ATR level test remains blocked behind the judgement.**

Paper only: `TRADING_MODE = "FORWARD_TEST"` throughout.

## 1. Session-start verification (all green)

| Check | Result |
|---|---|
| Branch / worktree | `arena/c484afa1-gold-trading-bot`, clean at `be447a5` (data collection 279) |
| `tools/check_data.py` | **0 fail, 8 warn** (warnings are the documented historical ones) on the reconciled 624-row ledger |
| `tools/handoff_check.py` | **FRESH** (2 advisory drift: snapshot 02:33 vs newest data 02:59; open SELL #626) |
| `tools/check_structural_stop.py` | **PASS** — era n=127, **0 stops inside their level**, median clearance +0.50 ATR; boundary #498 (old) → #499 (new) confirms `LIVE_CUTOVER 2026-10-06 03:00 UTC` |
| `tools/strategy_lab.py --calib-only` | Recall **100.0% / 100.0%** (0.75R master, max-hold) — harness and engine agree; A3 holds |
| `tools/smoke_test.py` | **SMOKE TEST PASSED** (incl. Scenarios U and V) |
| Ledger | 624 closed, 122W/271L/229BE/2TIME, 31.0% decisive, engine ledger $150.69; reconciled state from the 10-19 phantom-row incident holds (see `docs/REVIEW-2026-10-19-negative-balance.md`) |
| Open position | SELL #626 @ $4175.02, 2026-10-19 02:57 UTC, SL $4179.89 / TP $4167.71 (valid geometry, post-repair numbering). Not yet in the ledger, so era closed n is still 127. Production process identity remains **unverified from the repo** — the host check in the incident review is still an operator blocker |

## 2. The registered screen at n=127 (§7, judged A → B → C)

Era: entries ≥ 2026-10-06 03:00 UTC, 37W/60L/29BE/1TIME over 10 entry dates
(2026-10-06 → 2026-10-16), gross era P&L −$47.48 (−$0.374/trade).

**A. Is the code doing what the model says?**

| # | Metric | Value | Bar | |
|---|---|---|---|---|
| A1 | Stops inside their level (post-cutover) | **0 / 127** | must be 0 | ✔ |
| A2 | Median clearance | **+0.50 ATR** | ≥ 0 (≥ 0.5 level-bound) | ✔ |
| A3 | Replay funnel recall | **100.0%** | 99.6–100% | ✔ |
| A4 | Level-bound share | **83.5%** | 70–90% | ✔ |
| A5 | Median risk | **3.32 ATR** | 2.7–3.5 | ✔ |

**B/C. Screen (n ≥ 100 arm is met; the verdict is still interim):**

| # | Metric | Value | Bar | |
|---|---|---|---|---|
| B1 | SL events / calendar day | **6.00** (60 SL / 10 dates; 5.62 span-based) | ≤ 6.5 | ✔ |
| B2 | SL share of closed | **47.24%** (60/127) | ≤ 47.0% strict | ✘ |
| B3 | Scratch (BE) share | **22.83%** (29/127) | ≤ 35% | ✔ |
| C1 | R/trade, gross (win-rate scale) | **−0.065R** ($/trade ÷ mean 1R $5.75) | ≥ −0.10R | ✔ |
| C2 | Decisive WR | **38.14%** (37/97), Wilson 95% [29.1, 48.1] | ≥ 36% | ✔ |

**SCREEN: NOT MET** — on B2 alone, by 0.24 pp (one trade: 59/127 = 46.46%
would pass; 60/128 = 46.88% would also pass). Do not round this up: as written,
47.24% > 47.0% fails. This is the same marginal miss recorded on 2026-10-17;
era P&L has not moved since the last era close (#625, 2026-10-16 19:45 UTC).

**PASS is not reachable at this n on two independent grounds:** n=127 < 150,
and the Wilson lower bound is **29.1%**, below the required > 32.1% (at n=150
that bound needs ≈ 40% decisive WR). 23 more closes are needed for n=150; at
the era's ~12.7 trades/day pace the 21:00 UTC timestamp arrives first.

**Costed reads (the screen itself is on the cost-0 ledger scale, per §7):**
era net at the assumed $0.40 round trip is **−$98.28 (−0.135R)**; at the quote
logger's first-look $0.55 median it is **−$117.33 (−0.161R)**. The era is still
negative after realistic costs — no edge is claimed under any verdict available
tonight. Whole book at $0.40: **−$615.89** net.

**Replay cross-check (§7 reporting row):** `strategy_lab --table --only
baseline,structstop`, post-cutover window — `structstop` replay n=133,
38.1% decisive, −0.033R at zero cost / −0.116R at $0.20/side (vs `baseline`
40.4%, +0.007R / −0.120R). Row-to-row deltas only; the replay is not the ledger.

**Revert triggers R4/R5/R7: all clear.** R/trade −0.065R (revert ≤ −0.20R);
avg SL $5.85 vs the $8.60 trigger (2.2 × $3.91 pre-change; ≈ 1.5×); era
peak-to-trough drawdown $93.38 gross ($131.04 net at $0.40) vs $250. The fourth
revert condition — the closure-gap trigger — does **not** read clear. See §3.

Side split (descriptive): BUY n=63, 36.7% dec, −$24.67; SELL n=64, 39.6% dec,
−$22.81. No side action is registered or taken.

## 3. Must-resolve at the judgement: the closure-gap revert trigger

§7's extra revert trigger reads: *"2 or more post-cutover trades found open
across a daily/weekly closure with an unenforceable stop"* → revert and take
the gap guard first. `pressure.py` implements only R4/R5/R7, so no tool has
been counting this, and the "revert triggers clear" lines at the n=120 look
(2026-10-16/17) did not evaluate it. Counted the project's own way — a trade
whose entry ≤ gap start and exit ≥ gap end across a > 5 min price-log gap
(the `check_data.py` span test; the measure behind the "0 rides" recorded at
n=78 on 2026-10-13) — the era count is now **2**:

| Trade | Entry → exit (UTC) | Closure spanned | Exit |
|---|---|---|---|
| #595 BUY | 2026-10-14 18:28:04 → 22:21:03 | daily break 20:58:02 → 22:00:08 (62 min) | TP +$14.45 at 22:21 |
| #610 BUY | 2026-10-15 20:05:05 → 22:48:07 | daily break 20:58:06 → 22:00:07 (62 min) | SL −$6.95 at 22:48 |

No era trade spanned a weekend closure (2026-10-09 → 10-11 and 10-16 → 10-18
checked). Both exits printed 21–48 min **after** the reopen, not through the
opening print — a fact about what happened, not a reading of the rule.

On the literal text ("daily/weekly"), the trigger count has reached its
threshold. This session does **not** execute the revert: the confirmatory
judgement is scheduled for 21:00 UTC tonight, a revert is a runtime change
that can only take effect through merge + host autosync (operator action),
and prior sessions' silence on this trigger makes its intended counting
(daily-break rides vs gap-through fills) a definition the judgement must
settle explicitly rather than have settled by omission. What this session does
is put the count on the record so tonight's review cannot miss it:

1. The 21:00 review must resolve this trigger **first**, before B/C, and record
   the reasoning in the dated judgement. §7's thresholds may not be edited or
   relaxed to make the count go away.
2. If the trigger is judged fired, the pre-registered action is the
   single-commit `git revert` of the structural stop plus the gap guard first
   (HANDOFF §6.3(h)) — and the 0.25 ATR level test does **not** proceed.
3. If it is judged not fired, the judgement must state the counting rule it
   applied (e.g. only fills through the reopen, only weekly closures) so the
   count is reproducible from tonight onward.

## 4. Parallel tracks

- **Quote logger:** 2026-10-13 15:48 → 2026-10-19 02:59 UTC (5.5 days);
  **5/14 complete UTC days, 1/2 complete weekends** — target NOT met, so the
  $0.40 round-trip assumption stays in force. First-look median spread $0.55
  (p95 $0.58); 46 ledger trades with matched entry/exit quotes average $0.55
  measured vs $0.40 assumed. Server offset still only +3h observed; the
  2026-10-25 DST transition remains the verification point — do not guess it.
- **Pressure composite:** last-bar tape BUY 43.4% / SELL 56.6% ("balanced");
  calibration on the era (n=127 joined) still returns *collinear with side —
  not separable within-side* (no `against` bucket on either side). Context
  only; no hold/exit inference is drawn from it, and the owner's manual
  pressure method remains unspecified and unlogged (EXECUTION-PLAN research
  track unchanged).
- **Incident recovery:** the reconciled ledger in this snapshot passes
  integrity, but host process/deploy verification (incident review steps 1–5)
  is still outstanding and cannot be done from the repo.

## 5. Decision and next eligible action

- **Decision: none.** SCREEN NOT MET at n=127; no PASS, KEEP or REVERT verdict
  is available before the registered point, and no parameter, gate, stop,
  target, ratchet or blackout was changed.
- **Next eligible action:** the confirmatory judgement session at
  **2026-10-19 21:00 UTC** (or on the close that takes the era to n=150, if
  earlier), in §7 order: (0) resolve the §3 gap trigger, (a) re-run
  `check_structural_stop.py` + `--calib-only`, (b) judge B/C on the then-current
  rows, (c) only if that judgement permits, consider the already-registered
  0.25 ATR level test (`docs/PREREG-2026-10-15-level-test-0.25.md`) as the
  single next variable, with its cutover taken from the host deploy time.
- **Blockers:** production-host verification (incident + deploy identity) is
  operator-only; quote-cost sample needs 9 more complete days and 1 more
  weekend; the manual pressure hypothesis needs the owner's explicit
  source/timeframe/rule definition before any log or test exists.

Reproduce: `python3 tools/check_data.py`, `tools/handoff_check.py`,
`tools/check_structural_stop.py`, `tools/strategy_lab.py --calib-only`,
`tools/pressure_report.py --root .`, `tools/win_rate_report.py --spread 0.40`,
`tools/strategy_lab.py --table --only baseline,structstop`,
`tools/xm_quote_report.py` — all run 2026-10-19 ~04:41 UTC on collection 279.
