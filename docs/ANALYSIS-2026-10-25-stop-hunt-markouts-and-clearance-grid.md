# ANALYSIS — stop-hunt mark-outs and the stop-clearance grid (2026-10-25)

**Date:** 2026-10-25 ~03:30 UTC
**Data:** collection 334, through 2026-10-23 20:57 UTC (50 494 bars; 697 closed; struct-stop era n=200)
**Scope:** (1) descriptive, bounded mark-outs of the "hover — tag — bounce" stop-hunt pattern the
owner described; (2) a costed, stateful replay of the stop-clearance grid
(`tools/strategy_lab.py`, new variant `structstop1.5`).
**Status:** evidence recorded. **No engine, filter, gate or runtime change. No ledger change.
No deploy.** The replay result makes `structstop1.5` a *pre-registration candidate* — it is not
registered and nothing may be deployed on the strength of this document.

## 1. The question

Owner observation (2026-10-25): price often hovers around the stop, tags it, and bounces back;
some traders deliberately place their stop slightly past the level the instrument suggests, to
avoid exactly that. Two measurable questions follow:

1. How often does the tape actually do this on the bot's own stopped trades, and how deep does
   the "hunt" go past the stop?
2. If the structural stop's clearance beyond the tested level is widened (0.25 / 0.5 live / 1.0 /
   1.5 ATR), what does the costed, stateful replay say — under the registered $0.40 round trip and
   the measured $0.55 round trip?

## 2. Descriptive stop-hunt mark-outs (new tool: `tools/stop_hunt_markout.py`)

Bounded 24 h mark-outs on observed log bars only (gaps are never bridged), struct-stop era
(n=200: 55W/90L/53BE/2TIME). Reproduce: `python3 tools/stop_hunt_markout.py`.

**Pre-exit hover near the original stop level** (selection caveat: the stop is the boundary —
approaching it is a prerequisite to printing, so this is context, not a predictor):

| band | SL trades | TP wins | BE scratches |
|---|---|---|---|
| within 0.25R before the exit bar | 76/90 (84%) | 7/55 (13%) | 9/53 (17%) |
| within 0.10R before the exit bar | 50/90 (56%) | 3/55 (5%) | 4/53 (8%) |

**After an SL print — time to return to entry (24 h horizon):**

| return to entry | ≤15 m | 15–60 m | 1–4 h | 4–24 h | never in 24 h |
|---|---|---|---|---|---|
| of 90 SLs | 24 (27%) | 28 (31%) | 17 (19%) | 10 (11%) | 11 (12%) |

**Hunt depth past the stop before a ≤15 m bounce:** median **0.17R** (≈0.57 ATR), p75 0.49R
(≈1.6 ATR), max 1.06R. With the live stop at level + 0.5 ATR, the *median* hunt reaches ≈1.1 ATR
beyond the tested level; the p75 hunt ≈2.1 ATR.

**Full signature (SL → back to entry ≤15 m → TP within 24 h):** 21/90 SLs (23%). Of the 24 fast
bounces, **21 (88%) reached the target within 24 h**.

**Symmetry check (why mark-outs alone cannot justify a stop change):** 16/55 TP wins (29%)
survived an adverse move ≥0.5R before printing their target (median winner MAE 0.31R). The same
adversity that hunts losing stops routinely threatens winning trades; what decides expectancy is
the base rate against cost, not the existence of the hunt. This is also the reason the plan's
guardrail — never widen a live stop because selected examples recovered — binds: the 88% figure
is a bounded mark-out with survivorship, not a rule.

## 3. The clearance grid (costed, stateful replay)

**Method.** `tools/strategy_lab.py --table --only baseline,structstop0.25,structstop,structstop1.0,structstop1.5`
— every cell is a full independent cascade restarted at the era boundary, with production
cooldown/breaker/blackout/ratchet semantics and the pessimistic same-bar ordering (stop wins
inside one bar). The "post-cutover" era row (entries ≥ 2026-10-06 03:00 UTC) is the real
measurement; earlier eras are counterfactuals. Calibration was re-verified after the one-line
variant addition: entry-stream recall 99.8% (unchanged); `tools/smoke_test.py` PASSED.
`structstop1.0` already existed; **`structstop1.5` was added this session** (one VARIANTS entry,
no other code change).

**Grid and decision bar — declared before the replay was read.** Grid points {0.25, 0.5, 1.0,
1.5} ATR: 0.5 = live; 1.0 ≈ the measured median hunt depth beyond the level (≈1.1 ATR); 1.5 sits
between the median and p75 hunt; 2.0 excluded a priori (median risk would exceed ~4.5 ATR and the
entry gate caps ATR at 4.50). A variant earns *pre-registration eligibility* only if, vs `structstop`
(live, 0.5) on the post-cutover era, **all** of:

