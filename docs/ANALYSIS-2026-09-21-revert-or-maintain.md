# Analysis — 2026-09-21 (PM): "revert or maintain?" — whole book before vs after the recent parameter changes

**Question (user, ~18:00 UTC 09-21):** compare the whole trade book from before
the recent parameter changes against the book after them, referring to
`docs/HANDOFF.md`, and decide whether to **revert or maintain**.

**Answer: MAINTAIN. Revert none of the three changes.** Each change is either
demonstrably better than what it replaced, or physically incapable of having
caused today's bleed. The one genuine, ongoing failure — the 0.75R book still
has no edge — is already governed by the pre-registered fallback protocol, and
that protocol is mid-flight by design.

Sample: **281 closed trades**, 2026-09-04 08:20 → 2026-09-21 17:53 UTC
(deduped by entry timestamp), 0 active, data collection 92 = `origin/main`
`7a2dc11`. Suite re-run on this snapshot (§6): all green.

---

## 1. What "the recent parameter changes" are

| # | Deployed (UTC) | Change | PR |
|---|---|---|---|
| 1 | 09-10 12:34 | New-regime stack: BE ratchet (`BE_TRIGGER_R = 0.30`) + direction-aware London blackout + trend-side daily breaker | #7 |
| 2 | 09-15 06:00 | `BE_TRIGGER_R` **0.30 → 0.75** (scratch rate 75% → ~35%) | #9 |
| 3 | 09-21 ~06:00 | `MAX_HOLD_MINUTES = 240` — max-hold time stop, reason TIME, neutral bucket like BE (falsification fallback step 1) | #15 |

Boundaries are the entry-time boundaries established in
`docs/ANALYSIS-2026-09-21-win-rate-drop-check.md` §2b (no-reset decision: the
max-hold deploy resets nothing; the falsification bar stays judged on the
whole 0.75R ratchet book).

## 2. The comparison — the ledger partitioned into non-overlapping books

Computed on the 2026-09-21 17:59 UTC snapshot (281 trades). Wilson 95% CIs;
`dec` = decisive WR excluding BE/TIME. Rows 1 + 2 + 3a + 3b partition the
ledger (45 + 130 + 95 + 11 = 281); P&Ls sum to −$186.88.

