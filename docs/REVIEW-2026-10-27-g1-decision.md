# REVIEW — G1 decided: `structstop1.5` REGISTERED (branch A), A1 tool work landed, nothing deployed

**Date:** 2026-10-27 (session start ~11:45 UTC; sign-off received ~13:17 UTC)
**Scope:** the G1 owner gate + step **A1** (pre-deploy tool work). **No strategy change, no deploy, no order,
no engine edit.** `engine.SL_CLEAR_ATR` is still **0.5**. The live book was not touched by this session.
**Authoritative artefacts:** `docs/PREREG-2026-10-26-structstop1.5.md` (now REGISTERED), `docs/EXECUTION-PLAN.md`
Track A, `docs/BRIEF-2026-10-27-g1-owner-decision.md` (the pack the owner answered).

---

## 1. What was decided, in the owner's words

The §7 closure-gap REVERT trigger had fired (3 post-cutover closure rides vs the registered threshold of 2, with
0 gap-through, 0 worse exits and 0 weekend rides), and the registered response is a single-commit revert to
`2·ATR / 3·ATR`. The 10-25 `hold_for_dst` wait was over and the decision was the owner's alone, so the session put
three options in front of the owner instead of picking one:

| option | content |
|---|---|
| **(A)** | sign `docs/PREREG-2026-10-26-structstop1.5.md` → one more structural change, `SL_CLEAR_ATR 0.5 → 1.5` |
| **(B)** | reject it and execute the literal §7 revert |
| **(C)** | hold, recorded with a reason |

**The owner chose (A)**, and separately chose to have this session finish **all of A1** now, with **A2 (the deploy)
left as its own later step**. That is the whole decision — this document adds no interpretation to it. Two things
it explicitly does *not* authorise, restated because they are the easy ones to over-read:

- it does **not** authorise changing `engine.py` today (A2 waits for a trade-free window on the host), and
- it does **not** make PASS likely. The registration's own §4 eligibility bar stays **3/4** (trade count −21.9%),
  and reaching PASS needs ≈48% decisive WR against an era reading of 35.8%. The expected outcome of the window is
  "KEEP, no edge" or REVERT, and that is a fine outcome: the change is a stop-hunt defect fix, not a claim of edge.

## 2. The state of the book at sign-off (the "before any post-change trade exists" condition)

`trades.csv` + `forward_test_log.csv` as collected at 12:00 UTC, 722 closed trades; the struct-stop era
(entries ≥ 2026-10-06 03:00 UTC) at **n=225**: 58W / 104L / 61BE / 2TIME.

| reading | value |
|---|---|
| decisive WR | 35.8% [28.8–43.4] |
| R/trade (gross, `win_rate_report` scale) | −0.081R ($−105.75 total) |
| SL events/day · SL share · scratch | 6.12 · 46.22% · 27.11% |
| avg SL loss · era DD | $5.80 · $151.65 |
| geometry guard | 0 stops inside the level, 82.2% level-bound, median risk 3.31 ATR, median clearance **+0.50 ATR** |
| `pressure_report` §5 card | **SCREEN NOT MET** — only C2 (35.80% < 36.0%) fails; no revert fired |

The last host check before sign-off (`D:\gold\mt5_status.py` on the MT5 host, read-only, 06:02:24 UTC) showed the market OPEN, the last
bar at 06:00, and **BUY #723 still open** → A2 was correctly refused for today, and no post-change trade exists,
so the registration satisfies its own precondition. That host check is also why the daily-break signature is
recorded as unchanged: 06:02Z is inside the trading day, not at the 20:58–22:00 break.

## 3. What A1 built, and how each item was checked

The PREREG's §2 froze three pre-deploy engineering tasks. Each is done, and each was verified by running it, not
by asserting it in prose. The invariant across all of them: **pre-deploy, no default output reports a judgement it
did not report before** — the tools learn the new window without the new window being able to affect a reading yet.
What *is* added is additive and says so: one `[OK/FAIL] A2 clearance` line appended in `check_structural_stop.py`,
an opt-in `5b` card in `pressure_report.py`, and a three-line footer in `strategy_lab.py --table` stating that
`structstop1.5` is registered but undeployed — so nobody can read the counterfactual variant rows as a window
judgement. No table cell, era row or verdict string moved.

1. **`tools/strategy_lab.py`** — `CLEAR15_ATR = 1.5`, `CLEAR15_CUTOVER = None`, `CLEAR15_ERA = "structstop1.5"`,
   `clear15_eras()` feeding `--table`. *Check:* the 1.5 era row appears only once a deploy time exists
   (`clear15_eras() == []` while `CLEAR15_CUTOVER is None`, pinned by Scenario AB); pre-deploy the only difference in
   the output is the footer note above, not a single number.
2. **`tools/check_structural_stop.py`** — `--era {auto,struct,clear15}`; `geometry_class()` now takes the *judged*
   era's clearance and its predecessor's (so a post-deploy trade is not classified `???`); an `A2 clearance` line
   (median clearance vs the bar) that FAILs if any level-bound trade in the window sits under it; and a
   `NOT STARTED` exit-0 path while `CLEAR15_CUTOVER is None`. *Checks run:* default output still 720 joined rows /
   PASS with `[OK ] A2 clearance: median +0.50 ATR; 0/185 below it`; `--since 2026-10-06` still filters (229
   joined); `--era clear15` → `NOT STARTED`, exit 0. One regression was introduced and reverted on the way:
   defaulting `--since` to the judged cutover silently emptied the historical era rows and the OLD/NEW boundary
   evidence. The cutover selects **which era is judged**; it must never narrow the report.
