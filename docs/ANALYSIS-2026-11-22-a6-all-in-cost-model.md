# ANALYSIS 2026-11-22 — A6: the all-in cost model (spread + slippage + commission + swap)

**Queue step:** `docs/EXECUTION-PLAN.md` Track A, **A6** — *"Complete the cost model: measured all-in
round trip (spread + slippage + commission + swap), re-cost the ledger and canonical replay with a
sensitivity range, write a dated cost doc. Keep $0.40 registered until that analysis is complete."*

**Status of A6 after this doc:** the **analysis is DONE and the evidence class is resolved** — every
leg is now either *measured*, *computed from the captured spec*, or *explicitly declared
unobservable with a sensitivity range*. The **registered assumption is NOT replaced**:
**$0.40 round trip / `--cost 0.20` per side stays registered and binding**. Replacing it is an owner
decision (see §7), not something a tool may do on its own.

**Tool:** `python3 tools/cost_model.py` (new, read-only, stdlib only, never imports `engine.py`) and
`python3 tools/test_cost_model.py` (19 hermetic tests). Snapshot: `trades.csv` **998 closed trades**,
`xm_data/` **111 607 quote rows** through `2026-11-22 08:59:30 UTC`, struct-stop era **n=501**.

---

## 1. The four legs, and what each one actually is

| leg | value used | class | basis |
|---|---|---|---|
| **spread** | **$0.55** per round trip (median) | **OBSERVED** | the broker's own 30 s quotes joined to each trade's entry and exit (±75 s), via `xm_quote_report.trade_costs` — the same helper the quote report uses, so the two tools cannot disagree |
| **commission** | **$0.00** | **ASSUMED** | the captured account/symbol spec has no commission field; XM prices metals in the spread. Carried as a sensitivity (+$0.05 / +$0.10) rather than claimed as fact |
| **slippage** | **$0.02** per round trip (0.01 per side = one tick) | **ASSUMED** | the paper ledger books fill = stop/target price exactly, so slippage is invisible in the data. One 0.01 tick per side is the planning default; range 0.00 / 0.01 / 0.02 per side |
| **swap** | **−$2.66** for the whole book | **COMPUTED** | `swap_long −69.50` / `swap_short +15.07` points from the captured spec, ×0.01 per point at 0.01 lot, triple charge on the WED rollover (`swap_rollover3days = 3`, MT5 `ENUM_DAY_OF_WEEK`), and the rollover **instant** derived from the EU DST rule the logger confirmed (`broker_time.server_to_utc`) |

**All-in planning figure: $0.57 per round trip** (= 0.55 spread + 0.02 slippage + 0 commission), with
swap applied per trade rather than per round trip because it only exists when a position is carried.

### 1.1 The honest limit of this analysis

Commission and slippage **cannot** be measured from a quotes CSV. They are the difference between what
the broker quotes and what a real fill and a real statement would show. What this document does is stop
them being *silent*: each one now has a value, a class, and a sensitivity range, so no reader can mistake
a planning default for a measurement. **Only demo-account evidence (B5) or a real statement can promote
them to OBSERVED.**

---

## 2. Swap: the leg nobody had computed

Ten of 998 trades were carried through a broker rollover (988 were intraday). Itemised:

| trade | side | nights | swap | note |
|---|---|---|---|---|
| #95 | SELL | 3 | +$0.45 | weekend carry |
| #409 | BUY | 1 | −$0.70 | |
| #476 | SELL | 3 | +$0.45 | the 49 h weekend ride |
| #595 | BUY | 1 | −$2.08 | **includes the triple-Wednesday charge** |
| #610 | BUY | 1 | −$0.70 | |
| #687 | SELL | 1 | +$0.15 | |
| #815 | BUY | 1 | −$2.08 | **includes the triple-Wednesday charge** |
| #835 | SELL | 1 | +$0.15 | |
| #887 | SELL | 1 | +$0.45 | |
| #968 | SELL | 1 | +$0.45 | |

