# ANALYSIS 2026-10-20 — can box theory be used for manual gold trading?

**Status:** tooling + docs only. **No** `engine.py` / `trade_filter.py` change, no
parameter, gate, exit or strategy change. The open **struct-stop window**
(entries ≥ 2026-10-06 03:00 UTC) and its 2026-10-19 judgement are untouched.

**Owner ask:** *"Need your advice if I can incorporate box theory in my manual trade for gold."*

**Short answer: yes, but only as a location and risk container — not as a signal.**
On the repo's own 1-min tape, every box breakout and every box fade lands **on or
below the driftless reference** once the real spread is charged. What does survive
is the geometry: **the stop belongs outside the whole box, and the target should be
the measured move (one box width)**. That is already what the engine's structural
stop does with its 20-bar level. Boxes tell you *where*, never *when*.

**Files:** `tools/box_report.py` (new, read-only, stdlib + `pressure`),
`tools/test_box_report.py` (14 hermetic tests), the dashboard's **📦 Boxes & Timing**
tab (`pressure.box_geometry` / `pressure.box_status`, §7), `README.md`,
`docs/HANDOFF.md`.
Method and numbers below are reproducible with
`python3 tools/box_report.py` (add `--json`, `--root DIR`, `--spread …`).

---

## 1. Method (read before quoting any number)

- **Box** = high/low of the **N bars strictly before** the bar being judged — the
  same convention as the engine's own floor (`pressure.levels()`), so the level
  never contains the candle it is testing.
- **Break event** = a bar whose *close* is outside that box (a wick through the
  edge is not a event; that distinction is the whole point of "close beyond").
- **Sequential sample, one position at a time.** After a break is taken the next
  one is only considered once the previous walk window has closed. Overlapping
  1-min events are not independent, and a Wilson interval over them would be far
  too tight — the first draft of this report made exactly that mistake and
  produced "EDGE" cells with negative expectancy. It also matches the engine's
  one-position rule.
- **Forward walk** = 60 min for the 20-bar box, 120 min for the 60-bar box,
  starting on the bar *after* the break, and stopped at any log gap > 3 min.
  A window with nothing usable ahead is **censored (dropped)**, never guessed.
- **Race** = first touch of target vs stop. A bar that spans both is counted as
  a **stop**. No breakeven ratchet, no exits, no cooldown, no breaker.
- **Reference** = `risk / (risk + target)`, the target-first share a **no-edge
  coin** produces at those distances. 50% is the wrong yardstick unless the
  payoff is exactly 1:1. A cell is only called an `EDGE` when the 95% Wilson
  **lower** bound clears the reference **and** expectancy after cost is positive.
  Clearing the reference while losing money is not an edge — it is a good ratio
  with a spread problem.
- **Cost** = **$0.55/oz round trip**, the quote logger's measured median
  (`docs/XM-LOGGER.md`). The registered model in HANDOFF is $0.40; both are
  printed if you pass `--spread`, and $0.55 is the pessimistic one. Run
  `python3 tools/box_report.py --spread 0.40` to see the friendlier case.
- **Data:** checked-in `forward_test_log.csv`, 44,982 usable bars,
  2026-09-01 14:25 → 2026-10-19 20:58 UTC. One instrument, one broker feed, one
  regime. This is a **screen**, not an edge.

### The four geometries

| id | entry | stop | target |
|---|---|---|---|
| **G1** | close beyond the edge | repo structural stop on the **broken** edge: `max(2·ATR, \|entry − edge\| + 0.5·ATR)` | 1.5R |
| **G2** | close beyond the edge | **past the far edge** + 0.5·ATR (the whole box is noise) | 1.5R |
| **G3** | close beyond the edge | same as G2 | **1 box width** (measured move) |
| **G4** | fade the edge back inside | 0.5·ATR beyond the edge | opposite edge (1 box) |

G1 is what the engine *would* do if it entered the break, so it answers "does box
theory add anything to what the bot already does?". G2/G3 are what a box trader
would actually place.

---

## 2. Results (measured 2026-10-19 20:58 UTC snapshot)

### 20-bar box — median width **$6.41 (4.1 ATR)**, 648 breaks, 74% closed back inside within 15 min

| geometry | n | target-first | 95% CI | ref | E/trade | cost as % of risk | verdict |
|---|---|---|---|---|---|---|---|
| G1 structural stop on broken edge, 1.5R | 630 | 42.1% | 38.3–46.0 | 40.0% | −$0.49 | 16.0% | no edge |
| G2 stop past far edge, 1.5R | 364 | 35.4% | 30.7–40.5 | 40.0% | −$1.70 | 3.5% | no edge |
| G3 stop past far edge, 1 box | 481 | 56.8% | 52.3–61.1 | 55.1% | −$0.34 | 4.7% | no edge |
| G4 fade the edge, 0.5 ATR stop | 642 | 10.1% | 8.0–12.7 | 10.3% | −$0.63 | 66.3% | no edge |

### 60-bar box — median width **$11.56 (7.7 ATR)**, 315 breaks, 75% closed back inside within 15 min