3. **`tools/win_rate_report.py`** — a second era book + `ERAS` row for `structstop1.5`, inside the existing
   `--spread`/lazy-import guard. *Check:* default report unchanged (rows inert while `CLEAR15_CUTOVER is None`).
4. **`pressure.py` + `tools/pressure_report.py`** — `BAR15` is this PREREG's §5 transcribed (screen n≥100 at
   net ≥ −0.05R and decisive WR ≥ 40% with B1–B3; PASS at n≥150 with Wilson LB > 40%, R ≥ 0.00R at $0.20/side,
   ≥ −0.05R at $0.275/side, DD ≤ $200; reverts at ≤ −0.15R, DD > $250, avg SL > 2.2× pre-change) and
   `era_stats()` is bar-driven instead of hard-wired to the 0.5 ATR era, with `BAR7` holding the frozen 10-19
   wording verbatim. `--era clear15` prints a `5b` card. *Checks run:* the §5 card for the live era is
   byte-identical to before the change; a **simulated** deploy (`CLEAR15_CUTOVER = 2026-10-27 06:00`) renders the
   1.5 card with its own B1/B2/B3/C1/C2/C3 + A4/A5 + R4/R5/R7 rows; and `era_stats(bar=BAR15)` returns `None`
   rather than falling back to the 0.5 ATR era's boundary — the trap that would have "failed" a window that has
   not started. A second temptation, rejected in review: making the frozen §7 card print a "short of the screen n"
   status. That window's judgement closed on 2026-10-19; its wording is not ours to improve.
5. **`tools/journal.py`** — `--era clear15`, resolving its boundary from the deploy time and exiting 0 with a
   "window has NOT STARTED" line before one exists. *Check:* `--era structstop` unchanged (n_era=225).
6. **`tools/smoke_test.py` Scenario AB** — the one-dial proof plus the refusal guards. On Scenario N's tape with
   only `SL_CLEAR_ATR` patched to 1.5: risk = distance-to-level + 1.5·ATR (6.654 vs 4.818 at 0.5, delta exactly
   one ATR of 1.836), clearance ≥ 1.5 ATR, TP still 1.5× the actual risk, a dip that stops the 0.5 ATR trade out
   leaves the 1.5 ATR trade alive, and the ratchet arms at 0.75R of the **wider** risk; the patched constant is
   then restored and pinned back to 0.5 so no later scenario can inherit it. It also asserts the three judging
   tools refuse the unstarted window and that `BAR15` cites this registration (including its `replay 4.37` A5
   baseline) rather than a copy of the live bar. **`SMOKE TEST PASSED`** (Scenarios A–AB).

## 4. What A2 will consist of (contract, not work done here)

1. Wait for **no open position** on the host (`tools/live_readiness.py` / the host's `mt5_status.py`), then commit exactly one
   line: `SL_CLEAR_ATR = 0.5 → 1.5`, plus nothing else (PREREG §2 freeze).
2. Record the host's `autosync: merge upstream` commit **time** for that deploy as `strategy_lab.CLEAR15_CUTOVER`
   — never the PR date, never the merge date (the 2026-10-13 `LIVE_CUTOVER` erratum).
3. Confirm it with `python3 tools/check_structural_stop.py --era clear15`: it must print the OLD/NEW bracket
   around that timestamp (last 0.5 ATR trade, first 1.5 ATR trade) and then judge the window's A1/A2 rows.
4. Read `pressure_report.py --root . --era clear15` after 10–20 trades for the geometry check; SCREEN at n=100;
   PASS/FAIL at n=150 **or 2026-12-01 21:00 UTC, whichever comes first** — crossing n=150 after the date gate does
   not reopen PASS.
5. `docs/HANDOFF.md` era timeline + `python3 tools/handoff_check.py --update`, in the same commit as the cutover.

## 5. Follow-ups this session recorded rather than silently absorbed

- `readiness.py` (the repo-root read layer behind the dashboard's 🚦 tab): the `g1` timeline row moved from
  `blocked` to `done`, a new `a2` row carries the owner's remaining action ("one line + the cutover it writes,
  gated on no open position"), `window_15`'s detail now says the clock begins at the deploy and not at the
  sign-off, the blockers list swapped the sign-off item for the deploy item, and a dated milestone row points at
  this document. `tools/test_readiness_tab.py` was moved with it (it pins `g1`/`a2` states and renders the page),
  and the `structstop_era` row deliberately still reads 21 days elapsed — the old era's judgement closed on
  2026-10-19 and re-labelling it here would rewrite that history.
- G2 (real spread/swap evidence — 12/14 complete days and 1/2 weekends at the time of writing) stays open. A2 is
  blocked by neither G2 nor G3, but a PASS reading of the registered §5 C is not admissible until G2 closes,
  because C is written at an assumed cost.
- Test evidence: `python3 -m unittest discover -s . -p 'test_*.py'` run from `tools/` → **154 tests, OK**; `python3
  tools/smoke_test.py` → **SMOKE TEST PASSED** (Scenarios A–AB); `python3 tools/handoff_check.py` → **FRESH, 0 advisory
  drift** (no `--update` was needed: the snapshot numbers did not move, only the prose did). Two failures seen while running the suite from the repo root
  (`tools.test_box_watch`, `tools.test_repair_phantom_ledger`) are import-path artifacts of that invocation, not
  regressions: both are OK when run from `tools/`, where they belong.
