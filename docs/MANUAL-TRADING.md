# MANUAL TRADING — the operator's own playbook, and what the repo can honestly tell them

**Status:** display-only feature, landed 2026-11-26. **No `engine.py` / `trade_filter.py`
change, no parameter, no gate, no exit, no sizing rule, no cost assumption.** The open
`structstop1.5` window, the registered `$0.40` round trip and the LIVE gate
(**CLOSED**) are untouched. Nothing in this document, the `🤝 Manual Trade` dashboard tab
or `tools/manual_trade.py` can place an order, write a bot file or open the gate.

**Owner ask (2026-11-26):** *"Please follow execution plan and proceed with improvements —
if there's anything that can be helpful when we are also manually trading, please include
anything that can be helpful."*

---

## 0. The honest answer, first

The repo has measured, on its own tape, that **the classic reasons to enter a gold trade do
not survive contact with the data**:

| Claim | Measurement | Doc |
|---|---|---|
| "A box breakout works" | **0 of 8** geometries (2 box sizes × breakout/fade) cleared the driftless no-edge reference; 74–75% of closes outside a box are back inside within 15 min | `ANALYSIS-2026-10-20-box-theory-manual-trading.md` |
| "An 8/8 signal is a strong signal" | 50.4% trade-way at 30 min [42–59]; the target prints before the stop ~1/3 of decisive races where the 1:1.5 geometry needs 40% | `ANALYSIS-2026-10-19-signal-outlook.md` |
| "The pressure gauge tells you the direction" | Collinear with side — the trend gate makes BUYs print high and SELLs low, so there is no within-side contrast to test | `ANALYSIS-2026-10-16-dashboard-pressure.md` |
| "Waiting for the held retest fixes it" | 59.0% vs a 57.2% reference — no edge | `ANALYSIS-2026-10-21-box-chop-retest-alerts.md` |

And the bot itself is **negative before costs** (−0.085R whole book, −0.035R in the
structural-stop era, at $0.00 cost — `ANALYSIS-2026-11-22-a6-all-in-cost-model.md` §5). So the
useful thing a manual trader can take from this repo is **not a signal**. It is the three
things that are arithmetic rather than belief:

1. **Where the stop goes** — and therefore what 1R is worth in dollars.
2. **What the spread costs as a share of that 1R** — the single most expensive mistake in
   manual gold scalping, and pure arithmetic.
3. **How long until the daily break makes the stop unenforceable** — the gap risk the engine
   guards against and a manual position does not.

That is exactly what the new tab and CLI compute. **R ≥ 10 × round-trip cost** is the one-line
rule the whole feature exists to make visible: at the measured $0.55 round trip, a manual stop
must be **≥ ~5.5/oz** wide (≈ **3 ATR** on a quiet tape) or the spread alone eats more than
10% of the risk before the market does anything.

---

## 1. What shipped

| File | What it is |
|---|---|
| `manual_plan.py` | The read layer (stdlib only, **no engine import**, writes nothing): the structural stop on your entry, cost as a share of 1R, break-even win rate, a lot-size table on the broker's own grid, the observed daily-break clock, and the private-journal schema. |
| `tools/manual_trade.py` | The CLI: `python3 tools/manual_trade.py` prints the read; `--side/--entry/--stop/--budget` judges **your** numbers; `--log-decision` appends one journal row; `--journal-summary` counts rows. |
| `dashboard.py` → **🤝 Manual Trade** tab (`?tab=manual`) | The same read as cards: both sides' entry/stop/target/1R, the size table, the daily-break clock, the cost ruler, and the journal command. Display-only, no form, no input, no button. |
| `tools/test_manual_plan.py` | **39 hermetic tests** (no live CSVs, no clock, no network). |
| `tools/smoke_test.py` **Scenario AE** | 8 deploy-gate checks, including the one that matters: the manual daily-break mirror must equal `engine.derive_daily_closure()` on the live log. |
| `tools/autosync.sh` | `manual_plan.py` added to `DASH_CHANGED` (and the hand-edit detector): it restarts the **dashboard**, never the engine. |

---

## 2. The four numbers, and how each one is built

### 2.1 The stop and 1R

The tab proposes the **engine's own** stop rule on the level the entry was built on:

```
risk = max(ATR_SL_MULT · ATR,  |entry − level| + SL_CLEAR_ATR · ATR)
```