1. net R/trade improves ≥ **+0.05R** at the registered $0.20/side **and** still beats live at the
   measured $0.275/side;
2. decisive WR does not drop;
3. max drawdown is not >25% worse;
4. trade count falls by ≤15% (sample integrity — an improvement bought by trading less is the
   ratchet-off trap, HANDOFF §6 item 2).

**Results — post-cutover era, net R/trade by cost (stateful cascade):**

| cost/side | baseline (2·ATR/3·ATR) | 0.25 ATR | **0.5 ATR (live)** | 1.0 ATR | 1.5 ATR |
|---|---|---|---|---|---|
| $0.00 | −0.005 | −0.030 | −0.022 | −0.005 | **+0.060** |
| $0.15 | −0.098 | −0.092 | −0.082 | −0.058 | +0.015 |
| $0.20 (registered) | −0.130 | −0.112 | −0.102 | −0.076 | **−0.000** |
| $0.275 (measured $0.55 RT) | −0.176 | −0.143 | −0.132 | −0.103 | **−0.023** |
| $0.35 | −0.223 | −0.174 | −0.162 | −0.130 | −0.045 |

**Full rows, post-cutover era** (net of cost; $0.20/side then $0.275/side):

| variant | n | decWR | SL% | BE% | T | R/t | $/t | $/day | n/day | hold | maxDD | avgSL$ | avgTP$ | payoff | medR$ | medR·ATR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline ($0.20) | 315 | 39.7% | 41.0 | 32 | 0 | −0.130 | −0.454 | −8.95 | 19.7 | 9.0 m | 164.7 | −3.85 | 4.64 | 1.20 | 3.18 | 2.00 |
| structstop0.25 ($0.20) | 220 | 38.4% | 44.5 | 28 | 0 | −0.112 | −0.679 | −9.34 | 13.8 | 22.0 m | 181.2 | −6.13 | 7.79 | 1.27 | 5.24 | 3.13 |
| **structstop — live ($0.20)** | 207 | 38.7% | 42.0 | 30 | 2 | −0.102 | −0.676 | −8.74 | 12.9 | 26.1 m | 174.1 | −6.41 | 8.06 | 1.26 | 5.43 | 3.33 |
| structstop1.0 ($0.20) | 190 | 39.8% | 37.4 | 36 | 4 | −0.076 | −0.599 | −7.11 | 11.9 | 31.0 m | 167.4 | −7.17 | 9.10 | 1.27 | 6.20 | 3.80 |
| **structstop1.5 ($0.20)** | 163 | 43.1% | 35.6 | 34 | 5 | **−0.000** | −0.221 | −2.26 | 10.2 | 37.0 m | 165.3 | −8.34 | 10.30 | 1.23 | 7.11 | 4.37 |
| structstop — live ($0.275) | 207 | 38.7% | 42.0 | 30 | 2 | −0.132 | −0.826 | −10.68 | 12.9 | 26.1 m | 201.6 | −6.56 | 7.91 | 1.26 | 5.43 | 3.33 |
| **structstop1.5 ($0.275)** | 163 | 43.1% | 35.6 | 34 | 5 | **−0.023** | −0.371 | −3.78 | 10.2 | 37.0 m | 183.3 | −8.49 | 10.15 | 1.23 | 7.11 | 4.37 |

**Bar scorecard (post-cutover, vs live 0.5):**

| | structstop1.0 | structstop1.5 |
|---|---|---|
| 1. ≥+0.05R at $0.20 and still better at $0.275 | **FAIL** (+0.026R / +0.029R) | **PASS** (+0.102R / +0.109R) |
| 2. decisive WR no drop | PASS (39.8 vs 38.7) | PASS (43.1 vs 38.7) |
| 3. maxDD within 25% | PASS (167.4 vs 174.1) | PASS (165.3 vs 174.1 at $0.20) |
| 4. trade count within 15% | PASS (190 vs 207, −8.2%) | **FAIL (163 vs 207, −21.3%)** |

**Reading the 1.5 trade-count miss:** the mechanism is disclosed, not an artifact — a deeper stop
means longer holds (median 37 m vs 26 m) and a further target (1.5 × $7.11 = $10.30 vs $8.06), so
more trades hit the 240-min TIME cap (5 vs 2) and fewer re-entry slots fit in the ~3-week window.
Even so, 10.2 trades/day would reach n=150 in ~15 days — statistical power is not the concern;
the bar flags that part of the improvement is "fewer, longer, more survivable" rather than
"same activity, better outcomes."

## 4. Interpretation and verdict

1. **The owner's hypothesis is the strongest directional evidence this project has produced.**
   The geometry lever works monotonically in the same direction it worked on 2026-10-06: at every
   cost tested, deeper > live > 0.25 > baseline (old geometry). The old 2·ATR/3·ATR geometry is
   worst at every cost — the 10-06 structural change was not a fluke; it was the first step of
   this same lever. `structstop1.5` is the first variant in the era at **breakeven net** at the
   registered cost (−0.000R; −$0.221/trade) and −0.023R at the measured $0.55 round trip.
