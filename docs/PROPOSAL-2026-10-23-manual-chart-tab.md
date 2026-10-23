# PROPOSAL 2026-10-23 — a chart tab for manual gold trading

**Status: BUILT the same day (see §0) — display-only, not deployed, no gate or
parameter touched.** §1–§9 are the reasoning that produced the build; §0 records
what actually shipped and what was deliberately cut. Every number below is from
this checkout and reproducible — commands are in §9. **Later same-day follow-up:**
the deferred manual logger is now built as the separate `/scalp` workspace and its
own host-local journal; this Chart & Placement tab remains read-only. See
`docs/MANUAL-SCALPING.md` and HANDOFF §1/§6.

---

## 0. What shipped (2026-10-23, same session)

The owner's answer to the open questions was **"you recommend — I have never used
any tools before."** That settles every one of them, so they were decided rather
than asked again:

| Question | Decision | Why |
|---|---|---|
| Default timeframe | **M5** (140 bars ≈ 11.7 h), toggle `?tf=1|5|15` | An M1 gold chart is 4-ATR noise — the box doc's own finding — and would make every level look meaningless. M15 is one click away. |
| Tier 3 (Fibonacci/pivots/round numbers) | **Excluded for now** | A beginner cannot calibrate a subjective tool, and drawing an unmeasured one teaches them to trust it. Pivots and round numbers remain the best *next* candidates for a real `strategy_lab.py --bars` test. |
| Manual-trade logging | **Built later in `/scalp`** | The owner approved a separate workspace. Its schema and atomic host-local journal are in `docs/MANUAL-SCALPING.md`; this chart tab still writes nothing. |
| Draw the open paper trade | Deferred | Nothing open in the current ledger; it is a small follow-up when there is one. |

**Files:** `chart.py` (new, stdlib-only read layer), `dashboard.py` (tab + route +
`chart_context`), `tools/test_manual_chart.py` (32 hermetic tests),
`tools/test_dashboard_context.py` (chart-tab render test), `README.md`,
`docs/HANDOFF.md` §1/§6/§9.

**What the tab does, top to bottom:** plain-English verdict → candle chart
(M1/M5/M15) with the same `pressure.box_geometry()` levels, session bands,
blackout shading, current price and off-range level arrows → **where the trade
would go** (entry / stop / target / risk / reward / R:R / spread-share per side,
badged SKIP or WATCH) → **the cost ruler** → "new to charts?" teaching block →
measured footer.

**Two design decisions worth reviewing:**

1. **The placement card is built on the tightest usable box, not the nearest edge.**
   On live data the nearest edge belonged to the prior-day box — 71 ATR wide, i.e.
   a **$105 stop**. Printing that would have been accurate and useless. `chart.pick_box()`
   refuses boxes wider than 20 ATR and the card says what it skipped and why.
   The geometry maths still comes from `pressure.box_watch_cards()` (called with a
   narrowed geometry), so the two tabs cannot disagree about where a box is.
2. **A card is never `ready` on bad geometry.** Sub-1R targets and spreads over 10%
   of R are stated as reasons, not footnotes. On the shipped snapshot *both* sides
   read SKIP — 0.86:1 and a 4% spread — which is the honest answer, and a better
   teaching example than a green light would have been.

**Not done, on purpose:** nothing was deployed, `engine.py` and `trade_filter.py`
were not touched, `pressure.py` was not touched (so Scenario U's mirror pinning is
unaffected), and no number in this doc was re-judged.

**Owner ask:** *"Gold traders use charts to place trades, with multiple tools for
higher accuracy. List the most effective ones we can add to a new tab on the
existing dashboard, represent them graphically, summarise so it's easy to
understand, and advise where to place trades."*

---

## 1. The constraint that decides the answer

The dashboard is **display-only** (HANDOFF §1, `docs/ANALYSIS-2026-10-16-dashboard-pressure.md`).
It must never import `engine.py`, must never place an order, and must never turn
a colour into a forecast. So the question is not *"which indicators look
impressive"* — it is *"which tools genuinely change where a human puts their stop
and target, and which do we have data to draw honestly?"*

Three of this repo's own findings shape the list, and they all point the same way:

| Finding | Source | What it rules out |
|---|---|---|
| Box breakouts and fades have **no edge**: 8 geometries across 2 box sizes, **0** cleared the driftless reference; 74–75% of breaks close back inside within 15 min | `ANALYSIS-2026-10-20-box-theory-manual-trading.md` §2 | Any panel that says "breakout = BUY". Boxes are location, not signal. |
| The 8/8 signal has **no directional edge**: 50.4% [42–59] trade-way at 30 min, median **+0.02R** | `ANALYSIS-2026-10-19-signal-outlook.md` | A "signal strength" score dressed up as probability |
| The pressure composite is **collinear with side** at n=160 (BUY 67 aligned / 4 mixed, SELL 86 aligned / 3 mixed) | `ANALYSIS-2026-10-16-dashboard-pressure.md` | A momentum gauge presented as independent evidence |
| **Cost, not entries, kills tight setups**: at the measured $0.55 round trip a 1-ATR stop pays **37% of R** in spread | §7 below, this doc | Ignoring geometry — the single most expensive mistake in manual gold scalping |

**Therefore the tab's job is placement and risk, not prediction.** That is not a
compromise — it is what the tools that actually earn their keep do. A trader's
edge in a 1.5:1 system at this spread comes from *not taking bad geometry*, and
that is exactly what a chart plus a cost ruler makes visible.

---

## 2. The tools, scored

Score = how much it changes a real placement decision × how honestly we can draw
it from data already in `forward_test_log.csv`.

### Tier 1 — build these (the tab is not worth building without them)

| # | Tool | Why it earns the space | Data we already have | Honesty risk |
|---|---|---|---|---|
| 1 | **Candlestick chart** | The dashboard has **no price chart at all** today — it is cards and tables. Everything else hangs off this. | `Timestamp,Open,High,Low,Close` | none |
| 2 | **Structural levels + boxes** (20-bar engine level, 1h, 4h, prior day) | This *is* the bot's stop logic, and the box doc's verdict is that the box is "a fine place to put a stop". | `pressure.box_geometry()` — already computed, already rendered as numbers | Must be labelled "location, not signal" |
| 3 | **Placement bands** — entry / stop / target drawn as zones on the chart | Turns three numbers into a picture. This is the direct answer to "where do I place it". | `box_watch_cards()` gives entry/stop/target/RR/cost-share per side | Must read "if you take it", never "take it" |
| 4 | **Cost ruler** — spread as % of R, live | **The most valuable unique thing we can add.** No retail indicator shows it, and it is the reason most tight-stop gold trades lose. | `ATR` + `$0.40`/`$0.55` cost constants | none — it is arithmetic |
| 5 | **Session + blackout shading** | The bot's own blackouts (07:55–09:00 BUY-only, 12:25–12:45, 13:25–15:15, 21:45–22:30 both sides) and the 20:58–22:00 daily break are invisible on a naked chart. | `trade_filter.BLACKOUT_WINDOWS` mirrored in `pressure.py` | none |
| 6 | **Prior-day + session high/low rails** | The levels every gold desk actually marks. Cheap, and they explain why price stalls where it does. | `pressure.market_map()` levels | none |

### Tier 2 — worth adding, cheap, but secondary

| # | Tool | Why | Caveat to print |
|---|---|---|---|
| 7 | **EMA50 / EMA200 + 30-bar slope** | This is the bot's trend gate. Showing it makes "which side is the bot even allowed to take" legible. | The gate makes direction and side ~94/96% collinear (`ANALYSIS-2026-09-28`) |
| 8 | **RSI panel with the bot's actual window drawn** (BUY 30–68, SELL 32–70) | Not "oversold/overbought" doctrine — the engine's real window, so a human sees what the bot sees. | The window is a filter, not a signal |
| 9 | **ATR strip with the 1.10–4.50 trade band shaded** | Instantly shows "the bot will not trade here". | Engine bound, not a volatility prediction |
| 10 | **Trade & signal markers on the chart** (past entries, SL/TP/BE/TIME exits, 8/8 events) | Highest learning value of anything in this tier — you can *see* where the system wins and loses. | Marker ≠ validation; base rate is ~50% |
| 11 | **Momentum tape badge** (rising / flat / falling, 60 min) | Already exists in `Simple`; belongs next to the chart. | Collinear with side — never read it alone |
| 12 | **Volume + Vol_MA** | Present in the log; useful for exhaustion reads. | `REQUIRE_VOLUME_CONFIRM = False` — the engine does not use it. Say so. |

### Tier 3 — do **not** ship as tools (yet)

These are the classic ones a gold trader expects. I am not refusing them; I am
refusing to draw them *as if they worked* before we measure them, because a chart
that implies an edge it does not have is worse than a blank chart.