with the *same* constants the engine runs (`ATR_SL_MULT = 2.0`, `SL_CLEAR_ATR = 0.5`,
`RR_TARGET = 1.5`) imported from `pressure.py`, which Scenario U already pins to `engine.py`.
Two consequences worth stating:

* If the level is further than 2 ATR away, the **level** sets the risk, not the ATR. On the
  current tape that is 4.1 ATR on the BUY side — which is why the BUY card costs 6% of 1R
  while the SELL card (2.0 ATR) costs 11%.
* A stop that would sit **inside** the tested level is refused outright. That is not a
  preference: it is the defect that made 64% of the pre-2026-10-05 book's stops fire without
  any structural break (`ANALYSIS-2026-10-05-stop-loss-geometry.md`).

A stop on the *winning* side of the level is not a constraint (the floor under a BUY only
matters once price is above it) and is deliberately not flagged.

### 2.2 The cost share — and the break-even win rate

```
share  = round-trip cost ÷ 1R                (invariant to lot size)
net R:R = (reward − cost) ÷ (risk + cost)
break-even decisive WR = 100 ÷ (1 + net R:R)
```

The share is the same at 0.01 lot and at 5 lots — a bigger size changes the dollars, never the
ratio. Zones: **green ≤ 10%**, amber ≤ 20%, **red > 20%** (the LIVE path's own
`LIVE_COST_MAX_PCT_OF_R` veto — quoted, not re-invented).

The break-even WR is the number to compare with the evidence: the book's decisive win rate is
**33–37%**, so any geometry whose break-even WR is above that is asking you to beat the base
rate. On the current tape the BUY card needs **42%** and the SELL card **45%** — i.e. both are
*above* the measured base rate. That is the honest answer, and it is printed on the card.

### 2.3 The size table

```
lots = risk budget ÷ (contract size × |entry − stop|)     → snapped DOWN to volume_step
```

Every row is the **same trade at a different size**, so the cost share never moves. The
critical behaviours (all pinned by tests):

* **snap down, never up** — rounding up silently risks more than you asked for;
* **below `volume_min` → refused, not raised** — same reason in the other direction. On the
  current tape a $5 budget at a $9.96 stop needs 0.005 lot, which is not tradeable; the table
  says so instead of pretending;
* the contract facts (100 oz/lot, grid, point, leverage) are read from the logger's captured
  `xm_data/symbol_spec.json` at run time, and the panel says **"DEFAULT constants"** when no
  spec has been captured. B4's own lesson applies: read the spec, don't hard-code it.

Margin is `lots × contract × price ÷ leverage` using the captured **1:1000**; it is indicative
and ignores hedged/partial fills.

### 2.4 The daily-break clock

The bot refuses new entries in `[daily_close − 30 min, daily_reopen)`
(`GUARD_CUTOFF_MIN`, registered 2026-10-25). A manual position has no such guard, and the
ledger shows why that matters: **#815** rode the 2026-11-04 break as a ratcheted scratch and
reopened **$2.77 through its stop**; **#95** reopened $0.09 through a weekend stop and printed
a **TP** off a price that never traded while it was open (`tools/check_gap_rides.py`).

The clock therefore reports one of four states: **open** / **guard** (inside the bot's
pre-close block) / **closed** (inside the break) / **unknown** (no signature yet). The
signature is the **mode of the last five observed 30–180 min holes** in the price log.

**It is a mirror, not the engine.** `manual_plan.observed_closure()` must not import
`engine.py`, so it does not re-implement the engine's ±60 min DST adaptation — it reports the
observed mode and labels itself `source="observed"`. **Scenario AE pins it to
`engine.derive_daily_closure()` on the live log** (currently `21:58 → 23:00` UTC both sides),
so a drift turns the deploy gate red. When they ever disagree, the engine is right.

---

## 3. Using it

### 3.1 The dashboard

**🤝 Manual Trade** (`?tab=manual`). Read it top to bottom:

1. **the clock** — is the daily break close enough to matter?
2. **BUY / SELL cards** — proposed entry/stop/target, 1R in $ and ATR, the cost share, the
   break-even WR, the size table for $5/$10/$20/$50, and the bot's own gate count
   (*context, never a veto* — you are allowed to take a trade the bot would skip; just do it
   knowingly);
3. **the cost ruler** — spread as a share of 1R for 1.0 → 4.0 ATR stops, at both the
   registered $0.40 and the measured $0.55;
