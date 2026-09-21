# Analysis — 2026-09-21: "did the win rate just drop tremendously?"

**Question (user, ~07:00 UTC 09-21):** did the win rate collapse after the last
change (the ~4 h max-hold time stop, PR #15), reported right after a manual
`tools/autosync.sh` run at 06:59.

**Verdict: No.** The decisive win rate is unchanged within noise, and the last
change **cannot** have caused any win-rate change because it has not fired once.

Sample: **271 closed trades, 2026-09-04 08:20 → 2026-09-21 06:41 UTC** (17,719
log bars), 0 active. Reproduce: `python3 tools/check_data.py`,
`tools/win_rate_report.py`, `phantom_trades.py`, `analyze_losers.py`,
`validate_gates.py`, `smoke_test.py` (all green — §6).

---

## 1. The numbers, by window

| Window | n | Result | Decisive WR | P&L | $/trade |
|---|---|---|---|---|---|
| **All trades** | 271 | 38W/101L/132BE | **27.3%** (CI 20.6–35.3) | −$169.40 | −$0.625 |
| **+0.75R era** (entries ≥ 09-15 06:00) | 96 | 20W/42L/34BE | **32.3%** (CI 22.0–44.6) | −$45.20 | −$0.471 |
| New regime (entries ≥ 09-10 12:34) | 226 | 30W/64L/132BE | 31.9% (CI 23.4–41.9) | −$86.89 | −$0.384 |
| last 120 h | 66 | 15W/31L/20BE | 32.6% | −$29.70 | −$0.450 |
| last 30 trades | 30 | 8W/12L/10BE | 40.0% | +$1.67 | +$0.056 |
| last 20 trades | 20 | 4W/10L/6BE | 28.6% | −$11.97 | −$0.599 |
| last 10 trades | 10 | 2W/6L/2BE | 25.0% | −$9.85 | −$0.985 |
| **last 5 trades** | 5 | 0W/4L/1BE | **0.0%** | −$14.45 | −$2.890 |
| TIME exits anywhere | 0 | — | — | — | — |

Reference points from the previous session (07:00 earlier today,
`docs/REVIEW-2026-09-21.md`): pooled 27.6% decisive at n=265, 0.75R era 33.3% at
n=90. Today: 27.3% at n=271 and 32.3% at n=96. **Δ = −0.3 pp and −1.0 pp —
inside a ±11 pp confidence interval. No regime change.**

The whole of the impression lives in the last row: the **6 trades that closed
since the last review went 1W/4L/1BE (−$8.09)**; the last 5 closed trades are
0W/4L/1BE. With a ~33% base rate that is not even unusual:
**P(0 of 4 decisive) = 20%, P(≤1 win in 5) = 47%.**

Day-over-day eyeballing is also a trap right now: **09-19 (Sat) the market was
closed (0 trades)** and 09-20 (Sun reopen) produced 2 — so any "yesterday vs
today" comparison is against a dark or near-empty day.

## 2. Why the last change is exonerated

- The change is the ~4 h max-hold time stop (`MAX_HOLD_MINUTES = 240`, reason
  `TIME`, PR #15 merged 04:50:49Z). **A stop that has never fired cannot change
  any trade's outcome — and `TIME` exits are excluded from decisive win-rate
  math by design anyway** (`docs/REVIEW-2026-09-21.md` §2).
- **Deploy confirmed live, and it has fired zero times**: `status.json` as
  committed by autosync at 06:59:16 (engine write 06:59:06) carries
  `"time_exits": 0`. That key exists **only** in the PR #15 engine (added by
  that diff; no archived engine and no earlier `status.json` has it), and
  `save_status()` rewrites the file from scratch, so it cannot be a stale key —
  the new engine was already running before the user's manual 06:59 run. Given
  the 04:50:49Z merge, the deploy was the **~06:00 autosync run**; pin the exact
  restart from `/var/log/gold_autosync.log` / the Telegram digest.
- Since the deploy the ledger contains **1 trade** (#270 SELL 06:31 → 06:41, SL,
  −$4.59). Since the merge (04:50:49Z) it contains **2 closed trades, both
  losers** (#269, #270 = −$7.15). That is the entire post-change sample.

## 2b. Era table — the books behind every number (and the no-reset decision)

§1's windows overlap; this table partitions the whole ledger into
non-overlapping books, so every number on the dashboard or in a review maps
to exactly one row. Computed on the 2026-09-21 07:08 UTC snapshot (data
collection 86; 271 closed trades — the drop added bars, no new trades, so
every §1 figure is unchanged).

| Book | Boundary (entry time, UTC) | n | Result | Decisive WR (Wilson 95%) | P&L | $/trade |
|---|---|---|---|---|---|---|
| **All trades** — era-blind, what the Win-Rate tile shows | — | 271 | 38W/101L/132BE | 27.3% [20.6, 35.3] | −$169.40 | −$0.625 |
| Pre-ratchet (no BE ratchet) | < 09-10 12:34 | 45 | 8W/37L/0BE | 17.8% [9.3, 31.3] | −$82.51 | −$1.834 |
| 0.30R era (`BE_TRIGGER_R = 0.30`) | 09-10 12:34 → 09-15 06:00 | 130 | 10W/22L/98BE | 31.2% [18.0, 48.6] | −$41.69 | −$0.321 |
| **0.75R ratchet book (master — the falsification bar's era)** | ≥ 09-15 06:00 | 96 | 20W/42L/34BE | 32.3% [22.0, 44.6] | −$45.20 | −$0.471 |
| — of which pre-deploy ("0.75R-only"; stopped receiving trades at the restart) | 09-15 06:00 → 09-21 ~06:00 | 95 | 20W/41L/34BE | 32.8% [22.3, 45.3] | −$40.61 | −$0.427 |
| — of which **max-hold era (current)** | ≥ 09-21 ~06:00 | 1 | 0W/1L/0BE | 0.0% [0.0, 79.3] — n=1, no read | −$4.59 | −$4.590 |

The rows partition the ledger: 45 + 130 + 95 + 1 = 271, and the P&Ls sum to
−$169.40. The master 0.75R row is the "0.75R era" the reviews and the
pre-registered bar use — it is the *ratchet book*, not the pre-deploy
sub-period: at this snapshot it holds 96 trades (32.3% decisive,
−$0.471/trade; the bar, formally tripped 09-17 16:17 UTC, remains
breached). §1's "+0.75R era (n=96)" row is this same master row.

**Boundary precision.** The 0.75R boundary is exact (the 09-15 06:00
autosync run deployed PR #9, merged 03:00:23Z). The max-hold boundary is
the ~09-21 06:00 autosync run that picked up PR #15 (merged 04:50:49Z):
the last pre-deploy entry is #269 (05:18:05) and the first post-restart
trade is #270 (06:31:03). Pin the exact restart timestamp from
`/var/log/gold_autosync.log` / the Telegram digest at the re-review
(`docs/REVIEW-2026-09-21.md` §3); until then "~06:00" is the boundary, and
the split point (#269 vs #270) is immaterial at these counts.

### No-reset decision (binding for future sessions)

The max-hold deploy did not — and will not — reset anything. Concretely:

1. **No counter reset.** The 0.75R ratchet book keeps accumulating from
   09-15 06:00 UTC. Its n, W/L/BE/TIME and P&L are not zeroed at the
   max-hold boundary, and the pre-registered falsification bar (era
   P&L/trade ≤ −$0.40 at n ≥ 60) stays judged on the *whole* book:
   formally tripped 09-17 16:17 UTC, still −$0.471 at n=96. A reset would
   have manufactured a fresh, un-pre-registered pass/fail window and
   orphaned the trip record.
2. **"Closes at deploy" means the sub-period stopped receiving trades —
   not that its stats were re-zeroed.** The "0.75R-only" row above is
   historical (95 trades, closed at the restart); it is reported, not
   reset.
3. **The max-hold era is a sub-period of the same ratchet book** (the
   ratchet is still 0.75R), defined as entries ≥ the deploy restart for
   the fallback step-1 isolation read — judged at deploy + ~2 weeks /
   n ≈ 200 on P&L/day and bleed/trade, not on WR alone.
4. **No engine-state reset.** The autosync deploy restarts the engine and
   stats restore from `trades.csv` (total_trades, balance, streaks — the
   brief 0.0% tile right after a restart is the known restore artifact,
   §8); Trade_Num is not renumbered and the ledger is never zeroed.

For future sessions: quote any win rate with its book named (handoff §11
rule) — the tile is the "All trades" row, the era number in reviews is the
master 0.75R row, and the isolation read is the max-hold row.

## 3. The recent cluster, explained (it is not the change)

- Current **consecutive-SL run = 4**, daily SLs 5/10 in `status.json` → the
  escalating cooldown is in its 60-min state, so the bot was partly **dark**
  through the 06:00–06:30 sell-off.
- The cluster is the known *stop-inside-the-chop* pattern, not a signal break:
  the bot sold a −$35 move (4380 → 4345) and each entry was stopped by a 2.6–4.6
  point bounce. Re-priced 30/60 min after each exit, **4 of the 5 most recent
  rows were in the bot's favour** (#265 TP +4.9/+6.7, #266 BE +0.6/+8.1,
  #267 SL +2.6/−2.1, #268 SL +3.1 at +60m, #269 SL +3.0/+4.1) — direction right,
  timing wrong. Only #270 kept running against it.
- `phantom_trades.py` shows the same picture from the other side: the cooldown
  blocked a **cluster of winning SELLs at 05:30–06:17** (9 of 13 blocked would
  have printed TP, +$6 to +$7.8 each). The live book took the losers; the gate
  held it out of the winners. That is the long-documented **cooldown leak**
  (+$281.83 sequential phantom in this run), item (b) in `docs/HANDOFF.md` §6 —
  it is not a new behaviour and not caused by PR #15.

## 4. Independent verification that the live engine is the configured one

Reconstructed from `forward_test_log.csv` (no reliance on `Exit_Reason`):

- **Ratchet is really at 0.75R** (not stuck on the old 0.30R): every one of the
  34 BE exits in the 0.75R era reached MFE ≥ **0.76R** before exiting
  (min 0.76R, p10 0.85R, median 1.10R); zero BE exits below 0.70R. If the box
  were running the pre-09-15 code we would see BE exits at ~0.30R — we do not.
- **Geometry intact**: exit levels still sit at entry ∓ 2·ATR / ± 3·ATR from
  `ATR_At_Entry` on the newest rows.
- No `TIME` rows, no unknown `Exit_Reason` values, no duplicate entry
  timestamps, `status.json` agrees with `trades.csv`.

## 5. Status of the pre-registered bar (unchanged conclusion)

- 0.75R-era **P&L/trade is −$0.471 at n=96 — still below the −$0.40
  falsification bar**, which remains tripped. That is a *P&L* bar, not a
  win-rate bar: the WR itself never tripped it.
- Fallback step 1 (max-hold) is live and in isolation with an essentially empty
  sample. Judge it at **deploy + ~2 weeks / n ≈ 200 max-hold-era trades** on
  P&L/day and bleed/trade (plus TIME count + P&L split, >60-min holds ≈ 0) —
  **not** on win rate alone and not on a 5-trade window.
- **Engine/strategy/params untouched by this analysis.** The only code touched
  is the dashboard tile below (display-only; the dashboard is a separate
  service, `engine.py` and `trade_filter.py` are byte-identical, so the
  max-hold isolation window is not disturbed).

## 7. Cosmetic follow-up from this check (dashboard tile)

The tile the user was reading (`status.win_rate`) was the **era-blind pooled**
decisive rate with no context — the exact trap. Now labelled:

> **Win Rate (decisive)** — 27.3% — *all eras · excl. BE/TIME · all-in 14.0%*

Display-only change in `dashboard.py` (label + a computed all-in line); no new
data source, no engine change, guards against `total_trades = 0`. Verified by
rendering the app: HTTP 200 and correct values with (a) the live 271-trade
`status.json`, (b) a partial/old-schema `status.json`, (c) no files at all.
An **era-aware** tile would need the engine to track era stats (a config
decision about what defines an era) — deliberately *not* done here; noted as a
future option, not a queued change.

## 6. Data hygiene (suite run on this snapshot)

- `check_data.py`: **0 fail / 8 warn** (known balance-reset drift +$24.71; the
  >60-min-hold warning now fires only on pre-deploy rows — #95 49.1 h).
- `smoke_test.py`: **SMOKE TEST PASSED**; `py_compile` clean on
  `engine.py`, `trade_filter.py`, `dashboard.py`, `tools/*.py`.
- All six data tools re-ran end-to-end on 271 trades; TIME handling unchanged
  (no TIME rows exist yet — the first real one is expected ≥ 4 h after the
  deploy restart).

## 8. If a *different* number was on screen

Two display facts that can look like a "collapsed" win rate without anything
having happened (both are by design, both documented in §8 of the handoff):

1. **The dashboard tile is the pooled, era-blind decisive rate — 27.3%.** It
   mixes the bad pre-ratchet book (17.8% decisive, n=45) with the current one;
   the era rate the reviews quote is 32.3%. Never compare the two.
2. **All-in win rate is 14.0% (38/271)** — that is wins ÷ *all* closed trades,
   with 132 BE scratches + 0 TIME counted as neither wins nor losses. It keeps
   drifting down as neutral exits accumulate; it is not a signal metric.

A brief 0.0% on the tile is also normal right after an autosync restart, before
stats finish restoring from `trades.csv` — not a real reading.
