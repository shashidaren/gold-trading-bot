# Indicator audit + self-journal — 2026-10-23

**Status:** display-only, no `engine.py` / `trade_filter.py` change, no gate, no sizing, no exit change.
**Trigger:** owner asked "are there more indicators we could add? also can you self-journal BUY/SELL and show the success rate?"
**Ledger:** 695 closed trades, 49 956 log bars, 1 607 skipped attempts, open BUY #697 @ $4 027.91 (as of 2026-10-23 11:59 UTC).
**Tool:** `python3 tools/journal.py` (`--cost`, `--era`, `--json`, `--csv`) — the self-journal. Reproduce every number below with `python3 tools/journal.py --era structstop` and `--era all`.

---

## 1. What the bot already uses (and what each one actually does)

The funnel has 8 gates plus 3 portfolio rules plus the exit. Every threshold is mirrored in `pressure.py` and pinned by `tools/smoke_test.py` Scenario U — the dashboard cannot drift from the engine.

| Group | Indicator / gate | Engine param | What it does | Measured verdict |
|---|---|---|---|---|
| **Structure** | 20-bar floor/ceiling | `LOOKBACK=20`, `FLOOR_BUFFER_PCT=0.0020` (≈$8.30 at $4 150, 4.5× median ATR) | "price tested the level" | TRUE on 86.9% of bars — selects for almost nothing (ANALYSIS-2026-10-05 §1). Candidate to re-scale to 0.25 ATR, but that candidate is **blocked** by the fired §7 gap trigger; no deploy before a gap guard is defined (HANDOFF §6). |
| **Structure** | Wick ratio | `WICK_RATIO_TARGET=0.38` | Rejection wick ≥38% of bar range | Journal live era: 65%+ wicks 48.4% dec vs 38–50% 34.5% — the best wick bucket, but p=0.49 across all buckets, not a gate on its own. |
| **Trend** | EMA50 vs EMA200 | `EMA_FAST=50`, `EMA_SLOW=200`, `Trend_Confirmed` | Side = trend direction | The whole reason side≈momentum (BUY 92% in rising tape, SELL 93% in falling). Not an edge by itself — it **is** the side split (momentum_regime §3/4). |
| **Trend** | EMA slope (30-bar) | `REQUIRE_EMA_SLOPE`, `EMA_SLOPE_LOOKBACK=30` | EMA50 rising for BUY, falling for SELL | Live era lab: falling slope 40.8% vs rising 36.8% — upside down, p=0.57. Already in the funnel; not a standalone filter. |
| **Trend** | Price vs EMA50 distance | `MAX_BELOW_EMA_ATR=0.30` | Don't buy a collapsed candle | Journal: well below EMA50 (<−0.5 ATR) 46.7% vs just-below (−0.5..0) 7.7% (n=17, tiny). The gate is already lenient (+0.30 ATR); tightening would need isolation. |
| **Momentum** | RSI | `RSI_MIN=30`, `RSI_MAX=68` (SELL 32–70 mirrored) | Avoid chasing / exhausting | 30–45 bucket 40.0% vs 45–55 36.7% in live era — no gap. Candidate RSI≥45 lives in win_rate_report §6 but never cleared 5 pp + side split. |
| **Volatility** | ATR | `MIN_ATR=1.10`, `MIN_ATR_TO_TRADE=1.10`, `MAX_ATR_TO_TRADE=4.50` | Quiet floor, volatile ceiling | Live era sweet spot 1.2–1.4 ATR 57.6% (n=46) vs <1.2 14.3% and >2.0 23.7%. High ATR also means wider $ risk — $/trade worse. MAX_ATR at 4.50 already; no evidence to tighten. |
| **Risk** | Structural stop + RR | `ATR_SL_MULT=2.0`, `SL_CLEAR_ATR=0.5`, `RR_TARGET=1.5` | Stop beyond the tested level | Shipped 2026-10-06, guard PASS (0 inside). Level-bound 83.3%, median risk 3.32 ATR in era. |
| **Risk** | BE ratchet | `BE_TRIGGER_R=0.75` | Move to BE at +0.75R | Raised from 0.30 (which scratched 77% in 1.5 min). Live scratches 26.8%, still inside noise but far better. |
| **Risk** | Max-hold | `MAX_HOLD_MINUTES=240` | TIME exit | 2 exits in 695 trades; isolates closes across daily gaps. |
| **Portfolio** | SL cooldown escalated | `30 → 60 min` after 2 SLs | Avoid chasing after loss | Blocked 1 090 attempts (skipped_trades.csv). Live era: streak 3+ actually 46.4% vs streak 0 35.7% — cooldown protects P/L, not WR. |
| **Portfolio** | Daily breaker (10 SL) | `MAX_DAILY_LOSSES=10` trend-side-only | Tail risk | 23 blocks; never hit in era (max 4/day on 2026-10-23). |
| **Portfolio** | Blackouts (4 windows) | London BUY-only + 3 BOTH | News/session | 470 blocks. London/NY band bleed is a named candidate (§5a) — not adopted. |
| **Context** | Volume confirm | `REQUIRE_VOLUME_CONFIRM=False` | Off | Volume still logged; lab tests it below. |

