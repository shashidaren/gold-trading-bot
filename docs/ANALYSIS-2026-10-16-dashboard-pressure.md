# ANALYSIS 2026-10-16 — dashboard buy/sell pressure + daily-decision panel

**Status:** shipped on the branch, **display-only**. No `engine.py` / `trade_filter.py` change, no
parameter, gate, exit or strategy change, **no runtime change of any kind** — the open
**struct-stop window** (entries ≥ 2026-10-06 03:00 UTC) is untouched and un-stacked.
**Owner ask:** "add an indicator in the dashboard buy/sell pressure so I can make an informed
decision on daily trade… if there's other information that will be helpful please add this in."

**Files:** `pressure.py` (new, read-only), `dashboard.py` (panels + a read-only context layer),
`tools/pressure_report.py` (new, read-only CLI), `tools/smoke_test.py` **Scenario U** (45 checks),
`README.md`, `docs/HANDOFF.md`.

---

## 1. What was added, and what it is allowed to be

| Piece | What it does | What it must never do |
|---|---|---|
| `pressure.py` | One read-only snapshot: tape pressure, the engine's own gates read back on the last closed bar, the 20-bar location + hypothetical stop/target, portfolio state (blackout/cooldown/breaker/skips), the struct-stop era vs its §7 bar, book/today, feed health, and the calibration of the composite | Write anything, import `engine.py`/`trade_filter.py`/flask, invent a signal, or move a threshold |
| `dashboard.py` panels | Renders that snapshot next to the existing tiles — "🌡️ Tape pressure", "🎯 Setup read", "📍 Location in the 20-bar range", "🧮 If the engine entered this bar", "🧪 Live experiment", "📅 Today", "📡 Feed health" | Restart or influence the engine; show a number without provenance |
| `tools/pressure_report.py` | Same layer, printed: tape, gates, location, portfolio, §7 verdict, **calibration**, feed. `--json` for scripts | Change state; it exits 0 always |
| `tools/smoke_test.py` Scenario U | Pins every mirrored constant to `engine.py`/`trade_filter.py`, pins the §7 thresholds to the analysis doc, pins `STRUCT_STOP_CUTOVER` to `strategy_lab.LIVE_CUTOVER`, proves the module is read-only + stdlib-only by AST, and exercises the pure functions on synthetic tapes | — |

**Why a mirror instead of an import.** The dashboard must not import the engine: it would drag in
`requests`/`dotenv`/broker code and, worse, would keep *stale* constants across an engine-only
deploy (autosync restarts `goldbot` but only restarts the dashboard when `dashboard.py` itself
changes — `docs/AUTOSYNC.md`). So `pressure.py` duplicates the thresholds **and Scenario U fails the
deploy if they ever drift**. That is the same trade-off the file already made for
`MAX_HOLD_MINUTES`.

---

## 2. The trap this feature had to survive

The engine's trend gate keys side on `EMA50 vs EMA200`, so in this book **direction ≈ side** (94% of
falling-60m entries are SELLs, 96% of rising-60m are BUYs — ANALYSIS-2026-09-28, HANDOFF §8). A
"buy pressure" number at the entry of a BUY is therefore high *by construction*, and at a SELL it is
low. Pooled, the gauge is a restatement of the direction the bot was already willing to trade — the
exact shape of the error §8 exists to prevent.

So the composite was written **and then measured against the live ledger** before being shown as
anything other than context (§4). The dashboard prints the verdict next to the dial.

---

## 3. The composite (transparent, auditable, weighted)

Window: the last **60 closed bars**. Each component is reported as a raw value **and** a 0–1
buy-share, so the dial can be recomputed by hand from the panel:

| Component | Raw value | Weight | Buy-share |
|---|---|---|---|
| Volume-weighted flow | `Σ (close−open)/range × volume ÷ Σ volume` over the window | 0.30 | `(flow+1)/2` |
| 60-bar momentum | `(close_now − close_{−60}) / ATR` | 0.20 | `logistic(m/1.5)` |
| EMA50 vs EMA200 | `(EMA50 − EMA200) / ATR` | 0.20 | `logistic(t/0.5)` |
| EMA50 30-bar slope | `(EMA50_now − EMA50_{−30}) / ATR` | 0.15 | `logistic(s/0.5)` |
| RSI posture | `RSI` | 0.15 | `clip((RSI−50)/20)` mapped to 0–1 |