| Tool | Verdict | Reason |
|---|---|---|
| **Fibonacci retracement** | Not yet | The anchor choice is the whole tool and it is subjective — any level can be produced after the fact. Testable properly: fixed anchors (e.g. prior-day range 38.2/50/61.8) via `tools/strategy_lab.py --bars`, one pre-registered bar. |
| **Daily/weekly pivot points** (classic, camarilla) | Not yet | Fully mechanical and therefore honestly drawable — this is the *best* candidate in Tier 3. Still unmeasured here. ~30 lines to add, one session to test. |
| **Round-number psychology** ($4000, $50, $100 increments) | Not yet | Cheap and plausible on gold, trivially computable, zero measurement done. Prime candidate for a level test. |
| **VWAP** | No | Needs a session-anchored volume series. Our `Volume` is MT5 **tick** volume, not real traded volume — a VWAP off it is a guess wearing a formula. |
| **Volume profile / value area** | No | Needs per-price aggressor volume. Not in the feed. Cannot be drawn honestly. |
| **Trendlines, channels, H&S, flags, Elliott, harmonics** | No | Subjective by construction. Two people draw different lines; the chart would be showing *our* opinion in a confident font. |
| **Ichimoku, Bollinger, Keltner, Supertrend, MACD** | No | Not *wrong*, just unmeasured and redundant: the ATR band already covers volatility and the EMA gate covers trend. Six indicators on one chart is how traders talk themselves into trades. |

**Rule for this tab:** a tool gets drawn only if (a) it is deterministic, or
(b) it has been measured on our tape and its verdict travels with it. Tier 3
stays out until it clears a pre-registered bar.

---

## 3. What the tab looks like

