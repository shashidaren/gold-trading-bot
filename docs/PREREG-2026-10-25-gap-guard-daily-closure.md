# PREREG — Daily-closure entry guard (gap guard), 2026-10-25

**Status:** REGISTERED & **DEPLOYED 2026-10-25 02:48:12 UTC (`71317da`, PR #58 `d38117a`) into the closed weekend market; DST-responsiveness refinement in `1c02b2c`.** Stop geometry held on `SL_CLEAR_ATR = 0.5` until the post-DST broker offset (`+2h` EU vs `+3h` US) is observed in synced rows (see §9 below).
**Date:** 2026-10-25 (session: opening ritual + #697 fix committed as 8d84dcf; data collection 334,
checked-in data through 2026-10-23 20:57 UTC; deployed at collection 335 / `71317da`).
**Author:** agent session arena/17ce78e9-gold-trading-bot; post-merge DST refinement + deploy record on `arena/c5824a9f-gold-trading-bot`.
**Owner approvals (2026-10-25):** cutoff = 30 min; scope = entries only; PR #58 merged during the Saturday weekend closure and deployed harmlessly into a closed market (`71317da`), followed immediately by owner-approved (`hold_for_dst` + `fix_dst_lag`) DST-responsive `derive_daily_closure()` (`1c02b2c`) while holding stop geometry for post-DST offset observation.

This draft scopes the gap guard required before the prescribed structural-stop revert
(§7 closure-gap REVERT trigger FIRED at 3/2: #595/#610/#687). It is one scoped engine
change: **block new entries for a cutoff window before the daily market close**. It does
NOT revert the structural stop, NOT flatten open positions, NOT start the 0.25 ATR test,
and NOT change any stop/TP parameter. Approval of this draft → dated pre-registration →
single-commit engine change → verification → deploy on your say-so.

---

## 1. Trigger evidence (from `tools/check_gap_rides.py`, fresh data n=697)

Era under test: entries ≥ 2026-10-06 03:00 UTC (structural-stop cutover).
Price-log holes in the era log: 33 scheduled closures (26 daily, 7 weekend), 87 feed
outages (feed outages are excluded from the count by the registered rule).

| Trade | Side | Opened | Closure (hole) | Reopen | Headroom over stop at reopen | Exit | Gap damage |
|---|---|---|---|---|---|---|---|
| #595 | BUY | 2026-10-14 18:28 | daily break 20:58 → 22:00 UTC | 22:00 | +$11.43 | TP +$14.45 | none |
| #610 | BUY | 2026-10-15 20:05 | daily break 20:58 → 22:00 UTC | 22:00 | +$4.15 | SL −$6.95 at stop | none |
| #687 | SELL | 2026-10-22 20:20 | daily break 20:58 → 22:00 UTC | 22:00 | +$4.46 | SL −$5.70 at stop | none |

- **All three rides rode the daily closure** (daily break starts ~20:58 UTC, ends ~22:00
  UTC under the current +3h broker offset; ~62 min; 24 observed occurrences in the log).
- None gapped through, none exited worse than the stop, no weekend closure was ridden.
- Tightest reopen headroom: **#610 at +$4.15** — a stop that was enforceable only after the
  break, not during it.
- Counting rule (registered, `docs/REVIEW-2026-10-19-struct-stop-judgement.md` §3): a
  post-cutover trade open across a price-log hole >5 min classified as a scheduled daily
  or weekly closure. **3 ≥ threshold 2 → §7 extra REVERT trigger FIRED.**

---

## 2. Guard rule (exact, scoped)

### 2.1 What it does
Blocks **new simulated entries** from `daily_close_utc − GUARD_CUTOFF_MIN` until the market
reopens (a fresh post-close candle is accepted). Existing open paper positions are NOT
touched by this guard (see §3 tradeoff). No stop, TP, risk, or entry-gate parameter
changes.

### 2.2 Daily close — derived from the feed, not guessed
The daily close (start of the scheduled daily break) is derived from observed price-log
gaps: the recurring scheduled non-weekend gap. On the current checked-in data:

- daily break start ≈ **20:58 UTC**, end ≈ **22:00 UTC** (~62 min), 24 observed
  occurrences, under the current **+3h** broker offset.
- This is XM's daily market break; it recurs every trading day.

The engine computes `daily_close_utc` from this observed break. The cutoff window is
`[daily_close_utc − GUARD_CUTOFF_MIN, market_reopen_utc]`.

### 2.3 Cutoff minutes (GUARD_CUTOFF_MIN) — owner-approved: **30**
**Approved 2026-10-25.** Entries blocked from `daily_close_utc − 30 min` until the market reopens
(a fresh post-close candle is accepted). Under the current +3h broker offset that is ~20:28 UTC
through the ~22:00 reopen.

The 30-min figure was your noted preference from 2026-10-20; it is now an **approved registered
value** for this guard. No other value is assumed.

### 2.4 Schedule source — observed broker clock, never a guess
- The daily close in UTC = (broker-clock daily close) − (observed broker offset).
- The broker offset is taken from **observed** quote rows (`tools/xm_quote_report.py`,
  "offsets seen"), never assumed. Current observed offset: **+3h only** (2026-10-13 →
  2026-10-23).
- Whenever a new offset is observed, `daily_close_utc` is recomputed from it. The DST
  discriminating window (EU rule **2026-10-25 01:00 UTC** → +2h; US rule **2026-11-01
  06:00 UTC** → +2h) is exactly the window that tells the rules apart; **no post-transition
  offset has been observed yet** (newest synced quote row 2026-10-24 14:59:30, Saturday,
  pre-weekend). Until a post-transition offset is observed, the UTC equivalent of the
  daily close is **UNVERIFIED** and the guard must not be deployed on a guessed offset.

### 2.5 Effect: entries vs open positions — owner-approved: **entries only**
**Approved 2026-10-25.** The guard blocks **new entries only**; open paper positions are NOT
flattened. Rationale matches the 2026-10-20 prior read: the fired trigger is about new exposure
created by letting a trade open across the close; flattening open positions is a larger, separate
change (market close before the break, re-entry after, interaction with the 240-min TIME stop which
cannot fire while closed) that would need its own dated pre-registration.

| Option | Protects new rides across the close | Protects already-open rides | Status |
|---|---|---|---|
| **Block new entries only** (approved) | ✓ | ✗ | **Registered — this guard** |
| Block entries AND flatten open positions before close | ✓ | ✓ | Out of scope — separate registration |

### 2.6 Stale-feed behaviour
- If the feed is stale at or within the cutoff window, the engine **cannot confirm the
  close or the reopen** → **fail-safe: keep entries blocked**, do not resume on a stale
  tick.
- The cutoff is not computed from a stale feed; the last-known-good daily close stands
  until a fresh post-close candle confirms the market has reopened.
- Entries resume only after a fresh candle after `daily_close_utc` is accepted (deduped by
  the existing MT5 watermark). This dovetails with the existing stale-feed guard
  (`mt5_feed_problem()`): a frozen `mt5_last_candle.json` is a publisher failure, not a
  quiet market, and the heartbeat check stays authoritative.

---

## 3. What this guard does NOT do (boundary)

- Does NOT revert the structural stop (separate single-commit change, after this guard
  is approved and deployed — the registered order: guard first, then revert).
- Does NOT flatten or close any open paper position.
- Does NOT change `SL_CLEAR_ATR`, `RR_TARGET`, `BE_TRIGGER_R`, `MAX_HOLD_MINUTES`, ATR
  bounds, blackouts, or any entry/exit parameter.
- Does NOT start the 0.25 ATR level test (blocked by the fired §7 trigger).
- Does NOT deploy anything; deploy happens on your say-so after verification.

---

## 4. Pre-registration bar for the guard itself

The guard is a protective rule, not an expectancy experiment, so it has no P&L bar. Its
registration conditions:

- **Cutoff value `GUARD_CUTOFF_MIN`:** your explicit approval of the number (draft
  proposes 30).
- **Offset verification:** the UTC daily close must be derived from an observed broker
  offset; a guessed offset blocks deployment until the DST window (10-25 → 11-01) yields
  an observed offset, or you explicitly waive verification.
- **Schedule source:** the daily close is derived from observed price-log gaps (feed
  itself), re-derived on every observed offset change.
- **Entries-only:** open positions are not flattened by this guard (flattening, if ever,
  is a separate registration).

---

## 5. Implementation notes (engine.py, single commit)

- Add `GUARD_CUTOFF_MIN` (owner-approved number) and a function
  `guard_blocks_entry(now_utc, daily_close_utc, feed_fresh)` returning whether a new
  entry is suppressed:
  - `True` if `now_utc` is in `[daily_close_utc − GUARD_CUTOFF_MIN, reopen_confirmed_utc]`
  - `True` (fail-safe) if the feed is stale at the cutoff
  - `False` otherwise
- `daily_close_utc` computed from the observed offset and the observed daily-break
  broker-clock time; recomputed when the offset changes.
- Wired into the entry path before a trade number is consumed (so no trade number is
  burned by a suppressed setup — consistent with the 2026-10-17 skip-path correction).
- No change to `trade_filter.py` blackouts; this guard is separate from (and in addition
  to) the existing entry blackouts.

---

## 6. Verification (before deploy)

- `python3 -m py_compile engine.py trade_filter.py`
- `python3 tools/smoke_test.py` → SMOKE TEST PASSED (add a hermetic scenario: entries in
  the cutoff window are suppressed; entries outside are not; a stale feed keeps entries
  blocked; offset change recomputes the UTC cutoff).
- `python3 tools/check_data.py` → 0 fail
- `python3 tools/check_gap_rides.py` → trigger count unchanged (3/2) — the guard is
  preventive; it does not alter historical rides.
- `python3 tools/handoff_check.py` → FRESH (no snapshot change expected)

---

## 7. Deploy order (registered)

1. Owner approves this draft (incl. `GUARD_CUTOFF_MIN` and the offset-verification rule)
   → this doc becomes the dated pre-registration.
2. Single-commit engine change on this branch; py_compile + smoke test + check_data.
3. Push; PR open until you say so (no merge without your say-so).
4. On your say-so: deploy via autosync; verify host rows + executable before relying on
   it.
5. Only after the guard is deployed: prepare the **single-commit structural-stop revert**
   (the prescribed §7 consequence) in the registered order.

Until step 4, the checked-in engine remains on the structural stop, paper-only,
`TRADING_MODE = "FORWARD_TEST"`, and no runtime change is made.

---

## 7. Registration record (owner-approved 2026-10-25)

| Item | Approved value | Source |
|---|---|---|
| `GUARD_CUTOFF_MIN` | 30 minutes | Owner approval, this session |
| Scope | Block new entries only; open positions NOT flattened | Owner approval, this session |
| Daily close (`daily_close_utc`) | Derived from observed price-log gaps (~20:58 UTC under current +3h offset) | Fresh data, `check_gap_rides` / log gap scan |
| Offset verification | **Wait to observe** — code written now, deploy only after a post-DST-transition offset is observed (10-25 01:00 → 11-01 06:00 UTC window). No deploy on a guessed UTC close. | Owner approval, this session |
| Stale-feed behaviour | Fail-safe: keep entries blocked while feed is stale | Registered rule |
| Pre-registration bar | Protective rule — no P&L bar; registration conditions are the four items above | Registered rule |

## 8. Implementation notes (engine.py, single commit)

- Add `GUARD_CUTOFF_MIN = 30` (owner-approved) and pure helpers:
  - `derive_daily_close_utc(gap_starts)` — returns the recurring scheduled daily-break start (UTC) from observed price-log gaps, or `None` when unobservable (fail open).
  - `guard_blocks_entry(now_utc, daily_close_utc, cutoff_min, reopen_confirmed)` — True suppresses a new entry.
- Engine state: `_guard_daily_close_utc` (derived at startup from `forward_test_log.csv` gaps; `None` if unobservable), `_guard_reopen_confirmed` (set True once a post-close candle is accepted; resets each UTC day), `_guard_close_date`.
- Wired into `execute_simulated_trade` and `execute_live_trade` **before a trade number is consumed** — a suppressed setup sends a skip message (kind=`skip`) and returns without burning a trade number, consistent with the 2026-10-17 skip-path correction.
- No change to `trade_filter.py` blackouts; the guard is additive to them.
- No change to `SL_CLEAR_ATR`, `RR_TARGET`, `BE_TRIGGER_R`, `MAX_HOLD_MINUTES`, ATR bounds, or any entry/exit parameter.

## 9. Deploy order (registered)

1. This doc is the dated pre-registration (owner-approved above).
2. Single-commit engine change on this branch; py_compile + smoke test + check_data.
3. Push; PR open until you say so (no merge without your say-so).
4. **Deploy gate:** before deploying, confirm an observed post-DST-transition broker offset (or you explicitly waive verification). Until then the code is written but not deployed.
5. On your say-so: deploy via autosync; verify host rows + executable before relying on it.
6. Only after the guard is deployed: prepare the single-commit structural-stop revert (the prescribed §7 consequence) in the registered order.

Until step 5, the checked-in engine remains on the structural stop, paper-only, `TRADING_MODE = "FORWARD_TEST"`, and no runtime change is made.

## 10. Implementation + verification record (2026-10-25, this session)

**Implemented in `engine.py` (single commit, this branch):**

| Piece | What it does |
|---|---|
| `GUARD_CUTOFF_MIN = 30`, `GUARD_LOOKBACK_DAYS = 30`, `GUARD_MIN_BREAK_MIN/MAX = 30/180`, `GUARD_MIN_SAMPLES = 3` | Registered constants; the break duration band matches `tools/check_gap_rides.py`. |
| `derive_daily_closure(log_path)` | Reads the price log (read-only), takes holes of 30–180 min in the last 30 days, returns the **modal** start/end minute-of-day, or `None` below 3 samples. |
| `guard_blocks_entry(now_utc, closure, cutoff_min=30)` | Pure window test, `[close − 30 min, reopen)`, handles a midnight-crossing break. `None` closure → never blocks (fail-open). |
| `GoldEngine.guard_closure()` / `entry_guard_reason()` | Caches the derived signature per UTC day (0.55 s on the 50k-row log, once a day) and returns the skip reason. |
| `execute_simulated_trade()` / `execute_live_trade()` | Guard checked **first**, before any trade number is assigned; a suppressed setup logs a skip alert and writes no ledger row. |

**Observed derivation on the checked-in data:** daily break **20:58 → 22:00 UTC** (the signature is
derived, not hard-coded — the same function on a 20:57 fixture returns 20:57).

**Verification (all run 2026-10-25):**

| Check | Result |
|---|---|
| `python3 -m py_compile engine.py tools/smoke_test.py` | OK |
| `python3 tools/smoke_test.py` | **SMOKE TEST PASSED** — A–Y unchanged, new Scenario Z: derived signature, 20:27 allowed / 20:28 blocked, 21:30 blocked, 22:00 resumed, fail-open when underivable, midnight wrap, suppressed entry opens nothing / burns no number / writes no row, entry outside the window opens normally, derivation does not modify the log. |
| `python3 tools/check_data.py` | 0 fail, 8 warn (unchanged, informational) |
| `python3 tools/check_gap_rides.py` | **3 / 2 — unchanged.** Expected: the guard is preventive and alters no historical row. |
| `python3 tools/check_structural_stop.py` | PASS (0 post-cutover stops inside the level) |
| `python3 tools/handoff_check.py` | HANDOFF FRESH (1 advisory drift) |

**Not done, deliberately (in PR #58):** no structural-stop revert, no 0.25 ATR test, no
flattening of open positions, no change to `trade_filter.py` blackouts, no renumbering of any
historical ledger row.

---

## 9. Deploy record (`71317da`) + DST-responsiveness refinement (`1c02b2c`, 2026-10-25)

1. **Host deploy into closed weekend market (`2026-10-25 02:48:12 UTC`):** Owner merged PR #58 (`d38117a`, combining `#697` fix `8d84dcf` + initial guard implementation `4d911fa`) at `02:39:37 UTC`; `autosync.sh` synced `data collection 335` (`7b2e2ea`, `02:48:08 UTC`) and merged upstream (`71317da`, `02:48:12 UTC`), passing `smoke_test.py` and restarting `gold` while the weekend market was closed (`status.json` `trade_active: false`, `next_trade_num: 698`, last bar `2026-10-23 20:57:08 UTC`). Zero live/paper bars or trades were evaluated between the deploy and Sunday's reopen.
2. **DST-lag hazard found and fixed (`1c02b2c` on `arena/c5824a9f-gold-trading-bot`):** Under the initial 30-day modal window (`~19` summer `20:58 → 22:00 UTC` breaks), a `±1 h` broker DST shift (EU `2026-10-25 01:00 UTC` or US `2026-11-01 06:00 UTC`) would have needed ~10 post-shift daily breaks (~2 trading weeks) to overtake the old mode — leaving `21:28–21:58 UTC` unguarded and `20:28–20:58 UTC` falsely blocked in the interim. Per owner decision (`fix_dst_lag`), `derive_daily_closure()` now:
   - computes its modal `(close_tod, reopen_tod)` baseline over the most recent `GUARD_RECENT_SAMPLES = 5` daily breaks (within the 30-day lookback, still requiring `>= 3` breaks so `< 3` fails open and a single mid-day feed outage cannot move the mode), converging within 3 daily breaks for any schedule shift; and
   - checks the latest weekend hole (`>= 24 h`, `GUARD_WEEKEND_MIN`): when `< 5` daily breaks have been logged since that weekend, an exact `±60 min` (`±2 min` bar-timestamp tolerance, `GUARD_DST_TOL_MIN = 2`) shift observed in either the post-weekend daily-break mode (when `>= 1` exists) or the Sunday weekly reopen relative to the pre-weekend baseline shifts both `close_tod` and `reopen_tod` immediately on **Day 1**. Non-`±60 min` reopens (e.g. a Monday `07:15 UTC` feed-outage recovery) are ignored so feed outages never synthesize a bogus closure schedule (verified hermetically in `tools/smoke_test.py` Scenario Z).
   - **Invariant preserved:** `GUARD_CUTOFF_MIN = 30`, entries-only scope (open positions untouched), fail-open below 3 breaks, and historical overlap on `20:58 → 22:00 UTC` (`7 / 697` all-book entries, `0 / 200` struct-stop entries) are byte-for-byte unchanged.
3. **Quote-logger staleness + stop-geometry hold (owner decision `hold_for_dst`):** At `data collection 335`, `xm_data/quotes-2026-10-24.csv` ends at `2026-10-24 15:34:30 UTC` (`STALE`, ~11.3 h old; `mt5quotes-gold` needs a host restart before Sunday's reopen), so no post-`01:00 UTC` tick offset has been observed yet. Per owner decision, `engine.py` holds `SL_CLEAR_ATR = 0.5` + the deployed gap guard through Sunday reopen / Monday until the real post-DST broker offset (`+2h` vs `+3h`) is confirmed in synced rows, before choosing between pre-registering `structstop1.5` (`docs/ANALYSIS-2026-10-25-stop-hunt-markouts-and-clearance-grid.md`) or executing the literal §7 revert.

