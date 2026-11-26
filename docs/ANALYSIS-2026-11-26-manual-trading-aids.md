# ANALYSIS 2026-11-26 — manual trading aids: what the repo can say to a hand-trader, and what it cannot

**Type:** feature + analysis note. **Scope:** *display-only* read layer. **Not** a strategy
change, **not** a pre-registration, **not** an exit/entry/sizing gate, **not** a cost
re-statement. `engine.py` and `trade_filter.py` are **untouched**; `SL_CLEAR_ATR` stays
`0.5`, `TRADING_MODE` stays `FORWARD_TEST`, the LIVE gate stays **CLOSED**.

**Owner request (2026-11-26):** *"Please follow execution plan and proceed with improvements,
if there's anything that can be helpful, when we are also manually trading, please help include
anything that can be helpful."*

**Why this is allowed by the plan.** §0 of `docs/EXECUTION-PLAN.md` bans real orders, strategy
variables moved outside a pre-registered window, and edits to the paper ledger. It does not ban
read-only tooling and documentation — Track C's own items are analysis, reports and
pre-registrations. This work is the same class as `box_report.py` / `pressure_report.py` /
`chart.py`: it reads the tape and the captured spec, computes arithmetic, writes nothing the bot
reads, and carries every measured caveat with it. The one place it duplicates engine logic (the
daily break) is pinned to the engine by a deploy-gate scenario.

---

## 1. What the tape already told us — the constraint the feature had to respect

Anything sold to a hand-trader as a "signal" has to get past five measurement notes already in
the repo, and none of them survive:

| Candidate aid | Measurement in this repo | Verdict |
|---|---|---|
| Box breakout / fade | **0 of 8** geometries (2 box sizes × 2 edges × breakout/fade) beat the driftless no-edge reference; 74–75% of closes outside a box are back inside within 15 min | no edge |
| 8/8 signal strength | 50.4% trade-way at 30 min [42–59]; a target prints before the stop in only ~1/3 of decisive races | no edge |
| Pressure composite as direction | collinear with side by construction (the trend gate makes BUYs score high) — no within-side contrast exists | untestable |
| Held-retest confirmation | 59.0% vs a 57.2% reference | no edge |
| The bot's own entries | book **negative at $0.00 cost** (−0.085R whole, −0.034R structural-stop era) | negative |

So the deliverable is not an indicator. It is the four things that are **arithmetic**:
where your stop goes, what that makes 1R worth, what the spread costs relative to it, and how
long you have before the daily break can make the stop unenforceable.

---

## 2. The base rates the cards are built on (measured 2026-11-26)

| Quantity | Value | Source |
|---|---|---|
| Decisive win rate, whole book | **33.4%** (236W/470L, 354BE, 4TIME, n=1064) | `trades.csv` |
| Decisive win rate, structural-stop era | **36.8%** (151W/259L, n=567) | `check_structural_stop.py --era clear05` |
| Median 1R (structural-stop era) | **$6.01** (p10 $3.42 / p90 $9.65) | inline era study |
| Round-trip spread | **$0.55** median, p90 $0.57, max $1.66, 486 joined trades | `xm_quote_report.py` |
| All-in modelled round trip | **≈$0.57** ($0.55 spread + $0.02 slippage, slippage unobservable) | `ANALYSIS-2026-11-22-a6-all-in-cost-model.md` |
| Registered cost **this** window | **$0.40** (deliberately unchanged; A6 §C override fires only > $0.70) | `REVIEW-2026-11-22-a6-cost-decision.md` |
| Same, from **2026-12-01 21:00 UTC** | **$0.57** | A6 decision, to be written into the next pre-registration |
| Book net at the registered cost | **−$867.35**; ledger $75.18 vs true equity $58.25 | `handoff_check.py` |
| Daily-break signature (observed) | **21:58 → 23:00 UTC** | `engine.derive_daily_closure` on the live log |
| Gap rides registered | **9** (threshold 2), 1 reopen gapped through its stop, 148 gaps classified | `check_gap_rides.py` |

Two consequences drive almost every number the tab prints:

1. **The break-even win rate is higher than the base rate.** At a 1:1.5 target with a $0.55
   round trip, a geometry needing 42–45% to break even is asking the trader to beat the 33–37%
   the book actually earns. That comparison is on the card, not buried in a doc.
2. **1R is the denominator of everything.** A $6 median 1R against a $0.55 spread is a 9% cost
   share — marginal. A 1.5 ATR stop on a quiet tape is ~$3.6 → 15%. **Nothing about a manual
   gold trade is decided by the entry.**

---

## 3. The measured cost ruler (the feature's headline table)

Spread $0.55 as a share of 1R, on ATR $2.43 (bar 14:59:08, 2026-11-26):

| Stop | $ | Cost share | Zone |
|---|---|---|---|
| 1.0 ATR | $2.43 | **22.6%** | red — above the LIVE path's own 20% veto |
| 1.5 ATR | $3.65 | 15.1% | amber |
| 2.0 ATR | $4.86 | **11.3%** | amber (just over the 10% line) |
| 2.5 ATR | $6.08 | 9.1% | green |
| 3.0 ATR | $7.29 | 7.5% | green |
| 4.0 ATR | $9.72 | 5.7% | green |

