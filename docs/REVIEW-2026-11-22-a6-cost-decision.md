# REVIEW 2026-11-22 — the A6 cost decision: $0.40 stays registered, $0.57 applies from the next window

**Owner decision (recorded this session):** *"go with your recommendation"* on the A6 choice left open in
`docs/ANALYSIS-2026-11-22-a6-all-in-cost-model.md` §7.

**The recommendation, as recorded:**

1. **`$0.40` round trip (`--cost 0.20` per side) remains the registered cost for the CURRENT
   `structstop1.5` window.** It is not replaced mid-window.
2. **`$0.57` round trip (`--cost 0.285` per side) becomes the registered cost for the NEXT window**,
   i.e. from the current window's date gate **2026-12-01 21:00 UTC** at the earliest — and it must be
   written into that window's pre-registration *before* its first trade.
3. **No registered bar, threshold, epoch or ledger row changes today.** Nothing is re-read at the
   measured cost.

This document is the amendment's record. It changes **documentation and visibility only** — no
`engine.py`, no parameter, no data.

---

## 1. Why $0.40 stays: the pre-registration already answered this

This is not a preference. `docs/PREREG-2026-10-26-structstop1.5.md` (SIGNED 2026-10-27, binding) contains
its own cost clause, §C row **"Cost override"**:

> *"If the 14-day/two-weekend quote sample completes mid-window and the measured all-in round trip
> exceeds **$0.70**, re-run C at that measured cost **once**, in a dated amendment written before the
> re-run. Do not otherwise change the cost assumption inside the window."*

Both conditions were checked against the A6 model rather than assumed:

| condition | value | verdict |
|---|---|---|
| quote sample complete (14 days / 2 weekends)? | **37 days / 4 weekends** complete | **MET** |
| measured all-in round trip **> $0.70**? | **$0.57** ($0.59 at two ticks of slippage, $0.67 even with a hypothetical +$0.10 commission) | **NOT MET** |

**The override does not fire.** Under the pre-registration's own words, the cost assumption inside this
window therefore does not change. Swapping in $0.57 now would be precisely the post-outcome re-cost that:

* §0 of the plan forbids (*"bypassing or retro-editing a pre-registration"*), and
* §1 forbids (*"never tune a threshold after seeing the outcome"*), and
* §2's freeze rule forbids (*"no second variable, no re-slicing of eras, no threshold tuning after
  looking at outcomes"*).

The measured figure is $0.17 *below* the pre-declared trigger. The repo deliberately set that trigger
where it did: a cost change large enough to be worth re-opening a window must be large. $0.57 is not.

### 1.1 The direction argument, stated plainly

$0.40 is the **more generous** assumption. A strategy judged at a cheaper cost than reality can only be
**flattered**. So:

* a **FAIL** at $0.40 is a *safe* FAIL — it stays a FAIL at any higher cost;
* a **PASS** at $0.40 is the only case that would need scrutiny, and it would need it at $0.57 before any
  conclusion is drawn.

That asymmetry is why keeping the cheaper number for the *current* window is the conservative choice, not
a lenient one. Nothing is being let off the hook; the harder number is simply applied where it is
scheduled to apply.

---

## 2. Why $0.57 is nevertheless adopted — for the next window

Ignoring a measured number indefinitely would be its own dishonesty. `$0.57` is now the repo's
**measured** all-in figure and the only defensible yardstick for a *new* pre-registration, because a new
window's bar is written before its first trade — which is exactly the condition that makes pre-registration
honest in the first place.

**Effective from:** the current window's date gate, **2026-12-01 21:00 UTC** (n=150 or date gate,
whichever comes first — `PREREG-2026-10-26-structstop1.5.md` §3). The next window's pre-registration must
state, before it starts:

* cost basis **$0.57 round trip = $0.285 per side**;
* the spread leg is **measured** ($0.55 median, 420 joined trades), the swap leg **computed**
  (−$2.66 book, both-sided), and the slippage/commission legs **assumed** — carried as a stated
  assumption with a sensitivity range, never as a measurement
  (`docs/ANALYSIS-2026-11-22-a6-all-in-cost-model.md` §1);