No indicator here is claimed as edge; every funnel threshold's calibration lives in `tools/strategy_lab.py` and `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md`.

Deliberately **not** in the funnel (and why): Fibonacci / pivots / round numbers (unmeasured), VWAP & volume profile (feed is MT5 *tick* volume, not traded volume — a VWAP on it would be a guess in a formula), trendlines / H&S / Elliott (subjective), and the six "volatility + trend" duplicates below until measured (box doc §3 table).

---

## 2. Extra indicators measured — the lab (`tools/journal.py` §5)

Computed from `forward_test_log.csv` closes/highs/lows alone, same EMA/RSI/ATR definitions as the engine (simple means, not Wilder). Each bucket shows decisive WR with Wilson CI, $/trade, R/trade, Fisher p for best vs worst. n is decisive+BE; small-n buckets are flagged, not hidden. No new bucket was invented to make a number look good.

**Sample:** live era n=198 (55W/89L/53BE/1TIME, 38.2% dec [30.7–46.3], −$0.26/trade gross, −$0.66 net at $0.40). Whole book n=695 for power check. Costed view (`--cost 0.40`) moves P/L by −$0.40/trade but not WR.

| Lab indicator | Best bucket | Worst bucket | Δpp | Fisher p | Side-split? | Verdict |
|---|---|---|---|---|---|---|
| **ATR percentile (vs last 100)** | quiet <25th 55.6% (n=41, +$1.81/trade) | 50–75th 21.9% (n=40, −$2.53/trade) | +33.7 | **0.014** | BUY 41.9% vs 28.1%, SELL 45.5% vs 35.1% — same direction but p>0.2 within-side | **Most promising**: quiet regimes win, volatile regimes leak. But both sides move together only weakly; needs chronological holdout + up-tape check. Display-only. |
| **Donchian 20 position** | near low <0.2 63.6% (n=16, +$2.79/trade) | 0.5–0.8 31.4% (n=68, −$1.73) | +32.3 | 0.082 (n=16!) | — | Small-n fluke: n=16, CI [35–84]. Not a gate. |
| **Volume vs 20-MA** | spike >1.3× 46.2% (n=17, +$0.95/trade) | thin <0.7× 21.4% (n=18, −$3.15) | +24.7 | 0.23 | Whole book: spike 45.0% vs thin 20.5% p=0.031 — **side-split holds** (SELL 35.7% vs 21%? but within-side p≈0.05) | Participation helps, but feed is tick volume (proxy). Keep as context, not a veto. |
| **BB %B (20,2)** | far lower <0.2 43.8% (n=19) | far upper >0.8 30.0% (n=24) | +13.8 | 0.49 | Both sides same p≈1.0 | No edge over trend gate; redundant with Donchian. |
| **MACD histogram** | bear <0 44.1% (n=90) | bull >0 32.9% (n=108) | +11.2 | 0.17 | — | Bear bias = SELL regime; collapses to side. |
| **Stochastic %K** | overbought >80 44.4% (n=24) | 50–80 33.9% (n=81) | +10.5 | 0.42 | — | No monotonic pattern; oversold also 42.9%. |
| **ADX** | weak <15 50% (n=9!) | very strong >40 32.7% (n=78) | +17.3 | 0.43 | — | Weak trend *appears* better but n=9. Strong trend ≠ win rate (trend gate already). |
| **CCI** | oversold <−100 43.8% (n=21) | overbought >100 35% (n=25) | +8.8 | 0.73 | — | Noise. |
| **Trend strength (EMA50−EMA200 in ATR)** | weak −1..1 45.9% (n=43) | bull >1 33.3% (n=59) | +12.6 | 0.26 | — | Weak trend beats strong trend — same as ADX, suggests strong trends are choppier at 1-min scale. |
| **EMA slope** | falling <−0.5 40.8% (n=106) | flat −0.5..0.5 31.2% (n=21) | +9.6 | 0.57 | — | Flat worst; already a gate. |
| **BB width (squeeze)** | squeeze <3 ATR 39.3% (n=41) | 3–5 ATR 37.6% (n=110) | +1.6 | 1.0 | — | Squeeze ≈ quiet percentile; same story. |

