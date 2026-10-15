# ANALYSIS 2026-10-15 — "too many stop losses": what can be improved, and what cannot yet

**Status: analysis only. No runtime change.** The struct-stop window (entries ≥ 2026-10-06 03:00 UTC)
is still open and is judged at the scheduled 2026-10-19 21:00 UTC review (`HANDOFF.md` §6 item 1).
Nothing below is adopted. Any candidate needs a pre-registered bar (this doc, once signed off) and
its own isolation slot.

## 1. Short answer

Yes, there are real levers, and the data points at one mechanism. But the stop-loss *share* is the
wrong thing to fix on its own. What decides whether the bot makes money is expectancy against the
payoff ratio:

- Live struct-stop book (n=111, entries ≥ 10-06 03:00): **34 TP / 53 SL / 23 BE / 1 TIME**.
  Avg TP **+$8.14**, avg SL **−$5.90** (payoff 1.38). Decisive WR **39.1%**.
- At that payoff the breakeven WR is 5.90 / (8.14 + 5.90) = **42.0%** before costs. Costs add
  $0.40 round trip per trade. So the bot is about 3 pp short of breakeven before costs, not
  "stopped out too often" in a vacuum.
- Gross P&L on the book: **−$35.43 (−$0.319/trade)**.

So the SL rate matters because it is what pushes WR under 42%. The fix has to move WR up (fewer
bad entries, or fewer SLs that were never going to be winners), not just reduce the count of SLs.

## 2. What is already known (not re-derived here)

- The stop was inside the 20-bar level on 63.8% of the old-rule trades (`ANALYSIS-2026-10-05`).
  The structural stop shipped 2026-10-06 03:00 UTC fixed that: invariant guard `check_structural_stop.py`
  is PASS with zero stops inside their level after the cutover.
- The structural stop lowered SL share and the average SL loss per trade is now bigger (about
  $5.90 vs $3.9 pre-change). Replay on the 0.75R master book, $0.20/side: **−0.194R → −0.073R/trade**.
  It is better, but still negative.
- The BE ratchet at 0.75R is redundant next to the structural stop (`structstop+nord`, −0.052R vs
  −0.073R master; 54.8% of post-cutover trades become full stop-outs). Ratchet-off is not a fix.

## 3. Replay-vs-live gap — FOUND and FIXED (harness only, no runtime change)

Trade-by-trade matching (`tools/strategy_lab.py` replay vs `trades.csv`, struct-stop era) found:

- **Stop geometry is identical.** Every matched entry has the same entry price and the same pre-ratchet
  stop; the ledger stores the post-ratchet stop (= entry) on BE/TP rows, which is why it looks like zero risk.
  Exit reason agrees on **94 of 94** matched entries.
- The whole gap is **which trades get taken**. 17 live trades had no replay entry, and 16 replay trades
  had no live entry.
- The largest single cause was a **blackout boundary bug in the replay**. `trade_filter.is_in_blackout`
  tests `start <= now.time() <= end` on the full timestamp; a bar stamped 09:00 is evaluated at ~09:00:04
  and is **not** blocked, but the replay blocked the whole 09:00 minute (inclusive end). Live entries at
  09:00:04 and 15:15:03 were therefore "replay-blocked". Fixed in `strategy_lab.py` (end exclusive, minute resolution).
  This removed 10 of the 33 mismatches (live-only 17 → 7, replay-only 16 → 9).
- The remaining 16 mismatches are cascade (BE scratches and the cooldown/occupancy they change).

| Struct-stop era (≥ 10-06 03:00) | Live ledger | Replay, fixed harness |
|---|---|---|
| n | 111 | 113 |
| Decisive WR | 39.1% | 39.3% |
| SL share | 47.7% | 45.1% |
| Gross $/trade | −$0.319 | −$0.276 |

The replay now reproduces the live book for this era within about 2 pp. The earlier 43.2% decisive WR was
an artifact of the blackout bug. **Replay figures in older docs (incl. ANALYSIS-2026-10-05) were produced
before this fix and move by roughly 0.02–0.1R/trade; they are history, not re-cut.**

## 4. Candidates (costed replay, $0.20/side, R/trade; fixed harness)

| Variant | Master (0.75R, ≥09-15) | Max-hold era | Post-cutover (n) | Note |
|---|---|---|---|---|
| baseline (pre-cutover geometry) | −0.201 | −0.201 | −0.089 (182) | counterfactual |
| `structstop` (**live now**) | −0.102 | −0.108 | −0.095 (113) | the live experiment |
| `structstop+nord` | −0.084 | −0.083 | −0.068 (95) | 0% BE; SL share 58%; redundant (§2) |
| `tol0.25` | **−0.062** (n 152) | **−0.012** | +0.025 (45) | ~6 trades/day; **pre-registered** |
| `tol0.50+pause` | −0.065 | −0.040 | +0.061 (52) | pause is a second variable |
| `tol1.00` | −0.089 | −0.074 | +0.028 (94) | weakest of the tol family |

Reading it honestly:

- **`tol0.25` is still the strongest single lever** on the master and max-hold books, after the harness fix.
  It does not make the bot profitable at $0.20/side on the master book (−0.062R), so this is an improvement,
  not a fix.
- **Its post-cutover numbers are on 45 trades. They are not evidence.** Earlier evidence of the same kind was
  era-unstable (0 winners of 21 decisive in the 0.30R slice). It also needs ~4 weeks.
- It must not be stacked on the struct-stop window and must wait until after 10-19.

## 5. Options, in the order I would take them

1. **Done 10-15:** replay-vs-live gap closed (§3). Tooling fix only; `--calib-only`, smoke test and the
   structural-stop guard all pass.
2. **After the 10-19 review (per the handoff):** if the struct-stop judgement is SCREEN or PASS, register
   **one** next variable with a bar written before any post-change trade. Best candidate: the
   `tol0.25` level-test re-scale (handoff §6 item 3(i)). Second: `tol0.50+pause`, only if `tol0.25` is
   judged on its own first.
3. **Do not do:** raise `MIN_ATR` / cut ATR band (already normalized-rejected), RSI ≥ 45 (dropped),
   BUY-ban / momentum gate (dropped 10-05), session-band gate (downgraded 10-05), stop widening
   (degrades the ratio: `stopbeyond` 51.6% WR but −0.093R master), a looser stop with the same TP (same
   failure mode).

## 6. Pre-registration

**Registered on paper 10-15, NOT deployed:** `docs/PREREG-2026-10-15-level-test-0.25.md`.
It may only be deployed after the 2026-10-19 struct-stop judgement, must not be stacked on that window,
and its bars are fixed before any post-change trade exists. Pre-checks: the replay-vs-live gap is met (§3).

## 7. Decisions (owner, 10-15: "Let's do it")

1. Register the level-test draft to deploy after 10-19 — **done on paper** (`PREREG-2026-10-15-level-test-0.25.md`).
2. Close the replay-vs-live gap as tooling-only work — **done** (blackout end boundary, §3).
3. No live engine change before the 10-19 review — **held**.

## 8. Reproduce

```bash
python3 tools/check_structural_stop.py
python3 tools/strategy_lab.py --calib-only
python3 tools/strategy_lab.py --table --cost 0.20 --only baseline,structstop,structstop+nord,tol0.25,tol0.50,tol0.50+pause,tol1.00
# the trade-by-trade matching used for §3 is reproduced by comparing strategy_lab.Lab.run() with trades.csv on Entry_Time
python3 tools/win_rate_report.py --spread 0.40
```

Live-era figures (§1, §3) were computed directly from `trades.csv` for `Entry_Time ≥ 2026-10-06 03:00`.
