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

## 3. The replay does NOT yet reproduce the live book

Before trusting any counterfactual, this gap matters:

| Struct-stop era (≥ 10-06 03:00) | Live ledger | `strategy_lab` `structstop` replay |
|---|---|---|
| n | 111 | 110 |
| Decisive WR | **39.1%** | 43.2% |
| SL share | **47.7%** | 41.8% |
| Avg TP / avg SL | +$8.14 / −$5.90 | +$8.24 / −$5.99 (similar) |
| Gross $/trade | **−$0.319** | +$0.092 (at $0 cost) |

The replay has fewer SLs and more wins than the live book on the same window. The `--calib-only`
entry recall is 100%, so the difference is in exits and cascade (the replay takes 744 trades vs 608 live;
cooldown shifts with the exit bar). Until this is explained, the replay should be read as
**directionally useful but optimistic by roughly 4–5 pp of decisive WR** in this era.
This is a tooling item and is not a strategy result. It should be closed before any candidate is judged.

## 4. Candidates (costed replay, $0.20/side, 0.75R master book, R/trade)

| Variant | What it changes | Master R/t | Post-cutover R/t (n) | Note |
|---|---|---|---|---|
| baseline (pre-cutover geometry) | — | −0.194 | −0.078 (180) | counterfactual only |
| `structstop` (**live now**) | stop 0.5 ATR beyond level, TP 1.5R | −0.073 | −0.025 (110) | the live experiment |
| `structstop+nord` | + ratchet off | −0.052 | +0.015 (93) | 0% BE; SL share 55%; redundant (§2) |
| `tol0.25` | level test 0.25 ATR (replaces the price-% tolerance) | **−0.062** | **+0.025 (45)** | cuts flow to ~6/day |
| `tol0.50+pause` | level test 0.50 ATR + 15-min post-BE pause | −0.065 | +0.061 (52) | pause is a second variable |
| `tol1.00` | level test 1.00 ATR | −0.085 | +0.013 (93) | weakest of the tol family |

Reading it honestly:

- **`tol0.25` is the strongest single lever in the replay** (the same finding as handoff §6 item 3(i)). It is the only candidate that moves the book to around breakeven on the replay.
- **Its post-cutover numbers are on 45 trades. They are not evidence.** Earlier evidence of the
  same kind was era-unstable (0 winners of 21 decisive in the 0.30R slice). It also needs ~4 weeks.
- It is also **inside the replay's optimism gap** (§3): roughly 4.6 pp of decisive WR is about 0.11R/trade
  at this payoff, and the replay's *edge* over the live baseline is smaller than that. It may not survive the live check.
- It must not be stacked on the struct-stop window (handoff §1/§6) and must wait until after 10-19.

## 5. Options, in the order I would take them

1. **Now (no runtime change):** close the replay-vs-live gap in §3. Find why the replay has ~4.6 pp
   more decisive WR and 6 pp fewer SLs on the same era. A tooling PR, judged by `--calib-only`
   and the era table, not by P&L.
2. **After the 10-19 review (per the handoff):** if the struct-stop judgement is SCREEN or PASS, register
   **one** next variable with a bar written before any post-change trade. Best candidate: the
   `tol0.25` level-test re-scale (handoff §6 item 3(i)). Second: `tol0.50+pause`, only if `tol0.25` is
   judged on its own first.
3. **Do not do:** raise `MIN_ATR` / cut ATR band (already normalized-rejected), RSI ≥ 45 (dropped),
   BUY-ban / momentum gate (dropped 10-05), session-band gate (downgraded 10-05), stop widening
   (degrades the ratio: `stopbeyond` 52.6% WR but −0.081R), a looser stop with the same TP (same
   failure mode).

## 6. Draft pre-registration (for the owner to approve — NOT registered)

Proposed for the first isolation slot after the struct-stop judgement:

- **Variable:** level test `FLOOR_BUFFER_PCT` (price-%) → **0.25 ATR**, nothing else changed.
- **Window:** entries after the deploy time of that change (to be taken from the autosync log, not the plan).
- **Pre-check (must PASS first):** replay-vs-live gap in §3 closed to ≤ 2 pp decisive WR on the
  struct-stop era; `check_structural_stop.py` PASS; `--calib-only` ~100%.
- **Screen at n ≥ 100:** R/trade ≥ −0.05R, decisive WR ≥ 40%, SL/day ≤ 6, scratch share ≤ 35%.
- **PASS at n ≥ 150:** Wilson 95% lower bound on decisive WR > 42.0% (the breakeven at 1:1.5 with
  live payoff), and gross $/trade > 0.
- **REVERT:** R/trade ≤ −0.15R, or era drawdown > $250, or any stop inside its level.

These numbers are proposals taken from the existing bars in `ANALYSIS-2026-10-05` §7; the 42% breakeven
line is the one new element. The owner must sign off before anything is registered.

## 7. Decision needed from the owner

1. Approve the §6 draft (or name a different single variable) to register after 10-19.
2. Approve the §5(1) replay-calibration task as the next (tooling-only) work item.
3. Confirm no change to the live engine before the 10-19 review.

## 8. Reproduce

```bash
python3 tools/check_structural_stop.py
python3 tools/strategy_lab.py --calib-only
python3 tools/strategy_lab.py --table --cost 0.20 --only baseline,structstop,structstop+nord,tol0.25,tol0.50,tol0.50+pause,tol1.00
python3 tools/win_rate_report.py --spread 0.40
```

Live-era figures (§1, §3) were computed directly from `trades.csv` for `Entry_Time ≥ 2026-10-06 03:00`.
