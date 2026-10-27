# G1 decision pack — sign off (or reject) `structstop1.5`

**Date:** 2026-10-27 ~12:00 UTC · data collection 359 · bar log through `2026-10-27 11:59:06 UTC`
**Gate:** **G1** — `docs/EXECUTION-PLAN.md` §0, the only approval that blocks step **A1**
**Object:** `docs/PREREG-2026-10-26-structstop1.5.md`, which is still **DRAFT — not registered, not deployed**
**This pack decides nothing.** It exists so the owner can answer in one line. No agent session may sign on the owner's
behalf, and nothing in this file registers the pre-registration, changes `SL_CLEAR_ATR` (still **0.5**), deploys,
or places an order. `TRADING_MODE` remains `FORWARD_TEST`.

---

## 1. The one question

The §7 closure-gap REVERT trigger of `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` **fired (3 rides vs a
threshold of 2)**. Its registered response is a one-commit revert of the structural stop back to `2·ATR / 3·ATR`.
The owner's 10-25 decision was `hold_for_dst`: wait until the DST offset was observed, then choose. That wait is
over — the offset is `+2h` and confirmed, and the guard is deployed — so the choice is on the table **now**:

| | action | what it is |
|---|---|---|
| **(A)** | sign `docs/PREREG-2026-10-26-structstop1.5.md` | run the isolated forward window on **one** changed line: `SL_CLEAR_ATR 0.5 → 1.5`. Registered bar, judged at n=100 / n=150 / 2026-12-01. |
| **(B)** | reject it | execute the **literal** §7 revert to `2·ATR / 3·ATR` (already registered as the response; needs its own dated REVIEW, not a new pre-registration). |
| **(C)** | hold | neither. Legal, but it leaves a fired trigger un-actioned and the window start slipping; it must be recorded as a decision, not silence. |

**Nothing deploys before this line is written.** Every other plan step (Track B, A6) is already eligible and running.

---

## 2. Why (A) is recommended — the evidence, refreshed on today's data

Costed, stateful replay (`tools/strategy_lab.py`), post-cutover era only, three geometries:

| cost / side | **live** `0.5 ATR` | `1.0 ATR` | **`1.5 ATR` (A)** | revert `2·ATR/3·ATR` **(B)** | A − live | live − B |
|---|---|---|---|---|---|---|
| $0.20 registered | −0.141R | −0.126R | **−0.046R** | −0.155R | **+0.095R** | +0.014R |
| $0.275 measured | −0.171R | −0.154R | **−0.069R** | −0.202R | **+0.102R** | +0.030R |
| $0.35 stress | −0.202R | −0.181R | **−0.092R** | −0.249R | **+0.110R** | +0.047R |

Replay n per row: live 232, `1.0` 210, `1.5` 182, revert 348. **Revert (B) is the worst cell at every cost tested**,
and it puts ~66% of stops back **inside** the 20-bar level the entry was built on — undoing the one thing the
current geometry demonstrably fixed (`check_structural_stop.py`: 0 stops inside, 82.2% level-bound).
`1.0 ATR` is *not* a cheaper middle option: it buys +0.015R and fails the bar by a wide margin.

Side effects of `1.5` in the same replay — both directions, no cherry-picking:

| | live `0.5` | `1.5` | reading |
|---|---|---|---|
| decisive WR | 36.5% | 40.3% [32.0–49.3] | up, but the CI still straddles the 40% line |
| SL events / calendar day | 5.61 | 3.94 | the stated purpose, met (bar ≤ 6.0) |
| SL share / scratch share | 43.5% / 30.6% | 39.0% / 31.9% | B2 ✓ (≤40%), B3 ✓ (≤35%) |
| max drawdown (era) | $230.2 | $180.0 | 22% better |
| median risk | 3.31 ATR | 4.35 ATR | **+31% per trade at risk** |
| avg SL loss (net) | −$6.28 | −$8.20 | **+31% per stop-out**; REVERT trip-wire is 2.2× ≈ $12.8 |
| median hold / TIME exits | 23.5 min / 2 | 37.0 min / 5 | longer exposure to the closure-gap failure mode |
| trade count | 232 | 182 (−21.6%) | the pre-declared bar point that **fails** |

**The frozen eligibility bar (PREREG §4, written 10-25 before this outcome existed) scores 3 of 4** — expectancy,
win rate and drawdown pass; the −21.9% trade count fails and is recorded, not explained away. That score is the
registration determination and is **not** re-scored here; today's refreshed replay lands in the same place
(−21.6%), which is the only reason it is quoted.

## 3. What (A) does *not* buy — read this before signing

* **It is very unlikely to end in PASS.** PASS needs the Wilson 95% lower bound of decisive WR above 40%, which
  at n=150 means **≈48%** (72 wins of 150). The live era is at **35.8% [28.8–43.4]** today; the most optimistic
  replay reading of `1.5` is 40.3% with a CI of [32.0–49.3]. Realistic outcomes are **KEEP, no edge** (geometry
  fixed, still no demonstrated edge) or **REVERT**. Signing buys a clean, pre-registered answer plus a defect fix
  that roughly halves the modelled bleed — not a profitable strategy.
* **The era is getting worse while the decision waits.** In the 24 h since the last audit the era grew 212 → 225
  and its gross slipped **−0.054R → −0.081R/trade**, decisive WR 37.5% → 35.8%, engine ledger $131.30 → $92.38
  (book net −$669.26 → −$713.36 at $0.40 RT). This is a *grown-sample observation*, not a re-judgement — the
  10-19 gate is closed and stays closed — but it is the reason "wait for more data" is not a neutral choice.