**Total −$2.66.** Two facts matter:

1. **It does not explain the deficit.** −$2.66 against a gross −$426.39 is 0.6%.
2. **It is both-sided.** Longs pay (−69.5 pts), shorts *earn* (+15.07 pts). So the SELL-heavy part of
   this book has a small structural tailwind that the paper engine never booked — which is exactly the
   kind of thing a "just subtract a flat spread" model hides.

**Convention, disclosed:** MT5 reports `swap_rollover3days = 3` = WEDNESDAY. This model charges the
night that **ends** at Wednesday 00:00 server. The alternative reading (the night that starts
Wednesday) differs only for a single-night carry across that boundary; on a −$2.66 total the ambiguity
is worth a few cents. `tools/cost_model.py` states the convention in its docstring and in the output.

---

## 3. Re-costed ledger (net USD; cost charged on **every** trade including scratches)

Whole book, **n=998** (420 with a measured spread, 578 falling back to the measured median because they
predate the quote logger — those are excluded from every share-of-1R figure):

| model | net $ | $/trade | R/trade |
|---|---|---|---|
| **$0.40 registered round trip** (no swap) | **−825.59** | −0.827 | −0.187 |
| all-in, 0.00 slip/side | −973.94 | −0.976 | −0.220 |
| **all-in, 0.01 slip/side (planning default)** | **−993.90** | **−0.996** | **−0.225** |
| all-in, 0.02 slip/side | −1013.86 | −1.016 | −0.229 |

Struct-stop era, **n=501** (420 measured):

| model | net $ | $/trade | R/trade |
|---|---|---|---|
| **$0.40 registered** | **−307.98** | −0.615 | −0.105 |
| all-in, 0.00 slip/side | −382.96 | −0.764 | −0.131 |
| **all-in, 0.01 slip/side** | **−392.98** | **−0.784** | **−0.134** |
| all-in, 0.02 slip/side | −403.00 | −0.804 | −0.138 |

`win_rate_report.py --spread` cross-check (round trip, no swap): **0.00 → −426.39 · 0.40 → −825.59 ·
0.55 → −975.29 · 0.57 → −995.25 · 0.70 → −1 124.99 · 1.00 → −1 424.39.** The cost model's −993.90 at
$0.57 sits $2.50 inside the flat-$ cross-check because swap is *signed per trade* (shorts earn).

**The direction of every correction is the same: the measured cost makes the book worse, never
better.** That is the property that makes this analysis safe — it cannot rescue an edge that is not there.

---

## 4. Cost as a share of the trade's **own** 1R

Measured on the 420 joinable trades (1R = |TP − entry| ÷ 1.5, the ratchet-safe definition):

| | p50 | p90 | max |
|---|---|---|---|
| spread only | 9.3% | 16.3% | 61.8% |
| **all-in** | **9.7%** | **17.0%** | **62.5%** |

The engine's live-path veto, `LIVE_COST_MAX_PCT_OF_R = 20%`, refuses **21 of 420** measured trades
(**5.0%**) at the all-in cost — close to the 2.9% it refused on the spread-only measurement in
`docs/ANALYSIS-2026-11-12-b4-live-order-safety.md` §3, and it now vetoes the same expensive tail slightly
earlier. **The veto's threshold is a live-path cost rule, not a pre-registered edge** (unchanged).

---

## 5. Break-even: there is no cost that makes this book pay

`win_rate_report.py --spread` reports the round-trip cost at which the book nets exactly $0. Both the
whole book and the structural-stop era print **`none (<0)`** — i.e. the book is **negative at zero cost**.
That is the single most important line in this document:

* the whole book is **−0.085R/trade at $0.00**;
* the struct-stop era is **−0.035R/trade at $0.00**;
* breakeven decisive WR at 1:1.5 RR is **40.0%**; the whole book is at **33.2% [29.7–36.9]** and the
  era at **36.9% (CI 32.1–42.0)** — the era's upper bound only just reaches the 40% mark.

