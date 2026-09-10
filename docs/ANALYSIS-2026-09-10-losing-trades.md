# Losing-Trade Analysis — 2026-09-10

Question: can we find a way to increase the win rate by studying the losers?
Sample: 45 trades (2026-09-04 → 09-10), 8W/37L = **17.8% WR**, P&L **−$82.51**
(true equity $500 → $417.49). Breakeven at the engine's 2×ATR SL / 3×ATR TP
(1:1.5 RR) needs ~40%.

All findings reproducible with the new tools:
`tools/analyze_losers.py`, `tools/exit_sims.py`, `tools/pathwalk_sims.py`
(read-only; run after each new data drop).

## 1. Winners vs losers — what separates them

| Feature at entry | Winners (8) | Losers (37) | Reads as |
|---|---|---|---|
| RSI | 56.1 | 50.2 | RSI < 45 entries: **1W/14L (7%)** — weak-hand dip buys |
| ATR | 1.35 | 1.43 | no predictive power |
| Wick ratio | 62.6% | 61.7% | no predictive power |
| EMA50−200 gap | 4.99 | 6.11 | losers in *stronger* micro-trends (chasing extended moves) |
| Entry dist above EMA50 | +$3.58 | +$1.81 | entries closest to the "floor" die most (knife catches) |
| Early drawdown (first ~3 min) | −0.37R | −1.12R | **winners work immediately; losers never recover** |
| Time since previous exit | — | **re-entry <5 min: 0W/9L, −$23.32** | the revenge-trade bleed the SL cooldown (added 09-09) targets — data validates it |

Time of day: 08:00 UTC hour was 0W/8L — pre-dates the London blackout added
09-09, so that hole is already patched.

## 2. Exit rules cannot fix the entries (sequence-aware replay)

Each trade was walked bar-by-bar through `forward_test_log.csv`
(±2 min clock-skew tolerance, SL-first tie-break, validation check:
sim TP 1.5R = −$81.40 ≈ actual −$82.51 ✓).

| Hypothetical exit | WR | est. P/L |
|---|---|---|
| TP 0.33R | 37.8% | −63.35 |
| TP 0.50R | 31.1% | −72.80 |
| TP 1.00R | 20.0% | −84.46 |
| TP 1.50R (actual) | 17.8% | **−81.40 ✓** |
| BE-stop armed at +0.25R | 4W/27L/14BE | −63.97 |
| BE-stop armed at +0.33R | 5W/28L/12BE | −62.36 |
| 50% off at +0.50R, BE runner | 6W/39L | −70.93 |

Expectancy is ≈ **−0.45…−0.55R per trade at every TP placement**. No exit
geometry turns a negative-edge entry stream positive. Exit-side tweaks are
worth ~ +$18–20 over 45 trades (BE-stop at +0.25–0.33R converts ~12 losers
to scratches) and cut variance hard — worth doing, but they are not the fix.

Naive "losers that reached +0.5R first" counting overstates what tighter TPs
would capture (80% touched +0.33R at some point) — most of that run-up
happens *after* the trade is already deep underwater; sequence-aware replay
is the honest test.

## 3. THE FINDING — the blocked signals beat the taken ones

`tools/phantom_trades.py` replay of all 81 risk-gate skips
(same geometry, forward-walk of 1-min bars, SL-first tie-break):

| Stream | Trades | WR | P/L |
|---|---|---|---|
| **Actually taken** | 45 | **17.8%** | −82.51 |
| **Blocked by gates (phantom)** | 80 | **47.5%** (38W/42L) | **+41.17** raw |
| └ sequential/dedup view | 34 | **64.7%** (22W/12L) | +64.01 raw |
| └ blocked by daily-halt | 7 seq | **7W/0L** | +27.71 |
| └ blocked by blackout | 6 seq | 5W/1L | +20.09 |
| └ blocked by SL cooldown | 21 seq | 10W/11L | +16.21 |

The risk layer is **adversely selecting** the signal stream: it passes the
worst third and blocks the profitable half. Two specifics:

- **Daily loss halt**: it triggers precisely when the market is trending
  *against* the bot's side (loss clusters = trend days). After the halt, the
  fresh signals (now SELLs under the new stack) ride the trend — 7W/0L
  phantom. The halt is fighting today's P&L cause.
- **London blackout 07:55–09:00**: designed for the BUY-only era when early
  London whipsawed longs. On 09-10 the blocked 08:11–08:53 signals were
  **five SELLs, all TP (+~$23)**. With the SELL side live, this window is
  opportunity, not danger — *for the sell side only*.
- **SL cooldown**: phantom performance of blocked signals ≈ breakeven
  (+16.21 sequential but 10W/11L) — roughly fair-value, keep it; the 0W/9L
  for actual <5-min re-entries is why it exists.

Phantom P&L excludes spread/slippage (~0.05–0.11/trade) and phantom wins
would have displaced real trades — treat magnitude as estimate, *direction*
as strong evidence (17.8% vs ~48–65%, ~p≈0.001).

## 4. Recommendations (highest evidence first)

1. **Direction-aware London blackout.** Block BUYs 07:55–09:00, allow SELLs
   (or rerun `phantom_trades.py` after the next data drop to re-confirm
   before acting). Evidence: 5W/1L, +20.09 phantom in one session.
2. **Replace the daily-halt kill-switch with a side-switch.** After N losses,
   don't stop — require *trend-side-only* entries (side must agree with
   60/120-min momentum). Evidence: post-halt phantom signals 7W/0L, +27.71.
   Config-drift warning: live logs show limit = 3 ("11/3 SLs today") while
   repo `trade_filter.py` says MAX_DAILY_LOSSES = 10 — reconcile.
3. **BE-stop armed at +0.25…+0.33R** (SL ratchets to entry). −$82.5 → ≈−$63
   replayed; converts 12–14 of 37 losers into scratches. Cheap to implement
   inside the engine's open-trade loop. Keep the SL cooldown as-is.
4. **Skip RSI < 45 entries** — that bucket is 1W/14L (7%); every other RSI
   bucket is ≥11%. Small samples, but consistent with "winners work
   immediately" (early drawdown 0.37R vs 1.12R).
5. **More data before surgery.** 45 trades in one trending-down week is one
   regime (binomial CI on 17.8% ≈ 8–32%). Keep logging signals even during
   halts/cooldowns — the phantom stream is currently the decision-best
   instrument we have. Re-run all three tools after the next ~2 weeks of
   data; only then promote replay winners to live params.

## Appendix — data quality notes

- `trades.csv` has 3 batches (Trade_Num resets on 09-04) from the documented
  balance resets; dedupe by timestamp in any future analysis.
- Bar feed timestamps lag `trades.csv` by up to ~1 min (entry prints match,
  exit-minute bars arrive next minute) — all replay windows must be widened
  ±2 min or results invert (seen during this analysis).
