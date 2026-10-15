# PRE-REGISTRATION 2026-10-15 — level test re-scale to 0.25 ATR (next isolation slot)

**Status: REGISTERED on paper, NOT deployed.** Owner approval: "Let's do it" (2026-10-15, in reply to
`docs/ANALYSIS-2026-10-15-stop-loss-rate.md` §6–§7). The change may only be deployed **after** the
struct-stop judgement at the 2026-10-19 21:00 UTC review (`HANDOFF.md` §6 item 1), and must **not** be
stacked on the struct-stop window. This document is written **before** any post-change trade exists.
The bars below may not be edited after deployment; if they must change, that is a new dated document.

## 1. The single variable

- Engine level test: the price-relative buffer `FLOOR_BUFFER_PCT = 0.0020` (≈4.5× median ATR) is replaced by a
  **0.25 × ATR** tolerance for "the bar touched the 20-bar level" (BUY: `low ≤ floor + 0.25·ATR`;
  SELL: `high ≥ ceiling − 0.25·ATR`).
- **Unchanged:** the structural stop (`SL_CLEAR_ATR = 0.5`, `RR_TARGET = 1.5`), the BE ratchet at 0.75R,
  `MAX_HOLD_MINUTES = 240`, RSI, ATR bounds, blackouts, cooldowns, breaker, the wick and EMA gates.
- Replay name: `tol0.25` in `tools/strategy_lab.py` (`level_tol_atr = 0.25`). Its replay numbers are the
  ones quoted below.

## 2. Why this and not something else

Source: `docs/ANALYSIS-2026-10-15-stop-loss-rate.md` §4–§5. The 0.25 ATR tolerance is the strongest single
lever on the costed replay (0.75R master book, $0.20/side: `structstop` −0.102R/trade → `tol0.25` −0.062R;
max-hold era −0.108R → −0.012R). It is the same family already registered as handoff §6 item 3(i)
(`FLOOR_BUFFER_PCT` → 0.15–0.25 ATR), so this is the registration that item was waiting for.

## 3. Pre-checks — must all hold before the window is judged

1. `python3 tools/check_structural_stop.py` → PASS (0 stops inside their level, post-cutover).
2. `python3 tools/strategy_lab.py --calib-only` → entry-stream recall ~100% per era.
3. **Replay-vs-live gap ≤ 2 pp decisive WR** on the struct-stop era. *Status 10-15: MET* (the 10-15 harness
   fix — blackout end minute — brought it to 39.3% replay vs 39.1% live, SL share 45.1% vs 47.7%; see the
   analysis doc §3 and HANDOFF §8).
4. The deploy time is taken from the host's `autosync: merge upstream` commit (`docs/AUTOSYNC.md` §2), not the plan.

## 4. Window

Entries at or after the **deploy time of this change** (to be written into this document as a dated line
at deploy, from the autosync log — not from the plan). No other strategy, parameter, gate or harness
change may be deployed inside this window. The struct-stop window and this window never overlap.

## 5. Expected outcome (written before any data — so it can be checked)

- Flow falls from ~12 trades/day to **~6 trades/day** (replay `n/day` 12.2 → 6.3). So **n = 100 takes about
  16 trading days**, and n = 150 about 24. The 2026-10-19 review is not a judgement on this window.
- The replay **already predicts a borderline result at $0.20/side on the master book** (−0.062R/trade, which is
  inside the −0.05R screen only if the real cost is lower). On the post-cutover slice it predicts +0.025R, but on
  **n = 45**, which is not evidence. Expect the screen to be close, and do not read a near miss as a pass.

## 6. Bars (judged at n ≥ 100 for SCREEN, n ≥ 150 for PASS)

Cost: **$0.20/side** until the quote logger (`docs/XM-LOGGER.md`) has 14 days incl. two weekends; then the
measured round trip replaces it, and that switch is recorded here as a dated line before judging.

| Bar | Threshold | Basis |
|---|---|---|
| SCREEN (n ≥ 100) — R/trade | ≥ **−0.05R** | same as the struct-stop screen |
| SCREEN — decisive WR | ≥ **40%** | ≈ breakeven at the live payoff (42.0%) minus the sampling margin |
| SCREEN — SL events / calendar day | ≤ **6** | struct-stop bar |
| SCREEN — scratch (BE) share | ≤ **35%** | struct-stop bar |
| PASS (n ≥ 150) — decisive WR | Wilson 95% lower bound **> 42.0%** | breakeven at the live payoff (1:1.5, avg TP/SL 8.14/5.90) |
| PASS — gross $/trade | > 0 | not negative in the live book |
| **REVERT** (single-commit `git revert`) | R/trade ≤ **−0.15R**, OR era drawdown > **$250**, OR any stop inside its level, OR 2+ trades ride a closure gap | |

Judge on P&L/trade, R/trade, bleed per day and drawdown — never on WR alone.

## 7. Judgement rules

- Sample: entries in the window only. No re-slicing eras after the fact to rescue a bar.
- A SCREEN means "keep observing"; only PASS may be cited as evidence. A PASS still needs the owner's sign-off.
- Record the outcome in a dated `docs/REVIEW-*.md` and in `HANDOFF.md` §6 before any further change.