**So the cost model does not turn a winner into a loser. The book is a loser before costs, and the
measured cost simply prices the hole.** A6 therefore answers the question it was given and closes the
door on a hope: no plausible spread, commission or swap assumption makes this strategy profitable.

---

## 6. What changed in the repo

| file | change |
|---|---|
| `tools/cost_model.py` | **new** — the four-leg model, sensitivity ranges, re-costed ledger/era, per-trade share-of-1R, itemised swap, and the break-even cross-reference. Read-only; never imports `engine.py`; never writes |
| `tools/test_cost_model.py` | **new** — 19 hermetic tests: leg classification, swap arithmetic incl. the triple day, the DST-driven rollover instant (the discriminating summer-vs-winter case), measured-vs-fallback separation, "all-in is never cheaper than spread", and the write/import bans |
| `tools/live_readiness.py` | `cost_model` evidence check now reads the dated doc; still **MANUAL** (a document cannot promote itself to a measurement) — see §7 |
| `readiness.py` | the completed-milestone list gains A6; the cost rows quote the measured $0.55 and the all-in $0.57 |
| `docs/EXECUTION-PLAN.md` | §3 A6 marked DONE-analysis / owner-decision-pending; §2g snapshot refresh |

**No trading rule, no parameter, no ledger row and no registered bar changed.** `SL_CLEAR_ATR` stays
0.5, `TRADING_MODE` stays `FORWARD_TEST`, `$0.40` stays registered, and no order path was touched.

---

## 7. The owner decision this leaves open

The measured all-in round trip is **$0.57**, not $0.40. Two things follow, and **neither is authorised
by "follow execution plan"**, because both change the yardstick every registered bar is measured against:

1. **Re-costing the registered bar.** `$0.40` was registered *before any quote existed*. Replacing it
   with $0.57 would make every net-R figure in the project worse (era −0.105R → −0.134R at $0.40 vs
   $0.57 per trade) and would move the A5 PASS/FAIL arithmetic. **This model recommends $0.57; it does
   not adopt it.** Until the owner records a decision, `$0.40` remains the number every document quotes.
2. **Whether the A5 bar should be re-read at the measured cost** at all, or judged as registered and the
   cost change carried forward to the next pre-registration.

Recommendation, for the record: **keep $0.40 registered for the current window (it is the more generous
number, so a FAIL under it is a safe FAIL) and pre-register $0.57 as the yardstick for any *future*
window.** The direction matters: judging on the cheaper assumption can only flatter the strategy, so a
bar that fails at $0.40 needs no re-reading at $0.57.

`live_readiness.py`'s `cost_model` check **stays MANUAL**. A dated document that says "slippage and
commission are unobservable here" is *evidence of the gap*, not evidence that closes it. The check can
only go PASS when demo fills (B5) or a broker statement supply the missing two legs.

---

## 8. Verification

```
python3 tools/cost_model.py                                  # the report above, exit 0
python3 tools/test_cost_model.py                             # 19 tests, OK
python3 tools/win_rate_report.py --spread 0.57                # flat-$ cross-check (-995.25)
python3 tools/strategy_lab.py --table --only structstop       # post-cutover −0.124R/t at $0.40 RT
python3 tools/xm_quote_report.py                              # measured spread leg, 420 joined trades
python3 tools/check_data.py                                   # 0 fail / 9 documented warnings
```

The two tools agree on the spread leg by construction (they call the same function), and the flat-$
cross-check agrees with the itemised model to $2.50 on a $994 deficit — a 0.25% difference, entirely
attributable to signed swap.

---

## 9. One-line answer for the plan

**A6's analysis is complete and its evidence class is resolved: spread measured ($0.55/side-pair median),
swap computed (−$2.66, both-sided), slippage and commission declared unobservable with sensitivities →
all-in ≈$0.57 round trip. $0.40 stays registered pending an owner decision. There is no cost assumption
under which this book pays: it is negative at $0.00.**
