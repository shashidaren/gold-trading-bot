# REDESIGN 2026-10-23 — the v1 post-mortem, and the v2 harness

**Status:** the owner gave a free hand to redesign and to remove the scalper tab.
**Scope of what actually changed:** dashboard + new package + docs. **`engine.py` and
`trade_filter.py` are byte-identical** — see §3 for why that was the constraint that
shaped everything else.
**Every number below was recomputed in this session** from the checked-in ledger and
log (collection 326, last log bar 2026-10-23 17:59 UTC). Reproduce with the commands
in §8.

---

## 1. The question that started this

> "I'm doubting if the gold bot trading will actually work given gold's volatility."

The doubt is right. The diagnosis is not, and the difference matters because it decides
what to fix.

### Volatility is not what is hurting the book

Every struct-stop-era trade bucketed by ATR at entry (`tools/journal.py --era structstop`,
costed at the measured $0.55):

| ATR at entry | n | W | L | BE | decisive WR | gross | net | net/trade |
|---|---|---|---|---|---|---|---|---|
| **< 1.2 (quietest)** | 18 | 2 | 12 | 4 | **14.3%** | −40.62 | −50.52 | **−2.81** |
| 1.2 – 1.4 | 46 | 19 | 14 | 13 | 57.6% | +61.37 | +36.07 | +0.78 |
| 1.4 – 1.7 | 46 | 12 | 21 | 13 | 36.4% | +0.24 | −25.06 | −0.54 |
| 1.7 – 2.0 | 37 | 13 | 14 | 10 | 48.1% | +38.44 | +18.09 | +0.49 |
| ≥ 2.0 (most volatile) | 52 | 9 | 29 | 14 | 23.7% | −120.56 | −149.16 | −2.87 |

The **quietest** bucket is the worst on the board, tied with the most volatile. And
none of it holds up: Fisher exact gives quiet p=0.080, volatile p=0.051, and the one
significant bucket (1.2–1.4, p=0.013) does not survive a BUY/SELL split (p=0.294 within
BUY, p=0.373 within SELL). BUY vs SELL overall is p=0.492.

So the honest statement is stronger than "volatility isn't the cause": **with 199 trades
you cannot establish any reliable relationship between gold's volatility and this bot's
win rate, in either direction.**

### What volatility actually does — it is a geometry problem

Gold's volatility forces the stop into a shape that makes a fixed dollar cost enormous:

```
median risk per trade       $3.94    (on a $4,000 instrument = 0.099% of price)
round trip (measured)       $0.55    = 14.0% of that risk
break-even decisive WR      40.0% cost-free  ->  43.2% after cost
```

A 20-bar M1 box on gold is ~$7 wide. A stop that tight *has* to be tight or noise takes
it. Volatility did not make the signals worse — **it made the stops expensive.** And that
has a clean escape hatch, because the cost is fixed in dollars while risk scales with the
timeframe (live boxes from `tools/box_report.py`, 2026-10-23 17:59 UTC):

| geometry | risk | round trip as % of R |
|---|---|---|
| 20-bar M1 box, BUY | $2.82 | **19.5%** |
| 1h box, BUY | $3.13 | 17.6% |
| median v1 trade | $3.94 | 14.0% |
| **4h box, BUY** | $26.34 | **2.1%** |
| prior-day box, BUY | $127.15 | 0.4% |

### The thing that is actually fatal

Direction. After a full 8/8 v1 signal the tape goes the trade's way **49% [41–57]** at
30 minutes (`docs/ANALYSIS-2026-10-19-signal-outlook.md`), and the target prints before
the stop in about a third of decisive races against the 40% the 1:1.5 geometry needs.

And no exit can rescue it. `tools/pathwalk_sims.py`, sequence-aware over all 696 trades:

```
TP 1.5R, no BE ratchet at all      37.8% win   -$150.97
TP 1.5R, BE at +0.75R (current)    25.0% win   -$381.77
TP 1.5R, BE at +0.30R (old)         6.2% win   -$633.72
TP 2.00R, no BE                    32.5% win      +$2.93   <- best cell in the whole grid
```

The best exit configuration buildable on these entries makes **+$2.93 over 696 trades
before cost.** At $0.55 a trade that is roughly −$380 after.