| geometry | n | target-first | 95% CI | ref | E/trade | cost as % of risk | verdict |
|---|---|---|---|---|---|---|---|
| G1 structural stop on broken edge, 1.5R | 307 | 37.8% | 32.5–43.3 | 40.0% | −$1.03 | 15.3% | no edge |
| G2 stop past far edge, 1.5R | 140 | 26.4% | 19.8–34.3 | 40.0% | −$5.02 | 1.6% | **BELOW ref** |
| G3 stop past far edge, 1 box | 199 | 55.3% | 48.3–62.0 | 53.0% | **+$0.14** | 2.2% | no edge |
| G4 fade the edge, 0.5 ATR stop | 309 | 10.4% | 7.4–14.3 | 5.8% | −$0.09 | 63.0% | no edge (cost) |

### By session (G2, stop past the far edge, 1.5R)

| session | 20-bar n | 20-bar target-first | 60-bar n | 60-bar target-first |
|---|---|---|---|---|
| Asia 00–07 | 106 | 39.6% (ref 40.0) | 37 | 32.4% (ref 40.0) |
| London 07–12 | 91 | 37.4% (ref 40.0) | 38 | 21.1% (**below** ref) |
| NY 12–21 | 127 | 31.5% (**below** ref) | 42 | 23.8% (**below** ref) |
| late 21–24 | 40 | 32.5% | 23 | 30.4% |

No session rescues the breakout. The late/NY bands are the *worst*, which is the
opposite of the folk rule ("breakouts work in the London overlap").

### Live boxes (last closed bar 2026-10-19 20:58 UTC, close $4140.20, ATR $0.59)