Top to bottom, one screen, no scrolling to find the answer:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  🧭 CHART & PLACEMENT        close $4022.77 · ATR $1.48 · 08:59 UTC · M5     │
│  ──────────────────────────────────────────────────────────────────────────  │
│  ⏳ WAITING — price is 1.5 ATR under the ceiling, no fresh close beyond it.   │
│  Location: good.  Trigger: missing.  Cost: BUY geometry is fine, SELL is not.│
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  4125 ┬─────────────────────────────────────  prior-day high 4126.09 ──────  │
│       │                                                                       │
│  4028 ┤━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 4h box high 4028.40 ━━━━━━━━━━━━━━━━━━   │
│  4025 ┤─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ 20-bar ceiling 4024.98 ─ ─ ─ ─ ─ ─ ●           │
│  4022 ┤   ▁▂▃▅▂▁▂▃▄▃▂▁▂▃▅▃▂▁▂▃▄▃▂▁ ▂▃▅▄▃▂▁▂▃▄▅▃▂▁▂▃▄▂▁▂▃▄▃▂▁▂▃▄▃▂▁▂▃▄▃▂      │
│  4009 ┤ ─ ─ ─ ─ ─ ─ 1h box low 4009.17 ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─     │
│  4003 ┼──────────────────────────────────────  4h box low 4003.12 ─────────  │
│       └──┬──────────┬──────────┬──────────┬──────────┬──────────┬────────    │
│          23:00      03:00      07:00      11:00      15:00      19:00        │
│         ░░Asia░░░░░░░░░░▒▒London▒▒▒▓▓▓▓▓NY▓▓▓▓▓▓▓▓▓░░░                  │
│                        (blackout shading: 07:55–09:00 BUY-only)              │
├──────────────────────────────────────────────────────────────────────────────┤
│  IF YOU TAKE IT — the placement card                                         │
│  ┌────────────────────────────┬────────────────────────────┐                │
│  │ BUY above 4025.61          │ SELL below 4008.63         │                │
│  │ entry   4025.61            │ entry   4008.63            │                │
│  │ stop    4012.04  (−1.4 ATR)│ stop    4028.90  (+2.7 ATR)│                │
│  │ target  4038.40  (1 box)   │ target  3993.65  (1 box)   │                │
│  │ R $13.57 · reward $12.79   │ R $20.27 · reward $14.98   │                │
│  │ R:R 0.94 ✗ under 1:1       │ R:R 0.74 ✗ under 1:1       │                │
│  │ spread = 4.1% of R ✓       │ spread = 2.7% of R ✓       │                │
│  └────────────────────────────┴────────────────────────────┘                │
│  ⚠ Both targets are limited by the box width. A 1-box target here is under   │
│    1R — that is a geometry problem, and no entry timing fixes it.            │
├──────────────────────────────────────────────────────────────────────────────┤
│  💸 COST RULER — spread as a share of your stop                              │
│   1.0 ATR ██████████████████████ 37%   ┐                                     │
│   1.5 ATR ██████████████ 25%           │  red zone: most trades lose here    │
│   2.0 ATR ███████████ 19%              ┘                                     │
│   2.5 ATR ████████ 15%                                                       │
│   3.0 ATR ███████ 12%   ← minimum worth considering                          │
│   4.0 ATR █████ 9%      ← the bot's typical structural stop (3.3 ATR median) │
│  Measured round trip $0.55 (quote logger median) · $0.40 (registered model). │
├──────────────────────────────────────────────────────────────────────────────┤
│  ✅ / ❌ CHECKLIST        Location · Trigger · Feed · Session · Risk state · │
│                           Volatility · Geometry   →  4/7 pass               │
├──────────────────────────────────────────────────────────────────────────────┤
│  📊 Measured, not assumed: 8 box geometries, 0 cleared reference. 74–75% of   │
│  breaks fail within 15 min. 8/8 signal: 50.4% trade-way at 30m. No edge has  │
│  been validated. Recheck live price and spread before any manual decision.   │
└──────────────────────────────────────────────────────────────────────────────┘
```

M5 or M15 by default with a toggle — a raw M1 chart of gold is 4-ATR noise (the
box doc's finding) and would make every level look meaningless.

---

## 4. Where to place the trade — the playbook

This is the part that answers "advice where to place trades". It is the box doc's
§4 restated as a checklist the tab will encode, plus the cost arithmetic.

1. **Draw the box first, not the candle.** H1 / H4 / prior day. A 20-bar M1 box
   is $12 wide one day and $3 the next — it is noise, not structure.
2. **Stop goes *outside the far edge* + 0.5·ATR.** Never inside the box, never
   inside the edge wick. Same logic as the 2026-10-05 structural stop: a stop
   inside the range on 63.8% of trades was the single biggest leak in the old book.
3. **Let the cost decide whether the trade exists.** Minimum stop distance:
   `R ≥ 10 × round_trip_cost`. At $0.55 that is **R ≥ $5.50**; at $0.40, **$3.90**.
   At today's ATR $1.48 that means a stop of at least **3.7 ATR / 2.6 ATR**.
   If the box is too narrow to give you that, **there is no trade** — a better
   entry cannot fix a geometry problem.
4. **Target the measured move** (one box width) or 1.5R, whichever the next
   structure allows. Skip the trade if the next box is closer than 1R.
5. **Never move to breakeven before +0.75R.** The 0.30R ratchet scratched 77% of
   trades with a median lifetime of 1.5 min (`REVIEW-2026-09-15`). The reflex
   will do the same thing to a manual trade.
6. **Skip the dark windows.** 07:55–09:00 (BUY only), 12:25–12:45, 13:25–15:15,
   21:45–22:30 (both sides), plus the **20:58–22:00** daily break — a gap through
   a stop is not a stop (`REVIEW-2026-10-19`, the fired §7 closure-gap trigger).
7. **Do not chase.** More than ~1 ATR beyond the edge is a bad fill. 94% of breaks
   are retested within 30 bars at a median of 3 — the retest is usually available.
8. **One position at a time, and no re-entry within 10–15 min of a scratch.**
   27 of 58 0.75R-era entries came <10 min after the previous exit; that churn is
   a pure cost pump.
9. **Size from the stop, not from a lot you like.** 1% of account per R
   (`PREREG-2026-10-17-risk-sizer.md` is the engine's version).
10. **Log every manual trade** — box high/low, side, entry, stop, target, exit
    reason. The tab can write this to its own file (never `trades.csv`, never the
    engine). Until then manual results are survivorship bias, and the bar stays
    **n ≥ 100 with positive expectancy after the measured spread**.

### The brutal arithmetic, today's ATR $1.48

| Stop | $ risk | cost @ $0.40 | cost @ $0.55 | verdict |
|---|---|---|---|---|
| 1.0 ATR | $1.48 | 27.0% | 37.2% | structurally unprofitable |
| 1.5 ATR | $2.22 | 18.0% | 24.8% | very expensive |
| 2.0 ATR | $2.96 | 13.5% | 18.6% | expensive |
| 2.5 ATR | $3.70 | 10.8% | 14.9% | borderline |
| 3.0 ATR | $4.44 | 9.0% | 12.4% | acceptable |
| 4.0 ATR | $5.92 | 6.8% | 9.3% | comfortable |

At 1:1.5 you need **~43%** to break even on the $0.40 model; at 1:1, **~54%**.
Those are the numbers the payoff has to beat — not 50%.

---

## 5. Build plan (if you say go)

| Piece | Where | Effort |
|---|---|---|
| Candle aggregation + windowing (M1 → M5/M15, last N bars) | `pressure.py`, pure/stdlib | ~80 lines |
| Server-side SVG chart renderer (axes, candles, level lines, box rectangles, session bands, markers) | `pressure.py` → returns a dict of primitives; the template draws it | ~300 lines |
| Placement card per side | reuse `box_geometry()` / `box_watch_cards()` | ~60 lines |
| Cost ruler | new, arithmetic only | ~30 lines |
| Checklist | reuse `box_status()` checks | ~20 lines |
| HTML/template + tab wiring (`?tab=chart`) | `dashboard.py` | ~250 lines |
| Hermetic tests | `tools/test_manual_chart.py` | ~15 tests |

**Hard constraints, non-negotiable:**

- **No CDN / no JS charting library.** Server-side SVG only. The dashboard must
  render behind the preview proxy, offline and on the box, with zero new deps.
  `pressure.py` stays **stdlib-only** and must not import `engine.py` (Scenario U,
  `tools/smoke_test.py`). Any new threshold gets mirrored *and* pinned in
  Scenario U.
- **Display-only.** No order, no `trades.csv` write, no engine restart. Per
  `docs/AUTOSYNC.md`, a dashboard change restarts the dashboard only.
- **No new claimed edge.** Tier 3 stays off the chart until measured.
- **Price-scale honesty.** This feed is the broker demo **GOLD** series (~4.0k),
  not spot XAUUSD. Levels will not tick-for-tick match TradingView; the tab must
  say so, or a manual trader will compare and mistrust the whole panel.

---

## 6. What I would cut if you want it smaller

If a full chart is too much, the 80/20 is **items 2, 3 and 4 only**:

- the four boxes drawn as horizontal bands on a simple close-price sparkline,
- the placement card (entry / stop / target / R:R / cost share),
- the cost ruler.

That is most of the decision value with maybe 40% of the work, and no candle
renderer at all. But **without the chart** the levels are just numbers, and
numbers are exactly what the existing tabs already show.

---

## 7. Open questions (decide these and I'll build it)

1. **Default timeframe** — M5 (smoother, structure reads better) or M15
   (closer to how you'd draw an H1 box by eye)? M1 is not recommended.
2. **Which Tier 3 tool do *you* actually use manually** — Fibonacci? daily
   pivots? round numbers? If one of them is in your process, it is worth a proper
   measurement via `strategy_lab.py --bars` instead of shipping it as decoration.
3. **Should the tab log manual trades** to its own file (never `trades.csv`)?
   That is the only path that ever turns this advice into evidence.
4. **Draw the live/open paper trade** (entry, stop, TP, ratchet line) on the chart?
   Cheap, and useful for seeing why the bot did what it did.

---

## 8. What this is not

- Not a gate, not a parameter change, not an engine change, not a reason to
  re-judge the open struct-stop window.
- Not a claim that any of it predicts price. The measured base rates are ~50%
  and that is printed on the panel, permanently.
- Not a replacement for the **📦 Boxes & Timing** tab. That tab answers "do the
  conditions line up" in words; this one shows *where* they are in space.

---

## 9. Reproduce every number in this document

```bash
python3 tools/box_report.py                      # boxes + the 8-geometry verdict
python3 tools/pressure_report.py --root . --era structstop   # tape / gates / era
python3 tools/signal_outlook.py --root .         # the 50.4% base rate
python3 tools/check_gap_rides.py                 # the 2/2 closure-gap trigger
python3 - <<'EOF'                                # the cost ruler table
import pressure as P
rows = P.read_rows('forward_test_log.csv')
atr = P.parse_float(rows[-1]['ATR'])
for m in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0):
    r = m * atr
    print(f"{m:>4} ATR  ${r:5.2f}  0.40 -> {100*0.40/r:5.1f}%  0.55 -> {100*0.55/r:5.1f}%")
EOF
```

Snapshot used throughout: last bar **2026-10-23 08:59:06 UTC**, close
**$4022.77**, ATR **$1.48**, 49,776 usable bars. The levels are already stale —
run the tool.