**Whole-book check (n=695):** only **volume spike vs thin** reached p<0.05 (45.0% [30.7–60.2] vs 20.5% [10.8–35.5], Δ24.5 pp, p=0.031). Best-vs-worst ATR percentile 36.9% vs 28.0% p=0.20 — same direction but weaker pooled. Every other lab indicator's best-worst gap was <12 pp or p>0.2.

**What this means:** if you had to pick one *additional* context read, **ATR percentile / volatility regime** (quiet vs volatile) and **participation (volume spike vs thin)** are the only two that are not pure side proxies and have any statistical hint — and even those fail the repo's own adoption bar (see §5). All the classic "add MACD / Bollinger / Stoch / ADX" suggestions test as redundant with the EMA trend gate or as noise at this horizon.

The honest answer to "what more can we add?" is therefore: **nothing more as a gate today**. The next edge, if it exists, is likely *outside* the 1-min bar (session/volume regime, gap guard, or a bounded hold-past-stop rule with pre-reg) — not a 9th oscillator on the same bar.

---

## 3. Self-journal — what it logs and what success means

`tools/journal.py` **is** the self-journal. It does not create a new ledger; it journals the existing ones every run:

* **Every closed BUY/SELL** with its side, entry/exit, outcome (TP/SL/BE/TIME), P/L, risk, R, and contemporaneous tape: RSI, ATR, wick, EMA distance/gap, slope, level geometry, streak, session/weekday/hour, plus the lab indicators above (BB %B, MACD, Stoch, ADX, CCI, Donchian, ATR percentile, volume ratio, BB width).
* **Success = decisive WR**: TP / (TP+SL), Wilson 95% CI, with $/trade and R/trade. BE/TIME are neutral (excluded from WR, booked in P/L) per HANDOFF §8.
* **Cost toggle**: `--cost 0.40` re-costs every trade (including scratches) at the assumed round trip; the assumed model stays $0.40 until the quote logger's 14-day/2-weekend sample is complete (currently 7.8 days, 7/14, 1/2 weekends, median $0.55).
* **Slices**: baseline, side, era, hour, session, weekday, RSI/ATR/wick/EMA buckets, streak, lab buckets, side-split check, skipped-vs-taken, last-30 form. Nothing is pooled across sides without naming it (the §8 trap).
* **Exports**: `--json` for the dashboard Journal tab (same numbers, cached 10 min like the calibration join), `--csv` for a trade-by-trade sheet to share or pivot.

**Live-era snapshot (n=198, gross → net):**

* All: 38.2% dec [30.7–46.3]  P/L −$52.43  −$0.26/trade  −0.045R  →  **net −$131.63  −$0.66/trade** at $0.40
* BUY: 34.9% [24.3–47.2]  −$48.28  −$0.60/trade → net −$80.28  SELL: 40.7% [30.7–51.6]  −$4.15  −$0.03/trade → net −$51.35
* Best hour 02:00 & 15:00 60.0% (n=13, 15 each; +$2.5/trade) vs worst 06:00 9.1% (n=13, −$4.3/trade) — small-n, already named as London/NY band bleed, not adopted.
* Best session Asia 44.4% (n=56, +$0.60/trade) vs Rollover 31.8% (n=36, −$0.80/trade).
* Sweet ATR 1.2–1.4 57.6% (n=46, +$1.33/trade) vs <1.2 14.3% (n=18, −$2.25/trade) and >2.0 23.7% (n=52, −$2.31/trade).
* Wick 65%+ 48.4% (n=45, +$0.56/trade) — the only wick bucket with positive $/trade.
* Price well below EMA50 46.7% (n=91, +$0.55/trade) vs just-below EMA50 7.7% (n=17, −$3.37) — the "just-below" bucket is the 0.30 ATR gate's edge case; n=17, do not generalise.
* Last 30 in era: 45.0% [25.8–65.8]  +$0.42/trade — the recent print is inside noise of the era rate.