Where the era's money went (199 trades):

```
TP    n=55 (27.6%)  gross +472.08   cost  -30.25
SL    n=90 (45.2%)  gross -533.69   cost  -49.50
BE    n=53 (26.6%)  gross    0.00   cost  -29.15   <- zero upside, full cost
TIME  n= 1 ( 0.5%)  gross   +0.48   cost   -0.55
TOTAL               gross  -61.13   cost -109.45   net -170.58
```

**Cost is 1.8× the gross loss.** Gross, the strategy is nearly break-even (−$0.31/trade).
Cost is what turns it into −$0.86/trade.

> One number here was nearly reported wrong and is worth recording. A max-favourable-excursion
> walk put the BE ratchet's cost at $237.70 of forgone profit. An MFE walk cannot tell you
> whether the target printed *before* the stop came back, so the figure was unsafe. The
> sequence-aware replay prices the same question at **$230.80** (−$150.97 with no ratchet
> vs −$381.77 at 0.75R) — close, but the tool's number is the one to quote.

**The chain:** no directional edge at entry → no exit geometry can create one → cost then
guarantees the loss. Volatility appears nowhere in it.

---

## 2. What was deleted

The owner: *"probably don't need the scalper tab any more."* Removed, with the measured
reason rather than just the request — the scalper's own chart layer carries the finding
that tight manual gold scalps lose on cost alone (`chart.py`), and the ledger puts the
round trip at 14.0% of the median risk, 19.5% on 20-bar box entries.

| removed | why |
|---|---|
| `manual_scalp.py` (332 lines) | calculator + journal store for the deleted page |
| `scalp_template.py` (365 lines) | its HTML |
| `docs/MANUAL-SCALPING.md` | operating guide for a page that no longer exists |
| `tools/test_manual_scalp.py`, `tools/test_scalp_dashboard.py` | tests for the above |
| 4 `/scalp*` routes + nav link + 108 lines of `dashboard.py` | the page itself |
| `GOLD_MANUAL_JOURNAL_FILE` | read by nothing now |

`dashboard.py` is 2,298 → 2,178 lines. It has **no write route at all** now, which is a
simpler invariant to hold than "every panel is read-only except this one page."

A host-local `manual_scalp_journal.json` on the server is orphaned, not migrated. It was
self-reported, never broker-verified, and the docs already said it was not evidence.

`tools/autosync.sh` was updated in the same commit: `DASH_CHANGED` now watches
`dashboard.py pressure.py chart.py goldbot/`. Without that edit a `git diff` pathspec
would name files that no longer exist.

---

## 3. What was deliberately NOT touched

This is the constraint that shaped the redesign, so it is stated before the new code.

| frozen | why |
|---|---|
| `engine.py`, `trade_filter.py` | Live at `/opt/gold` as the `goldbot` systemd unit. Mid-experiment: the structural-stop gate was judged 2026-10-19, the §7 closure-gap trigger **fired 2/2**, and the pre-registered response (REVERT with a gap guard first) is blocked on an owner-defined rule. Rewriting the engine would destroy the forward-test history *and* invalidate the gate. |
| `pressure.py` | A systemd sidecar (`deploy/boxalert.service`) imports it. Also the read layer for four dashboard tabs, with thresholds pinned to the engine by `tools/smoke_test.py` Scenario U. |
| `tools/strategy_lab.py` | Canonical for **v1** rules. A v1 rule change must still be judged with it. |
| `trades.csv`, `forward_test_log.csv` | The evidence. |

So v2 is **additive**: a separate package that cannot reach the engine, plus deletions the
owner asked for. There is no code path from `goldbot/` to an order.

---

## 4. What was built: `goldbot/`

A modular, **pure-stdlib** package. Stdlib is not an aesthetic choice: this sandbox has no
`requests`, no `dotenv`, no `flask`, no `pandas` — so v1's `engine.py` cannot even be
imported here. Every v2 test runs anywhere Python 3.11 does.