* **The replay has a known bias in favour of exactly this candidate.** Fixed intra-bar ordering (arm-before-stop,
  stop-before-target) systematically flatters a deeper stop, because the walk cannot see a wick that took the
  target and then the stop. That bias is why the answer has to be a forward window, not a better replay.
* **The gain is not smooth in clearance** (0.5 → 1.0 buys +0.015R, 1.0 → 1.5 buys +0.080R), which is what a
  four-point grid can do to a number. The window is registered for `1.5` only: **2.0, 1.25 or any other point
  needs its own dated registration**, and no threshold may be tuned inside the window.
* **Longer holds raise the gap risk that started this.** The deployed guard only blocks *entries* in the last
  30 min before the derived daily break; a trade opened 31 min early can still ride it. The re-registered backstop
  is brutal and deliberate: **2 post-change rides across a closure = immediate revert.**

## 4. Verified this session (PREREG §2.3, the pre-deploy task that did not need the signature)

The blocker "no post-DST **daily** break logged yet" is **cleared from data**:

* first post-DST daily break in the price log: `2026-10-26 20:58:09 → 22:00:04 UTC` (61.9 min) — and
  `engine.derive_daily_closure()` on the same log returns exactly `((20:58), (22:00))`. **The deployed gap-guard
  schedule is right in the new DST regime**, and its ±60-min adaptation correctly did *not* fire.
* why it did not need to fire: the break is fixed in **UTC**, not in broker time — the quote sidecar shows the
  frozen tick window at `20:59 → 22:00 UTC` on 2026-10-22 (offset `+3h`) **and** on 2026-10-26 (offset `+2h`).
  The `+1 h` server-clock change moves the broker's *label*, not the closure.
* no reopen hole on 10-26 (the ~2 h Sunday-reopen gap of 10-25 is a separate, still-open **host** item:
  verify `mt5feed` / `goldbot` restart; the next weekend 10-31/11-01 is the next chance to observe it).

Everything else in the session ritual still passes: `check_data` 0 fail / 8 warn · `handoff_check` FRESH ·
`check_structural_stop` **PASS** (0 stops inside, +0.50 ATR clearance) · `check_gap_rides` 3/2 reached, 0 damage ·
`strategy_lab --calib-only` recall **99.8%** (A3 bar 99.6–100 ✓) · `live_readiness` **9 PASS / 8 TODO / 3 MANUAL,
gate CLOSED** · `smoke_test` PASSED · 64 `goldbot` tests + 18 `live_readiness` tests + 16 readiness-tab tests OK.
Quote sample: **12/14 complete UTC days, 1/2 weekends**, 38 451 rows, median spread **$0.55**, measured round trip
**$0.55** on 144 matched trades (still under the 14-day / two-weekend target, so **$0.40 stays registered**).

## 5. Timing — the only thing a delay costs

The registered window ends at **n=150 closed trades or 2026-12-01 21:00 UTC, whichever comes first** (the 10-19
lapse is exactly what that date gate is for). n=150 needs ≈15 trading days at the `1.5` replay rate (10.1/day),
≈12 at the book's observed rate (10.5–13/day); n=100 (SCREEN) needs ≈10. The date gate is **35 days** away, so a
deploy this week fits with ~2–3 weeks of slack — and the slack is the whole thing: sign in mid-November and the
window closes date-first with n<150, which means **no PASS arm at all**, a spent window and a new registration.

## 6. What each answer triggers (already sequenced in the plan)

* **(A) signed** → A1 rest of the work, paper-only, this session or the next: register the draft verbatim with the
  dated signature; add `CLEAR15_CUTOVER` to `tools/strategy_lab.py`; a 1.5-ATR `--since` era in
  `tools/check_structural_stop.py`; matching era splits in `tools/win_rate_report.py`, `tools/pressure_report.py`
  and the journal; a `structstop1.5` geometry assertion in `tools/smoke_test.py`. Then **A2** (single-line change +
  PR + autosync; the cutover is the host's `autosync: merge upstream` time, confirmed from the ledger boundary —
  never this document's date), **A3** at 10–20 trades, **A4** at n=100, **A5** at n=150/12-01.
* **(B) rejected** → the literal §7 revert in one commit with its own dated REVIEW; the `1.5` candidate is closed
  and stays closed (only new, dated, pre-registered evidence can reopen it).
* **(C) held** → recorded as a decision with a reason; Track B (B2 broker-side BE/time management) becomes the
  next step and the fired trigger stays open. A hold with no date is how a gate quietly becomes a default.

## 7. Sign-off block

The draft's own wording, unchanged (`docs/PREREG-2026-10-26-structstop1.5.md` §1):

> Approved / rejected by owner on ________ (UTC). If approved, this draft becomes the registered bar **before**
> any post-change trade exists.

One line from the owner — `A`, `B` or `C + reason` — is enough. A session will then write that line into the
pre-registration verbatim with its UTC timestamp, and only then touch `engine.py`.

## 8. Reproduction

```bash
python3 tools/check_data.py                  # 0 fail / 8 warn
python3 tools/check_structural_stop.py       # PASS: 0 inside, 82.2% level-bound, +0.50 ATR
python3 tools/pressure_report.py --root .    # §5 era card: 35.8% dec, -0.081R gross
python3 tools/check_gap_rides.py             # 3/2 reached, 0 gap-through, 0 worse exits
python3 tools/strategy_lab.py --calib-only   # recall 99.8%
python3 tools/strategy_lab.py --table --only baseline,structstop,structstop1.0,structstop1.5
python3 tools/xm_quote_report.py             # 12/14 days, 1/2 weekends, $0.55 median
python3 tools/live_readiness.py              # 9 PASS / 8 TODO / 3 MANUAL -> CLOSED
python3 -c "import sys; sys.path.insert(0,'.'); import engine; print(engine.derive_daily_closure('forward_test_log.csv'))"
```