`BUY pressure = 100 × Σ(wᵢ · shareᵢ)`, `SELL pressure = 100 − BUY pressure`. Labels are words, not
verdicts ("Tape pushed UP hard", "Tape balanced", …).

**What the panel is really for.** Because the composite is a side proxy, the decision-relevant part
of the panel is the rest of it: *where price is* relative to the 20-bar level the strategy trades
against, *which of the engine's own gates pass on this bar*, what the structural stop/target would
be, and *whether the portfolio gates even allow an entry right now*. That is knowledge a human can
act on (or explicitly choose not to), and every threshold on screen is the engine's own — nothing is
invented.

---

## 4. Calibration — measured, not asserted

Method (`pressure.calibration`, mirrored by `tools/pressure_report.py` §6): each closed trade is
joined to the **last log bar strictly before its entry minute** (HANDOFF §8: the log lags the ledger
by ~1 min and the entry bar must never be a pre-entry feature), the composite is computed there, and
the trade is bucketed by the **pre-specified** split below — one split, three buckets, per side, no
re-slicing to find a nicer cut. R is the repo's: `Profit ÷ (|TP − Entry| ÷ 1.5)`.

**Buckets.** For a BUY: `aligned` = buy-pressure ≥ 58, `mixed` = 42–58, `against` < 42. For a SELL
mirrored (≤ 42 / 42–58 / > 58).

### Struct-stop era (entries ≥ 2026-10-06 03:00 UTC, n = 120 at 2026-10-16 09:00 UTC)

| side | bucket | n | decisive | decisive WR | R/trade |
|---|---|---|---|---|---|
| BUY | aligned (≥58) | 57 | 46 | 37.0% | −0.076 |
| BUY | mixed | 4 | 1 | — | — |
| BUY | against | **0** | — | — | — |
| SELL | aligned (≤42) | 58 | 44 | 38.6% | −0.034 |
| SELL | mixed | 1 | 1 | — | — |
| SELL | against | **0** | — | — | — |

Within-side span of buy-pressure at entry: **BUY 49–81 (median 75)**, **SELL 14–42 (median 22)**.

### Max-hold era (entries ≥ 2026-09-21 06:00 UTC, n = 347) — the same shape

BUY aligned 155 (28.3% dec, −0.292R) + mixed 8; SELL aligned 179 (34.6% dec, −0.135R) + mixed 5;
**no `against` bucket on either side, in either era.**

### Verdict (what the panel prints)

> **collinear with side — not separable within-side.** The trend gate means BUYs print with high
> buy-pressure and SELLs with low; the aligned bucket is ~all of each side, so there is nothing to
> contrast inside it.

An earlier prototype bucketed the same composite into 0–40 / 60–70 / 70+ and got 38.6% / 36.4% /
37.1% decisive — i.e. nothing — which is consistent with the degenerate structure above. **The
composite is a description of the tape. It is not a signal, it is not a gate, and it has no mandate
to size, veto or time a trade.** Anything else would need a pre-registered bar first (HANDOFF §11).

---

## 5. The rest of the panel, and why each item is there