| box | high | low | width | ATR | close position | to high | to low |
|---|---|---|---|---|---|---|---|
| 20-bar level (the engine's own) | 4140.57 | 4137.51 | $3.06 | 5.2 | 87.9% | $0.37 | $2.69 |
| last 1h (60 bars) | 4142.48 | 4137.51 | $4.97 | 8.4 | 54.1% | $2.28 | $2.69 |
| last 4h (240 bars) | 4149.25 | 4136.57 | $12.68 | 21.5 | 28.6% | $9.05 | $3.63 |
| prior trading day 2026-10-16 | 4198.85 | 4147.17 | $51.68 | 87.6 | −13.5% (below it) | — | — |

Those numbers are a snapshot and will be stale by the time you read them — run the
tool. What matters in the column that does not go stale is **cost as a share of
risk**: on the 20-bar level it was **46.6% of a BUY's risk**. At that ratio the
spread alone eats nearly half of every R before the market does anything.

---

## 3. What the numbers actually say

1. **Box edges are not predictive on this tape.** Four geometries, two box sizes,
   eight session cells: not one clears its driftless reference. The best cell
   (G3 on the 60-bar box, +$0.14/trade) is inside its own confidence interval —
   calling it an edge would be the same mistake the 09-28 pooled-momentum
   analysis caught.
2. **The break itself is mostly noise.** 74–75% of closes outside the box are
   back inside within 15 minutes. Any stop placed just beyond the edge is
   therefore inside the noise by construction — which is precisely the finding
   that produced the structural stop on 2026-10-05 (stops *inside* the 20-bar
   level on 64–66% of trades).
3. **What survives is the geometry, not the signal.** The only near-break-even
   configuration is the one where the stop sits **outside the whole box** (G2/G3:
   cost = 2% of risk instead of 16%). The payoff there is <1:1, so it needs a
   ~53–55% hit rate just to stand still, and the measured rate is right on that
   line. That is the honest summary of box theory on gold here: **the box is a
   fine place to put a stop and a bad place to put a prediction.**
4. **The fade is worse, not better.** Fading the edge loses as reliably as
   breaking it, both before and after cost — mean-reversion at the edge is not a
   hidden edge either.
5. **Tight stops are structurally unprofitable at this spread.** Any geometry
   whose stop is ~1 ATR is paying 25–66% of R in cost. This is a cost problem
   that no entry rule fixes.

---

## 4. Working rules, if you are going to trade boxes manually

These are operating advice, not engine rules, and they are **not** pre-registered
in the sense of §7 — nothing here changes `engine.py`.

1. **Draw boxes on H1/H4 only** — session range, prior day's range, a clean
   consolidation of 2h+. A 20-bar M1 box is 4 ATR of noise and yields nothing.
2. **A box answers WHERE, not WHEN.** Use it to decide location and risk, and let
   price action (close beyond + retest, or the 8/8 funnel) decide timing.
3. **Stop outside the far edge**, never inside the box, never inside the edge
   wick. Add ~0.5 ATR of clearance. Size the position from that stop — one
   position at a time, as the engine does.
4. **Target the measured move** (one box) or the next box. Do not put a 1:1.5
   target on a stop that is already one box wide; the reference rate shows why.
5. **Never move to breakeven before +0.75R.** The 0.30R ratchet scratched 77% of
   trades before 2026-09-15 (HANDOFF §8); the same reflex will do the same to
   manual trades.
6. **Charge the real cost every time.** $0.40–$0.55 round trip. At 1:1 you need
   ~54% to break even; at 1:1.5 about 43%. A "50% box" is a losing system.
7. **Skip 20:58–22:00 UTC** (the daily break — see the §7 closure-gap trigger) and
   high-impact news. A gap through a box stop is not a stop.
8. **No re-entry within 10–15 minutes of a scratch.** 47% of the 0.75R-era
   entries came <10 min after the previous exit; that churn is a cost pump.
9. **Log every manual trade** — box high/low, side, entry, stop, target, exit
   reason. Unlogged trades are survivorship bias; the 10-17 note in HANDOFF §1 is
   exactly that failure mode.

### The bar to beat

Before you believe any of it, require **n ≥ 100 logged box trades** with a
**positive expectancy after the measured spread**. At 1:1 that means a lower
Wilson bound above ~54%; at 1:1.5, above ~43%. Anything less is a good week.

---

## 5. Limits

- **7 weeks, one regime, one venue.** The screen cannot detect a 3–5 pp edge and
  was never pre-registered; it may inform your manual rules and it may **not**
  justify a runtime change (HANDOFF §11).
- **The box you would actually draw cannot be measured here.** An H1/H4 session
  box yields ~1 setup per day; this log has ~35 trading days. The large-N path
  (`tools/history_to_log.py` → `tools/strategy_lab.py --bars`, see
  `docs/ACCELERATE-TESTING.md`) is the only way to test it properly, and it is
  still a first-run-on-the-box task.
- **The race is generous to the stop side** (no ratchet, no exits), and it is
  harsh in the other direction (a bar spanning both counts as a loss). Both are
  stated rather than tuned.
- **Cost is assumed, not yet measured to the §6 standard.** The quote logger has
  6.1 days of a 14-day target; $0.55 is its median, $0.40 is the registered
  model.

## 6. The dashboard tab — "Boxes & Timing" (shipped 2026-10-20)

`dashboard.py` now has a third tab (`?tab=boxes`, also remembered in
`localStorage`). It is **display-only, exactly like the pressure/setup panels**:
no order, no gate, no write, no engine import.

What it shows, top to bottom:

1. **Verdict banner** — one of
   `No box setup — mid-box` · `Waiting — at the edge, no trigger` ·
   `Blocked — session / risk state / volatility / feed` ·
   `Candidate, weak geometry` · `Candidate — conditions line up (context only)`.
   The banner never says "buy" or "sell"; the setup card does, and it is labelled
   context.
2. **Where the boxes are** — the engine's own 20-bar level, the last 1h (60 bars),
   the last 4h (240 bars) and the prior *trading* day (a Sunday evening is not a
   day to draw a box on), each with in-box position and $ distance to both edges.
3. **When to trade — the check**, seven measured preconditions:
   **Location** (≤ 0.5 ATR from an edge, or a live trigger at one) ·
   **Trigger** (a *fresh* close beyond an edge, or a rejection of it) ·
   **Feed** (last bar age; a closed market makes staleness expected, not a fault) ·
   **Session** (weekend / daily break / the engine's direction-aware blackouts) ·
   **Risk state** (SL cooldown, daily breaker) ·
   **Volatility** (the engine's own $1.10–$4.50 ATR band) ·
   **Geometry** (the spread as a share of R — the check that kills most box setups).
4. **If you take it** — entry, stop (past the far edge), target (measured move),
   risk, reward, R:R, the spread's share of R, and what the engine's structural
   stop would do on the same edge.
5. **Measured, not assumed** — the footer prints this document's verdict:
   8 geometries, 0 cleared the reference; 74–75% of breaks fail within 15 min.

**Why the checks and not a signal.** The measurement in §2 says a box breakout has
no edge; a panel that simply said "BUY" at an edge would be a lie with a nice
colour. The checklist answers the owner's actual question — *when* is a box trade
worth considering — by naming the conditions that must be true, and it refuses to
turn "all green" into a forecast. The geometry line is deliberately brutal: at
today's ATR a fade's stop is $0.66 and the $0.55 spread is **83% of R**, which is
the real reason most box trades lose.

**Architecture.** The read layer is `pressure.box_geometry()` (pure, cacheable)
plus `pressure.box_status()` (live checks). `pressure.py` stays stdlib-only and
read-only — Scenario U's AST checks still pass. `tools/box_report.py` now calls
the same `box_geometry()`, so the tab and the CLI cannot disagree about where a
box is. Dashboard geometry is cached against the log file's size+mtime; the
checks recompute on every request.

---

## 7. Next steps (in order, all optional)

1. Run `python3 tools/box_report.py` at the start of a session — boxes + the
   honest verdicts, one screen, no writes.
2. Log 100 manual box trades with the fields in §4.9 and judge them with the §4
   bar, not by memory.
3. Only if that clears: run the large-N H1 box test over broker history and
   pre-register a bar before anything touches `engine.py`.
