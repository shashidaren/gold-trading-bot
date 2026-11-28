# Volume-spike localisation on the M5 → M1 step-down — analysis and verdict

**Date:** 2026-11-28
**Status:** **display-only, no `engine.py` / `trade_filter.py` change, no gate, no parameter, no new file written by any of this.**
**Owner ask:** "Analyse intraday volume spikes by stepping down from a 5-minute chart to a
1-minute chart to identify the exact price level where volume surges. Check whether the spike
occurs near a recent intraday swing high or swing low (which accounts for roughly 80% of such
spikes) and evaluate whether price penetration of a channel high or low likely triggered
algorithmic order flow."
**Tool:** `python3 tools/volume_spike_report.py` (read layer `volume_spike.py`, stdlib only,
no engine import, no writes; tests `python3 -m unittest tools.test_volume_spike` — 14 hermetic).
**Data:** `forward_test_log.csv` through `2026-11-27 19:39 UTC` (83,278 M1 bars; 14,963 complete
M5 buckets over 69 trading days from the MT5-sidecar era, 2026-09-10 onward). Ledger
`trades.csv`, struct-stop era (from `2026-10-06 03:00 UTC`), n=411 decisive.

---

## 1. The answer in one paragraph

Of the three claims in the ask, **two do not survive the data and one is real but smaller and
causally backwards from how it was framed**. (a) The feed **cannot** localise a spike to the
exact price print: inside a spiking 5-minute bucket the largest single minute carries a median
**23%** of the volume and never once (0 of 158) reaches 50%, so a "surge" here is a busy five
minutes, not a one-minute burst. (b) The "≈80% of spikes are near a swing" figure is
**a base rate, not a spike signature** — 84.2% of spikes are within 0.50 ATR of a confirmed
swing, but so are **88.8% of all ordinary buckets**; the lift is **−4.6pp**, i.e. spikes are
*slightly less* swing-anchored than random bars. (c) Channel penetration **is** associated with
spikes (**20.3%** of spikes newly break the 20-bar channel vs **8.4%** of all buckets,
**+11.9pp**) — but only **16.7%** of penetration bars carry a 90th-percentile volume versus
**10.0%** of ordinary bars (**+6.7pp**), and 30 minutes later the fade rate is 64.7% with a spike
vs 61.7% without. The break and the surge travel together; neither leads. **Verdict: no
level-localisation edge on this feed.** Volume stays context, display-only, exactly where
`docs/INDICATOR-AUDIT-2026-10-23.md` §4 Tier 1 left it.

## 2. What was already in the repo (so this is not re-derived work)

Nothing in the repo implements the step-down read. The adjacent, already-measured pieces are:

| Existing piece | What it covers | What it does **not** cover |
|---|---|---|
| `engine.py` `VOLUME_SPIKE_MULTIPLIER = 0.9`, `REQUIRE_VOLUME_CONFIRM = False` | volume gate, **off** | never localises, never tests swings |
| `tools/journal.py` "Volume vs 20-bar MA — participation" | entry-time volume bucket vs trade outcome | no M1 step-down, no swing, no channel |
| `docs/INDICATOR-AUDIT-2026-10-23.md` §2 | "spike >1.3x is the only p<0.05 in the lab" | measured against a **trailing 20-bar mean** — see §3 |
| `tools/strategy_lab.py` `sweep` variant, `pressure.box_geometry` | level *tests* and 20-bar channel breaks | no volume dimension at all |
| `chart.py` | M1/M5/M15 candles, box levels | deliberately no volume profile (tick volume ≠ traded volume) |

So the ask was genuinely open. This doc closes it.

## 3. A measurement trap found on the way (and why the audit's number is inflated)

`engine.py` logs `Vol_MA` as a plain 20-bar trailing mean of the tick count. Gold's tick volume
is not stationary across the session — median **79/min** in the late-session lull (22:00 UTC) vs
**367/min** in the NY overlap (14:00 UTC), a **4.6x** swing. A trailing mean therefore mixes
regimes: in the first minutes after a session open the mean is still made of the quiet hours,
and vice versa. Measured directly on the ledger:

| Entry-time volume basis | thin | normal | spike | spike vs thin |
|---|---|---|---|---|
| **Seasonal** (same weekday-class + minute, 14 prior days, day-normalised) | 24.1% (n=29) | 37.1% (n=326) | **41.1% (n=56)** | +16.9pp, Fisher **p=0.154** |
| **Naive** `5m volume / (Vol_MA × 5)` — the audit's basis | 22.2% (n=11) | 37.1% (n=532) | **40.9% (n=37)** | +18.7pp |

and spike-vs-normal is **+4.0pp, Fisher p=0.655** (seasonal) / +3.8pp (naive) on n=411 decisive.
The audit's "spike 45.0% vs thin 20.5%, p=0.031" pooled the whole book across eras and compared
the two extreme tails of a *trailing* mean; with a seasonally-correct baseline and the live-era
sample, **the participation gap is not statistically distinguishable from zero**, and the
spike-vs-thin gap fails its own 5pp+side-split adoption bar (`p=0.154`, and see the side split
below). The participation hint is weaker than the docs currently imply.