| Book | Boundary (entry, UTC) | n | Result | Decisive WR (CI) | P&L | $/trade |
|---|---|---|---|---|---|---|
| **All trades** (era-blind — the dashboard tile) | — | 281 | 40W/107L/134BE/0TIME | 27.2% [20.7, 34.9] | −$186.88 | −$0.665 |
| **1. Pre-ratchet** (no BE ratchet) | < 09-10 12:34 | 45 | 8W/37L | 17.8% [9.3, 31.3] | −$82.51 | **−$1.834** |
| **2. 0.30R era** | 09-10 12:34 → 09-15 06:00 | 130 | 10W/22L/98BE | 31.2% [18.0, 48.6] | −$41.69 | −$0.321 |
| **3. 0.75R ratchet book (master — the falsification bar's era)** | ≥ 09-15 06:00 | 106 | 22W/48L/36BE | 31.4% [21.8, 43.0] | −$62.68 | **−$0.591** |
| — 3a. of which "0.75R-only" (closed pre-deploy) | → 09-21 ~06:00 | 95 | 20W/41L/34BE | 32.8% [22.3, 45.3] | −$40.61 | −$0.427 |
| — 3b. of which **max-hold era (current)** | ≥ 09-21 ~06:00 | 11 | 2W/7L/2BE | 22.2% [6.3, 54.7] | −$22.07 | −$2.006 |

Engine ledger $337.82 vs true $313.12 — known balance-reset drift +$24.70,
unchanged since 09-15.

## 3. Change-by-change verdict

**Change 1 (new-regime stack, 09-10): MAINTAIN — it is the single biggest
P&L improvement in the ledger.** Bleed per trade fell **5.7×**
(−$1.834 → −$0.321) and decisive WR rose 17.8% → 31.2% the moment it
deployed. The pre-09-10 book is the worst book on record; there is nothing
there to return to.

**Change 2 (ratchet 0.30 → 0.75, 09-15): MAINTAIN — and do *not* go back to
0.30R.** Honest live read: no edge (master book −$0.591/trade at n=106; the
−$0.40 falsification bar tripped 09-17 and stays tripped). But a *revert to
0.30R* is ruled out twice over:

- **Binding project decision** (handoff §6): fallback never returns to 0.30R.
- **The counterfactual grid on current data** (same entries re-walked,
  `tools/win_rate_report.py` §5b): **0.30R −$116.30** vs **0.75R +$28.74** vs
  ratchet-off +$119.49 (cascade-ignorant estimates; directionally robust, and
  the 0.30R replay reproduces the live 0.30R era exactly). At 0.30R, 174 of
  236 new-regime entries scratched at $0; the ratchet was converting runs
  into nothing.

The correct *forward* step if the book keeps failing is the pre-registered
**fallback step 2 = ratchet-off experiment** — a loosening, not a revert.

**Change 3 (max-hold 240 min, deployed today ~06:00): MAINTAIN — exonerated
by construction.** It **has never fired**: `status.json` carries
`time_exits: 0`, there are no TIME rows, and today's 11 post-deploy trades
held **1.0 → 24.9 min** — none within 3.9 hours of the cap. A stop that
never fires cannot change any outcome; reverting it would change precisely
nothing. Going forward it is pure downside insurance (the historical
>60-min holds — #95's 49.1 h weekend ride, #187's 65 min — are now capped
at 240 min).

## 4. So why is today red? (max-hold era day 1: n=11, −$22.07)

Not the change — the day:

- **Trend day.** Gold fell 51 pts peak → trough (4383 → 4332), closing
  −26 net. The strategy is a mean-reversion scalper (buy the 20-bar floor /
  sell the 20-bar ceiling); trend days are its worst environment by design.
- **Same old pattern.** 9 of the 11 trades were SELLs chopped out by 2–5 pt
  counter-bounces inside the sell-off — the documented
  stop-inside-the-chop bleed (FOMC day, this morning's 05:30–06:41 cluster).
  Direction often right, timing wrong; not a new behaviour.
- **Gates behaved as configured.** Escalating SL cooldown active most of the
  day; the **daily breaker tripped** (11 SLs ≥ `MAX_DAILY_LOSSES = 10` →
  trend-side-only at session end). The known cooldown leak also recurred:
  blocked signals replay **+$258.67 sequential** (phantom ledger) — the
  live book took the losers while the gate sat out winners. That leak is
  item (b) in the queue and is untouched by today's params.
- **Statistics.** At the era base rate (~32% decisive), P(≤2 wins in 9
  decisive) ≈ **41%**. The daily P&L (−$22.07) matches the era's worst days
  (09-16 −$22.92 pre-FOMC bleed, 09-17 −$14.74) — bad day, not a broken day.

## 5. Why "maintain" is the only protocol-compliant move right now

- The 0.75R book's **falsification bar (≤ −$0.40/trade at n ≥ 60) tripped
  09-17 16:17 UTC** and is still tripped (−$0.591 at n=106). The
  pre-registered response to that trip is **exactly what is live**: fallback
  step 1 (max-hold time stop), judged **in isolation at deploy + ~2 weeks /
  n ≈ 200 max-hold-era trades** on P&L/day and bleed/trade — not on win
  rate, and not on an 11-trade window. Today is hour ~12 of that window.
- Reverting or changing anything now would tear up the protocol at precisely
  the moment it is doing its job: protecting the project from re-tuning to
  a noisy sub-window.
- The proposed (not yet pre-registered) **fallback step-2 bar stands**:
  post-deploy P&L/trade ≤ −$0.40 at n ≥ 200 max-hold-era trades →
  **ratchet-off experiment** (replay: 44.3% decisive, est +$119).
- Watch for the same re-review (not adopted yet — one change at a time):
  **RSI≥45 ∧ ATR<2.5 combo filter** — new regime keep-bucket 37.0% dec /
  −$9.91 vs skip 25.0% / −$94.46, replay +$0.21–0.56/taken. Strongest
  entry-side candidate; adoption would be its own isolated cycle.

## 6. Decision record + suite

**Decision: MAINTAIN current parameters (no revert of PR #7 / #9 / #15; no
new changes).** Next decision point: max-hold deploy + ~14 d (≈ 10-05) or
n ≈ 200 max-hold-era trades → if still ≤ −$0.40/trade, fallback step 2
(ratchet-off) in isolation. Never back to 0.30R. Docs-only session: no
engine/strategy/param change, so the max-hold isolation window is
undisturbed.

Suite on this snapshot (data collection 92, 281 trades):
`tools/check_data.py` **0 fail / 8 warn** (known: +$24.70 drift, #95
gap-span, #17/#18 no-log-row); `tools/win_rate_report.py` and
`tools/phantom_trades.py` re-ran end-to-end; `tools/smoke_test.py`
**SMOKE TEST PASSED** (A–K); code untouched so nothing else to re-run.