```
goldbot/
  config.py       one frozen dataclass; every knob named; two configs can coexist so an
                  A/B is a value, not a code edit
  data.py         Bar + loader + timeframe aggregation
  indicators.py   EMA/SMA/ATR/RSI/slope as pure functions (simple means, matching v1)
  signal.py       the entry hypothesis, swappable; `trend_pullback` is the default
  risk.py         stop placement, the cost floor, lot sizing
  portfolio.py    one position, cooldown, daily loss cap — and nothing else yet
  replay.py       the costed, stateful backtest + the verdict
  __main__.py     CLI: python3 -m goldbot --compare
  tests/          64 hermetic unittest tests
```

### Four decisions that carry the analysis

**a) Timeframe is the primary knob.** `Config.timeframe_minutes` defaults to 240. At $26 of
risk the round trip is 2.1% of R instead of 19.5%. This is the only lever §1 found with a
measured payoff.

**b) An explicit cost floor that REFUSES trades.** `min_risk_to_cost = 20.0`, so any setup
whose risk is under $11 (20 × $0.55) is rejected and *counted*. v1 had no such rule; its
median trade was 7.2× and its 20-bar box entries 5.1×. This is the guard v1's ledger says
it needed, and the refusal counter is the direct measure of whether a timeframe is
tradeable at all.

**c) The structural stop, kept.** `stop_clear_atr = 0.5` beyond the level the trade's
premise rests on — the one v1 rule with a clean measured justification (63.8% of its stops
sat *inside* the tested level; median stop lifetime 7.2 min of a 240-min budget). Plus
`min_stop_atr = 1.5` as a floor, so a quiet tape cannot produce a stop the cost eats.
Every trade records which of the two bound (`level` vs `atr_floor`), because a book whose
stops are all ATR-floor-bound is a book whose levels are not being used.

**d) The entry is a named hypothesis, not a claim.** `trend_pullback` is documented in
`signal.py` as the hypothesis the v1 evidence *points at* — higher timeframe, with-trend
(side ≈ momentum is the one relationship that replicated: BUY 92% of signals in a rising
tape, SELL 93% in a falling one), entering on a pullback to the edge rather than on a
break (74% of breaks fail within 15 min, while the edge is the one thing boxes are
genuinely good for: putting a stop behind). It is not presented as an edge, and the
verdict line says so.

### Conventions a number can be trusted by

Stated in `replay.py` and each one tested:

* closed bars only — a signal is read on a bar that has finished, entry at its close
* one position — the convention every honest number in this repo is computed under
* **stop before target within a bar** — conservative, and the same rule
  `tools/pathwalk_sims.py` uses, so the two are comparable
* cost on every closed trade, **scratches included** — the v1 BE bucket booked $0.00
  gross and paid $29.15
* every rate printed with a Wilson interval and against the costed break-even

### Bugs the tests caught (both would have shipped)

1. **`warmup_bars()` ignored the ATR period.** ATR came back `None`, `risk.place` refused
   with "no ATR", and the replay reported **zero trades with a straight face**. Pinned by
   `test_warmup_covers_every_indicator_the_signal_reads`.
2. **The costed break-even formula was wrong.** My first version returned 0.4558 at v1's
   median risk; the ledger says 43.2%. The correct form is
   `p = (risk + c) / (risk·(1+rr) + c)` — cost is charged against the round trip, not
   against the winner's reward as well. The two tempting shortcuts give 0.4558 and 0.4289
   and quietly move the bar by 2.4pp. Pinned by `test_cost_raises_the_bar`.

---

## 5. The first result — and it is not the one anyone wants

```
$ python3 -m goldbot --compare
  tf       bars  trades   dec      WR  med risk   cost %R      net  net/trd
  15m      3466       3     2   50.0%     13.94      3.9%    +7.43    +2.48
  1h        878       0     0       -      0.00        -    +0.00    +0.00
  4h        239       1     0       -    111.56      0.5%   -56.50   -56.50
  24h      —          skipped: only 46 bars (needs > 50 before the slow EMA exists)
```

**Four trades in 52 days.** The harness works; the tape cannot judge it. This is the same
wall the repo already hit from the other side — `tools/box_report.py` notes that the H1/H4
box a trader would actually draw yields ~1 setup per day and "CANNOT be measured from this
log."

Two things the run *does* establish:

1. **The cost thesis holds mechanically.** 3.9% of R at M15, 0.5% at H4, against v1's
   14.0–19.5%. The cost floor fired and its refusals are counted, not hidden.