| Panel | Question it answers | Source of truth |
|---|---|---|
| Tape pressure + components | Which way is the tape being pushed, and how strongly? | `pressure.pressure()`; measured value stated above |
| Setup read (BUY / SELL, PASS/FAIL per gate) | Would the engine take this bar? If not, what is the *first* thing missing? | the engine's **own logged flags** where they exist (`Tested_Floor`, `Valid_Rejection`, `Held_Floor`, `Trend_Confirmed`, `Wick_Ratio`, `RSI`, `ATR`), recomputed with the engine's rules where the log has no column (the whole SELL side, the EMA slope, the EMA-proximity buffer) |
| Location in the 20-bar range | Is price at a level at all (the strategy only buys a tested floor / sells a tested ceiling)? | 20-bar floor/ceiling rebuilt exactly as `evaluate_candle` does (**previous** 20 bars), floor cross-checked against the logged `Dynamic_Floor` with a visible warning on mismatch |
| If the engine entered this bar | What stop/target/risk would the live rule set, in $ and ATR? | `structural_risk` = `max(2·ATR, |entry − level| + 0.5·ATR)`, TP = 1.5 × risk (live 2026-10-06) |
| Portfolio gates | Is the risk layer even going to allow it (blackout / cooldown / daily breaker / momentum side)? | mirrors of `trade_filter` (Scenario U pins them) |
| Skips (last 24 h) | What did the risk layer block, and how much? | `skipped_trades.csv` |
| Live experiment | Reader form of the analysis I would do anyway, judged as written | `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` §7 |
| Today + last 20 exits | What has actually happened today; is a losing run normal? | `trades.csv`. The panel states the base rate (≈39% decisive ⇒ P(4 straight losses) ≈ 14%) so a run is not read as a regime change |
| Feed health | Is the data alive? Is that gap the 2026-09-29 signature? | log timestamps; gaps counted **in open-market minutes**, weekends and the daily break excluded (mirrors `engine.is_market_quiet`) |

**Invariant checks (mechanical, from the ledger alone)** — A4 level-bound share and A5 median risk in
ATR are computed in the panel; A1 (no stop inside the level) stays a job for
`python3 tools/check_structural_stop.py`, which the panel names explicitly. The panel reports the
verdict; it never substitutes for the guard.

---

## 6. How this stays honest

1. **Scenario U** (deploy gate): every mirrored constant, the §7 thresholds, `LIVE_CUTOVER`, the
   `is_market_quiet` mirror, the previous-20-bars level rule, reward-leg risk, the §7 SCREEN/PASS/
   REVERT logic, the cooldown escalation, the direction-aware blackout, the skip buckets, the
   weekend-vs-outage gap rule and the calibration's degeneracy detection are all asserted on
   synthetic data (no wall clock, no `/opt/gold`).
2. **Read-only by AST**: Scenario U parses `pressure.py` and fails if it opens a file for writing,
   calls a fs-mutating `os`/`shutil` function, or spawns anything.
3. **Stdlib-only by AST**: `pressure.py` may not import `engine`, `trade_filter` or flask — the
   mirror is a deliberate duplicate, checked at deploy time instead of coupled at runtime.
4. **The calibration is recomputed, not typed in**: the panel joins the live log to the live ledger
   (10-minute cache) so the honesty note cannot go stale the way a hand-written number would.
5. **No wall clock in the library**: every function takes `now` explicitly; the dashboard passes it.

---

## 7. What this does NOT authorize

- **Not an entry gate.** No threshold here may be added to `engine.py`/`trade_filter.py` without a
  pre-registered bar in a dated doc (HANDOFF §11), and this doc is not one.
- **Not a change to the open struct-stop window.** The window runs to the 2026-10-19 21:00 UTC
  judgement (or n=150); nothing here is stacked on it. A dashboard change only restarts the
  dashboard (autosync `DASH_CHANGED`), never the engine.
- **Not evidence about edge.** The book is still paper-only, still negative at the assumed cost; the
  panel's era card exists to keep that in front of the operator, not to dress it up.
- **Not a licence to read the dial without a side split.** The printed verdict is the guard.

---

## 8. Notes for the box

- Deploy: merge to `main`; autosync restarts only the dashboard service (`DASH_CHANGED`). No engine
  restart, no state touched.
- Paths default to `/opt/gold/*` exactly as before. For local/dev rendering, override the directory:
  `GOLD_DATA_DIR=./ python3 dashboard.py` (also `GOLD_LOG_FILE`, `GOLD_TRADES_FILE`,
  `GOLD_SKIP_FILE`, `GOLD_STATUS_FILE`).
- `tools/pressure_report.py` is the CLI equivalent (`--root DIR`, `--era structstop|maxhold|075|all`,
  `--json`). Run it after a data drop to refresh the printed calibration; the dashboard does its own
  join every 10 minutes.
