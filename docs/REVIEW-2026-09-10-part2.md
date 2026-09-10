# Data Review — 2026-09-10, part 2 ("data collection 11")

Follow-up to `REVIEW-2026-09-10.md` (part 1, ended 09-10 00:47 UTC).
Fresh window: **09-10 00:47 → 06:54 UTC — 79 new price-log rows, trade #42,
2 new skip rows.** Strategy parameters are **unchanged** — one new trade is
not a sample, this review is about the stall recovery, trade #42's anatomy,
and two data-hygiene observations for the to-do list.

## The stall and the recovery

- The predicted Twelve Data outage is now in the log as a single **293.5-minute
  hole: 09-10 00:47:27 → 05:41:00** (gap count 81 → 82). It spans both the
  original 00:47 stall and the silent post-02:05-restart stall — the restart
  logged zero rows, consistent with the zombie-WebSocket diagnosis in the
  project log.
- Feed resumed 05:41 and has logged normally since (~1 row/min through 06:54).
- No trade was open across the gap (`check_data.py` confirms both directions).
- Engine restarted **~06:33** (funnel `candles_evaluated` = 22 = exactly the
  rows from 06:33:55 → 06:54:05; slope history re-seeded from the log). The
  06:33:55 row is the post-restart re-evaluation of the 06:33 candle (see
  § Data hygiene).
- `status.json` now reads `daily_losses: 2` for 09-10 (#41 + #42) — the
  schema-drift fix from part 1 is holding; the corrected count survived a
  real restart. Next trade #43, ledger $447.07.

## Headline numbers (42 trades)

| Metric | Full sample (42) | Since part 1 (#42 only) | New stack live (#41–42) |
|---|---|---|---|
| Win rate | 16.7% (7W/35L) | 0% (0W/1L) | 0% (0W/2L) |
| P&L | −$77.65 | −$3.33 | −$5.65 |
| True equity from $500 | **$422.35** (−15.5%) | — | — |
| Engine ledger | $447.07 (drift +$24.72, unchanged — no new resets) | | |

09-10 day so far: 0W/2L, −$5.65. Breakeven at RR 1.5 still needs ~40%.

## Tool results (4/4)

**1. `check_data.py` → 0 fail, 6 warn.** All warnings are known history:
3 duplicate `Trade_Num` + 3 ledger breaks (09-04/07 resets), 82 gaps > 5 min,
#17/#18 entries missing from the log. `status.json` agrees with `trades.csv`.
**2. `validate_gates.py` → #42 PASSES every gate**, including the full adopted
combo and even the rejected proximity gates:

```
# 42 BUY 09-10 06:09 loss -3.33  PASS PASS PASS PASS PASS PASS PASS PASS
                                  SLOPE ABV50 NOH8 RISE ABOVE PROX PROX OLD
                                  30    s          120  50   0.5  1.0  0.2%
```

Adopted combo (`SLOPE30 + ABV50s + NOH8`): keeps **7W/20L (26%), −$32.83**
(9/8+: 4W/17L, −$37.90). Five consecutive post-review losses (#38–42) now,
zero of them blocked by the regime gates.
**3. `phantom_trades.py` → reconstruction still 100% floor/ATR, 99.2% RSI.**
Two new cooldown phantoms (06:29, 06:30, both under the escalated 60-min
cooldown) both hit TP (+$7.11, +$7.14):

| Skip kind | Blocked | Raw phantom | Sequential (dedup) |
|---|---|---|---|
| SL cooldown | 56 | 23W/33L, +$2.15 | 20 taken: 10W/10L, **+$19.64** |
| Daily halt | 11 | 7W/4L, +$18.53 | 7 taken: 7W/0L, **+$27.71** |
| Blackout | 7 | 3W/4L, +$0.44 | 1 taken: 0W/1L, **−$3.39** |
| **Total** | 74 | 33W/41L, +$21.12 | 28 taken: 17W/11L (**61%**), **+$43.95** |

**4. `smoke_test.py` → PASSED** (scenarios A–H, incl. drift auto-fix F,
stale-feed guard G, MT5 sidecar H).

## Trade #42 anatomy — the same fingerprint

BUY 06:09 @ 4424.78 (SL 4422.12 / TP 4428.77, 2×/3× ATR geometry on ATR 1.33 ✓),
stopped 06:13 @ 4421.45, −$3.33. Textbook setup on paper: EMA50 4417.04 >
EMA200 4405.70 and rising, 20-bar floor test with a 57% lower-wick rejection,
close held above the floor, RSI 38.3, ATR 1.33. Price never threatened TP —
**max excursion 29% of the way to TP** before grinding down through SL in
4 minutes. Same "wrong immediately" signature as #38–40 and most historical
losers, and notably it passes even the rejected PROX0.5/PROX1.0 floor-proximity
gates: level quality was fine, timing/momentum was not.

## Data-semantics note (not a bug)

#42's trade row (RSI 38.3, ATR 1.33, EMA50 4417.04) differs from its 06:09 log
row (RSI 47.6, ATR 1.27, EMA50 4416.72). This is by design: `evaluate_candle()`
calls `log_candle()` *before* `update_indicators()`, so log rows carry
**pre-update** indicator values while the signal gates and the entry snapshot
use **post-update** values (the entry candle included). SL/TP geometry cross-
checks against the post-update ATR exactly (2.66 = 2×1.33, 3.99 = 3×1.33).
`phantom_trades.py` already models this split (reconstruction validated at
100%/99.2%). Future reviewers: compare trade rows to the *next* log row's
pre-update values, not their own minute's.

## Data hygiene

- **Same-minute multi-rows: 4 new, 11 all-time.** 06:14×3, 06:19×2, 06:26×2,
  06:33×2. Two patterns: (a) exact-duplicate re-logs (06:26, 06:33 — identical
  OHLC, only Vol_MA recomputed); the 06:33:55 dup is the post-restart
  re-evaluation. (b) seconds-apart *different* candles with jumpy prices and
  indicators (06:14:02/06:14:11/06:14:16 — EMA200 jumps $3 in 9 seconds; same
  pattern seen once before on 09-04). No trade entries, exits, or skip signals
  fall in any dup minute, so P&L and gate replays are unaffected — but each
  extra row appends to the indicator deques, mildly polluting EMA/RSI/ATR.
  **To-do**: add an INFO-level same-minute check to `check_data.py`, and
  consider a once-per-minute dedup guard in the engine's log path.
- Dup-minute count is small enough (11/8045 minutes) to ignore for now.

## Hypotheses watch (from part 1)

- (a) *Sell-side low-RSI clustering*: no new SELL trades (n still 1). No update.
- (b) *Blocked-vs-taken quality gap*: **widened**. Blocked-sequential 61% WR
  (+$43.95) vs taken 16.7% (−$77.65). Same caveats as part 1 (in-sample,
  tiny-n, no spread/slippage, cascade-ignorant) — watch, don't act.
- (c) *Only the NY blackout would have helped*: no new trades in the window.
  No update.

## Strategy: unchanged

No parameters touched (wick 0.38, ATR 2/3 geometry, RSI windows, blackouts,
cooldowns, MIN_ATR 1.10, slope/near-EMA gates). One new trade, no new
conclusions — the value of this cycle is confirming the stall recovery, the
drift fix surviving a restart, and two logged to-dos (same-minute check,
log-path dedup).

## Deploy notes

None — no code changes in this cycle. The ~06:33 restart already picked up
the current stack.