* that these three legs are the ones demo fills or a broker statement must eventually replace.

**Never** from this decision: $0.57 must not be applied retroactively to the current window's SCREEN or
PASS arithmetic, and no historical net-R figure is re-stated at it.

---

## 3. What is visible now (visibility, not mutation)

The tools keep their registered defaults — `strategy_lab.py --cost 0.20` and
`win_rate_report.py --spread 0.40` are **unchanged**, so no pasted command in any doc now reproduces a
different number. What changed is that the two costs are shown **side by side** so a later session cannot
mistake one for the other:

| where | what it shows |
|---|---|
| `readiness.py` `cost_basis` row (**new**) | which number is binding, why, and when the next one starts |
| `readiness.py` progress block | `assumed_cost_text` $0.40 **and** `next_cost_text` $0.57 from `next_cost_from` 2026-12-01 |
| `readiness.py` blockers | a **Rule** entry: no new reading at the measured cost until 2026-12-01 |
| `tools/cost_model.py` | already prints *"registered now: $0.40 … still binding"* and *"suggested: $0.57"* |
| `docs/EXECUTION-PLAN.md` | §2h records the decision; A6's row closes its owner-decision column |

This is the same pattern the repo used on 2026-10-30 for the never-rebaseline decision: state the number,
state its status, and make it impossible to apply silently.

---

## 4. What this decision does NOT authorise

* **No re-costing of the current window.** SCREEN (n=100) and PASS/FAIL (n=150 or 2026-12-01) are read at
  **$0.40 round trip ($0.20/side)** exactly as registered. A later session quoting a net-R figure "at the measured cost" as
  if it were the bar is wrong, and this document is the citation that says so.
* **No strategy change, deploy, or order.** `SL_CLEAR_ATR` stays 0.5, A2 stays host-blocked, `TRADING_MODE`
  stays `FORWARD_TEST`, the LIVE gate stays CLOSED at 17 PASS / 0 TODO / 3 MANUAL.
* **No promotion of `live_readiness.cost_model` out of MANUAL.** Slippage and commission are still
  unobservable from a quotes CSV; the A6 analysis documents the gap, it does not close it. Only demo fills
  (B5) or a broker statement can.
* **No new strategy variable.** The freeze on the current window is intact.

---

## 5. What would reopen the cost question inside the current window

Exactly one thing, and it is a number, not an opinion: **the measured all-in round trip rising above
**$0.70**.** Then the pre-registration's own clause applies — *"re-run C at that measured cost once, in a
dated amendment written before the re-run"*. Current headroom to that trigger is **$0.13** (23%).
Spreads would have to widen by roughly that much on a sustained basis (the p99 of the whole sample is
$0.58, the maximum $2.61 at the weekly open — a tail, not a regime).

---

## 6. Verification

```
python3 tools/cost_model.py        # "registered now: $0.40 … still binding"; "suggested: $0.57"
python3 readiness.py               # the new cost_basis row + the Rule blocker
python3 tools/win_rate_report.py --spread 0.40   # the binding view (unchanged)
python3 tools/strategy_lab.py --table --only structstop   # default --cost 0.20 (unchanged)
python3 tools/test_readiness_tab.py               # pins the new row/blocker wiring
python3 tools/handoff_check.py                    # FRESH; --cost blocks all still say 0.20
```

`sanity check on the freeze`: `grep -n "SL_CLEAR_ATR" engine.py` must still read `0.5`, and
`strategy_lab.CLEAR15_CUTOVER` must still be `None` (the window has not started).

---

## 7. One-line answer for the plan

**The owner's decision is recorded: the registered $0.40 round trip ($0.20/side) stays for the current
`structstop1.5` window because the pre-registration's own cost-override clause did not fire (measured $0.57
round trip ≤ the pre-declared $0.70); the measured $0.57 round trip ($0.285/side) becomes the registered
yardstick for the next window from 2026-12-01 21:00 UTC
and must be written into that pre-registration before its first trade. Nothing is re-read, re-costed or
deployed today.**