2. **It is a hypothesis with a number, not a demonstrated edge.** Four caveats bind the reading:
   - **Same-bar convention:** the replay's pessimistic ordering (stop wins inside one bar)
     systematically favours deeper stops on tag-and-bounce bars — the within-bar tick order is
     unknown, so the +0.10R may be overstated versus real ticks. The mark-outs say the bounces
     really happen (27% within 15 m), so this is not pure artifact — but only a forward window
     with real data adjudicates it.
   - **Grid selection was mark-out-triggered:** the 1.0/1.5 points sit at/past the measured median
     hunt. That is a named-hypothesis exploration, not a blind scan — and **no further point
     tuning is allowed** (2.0 ATR would need its own registration, as would any new point).
   - **Era truncation:** the window is ~3 weeks and TIME-capped; the deeper arm's longer holds
     make the window tail mildly unfavourable to it (disclosed in §3).
   - **The era is still negative overall** and the whole book is negative after cost. This
     changes the *next experiment*, not the verdict.
3. **Verdict:** `structstop1.5` is a **pre-registration candidate** (not registered).
   `structstop1.0` fails bar 1 and is recorded as measured-and-insufficient — do not re-litigate
   it without new pre-registered evidence. No live change is made or recommended by this document.

**Proposed pre-registration (NOT registered — owner sign-off required; bars mirror the
2026-10-05 registration's structure and revert rules):**

- **One variable:** `SL_CLEAR_ATR = 0.5 → 1.5`. TP stays 1.5 × actual risk (it scales with the
  stop by construction). Ratchet 0.75R, entries, blackouts, cooldowns, daily breaker: frozen.
- **New isolation window** dated from the host's `autosync: merge upstream` deploy time (the
  10-13 erratum rule), never from the plan or the PR merge.
- **SCREEN** (n=150 or 10 trading days, whichever comes first): the five 10-05 SCREEN checks
  (SL/day ≤ 6.5; SL share ≤ 47.0%; scratch ≤ 35.0%; gross R ≥ −0.10R; decisive ≥ 36.0%) **plus**
  net R/trade ≥ −0.10R at the then-registered cost.
- **PASS** (n ≥ 150): SCREEN maintained **and** net R/trade ≥ 0.00R (the costed bar — the point
  of this experiment) with the decisive-WR Wilson lower bound > 32.1%.
- **REVERT** (any time): net R/trade ≤ −0.20R (R4-style); era drawdown > $250 (R7-style); average
  SL loss > 2.2× the pre-change (R5-style); or the §7 closure-gap trigger firing under the
  counting rule then in force.
- **Sequencing:** the fired §7 gap trigger puts the owner's gap-guard decision **first** in the
  registered queue; this stop change must not stack on the open window. If the owner resolves the
  guard question, this is the next — and only — variable for the following window.

## 5. Operational note for manual positions (context, not a rule)

The measured typical hunt reaches ≈1.1 ATR beyond the tested level (median); the live bot stop
(level + 0.5 ATR) sits **inside** the median hunt. If the owner gives a *manual* position room
past the typical grab, the measured room is ≈1.5 ATR beyond the tested level (p75 ≈2.1 ATR).
This is the same number the replay favours, and it is context for the owner's own watch — it
gates nothing, and the manual-journal bar (≥100 closed rows, positive after measured costs) still
applies to any method claim.

## 6. Reproduction

```bash
python3 tools/stop_hunt_markout.py    # §2 mark-outs (read-only, era or --era all)
python3 tools/strategy_lab.py --calib-only   # calibration gate (99.8% at this data)
python3 tools/strategy_lab.py --table --only baseline,structstop0.25,structstop,structstop1.0,structstop1.5
```

The measured-cost single point ($0.275/side, post-cutover window) is not in the table's fixed
cost set; it was computed with the lab's own `run()` (no reimplementation):

```python
import sys; sys.path.insert(0, "tools")
import strategy_lab as SL
lab = SL.Lab(SL.load_bars()); first = lab.ready[0]
for nm in ("baseline","structstop0.25","structstop","structstop1.0","structstop1.5"):
    trs,_ = lab.run(dict(SL.VARIANTS[nm][1]), first_i=first, cost_per_side=0.275,
                    window=(SL.LIVE_CUTOVER, None))
    # same per-row stats as the --table section (summarize() prints n/W/L/BE/T, WR, net, R)
```

**Verification (this session):** `python3 -m py_compile tools/strategy_lab.py` OK;
`--calib-only` recall 99.8% (unchanged); `python3 tools/smoke_test.py` → **SMOKE TEST PASSED**.