Full reproduction: `python3 tools/journal.py --era structstop --cost 0.40` (or `--era all`).

---

## 4. What could still improve — ranked by evidence, not enthusiasm

**Tier 1 — already measured and closest to matter, but not a gate (display-only is correct):**

1. **Volatility-regime awareness (ATR percentile).** Quiet (<25th) 55.6% vs volatile >75th 31.5% is the largest lab gap that survives as a gap at all. The dashboard's volatility guard (pressure.py `volatility_guard`, green/amber/red) already translates this into "should *I* trade now?" in the Simple tab. No engine change needed; the guard is the right home for it.
2. **Participation (volume spike vs thin).** Spike >1.3× 45% vs thin 20.5% p=0.031 in the whole book is the only p<0.05 in the lab. But the feed is tick volume (not traded volume), so a VWAP/volume-profile built on it would be a guess in a formula — the doc's reason for leaving it out. Keep as context in the Journal tab; do not build a VWAP gate.

**Tier 2 — named candidates already in the repo, still not adopted:**

* **RSI ≥45 / ATR <2.5 combo** (win_rate_report §6): keep 36.7–38% vs skip 19–30%, but skip bucket n drifts and side-split was never shown. Needs chronological holdout.
* **London/NY session-band bleed** (REVIEW-2026-10-05 §5a): Asia 44% vs Rollover 31% hints at it, but the repo's own test said "not adopted — era-unstable".
* **0.25 ATR level-test re-scale** (ANALYSIS-2026-10-05 §7): big pooled replay gain, but 0 winners of 21 decisive in the 0.30R slice. **Blocked** by the §7 gap-trigger anyway.

**Tier 3 — unmeasured and deliberately absent (do not add without a bar):**

| Proposer | Why it stays out | What would change that |
|---|---|---|
| **Ichimoku, Bollinger/Keltner, Supertrend, MACD** | Not wrong, just unmeasured and redundant: ATR band already covers volatility, EMA gate covers trend. Six oscillators on one chart is how traders talk themselves into trades. Lab tested 4 of them — none beat the existing gate. | Dated pre-reg, `strategy_lab.py --bars` on the measured spread, side-split, up-tape hold, R/trade not worse, isolation window. |
| **Fibonacci, pivots, round numbers** | Unmeasured levels; gold at $4k+ has no natural $4 000 "magnet" in this data. | Same bar plus a level-hit definition that cannot be redrawn. |
| **VWAP / volume profile** | Tick volume ≠ traded volume; repo feed cannot build a true VWAP. | A true volume feed or a demonstrated tick-volume proxy (not assumed). |
| **Trendlines / H&S / Elliott** | Subjective by construction — two people draw two lines. | A deterministic rule that can be coded and measured. |

**What to actually do next (no code change):**

* Keep collecting quote-logger days until 14 complete + 2 weekends — the $0.40 assumption vs $0.55 measured is a bigger P/L lever than any new oscillator (difference = $0.15 × 198 ≈ $30 in the live era alone).
* Keep the journal running: `python3 tools/journal.py --era structstop --cost 0.40 --json /tmp/journal.json` after each data drop; the dashboard Journal tab will read the same JSON.
* If you want a bounded manual experiment (the EXECUTION-PLAN's "observation log"), define the pressure source/indicator/timeframe/reading **before** looking at the recovery, log before the next bar, and keep n≥100 matched post-stop observations with costs. The repo already has the template; the bar is n=150 or time gate again.

---

## 5. How to verify this

```bash
python3 tools/check_data.py                # 0 fail
python3 tools/journal.py --era structstop  # this doc's snapshot (n=198)
python3 tools/journal.py --era all         # whole book (n=695)
python3 tools/journal.py --era structstop --cost 0.40  # net view
python3 tools/journal.py --era structstop --json /tmp/j.json --csv /tmp/journal.csv
python3 tools/handoff_check.py             # FRESH after --update
python3 tools/check_structural_stop.py     # PASS (0 inside)
python3 tools/check_gap_rides.py           # 3/2 REACHED (see HANDOFF §6)
```

No file written by this audit requires a restart of `goldbot`; the journal and lab are display-only. Dashboard changes restart the dashboard only (AUTOSYNC.md `DASH_CHANGED`).