**Side split** (the repo's §8 trap — never pool sides without naming it):

| | spike | normal | thin | p |
|---|---|---|---|---|
| BUY | **47.8%** (n=23) | 32.3% (n=130) | 11.8% (n=17) | **0.020** |
| SELL | 36.4% (n=33) | 40.3% (n=196) | 41.7% (n=12) | 0.743 |

The whole effect is a **BUY-side, NY-session artefact**: 51.8% of era spikes sit in Asia, where
the live-era entry read shows spike-vs-normal at **−4.0pp** (34.5% vs 38.5%); the positive gap
appears only in NY (50.0% vs 37.5%, +12.5pp, n=18) on 18 trades. That is a session/regime proxy, not participation, and it is exactly the kind of
result the pre-registration bar exists to stop.

## 4. The step-down: can a 5m spike be pinned to one minute / one price?

Measured over 14,888 complete buckets (λ ≥ 50 ticks):

| measurement | value | meaning |
|---|---|---|
| observed within-bucket sd | 29.4 ticks | |
| Poisson-predicted sd (√λ) | 15.1 ticks | |
| **dispersion ratio** | **1.95x** | real sub-5m structure exists |
| largest minute's share of the 5m volume | median **23%**, p90 27% | but it is *diffuse*, not a burst |
| spikes where one minute carries ≥50% | **0 / 158** | the surge is spread over the five minutes |
| penetration spikes whose top-volume minute holds the extreme | **34.4%** (11 of 32) | worse than any of the five minutes "winning" at random (20%) only because the extreme is usually in the bucket at all |

**Conclusion:** the 1-minute chart can tell you *that* five minutes were busy. It cannot tell you
*which* minute, and therefore cannot identify "the exact price level where volume surges" on this
feed. This is a property of MT5 tick counts (a tick is a price update, not a trade, and XM's
pipeline stamps them across the minute), not of the analysis.

## 5. Swing proximity — the "≈80%" claim is a base rate

Method: fractal pivots (`k=2`, i.e. a high must exceed two bars either side), used **past-only**
(a pivot is readable only after it confirms, so there is no look-ahead); "near" = the swing price
sits within the bar's range or within *tolerance* × M5-ATR of it; window = 4 h (48 M5 bars).

Two distance definitions were run, and they agree on the sign at every tolerance:

**A. Range overlap** (the tool's `nearest_swing`): the swing price is inside the bar's high-low
range, or within *tolerance* × ATR of the nearer extreme — "did this surge print *at* the level?"

| tolerance | spikes near a swing | **all buckets** near a swing | lift |
|---|---|---|---|
| 0.25 ATR | 81.6% | 81.7% | **−0.1pp** |
| 0.50 ATR | **84.2%** | **88.8%** | **−4.6pp** |
| 0.75 ATR | 87.3% | 92.3% | **−5.0pp** |
| 1.00 ATR | 89.2% | 94.2% | **−5.0pp** |

**B. Like-for-like** (high-to-high and low-to-low only — "is this surge at the same *sort* of
level?")

| tolerance | spikes near a swing | all buckets near a swing | lift |
|---|---|---|---|
| 0.25 ATR | 46.8% | 53.1% | **−6.2pp** |
| 0.50 ATR | 61.4% | 72.7% | **−11.3pp** |
| 0.75 ATR | 67.7% | 81.8% | **−14.1pp** |
| 1.00 ATR | 75.3% | 86.9% | **−11.6pp** |

The headline "~80%" is reproducible — 84.2% under definition A at 0.50 ATR — but it is the **base
rate of standing near a swing** on a tape that prints a confirmed pivot every ~8 bars in a 48-bar
window. The tool prints the control row beside every spike row for exactly this reason. A spike is
not "attracted to" a swing; it is marginally *less* likely to be sitting on one, which is what you
would expect if the surge is often the bar that *creates* the next pivot.

## 6. Channel penetration and the algorithmic-flow question

**Definition:** the channel is the prior 20 completed M5 bars (mirrors `engine.LOOKBACK_PERIOD`);
a penetration must be *new* (previous bar inside), clear 0.10 × ATR, and its depth is measured to
the level.

| | penetration |
|---|---|
| spikes that newly break the 20-bar channel | **20.3%** (32/158; 21 up, 12 down) |
| all buckets | 8.4% |
| lift | **+11.9pp** |
| median depth | 0.57 ATR (p90 2.6 ATR) |

That is the one genuine association in the ask. But the causal story ("the penetration triggered
algorithmic order flow") requires the break bar to be the loud one:

| volume percentile (vs trailing 100-bar median) | penetration bars | ordinary bars | lift |
|---|---|---|---|
| ≥ p90 (1.69x) | **16.7%** | **10.0%** | +6.7pp |
| ≥ p95 (1.93x) | 8.6% | 5.0% | +3.6pp |

n = 1,255 penetration bars vs 13,708 ordinary. A break bar is modestly louder than a normal bar —
consistent with "breaks happen when the tape is busier", not with "a break summons a burst". If
the channel break were the trigger, the break bar would sit in the top decile far more than one
time in six.

**Follow-through** (30 min, `back_inside` = price closes back inside the broken channel):

| | n | closed back inside | median MFE / MAE (ATR) |
|---|---|---|---|
| penetration **with** a volume spike | 17 | 64.7% | 2.96 / 0.58 |
| **all** penetrations | 776 | 61.7% | 2.05 / 0.54 |

Δ = +3.0pp on n=17. This is the repo's already-measured "~74–75% of breaks close back inside
within 15 min" (`docs/ANALYSIS-2026-10-20-box-theory-manual-trading.md`); the spike subset does not
change the fade. **No fade edge, and no continuation edge, attributable to volume.**

## 7. What this means for the bot — nothing changes, and why

* **No gate.** `REQUIRE_VOLUME_CONFIRM` stays `False`; `VOLUME_SPIKE_MULTIPLIER` stays `0.9`.
  A volume gate would need (i) a dated pre-registration, (ii) a lift that survives the side split
  and the session control, and (iii) a costed `strategy_lab.py --table` run. None of the three
  exists, and the honest measurement in §3 moves *away* from one.
* **No new indicator.** Volume remains **context**, per `docs/INDICATOR-AUDIT-2026-10-23.md` §4
  Tier 1: "keep as context in the Journal tab; do not build a VWAP gate". This analysis does not
  promote it and does not demote the ATR-percentile hint beside it.
* **The one thing worth queuing.** The penetration association (+11.9pp) and the 1.95x
  dispersion are the first evidence that *something* is measurable at M1 beyond the bar close.
  The right way to test it is **not** on 69 days of this log but on the large-N MT5 history dump
  already queued as **A9 / E1** (`tools/mt5_history_dump.py` → `tools/history_to_log.py` →
  `strategy_lab.py --bars` / `goldbot --bars`). This doc adds one candidate to that queue and
  does not create a new step: see `docs/EXECUTION-PLAN.md` §3 A9 (E1) — unchanged.
* **A warning for future sessions.** Any future "volume spike" number in this repo should be
  computed against `volume_spike.session_profile`, not `Vol_MA`. The two bases disagree on the
  significance of the same effect (§3).

## 8. How to reproduce

```bash
python3 volume_spike.py                          # the verdict, six bullets
python3 tools/volume_spike_report.py             # the full tables above
python3 tools/volume_spike_report.py --spikes 20 # the step-down detail, largest spikes first
python3 tools/volume_spike_report.py --json      # machine-readable (dashboard-ready)
python3 tools/volume_spike_report.py --threshold 1.3   # looser spike definition
python3 -m unittest tools.test_volume_spike      # 14 hermetic tests
```

Numbers in this doc were produced on collection 612 (`forward_test_log.csv` through
`2026-11-27 19:39 UTC`). A later log will move them slightly; the **signs** — negative swing lift,
positive penetration lift, no causal ordering — are the claims, not the decimals.

## 9. The 14 things the tests pin

1. A monotone session shape is **not** a spike under the seasonal baseline, while the naive
   `Vol_MA` basis calls every one of them a spike (the trap in §3).
2. Pre-2026-09-10 vendor bars can never enter a ratio.
3. A partial bucket is never judged — a feed gap must not manufacture thinness.
4. The baseline is strictly past-only: a repeat of an anomaly becomes the baseline.
5. Pivots need `k` bars each side and cannot be read before they confirm.
6. "Near a swing" is distance from the swing price to the bar's range: zero when the bar trades
   through it, and *not* zero when it merely comes close to the other extreme.
7. A penetration must be new (previous bar inside), must clear the ATR floor, and a bar that
   broke nothing returns `back_inside=None` — never `False`, which would pad the fade denominator.
8. An incomplete forward window is not judgeable.
9. The report always carries a base rate **and** a lift beside the spike rate.
10. The verdict names the base-rate trap.
11. The feed-resolution block is present and its `localised` flag is a real boolean.
12. The closing verdict is **derived** from the numbers (a `>=10pp` lift on `>=30` spikes plus
    localisation), so an edit that improves the data must change the sentence the tool prints.
13. The report is JSON-safe end to end.
14. A flat tape produces no spikes at all.

## 10. Unchanged, explicitly

`SL_CLEAR_ATR = 0.5`; `strategy_lab.CLEAR15_CUTOVER = None`; `BE_TRIGGER_R = 0.75`;
`RR_TARGET = 1.5`; `MAX_HOLD_MINUTES = 240`; `REQUIRE_VOLUME_CONFIRM = False`;
`VOLUME_SPIKE_MULTIPLIER = 0.9`; `TRADING_MODE = "FORWARD_TEST"`; the registered **$0.40**
round-trip cost; the LIVE gate (17 PASS / 0 TODO / 3 MANUAL, **CLOSED**); every paper trade and
ledger row. No orders, no deploy, no arming, no broker connection, no second strategy variable.