2. **The binding constraint on v2 is sample size, not cost.** Which means the large-N path
   is not optional any more: `tools/mt5_history_dump.py` → `tools/history_to_log.py` →
   `python3 -m goldbot --bars history_utc.csv`.

Relaxing the parameters to confirm the plumbing produces trades (this is hypothesis
*generation*, not evidence, and must not be quoted as a result):

```
$ python3 -m goldbot --timeframe 60 --lookback 10 --wick 0.25 --ema-fast 10 --ema-slow 30
  trades 9   decisive 5   (1W/4L/4 scratch)   20.0% WR [3.6-62.4]
  median risk $25.99   cost 2.1% of R   net -66.07 (-7.34/trade)
  stop basis: atr_floor=5  level=4
```

---

## 6. The bar a v2 hypothesis must clear

Written before any further tuning, because the alternative is the thing v1's funnel
became — a level gate that is TRUE on 86.9% of bars and selects for almost nothing.

A v2 hypothesis is worth deploying only if, on **converted broker history** (not this
52-day log), all of the following hold:

1. **n ≥ 100 decisive trades**, and the Wilson **lower bound** on the decisive win rate
   clears `breakeven_wr_after_cost(median risk)` — not the cost-free 40%.
2. **Median cost ≤ 5% of risk.** If it is not, the timeframe is wrong and nothing else
   matters.
3. **The same direction within BUY and within SELL.** No pooled-only gaps. (Every lab
   indicator v1 measured failed exactly here.)
4. **A chronological holdout** that was not used to choose the parameters.
5. **Net R/trade > 0 after cost**, with worst-loss and drawdown reported alongside —
   not win rate alone.

Anything less is a hypothesis to pre-register, never a rule to ship. And per the standing
guardrails: one variable per forward-test window, no tuning after seeing the outcome, and
nothing goes live without a separate explicit owner decision.

**What v2 does not authorise:** an engine change, a revert of the structural stop, a
parameter flip on replay evidence, or treating §5's four trades as a signal of anything.

---

## 7. What is still open

| item | state |
|---|---|
| Structural-stop revert + gap guard | **Blocked on the owner** — the cutoff/schedule-source/open-position policy is undefined. Unchanged by this session. |
| Broker-clock / DST | Unverified; the discriminating window is 2026-10-25 01:00 UTC → 2026-11-01 06:00 UTC. Re-check from observed offsets. |
| Quote-cost sample | Logger at 9/14 complete UTC days, 1/2 weekends, median $0.55. The registered assumption stays $0.40 until the target is met. **v2 defaults to the measured 0.55** because cost is the thing it is designed around; costing it optimistically is how the problem stayed invisible. |
| Large-N history | **The next real step for v2.** Without it §5 cannot be extended. |
| v2 has no live runner | Deliberate. It is a replay harness. A paper loop would need the MT5 feed and an operator decision. |

---

## 8. Verification

```bash
python3 -m unittest discover -s goldbot/tests -t .   # 64 tests, OK
python3 -m goldbot --list
python3 -m goldbot --compare
python3 -m goldbot --timeframe 60 --lookback 10 --wick 0.25 --ema-fast 10 --ema-slow 30
python3 -m py_compile dashboard.py                    # the scalper excision compiles
python3 tools/handoff_check.py                        # structure + dangling-reference check
python3 tools/journal.py --era structstop             # §1 tables
python3 tools/pathwalk_sims.py                        # §1 exit grid
python3 tools/box_report.py --root .                  # §1 cost/risk geometry
```

`git status`: the deletions, `dashboard.py`, `tools/autosync.sh`,
`tools/test_dashboard_context.py`, `README.md`, `docs/AUTOSYNC.md`, `docs/HANDOFF.md`
and the new `goldbot/` package. `engine.py`, `trade_filter.py`, `pressure.py` and
`tools/strategy_lab.py` are unmodified — verify with `git diff --stat main`.

**Not verified in this sandbox, and stated plainly:** the Flask dashboard routes
(`tools/test_dashboard_context.py` needs Flask, which is not installed here) and
`tools/smoke_test.py` (needs `requests` + `dotenv` for the engine import). The dashboard
change was checked by `py_compile` and by a grep showing zero residual `/scalp`
references; it was not rendered.
