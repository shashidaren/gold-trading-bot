# PREREG — `structstop1.5`: one-variable stop-clearance window **REGISTERED 2026-10-27, NOT YET DEPLOYED**

**Date:** 2026-10-26 ~14:15 UTC
**Data used to write the bar:** collection 349, 709 closed trades, struct-stop era n=212, log through `2026-10-26 11:59:07 UTC`.
**Status:** **REGISTERED (owner sign-off 2026-10-27 ~13:17 UTC) — NOT DEPLOYED.** The owner chose branch **(A)** over the literal §7 revert, so from this line down this document is the binding bar for the `structstop1.5` window: it may not be edited, re-tuned or re-sliced after outcomes are seen (§2's own freeze rule: "no second variable, no re-slicing of eras, no threshold tuning after looking at outcomes"; a miss is reported as a miss). **Deployment is a separate step (A2)** and is still gated on there being no open trade on the host; `engine.SL_CLEAR_ATR` is **0.5** until that commit lands, and `strategy_lab.CLEAR15_CUTOVER` stays **None** until the deploy happens, so no pre-change trade can be counted into the window. Sign-off record: `docs/REVIEW-2026-10-27-g1-decision.md`.
**Evidence:** `docs/ANALYSIS-2026-10-25-stop-hunt-markouts-and-clearance-grid.md` (pre-declared grid + bar), refreshed on today's data in `docs/REVIEW-2026-10-26-full-system-audit.md` §3.

---

## 1. Why this is on the table, and why it is an owner decision

The §7 closure-gap REVERT trigger fired at **3/2** post-cutover closure rides. Its registered response is a single-commit revert of the structural stop to `2·ATR / 3·ATR`, with the gap guard first. The gap guard is now **deployed** (`71317da`, 2026-10-25 02:48:12 UTC) and the post-DST broker offset that blocked the choice is now **observed** (+2h, EU rule 100% agreement).

The owner's 10-25 decision (`hold_for_dst`) explicitly reframed the response as a **choice** between:

- **(A)** pre-register and stage `structstop1.5` (`SL_CLEAR_ATR = 1.5`), or
- **(B)** execute the literal §7 revert.

**Recommendation: (A).** On today's costed/stateful replay, (B) is the **worst** cell at every cost tested (`−0.137R/t` at $0.20/side vs `−0.110R/t` live and `−0.024R/t` for 1.5 ATR) and would put ~66% of stops back inside the 20-bar level the trade was built on. (A) passes **3 of 4** points of the *pre-declared* bar written on 10-25 (see §4). That is new, dated, pre-declared evidence — the only mechanism this repo allows for revisiting a rejected candidate. It is **still a hypothesis**: the 4th bar point (trade count) fails, the replay's pessimistic same-bar ordering systematically favours deeper stops, and the era is net negative after cost.

**Sign-off (one line, as required above):**
> **Approved by the owner on 2026-10-27 (branch A — register `structstop1.5` and stage the deploy as A2)**, recorded in the Arena session's owner response and written up in `docs/REVIEW-2026-10-27-g1-decision.md`. The approval was given **before** any post-change trade exists (the last ledger row at sign-off was trade #723, still open, entered under the 0.5 ATR rule), which is the condition this line imposed.

No agent session may declare this registered on the owner's behalf — this line exists only because the owner answered the question; it reproduces that answer and adds nothing to it.

---

## 2. The single variable — and the frozen list

**Change exactly one line:** `SL_CLEAR_ATR = 0.5 → 1.5` in `engine.py`. `risk = max(2·ATR, |entry − level| + 1.5·ATR)`; `TP = RR_TARGET × actual risk` (still 1:1.5 against the **real** stop, by construction). Nothing else is tuned.

Frozen for the whole window: `ATR_SL_MULT`, `ATR_TP_MULT`, `RR_TARGET`, `FLOOR_BUFFER_PCT`, `BE_TRIGGER_R = 0.75`, `MAX_HOLD_MINUTES = 240`, `MAX_BELOW_EMA_ATR`, RSI/ATR bounds, blackouts, cooldowns, daily breaker, `GUARD_CUTOFF_MIN = 30` and the derived gap-guard schedule, the LIVE-path hardening from 10-26, and the data source. **No second variable, no re-slicing of eras, no threshold tuning after looking at outcomes.**

**Pre-deploy engineering tasks (must be done before the change can be judged):**
All three are **DONE on 2026-10-27** (see `docs/REVIEW-2026-10-27-g1-decision.md` §3 for the evidence each was checked against). What each became:

1. ✅ `tools/strategy_lab.py`: `CLEAR15_ATR = 1.5`, `CLEAR15_CUTOVER = None`, `CLEAR15_ERA = "structstop1.5"`, `clear15_eras()` feeding `--table`; a `VARIANTS["structstop1.5"]` entry already existed. `tools/check_structural_stop.py`: `--era {auto,struct,clear15}`, geometry classified against the **judged era's** clearance (`OLD/NEW/???` now means "≥ cur bar / ≥ prev bar / neither"), an `[OK/FAIL] A2 clearance` line, and a hard FAIL on any level-bound trade in the window under the bar; it prints `NOT STARTED` and exits 0 while `CLEAR15_CUTOVER is None`. `tools/win_rate_report.py`: a second era book + ERAS row for `structstop1.5`, inert until the cutover exists. `pressure.py` / `tools/pressure_report.py`: `BAR15` (this document's §5, transcribed) + a `5b` card and `--era clear15`. `tools/journal.py`: `--era clear15`.
2. ✅ `tools/smoke_test.py` **Scenario AB**: with only `SL_CLEAR_ATR` patched to 1.5 on Scenario N's tape, risk = distance-to-level + 1.5·ATR, the stop clears the floor by ≥1.5 ATR, TP stays 1.5×the actual risk, the ratchet arms at 0.75R of the **wider** risk, and the delta vs the live bar is exactly one ATR; it also pins that the three judging tools refuse the unstarted window.
3. ✅ Post-DST daily break confirmed on the host feed: the first post-DST break is `2026-10-26 20:58 → 22:00` UTC and matches `derive_daily_closure()` byte-for-byte, and the quote sidecar shows the break is fixed in UTC across the offset change (recorded in `docs/HANDOFF.md`'s 2026-10-27 timeline row). Re-verified on 2026-10-27 06:02 UTC: market open, last bar 06:00, trade #723 open — no break signature to re-pin, so `(20:58, 22:00)` stands.

**Cutover date is NOT this document's date and NOT the PR merge time.** It is the host's `autosync: merge upstream` commit time (the 10-13 erratum rule), confirmed from the ledger by the OLD/NEW boundary evidence in `tools/check_structural_stop.py`. Record it in a dated REVIEW before the first post-change trade is judged.

---

## 3. Window and sample

- **Window:** entries with `Entry_Time ≥ <recorded deploy time UTC>` == the `structstop1.5` era. One variable only.
- **Interim geometry check:** after **10–20** trades (A1–A5), before any P&L reading.
- **SCREEN:** first judgement at **n = 100** closed trades.
- **PASS/FAIL:** at **n = 150** closed trades **or 2026-12-01 21:00 UTC, whichever comes first**. (Replay rate ≈10–13 trades/day, so n=150 needs ~3 weeks; the date gate is deliberately generous — the 10-19 arm lapsed with its time gate and must not be repeated. Crossing n=150 *after* the date gate does **not** reopen PASS.)
- **n < 60 is not a result** in either direction. No re-judgement on a grown sample without a new dated registration.

---

## 4. Pre-declared eligibility bar (from 10-25, re-scored on today's data)

`structstop1.5` earns registration only if, vs live `structstop` on the post-cutover era, **all** of: (1) net R/trade improves ≥ +0.05R at $0.20/side and still beats live at $0.275/side; (2) decisive WR does not drop; (3) max drawdown no more than 25% worse; (4) trade count falls by ≤15%.

| | result (today) | verdict |
|---|---|---|
| 1 | +0.086R at $0.20/side; +0.093R at $0.275/side | **PASS** |
| 2 | 41.7% vs 38.3% | **PASS** |
| 3 | maxDD 165.3 vs 186.0 | **PASS** |
| 4 | n 171 vs 219 = **−21.9%** | **FAIL** (mechanism disclosed: fewer, longer trades — median hold 37 m vs 25 m, 5 TIME vs 2) |

**3/4 → eligible as a candidate, not proven.** The 4th miss is recorded, not explained away. No further clearance grid point (2.0 ATR, 1.25, etc.) may be tested without its own dated registration.

---

## 5. Forward bar for the new era (write the numbers AFTER the window, never re-tune)

Judge in this order. A failure at A invalidates the reading of C.

**A. Is the code doing what the model says?** (after 10–20 trades)

| # | metric | requirement |
|---|---|---|
| A1 | `check_structural_stop.py` on the new era → stop INSIDE level | **0** |
| A2 | median clearance on level-bound trades | **≥ 1.5 ATR** (the variable under test) |
| A3 | `strategy_lab.py --calib-only` | recall **99.6–100%** on 0.75R-master / max-hold (funnel untouched) |
| A4 | level-bound share | **70–90%** (current live era 83.0%) |
| A5 | median risk in ATR | **3.8–5.0** (replay 4.37) |

**B. Fewer stop-outs** (`win_rate_report.py`, `pressure_report.py --root .` on the new era)

| # | metric | bar |
|---|---|---|
| B1 | SL events / calendar day | **≤ 6.0** (live era 5.94; replay 1.5 ≈ 3.7) |
| B2 | SL share of closed | **≤ 40%** (live 42.0%; replay 36.8%) |
| B3 | BE (scratch) share | **≤ 35%** (live 31%; replay 34%) |

**C. Expectancy** — the only part that could justify keeping this as more than a defect fix. `R` is the reward-leg risk of each trade; costs are applied to **every** trade including scratches.

| verdict | condition |
|---|---|
| **SCREEN (n ≥ 100)** | net R/trade **≥ −0.05R** at the registered $0.20/side **and** decisive WR **≥ 40%** **and** B1–B3 hold **and** A still passes. A screen, not a pass. |
| **PASS (n ≥ 150, before the date gate)** | SCREEN conditions still hold **and** the Wilson 95% lower bound of decisive WR **> 40%** (≈ the 1:1.5 breakeven) **and** net R/trade **≥ 0.00R** at $0.20/side **and** **≥ −0.05R** at the measured $0.275/side **and** era drawdown **≤ $200**. |
| **KEEP, no edge** | SCREEN holds but PASS does not: keep the geometry, record that the strategy still has **no demonstrated edge**, and do not start another variable until an independent window is pre-registered. |
| **REVERT** | net R/trade **≤ −0.15R** at n ≥ 100; **or** era drawdown **> $250**; **or** average SL loss **> 2.2×** the pre-change average ($5.88 → $12.94); **or** **any** post-change stop inside its level after A1 was shown to work (a code regression); **or** **2+** post-change trades open across a daily/weekly closure (the §7 gap trigger — the guard must have failed). |
| **Cost override** | If the 14-day/two-weekend quote sample completes mid-window and the measured all-in round trip exceeds **$0.70**, re-run C at that measured cost **once**, in a dated amendment written before the re-run. Do not otherwise change the cost assumption inside the window. |

Report with `win_rate_report.py`, `pressure_report.py --root .`, and `strategy_lab.py --table --only structstop,structstop1.5` on the new window. No `exit_sims.py` / `pathwalk_sims.py` / `phantom_trades.py` result is admissible.

**If PASS:** the next isolation slot is an **independent forward window on the same unchanged strategy** to test durability — not another parameter. **If REVERT:** `git revert` the single commit, record the outcome in a dated REVIEW, and stop treating “wider stop” as a design goal in itself.

---

## 6. What this document does NOT do

- Does not place an order, switch to LIVE, or change `TRADING_MODE`.
- Does not change `SL_CLEAR_ATR` today. The engine is still on **0.5**.
- Does not waive the fired §7 gap trigger: the gap guard stays live, and the same 2-ride revert trigger is re-registered above.
- Does not authorise a second strategy variable, the 0.25 ATR level test, or any post-hoc threshold tuning.
- Does not replace `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` §7 for the **old** experiment; that judgement (SCREEN MET, PASS unavailable) is closed and stays closed.

---

## 7. Reproduction

```bash
python3 tools/strategy_lab.py --calib-only
python3 tools/strategy_lab.py --table --only baseline,structstop,structstop1.0,structstop1.5
python3 tools/stop_hunt_markout.py
python3 tools/check_structural_stop.py
python3 tools/check_gap_rides.py
python3 tools/live_readiness.py
python3 tools/smoke_test.py
```