4. **the journal command** — the exact line to record what you actually did.

### 3.2 The CLI

```bash
python3 tools/manual_trade.py                                  # both sides, live numbers
python3 tools/manual_trade.py --contract-ruler                 # just the ATR/cost table
python3 tools/manual_trade.py --json                           # machine-readable

# Judge YOUR geometry instead of the proposed one (one code path, so no number is stale):
python3 tools/manual_trade.py --side SELL --entry 3580.63 --stop 3589.00 --budget 10
python3 tools/manual_trade.py --side BUY  --entry 3580.63 --stop 3570.67 --target 3600 --budget 20
```

**Paths.** With no flags the tool reads `/opt/gold` when that directory exists and otherwise
the checkout it is run from, so a fresh clone prints real numbers instead of an empty read;
`--dir` / `--log` / `$GOLD_DATA_DIR` still win.

### 3.3 The private journal — the only path to ever testing your own idea

`docs/EXECUTION-PLAN.md` §7 defines the record; `--log-decision` writes exactly those fields,
in that order, to a **host-local** JSONL file:

```bash
python3 tools/manual_trade.py --log-decision \
  --side BUY --entry 3580.63 --stop 3571.89 \
  --reason-code level_retest --action took_it \
  --exit-rule "stop or 1.5R, 240 min max" --post-stop 15,30,60 \
  --notes "wick rejection at the 20-bar floor, no news"

python3 tools/manual_trade.py --journal-summary     # counts by side / action / reason only
```

Rules the tool enforces, and why:

* **Record the decision BEFORE the outcome.** The timestamp is not auto-filled when you leave
  it out, precisely so a row cannot look retrospective-proof when it is not.
* **Record the losses and the no-trades.** A journal of wins measures memory.
* **It refuses to write inside the checkout.** Filled rows stay private. The default is
  `/opt/gold/manual_trade_journal.jsonl` on the host, and when there is no `/opt/gold` the
  tool reads the checkout you are standing in but writes the journal to
  `$XDG_STATE_HOME/gold/` (`~/.local/state/gold/`) — **never** under the repo. Override with
  `$GOLD_MANUAL_JOURNAL_FILE` (`docs/MANUAL-TRADING.md`).
* **It refuses credential-shaped fields** (`*login*`, `*account*`, `*server*`, `*token*`…), and
  `--journal-summary` prints counts only — never your notes.

When there are **≥100 matched post-stop observations**, that is when a *new dated
pre-registration* can test the owner's pressure/hold hypothesis (`EXECUTION-PLAN.md` §7,
step A8). Until then it is an observation log, not evidence — and nothing in it may become an
engine gate, a dashboard colour or a change to a registered bar.

---

## 4. What this deliberately does **not** do

* **No signal.** Every card carries the measured base rate; a "GEOMETRY OK" verdict means the
  *stop and the cost* are sane, not that the trade will win.
* **No direction call.** The pressure composite is a side proxy (§0), so the tab shows the
  bot's gate count as context and never a green light.
* **No order, no arming, no sizing of anything real.** It cannot place a trade and it does not
  talk to the broker; the margin/leverage figures are arithmetic on a captured spec.
* **No file writes from the dashboard.** The only write in the whole feature is the CLI's
  opt-in journal append, outside the repo.
* **No new indicator.** Fibonacci, pivots, round numbers, VWAP and volume profile stay refused
  for the reasons in `PROPOSAL-2026-10-23-manual-chart-tab.md` — unmeasured, or built on data
  this feed does not carry.

---

## 5. Verification (all run in this session)

```bash
python3 tools/test_manual_plan.py                      # 39 tests OK
python3 tools/smoke_test.py                            # SMOKE TEST PASSED (incl. Scenario AE)
python3 tools/test_dashboard_context.py                # 17 OK  (the existing tabs still render)
python3 tools/check_data.py                            # 0 fail / 9 documented warnings
python3 tools/live_readiness.py                        # 17 PASS / 0 TODO / 3 MANUAL, gate CLOSED
python3 tools/manual_trade.py                          # the read, on the live checkout
```

**A green result here is a code check, not evidence of an edge, and never permission to go
live.** `TRADING_MODE` stays `FORWARD_TEST`, `SL_CLEAR_ATR` stays `0.5`, and G2 (real money)
remains a separate, explicit, informed owner decision.