**Rule of thumb the tab states:** a stop of **≥ 2.3 ATR (~$5.50)** keeps the round trip under
10% of 1R; **≥ 3 ATR** is comfortable. Below 2 ATR, the spread — not the market — is your
biggest opponent. This is a re-statement of B4's `LIVE_COST_MAX_PCT_OF_R` at 20%, applied to
the manual trader's own geometry rather than the bot's.

**Sensitivity (what the reader should watch):** the share is linear in cost, so from
2026-12-01 the *same* geometry costs 3.6% more of 1R at $0.57 than at $0.55; the 10% line moves
from 2.3 ATR to 2.4 ATR. That is the whole effect of A6 on a hand-trade — small, and never the
reason a trade is bad.

---

## 4. Cost invariance, and why the size table exists

```
share_of_1R = cost ÷ risk      (independent of lot size)
lots        = budget ÷ (contract × |entry − stop|)   → snapped DOWN to volume_step
```

Because both risk and cost scale with size, **the ratio cannot be improved by trading bigger** —
only by widening the stop or getting a better price. Pinned by a test: the cost share is
identical across the whole budget row set. The table's job is therefore narrow and honest:
translate a risk budget into a broker-legal lot **without ever rounding up** (which silently
risks more than asked) and **without ever raising a size to the minimum** (which silently risks
more than the account's budget).

On the current tape: a $10 budget at a $9.96 stop → **0.01 lot** (margin $3.58 at 1:1000);
$20 → 0.02; $50 → 0.05; **$5 → refused**, "below the broker's minimum lot" (it needs 0.005).
Crucially the spec's **`volume_step` is 0.001**, so the true answer to "$10 at $8.37" is
**0.011 lot**, not 0.01 — the panel prints the broker's own grid, not `LOT_SIZE`.

---

## 5. The gap-ride exposure a manual position carries

The bot stops taking entries 30 min before the daily break (`GUARD_CUTOFF_MIN`, registered
2026-10-25) and reopens at the break's end; it can also reconcile against the broker. A manual
position gets no such treatment, and the ledger shows the cost:

| Case | What happened | Why it matters to a hand-trader |
|---|---|---|
| **#815** (2026-11-04) | opened 18:11, held through the 21:58 break, reopened **−$2.77 through its ratcheted stop** and was booked at the stop | a "can't move" stop did move — by the gap, not by the tick |
| **#95** (2026-10) | weekend stop gapped **$0.09** through, then printed a **TP** on a price that never traded while open | one of the book's "wins" is an artifact of not being able to trade |

Hence the clock on the tab: **open** (trade normally) / **guard** (inside the bot's pre-close
block — do not open a position you cannot watch) / **closed** (inside the break — stops cannot be
enforced; any working order is exposed to the reopen print) / **unknown** (no signature yet —
treat as open but verify). It **warns, never gates**: it cannot stop a human, so it does not
pretend to.

---

## 6. The tab/CLI map (what a reader should expect on screen)

| Block | Content | Source |
|---|---|---|
| Clock strip | state + minutes to close/reopen + the observed signature | `manual_plan.session_clock` |
| BUY card | entry / stop / TP, 1R in $ and ATR, cost share, break-even WR, bot gate count + missing factors, verdict | `manual_plan.plan` + `attach_bot_view` |
| SELL card | same, on the short side | idem, symmetric |
| Price check | what a *choice* of stop does to 1R, cost and sizes — the "your numbers" path | `plan(..., stop=)` |
| Size table | $5 / $10 / $20 / $50 → lots, $ risk, margin, or the refusal | `sizing_rows` |
| Cost ruler | ATR 1.0–4.0 → % of 1R at $0.40 and $0.55 | `chart.cost_ruler` |
| Footer | measured base rates: 0/8 box cells, ~74% re-entry, book negative at $0.00 cost; journal command | `read()["measured"]` |

`manual_plan.py` imports **only** the stdlib plus `chart` and `pressure` (both already part of
the dashboard layer). It never imports `engine.py` (asserted by a test), so a manual read cannot
touch the trading path even by accident — the price of that is one mirrored function, which
smoke Scenario AE pins.

---

## 7. What would make this bigger — and why it is not being done now

If the owner wants their own read tested rather than assisted, the route is `EXECUTION-PLAN.md`
§7 step **A8**: ≥100 matched post-stop observations in the private journal, then a **new dated
pre-registration** with a frozen statistic, one variable, and a boundary. Until then the journal
is an observation log: it may not become a gate, a dashboard colour, or a registered bar, and
this note must not be cited as evidence for one.

**Files:** `manual_plan.py`, `tools/manual_trade.py`, `tools/test_manual_plan.py`,
`docs/MANUAL-TRADING.md`, dashboard Manual tab, `tools/smoke_test.py` Scenario AE,
`tools/autosync.sh` (`DASH_CHANGED`).
