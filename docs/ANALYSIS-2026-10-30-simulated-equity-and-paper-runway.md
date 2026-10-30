# ANALYSIS — the simulated balance is a counter, not capital: should it be increased? (2026-10-30)

**Question asked (owner, 2026-10-30):** *"Follow execution plan, simulated equity is down to 52 usd, should we increase it?"*
**Short answer:** **No — not now, not ever.** The owner signed **"no rebaseline ever — let it go negative"**
on 2026-10-30 (**§8 = the decision; it supersedes §5, which is the rebaseline-at-zero proposal he declined and
which stays on the record unsigned**). So: no top-up, no reset, no ledger edit — the book is expected to cross
zero and keep trading on a negative balance. §3 shows exactly what a top-up would and would not buy: it buys
**nothing** the experiment needs, and it destroys the one number that is currently telling the truth.
**Read §8 first if you are only reading one section.**
**Verdict type:** accounting/process decision — **no parameter, no code, no deploy, no order, no ledger row touched.**
Re-run the numbers any time: `python3 tools/equity_runway.py` (read-only; 18 tests in `tools/test_equity_runway.py`).

---

## 1. What was actually asked, and what the number is

`status.json` says `equity: 52.98`. That is the **engine's paper ledger**, and it is not the whole story:

| figure | value | definition |
|---|---|---|
| engine ledger | **$52.98** | `status.json.equity` — `Balance_After` of the last closed trade |
| **true equity** | **$36.05** | $500 start **+ summed ledger P&L** (`tools/handoff_check.py`'s definition) |
| drift | **$16.93** | historical balance resets, *not* trading (`docs/REVIEW-2026-09-09.md`) |
| net P&L at the registered $0.40 round trip | **−$767.15** | every trade charged, scratches included |

Book at this snapshot (collection **381**, bar log through `2026-10-30 02:59:04 UTC`):
**758 closed — 150W/334L/271BE/3TIME, decisive 31.0% [27.0–35.2]**, gross −0.149R/trade,
net −0.248R/trade at $0.40. Structural-stop era **n=261** — decisive **34.6% [28.1–41.6]**,
gross **−0.098R/trade**, net **−0.170R/trade**, median 1R **$5.55**, era DD **$191.04**.
One position open (**SELL #759**). Ritual: `check_data` 0 fail/8 warn, `handoff_check` FRESH,
`check_structural_stop` PASS (0 inside level, +0.50 ATR), `check_gap_rides` 3/2 with 0 damage,
`live_readiness` 11 PASS / 6 TODO / 3 MANUAL, **LIVE GATE CLOSED**.

---

## 2. Why "increase it" is not a strategy question

The paper book trades a **fixed 0.01 lot**, by design and by correction:

```python
# engine.py — size_lots()
base = getattr(self, "account_balance", None)
if not base:
    return LOT_SIZE          # paper: no broker account exists -> always 0.01
```

`docs/PREREG-2026-10-17-risk-sizer.md` §"ERRATUM 2" is explicit about why it must stay that way: sizing the
paper book off its own ledger balance would have **skipped 76% of setups** and changed lot size to 0.02 on
16/127 era trades back when the ledger was at $500 — a flow stop and a confound, not an R-invariant no-op.

So the balance is used for **nothing** on the paper path. It does not touch an entry, an exit, a lot, the
BE ratchet, the 240-min stop, the daily-loss breaker (count-based, `MAX_DAILY_LOSSES = 10`) or the gap guard.
Changing it moves **no trade**, and by extension **no bar**:

| registered judgement input | computed from | moves if the balance is re-based? |
|---|---|---|
| R/trade, decisive WR, Wilson CIs | `Profit ÷ risk` per row | **no** |
| era drawdown (**$191.04**) — A5's `≤ $200` and REVERT's `> $250` | the era's cumulative **P&L** curve | **no** |
| `net_pnl_usd_at_cost` (−$767.15) | summed `Profit`, not the balance | **no** |
| `true_equity` ($36.05) | $500 + summed `Profit` | **no** — by construction |
| `engine_ledger_usd` ($52.98) | `status.json` | **yes** — and that is the *problem* (§4) |

That table is the whole argument. A top-up is **not measurable in the experiment** — it can only change
presentation, and it can only change presentation *in one direction*.

---

## 3. What a top-up would buy (nothing) vs cost (the record)

**It would not buy more evidence.** Statistical power is a function of **n**, not of dollars. The PASS/REVERT
bar in `docs/PREREG-2026-10-26-structstop1.5.md` §5 counts trades (n = 100 / 150) and reads R and $. Running
the same 150 trades on a $5,000 ledger produces *the same 150 trades and the same R/trade* — with a bigger
dollar number attached to a negative expectancy.

**It would not extend the sample.** It extends only the *reporting* of the sample, by postponing the moment the
number reaches zero. The trades keep coming at the same rate either way; the engine keeps trading on a negative
balance (startup deliberately preserves a finite ledger balance even when it is zero or negative —
`docs/REVIEW-2026-10-19-negative-balance.md`).

**It would destroy the only live audit trail of the loss.** A ledger edit with an unchanged trade count is
exactly what the repo's own machine check calls tampering:

> "money — `engine_ledger_usd` / `true_equity_usd` / `net_pnl_usd_at_cost` may differ only as far as the
> closed-trade gap can explain … **with an unchanged trade count they must not move at all**."
> — `tools/handoff_check.py`

A quiet $52.98 → $500 edit turns `handoff_check` **STALE**, and that STALE verdict would be *correct*: it is
the same failure class as the 2026-09-09 incident, where three silent `Balance_After` resets to $500
**erased $24.74 of real losses** and made the reported equity wrong until someone reconstructed it from the
ledger (`docs/REVIEW-2026-09-09.md` #1). The $16.93 drift still in every number above is that incident's
signature. Doing it deliberately would be the same act with a paper trail.

**And it would answer the wrong question.** The number is down because the book has **no demonstrated edge
after cost**: −0.170R/trade net in the era, and B2 (SL share) is now a fresh **FAIL** at 47.1% vs the 47.0%
bar. Topping up the ledger so a negative-expectancy strategy can keep losing is not risk management; it is
removing the one instrument that is registering the loss.

**One thing it *would* buy:** keeping the dashboard's `Δ from $500 start` panel meaningful, and keeping the
ledger out of negative territory, where percentages and "equity −x%" stop parsing sensibly. That is a real but
**cosmetic** motivation — and the honest fix for it is §5's declared rebaseline at zero, not a top-up now.

---

## 4. The real issue the question exposes: runway, and no floor

The engine has **no balance floor**. Nothing stops the paper book at zero, and at the era's burn rate the
ledger reaches zero soon:

| input | value | source |
|---|---|---|
| net burn per closed trade (era, $0.40 RT) | **−$0.94** | −0.170R/t × median 1R $5.55 |
| pace | **13.1 trades per active day** | 261 era trades over 20 active days |
| true equity left | **$36.05** | 500 + summed P&L |
| **runway** | **≈38 closed trades ≈ 2.9 trading days** | `tools/equity_runway.py` |
| bootstrap 90% range | **33 → 336 trades** | 2 000 resamples of the era's R/trade; **6% of draws have no burn at all** |

The range is the important part, and it is not a hedge: **the era's R/trade is not statistically separated from
zero** (gross CI [−0.218, +0.025] at n=261; 6% of bootstrap draws are break-even or better). At the measured
$0.55 round trip the runway is **≈33 trades**. So:

* the **honest statement** is "roughly 3 trading days of runway at the point estimate, and it could be a
  fortnight or it could be a week — n=261 cannot resolve a −0.098R/trade book", not "we are about to blow up";
* but **something must be decided before** those ~38 trades are consumed, because the alternative is a
  decision taken at or after the event — i.e. the one kind of decision this repo does not allow.

---

## 5. The pre-registered rule (this is the recommendation)

Written now, before it fires, so it can never be a rescuer of a bar:

> **PAPER-LEDGER REBASELINE RULE (registered 2026-10-30, `tools/equity_runway.py` checks it).**
> 1. While **true equity > $0.00** there is **no** top-up, rebaseline or balance edit of any kind. The ledger
>    stays a single unbroken record across the open `structstop1.5` window.
> 2. **The trigger is mechanical and only one thing counts:** the first closed trade that leaves
>    **true equity ≤ $0.00** (true equity = $500 + summed `Profit`, *not* `status.json.equity`).
>    `python3 tools/equity_runway.py --strict` exits 1 at that moment.
> 3. **When it fires**, a rebaseline is performed *as a declared accounting event*, by the operator on the host,
>    with the engine stopped:
>    a. copy `trades.csv`, `status.json`, `forward_test_log.csv` to a private, git-ignored
>       `incident_backups/<UTC>/` (§4 of `docs/REVIEW-2026-10-19-negative-balance.md` — the existing pattern);
>    b. keep **every row and every trade number**; nothing is deleted or rewritten; numbering continues
>       (no `#1` reset — that is what produced the duplicate-number defects);
>    c. set the ledger to **$500.00** and publish **one** row-level marker documenting the jump and its reason,
>       so `handoff_check`'s money drift is explicable rather than silent;
>    d. record the event in a dated `REVIEW-…-paper-ledger-rebaseline.md`: true equity at the fire, the trade
>       number, the collection id, the drift carried forward and the archived path;
>    e. **no parameter, no code and no era boundary changes.** The rebaseline is *not* a new forward window and
>       creates no new isolation era: R/trade, decisive WR, era DD and the registered PASS/REVERT bars are all
>       computed from per-trade P&L and are unchanged by it (§2 table). Mislabelling it as "a fresh $500 test"
>       would be the exact re-slicing the plan forbids — it is the *same* book with a renamed denominator.
> 4. **What it does not authorise:** re-opening a lapsed arm, resetting n, restarting the A2 window, changing a
>    threshold, or any LIVE-path action. It also does not authorise going the other way — an owner who wants the
>    ledger *lowered* or the last $36 declared spent must say so explicitly; that is a stopping decision, not a
>    rebaseline.
> 5. **If the owner prefers never to rebaseline:** then the paper book simply goes negative and keeps trading
>    (a supported state, already covered by the restart tests). Nothing in the analysis breaks — but say that
>    out loud now, because a negative `equity` on the dashboard is indistinguishable from *the 10-19 phantom
>    incident* to anyone reading it later.

**Why this and not "increase it now":** an increase *now* is an edit inside an open window, motivated by a
number the owner finds uncomfortable — the textbook outcome-driven edit. An increase *at the registered fire
point* is an accounting consequence of the strategy losing the simulated stake, recorded in advance, and it
costs the experiment nothing because it moves no measurable input.

---

## 6. What this session did and did not do

**Did:** ran the full session ritual on collection 381; added `tools/equity_runway.py` (read-only: ledger,
true equity, drift, era R/trade, burn, runway + bootstrap, and the §5 policy state) with
`tools/test_equity_runway.py` (**18 OK**, hermetic); registered the §5 rule; refreshed the plan's baseline
(§2d) and the handoff snapshot. Numbers re-derivable with one command.

**Did not:** change a parameter, a constant, `TRADING_MODE`, `SL_CLEAR_ATR`, the ledger, `status.json`, any
ledger row, the deploy, or anything on the host. **No order. Gate still CLOSED.** In particular the simulated
balance is **still $52.98** — this document is a decision about *if and when* it may move, not the move.

---

## 7. The answer, one more time

* **Should we increase the simulated equity? No — not as a top-up.** It cannot improve the evidence (n and R
  are what the bars read), and it would rewrite the only number that is currently honest about a
  negative-expectancy book. The repo's own `handoff_check` would flag it as a ledger edit, correctly.
* **Is the low balance a problem? Yes, one problem, and it is not the currency:** there is **≈38 trades
  (~3 trading days, wide range)** of runway and **no floor**, and `A2` — the next eligible plan step — still
  needs a **flat moment on the host** (it is blocked right now by open **SELL #759**). Those two facts, not the
  dollar figure, are what to act on.
* **So:** leave the ledger alone, judge everything in **R**, and let the pre-registered §5 rule handle the
  zero crossing when it happens. If the owner's real intent is *"I want the paper test to keep producing
  evidence for another few months"* — it will, unchanged, on a negative or rebaselined ledger; the number
  is not what is running out, the **edge** is, and that is what the next 150 trades are for.

**Owner sign-off — GIVEN 2026-10-30: `no rebaseline ever — let it go negative` → see §8** (this line used to
offer three options; the owner chose the second, so `rebaseline rule approved` and `stop the paper book at the
fire point` are both **not** the decision and must not be recorded as if they were).

---

## 8. OWNER SIGN-OFF (2026-10-30, recorded by an agent session at the owner's direction)

**The owner's answer, verbatim:**

> **"no rebaseline ever — let it go negative"**

Given after the question was put as a four-way choice (§7's three lines plus "record nothing yet"), so this
is a decision among stated options, not an inferred one. **§5 above is now history: its rule is NOT adopted.**
Nothing in §5 is edited, deleted or re-tuned — it stays exactly as it was written on 2026-10-30, unsigned,
because an unsigned proposal that was declined is part of the record. **This section overrides it in effect,
and this section may not itself be widened later.**

### 8.1 What this authorises

- **Nothing on the ledger, ever.** No top-up, no rebaseline, no reset, no edit to `status.json.equity`, no edit
  to any row of `trades.csv`. The paper book runs as one continuous, unbroken record from trade **#1** onward
  for the rest of its life.
- The paper book is expected to cross zero and keep trading on a **negative balance**. That is the chosen
  policy, not a failure mode: startup already preserves a finite ledger balance even when it is zero or
  negative (`docs/REVIEW-2026-10-19-negative-balance.md`), and the restart path is covered by the smoke suite.
- Everything continues to be judged in **R** (`Profit ÷ actual risk`), never as a % of the starting balance.
  `true_equity` (= $500 + summed `Profit`) remains a **reporting** number only; it is not a gate and no longer
  has a declared consequence attached to it.

### 8.2 What it explicitly does NOT authorise

- It is **not** permission to stop, pause, restart or re-scope the forward test, and it resets no `n`, no era,
  and no bar. The `structstop1.5` window (`docs/PREREG-2026-10-26-structstop1.5.md`) is untouched.
- It is not permission to hide the number: a negative `equity` field will appear on the dashboard with no
  explanation unless §8.3's marker is kept current.
- It authorises no LIVE action, no `TRADING_MODE` change, no arming, no order. `SL_CLEAR_ATR` stays **0.5**.

### 8.3 The two consequences the owner should expect, written down now

1. **A negative `equity` on the dashboard will look exactly like the 2026-10-19 phantom-ledger incident**
   (`Balance_After` collapsing, negative equity, panicky readings). It is not that. The difference is checkable
   in one command: `python3 tools/equity_runway.py` prints the ledger, true equity, the drift and the burn, and
   `python3 tools/check_data.py` / `handoff_check.py` stay green throughout the decline. Anyone reading the
   dashboard in 2026-11 or later should run those first. If a *sudden* collapse appears (thousands of dollars in
   one bar, `Take_Profit == 0`, blank `Entry_Time`), that IS the incident signature — a real book loses
   ~$1/trade, not $4,000/trade.
2. **`tools/handoff_check.py`'s money rule will keep flagging the drift.** It allows money to move only as far
   as the closed-trade count explains, so a negative ledger is fine *while trades are closing*; it goes STALE if
   the ledger moves with no trades behind it — which is precisely the thing the owner has now ruled out. That
   check stays armed as the guard for exactly this decision.

### 8.4 The tool was changed to match the decision

`tools/equity_runway.py` no longer describes a rebaseline as the pending policy. It now reports the owner's
decision (`mode: never_rebaseline`, `rebaseline_permitted: false`), keeps printing the runway and the burn, and
keeps `--strict` as an **accounting alert** — exit 1 once `true equity ≤ $0` — with no implied action attached,
so a monitoring loop can shout without anyone reading it as "time to top up". The registered-but-declined
proposal's numbers are still shown, labelled **not adopted**, so the record of what was considered survives.
Pinned by `tools/test_equity_runway.py` (**21 tests**, 3 new for this decision).

### 8.5 Status of this document

**Closed.** The question that opened it ("should we increase the simulated equity?") has an owner answer —
**no, now or ever** — and the ledger is not a decision surface again. Nothing here reopens: a future session
that wants to raise or reset the balance needs a **new dated pre-registration plus a new explicit owner
sign-off**, and may not cite §5 as if it were live.
