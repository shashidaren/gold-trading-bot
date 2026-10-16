# Pre-registration — Risk sizer + gates (2026-10-17)

> **ERRATUM (2026-10-17, same session) — read this before the body below.**
> The body is kept verbatim as what was registered; three of its claims are now
> corrected by measurement, and one of its changes is reverted.
>
> **1. It deployed.** Cutover by the §7/§10 rule (deploy time, not plan/merge):
> autosync `d5b81151` **2026-10-16 23:01:54 UTC**, engine restarted 23:02:09.
> The market closed at 20:57 UTC, so it landed on a closed market: **no trade
> has been affected** (ledger 624 closed, struct-stop era unchanged at n=127).
> The first bar it can act on is the Sunday reopen (~22:00 UTC 10-18).
>
> **2. "the sizer's only effect is refusing dead-end setups" was wrong.** The
> sizer sized off `self.balance` (the **paper ledger**, $150.69 today), not a
> broker account. Replayed against the struct-stop era's own 127 entries:
>
> | base | skipped | taken | lots chosen |
> |---|---|---|---|
> | the era's rolling ledger balance | **97/127 = 76.4%** | 30 | all 0.01 |
> | constant $150.69 | **116/127 = 91.3%** | 11 | all 0.01 |
> | constant $180.15 (XM balance) | 107/127 = 84.3% | 20 | all 0.01 |
> | constant $200.95 (equity) | 97/127 = 76.4% | 30 | all 0.01 |
> | constant $500 (ledger start) | 7.1% | 118 | **0.01 and 0.02** |
>
> Only stops ≤ ~$3.01 are takeable at 0.01 lot from $150.69, and the era's
> median stop is $5.26 (median risk 3.32 ATR), so the rule refuses most of the
> M1 book — and at the $500 ledger start it would instead have **sized up** to
> 0.02 lots on 16/127 era trades (128/449 in the 0.75R book), so the ledger's $
> scale was not invariant in that regime either. It is not R-invariant in
> effect: R/trade is preserved per trade, but the *entry stream*, the cascade
> (cooldowns/occupancy) and n all change. The published screen (R/trade,
> decisive WR, SL/day, scratch share) is not safe.
>
> **3. A defect in the skip path.** `execute_simulated_trade()` armed the state
> machine (`trade_active`, `trade_type`, `entry_price`) *before* the sizer check,
> and the refuse branch returned without clearing it — leaving the previous
> trade's SL/TP armed against the new entry price. The next published candle
> resolved it and **logged a trade that was never taken**. Reproduced hermetically
> (0 rows logged at the skip → 1 phantom `BE` row on the next candle).
>
> **4. Corrected in the same session (this commit).** (a) `size_lots()` is
> **LIVE-only**: with no broker account it returns `LOT_SIZE`, so the paper book
> is byte-identical to pre-PR-34 and the open struct-stop window is un-stacked
> again; (b) the trade is committed atomically — size, refuse, *then* arm, so a
> skip leaves nothing behind; (c) the LIVE path refuses the order when
> `account_info()` is unavailable instead of falling back to the paper ledger, and
> logs the sized volume; (d) the **FOMC 17:55–18:30 blackout is reverted** —
> blackouts are frozen by §6.1, and the window changed the stream the 10-19
> judgement reads: it blocked 3 of the 127 era entries (+$15.80), moving era
> R/trade by **~0.023R**, about a quarter of the headroom to the −0.10R bar.
> Re-register it as its own gate after 2026-10-19.
>
> **Bars, restated:** the paper book must be **identical to pre-PR-34**
> (same entries, same 0.01 lot, same $ scale); `tools/smoke_test.py` **Scenario V**
> pins paper lot parity, the LIVE sizing arithmetic, the skip-path invariant and
> the frozen 4-window blackout list (the previous PR shipped with **zero** smoke
> coverage of its own code); `SMOKE TEST PASSED` and `check_structural_stop.py`
> PASS remain the deploy gate. `ATR_SL_MULT` / `RR_TARGET` / `SL_CLEAR_ATR` are
> still untouched and the 1:2 target stays blocked until 2026-10-19.

> Binding only after the struct-stop judgement (2026-10-19) for any *param* change.
> This change is additive + R-invariant, so it is isolated from the open struct-stop
> window (§6.1) but is still recorded here per §11 rule 3.

## Change
Add a `%-risk` position sizer and two portfolio gates to the forward-test engine
(`engine.py` / `trade_filter.py`):

- `engine.py`: `size_lots(stop_usd)` with `RISK_PCT=1.0`, `CONTRACT_SIZE=100`,
  `VOLUME_MIN=0.01`, `VOLUME_STEP=0.01`. Sizes
  `lots = balance × RISK_PCT/100 ÷ (stop$ × CONTRACT_SIZE)`, normalized to
  `VOLUME_STEP`; **returns `None` → SKIP when the sized lot is below `volume_min`**.
  Wired into both `execute_simulated_trade` and `execute_live_trade`; P&L rescaled
  by lot via `_pnl()`. Live sizes off `account.balance`.
- `trade_filter.py`: minimum-spread filter `MIN_SPREAD_POINTS=60` (LIVE only — paper
  has no spread feed) + FOMC 18:00 UTC blackout. `pressure.py` blackout mirror
  updated in the same commit (Scenario U pin).

## Hypothesis
At a ~$200 GOLD Standard account the fixed 0.01 lot is a structural dead-end above
M1: a 1.5×ATR stop risks ~1% only on M1 low-ATR and 3–66% on M5+/high-ATR. The
sizer converts "I want 1% risk" into "skip if the market won't let me," without
changing stop/TP geometry or the open struct-stop experiment.

## Invariants / bars (must hold)
- **R-invariance:** `R = P&L ÷ $risk` scales with lots, so the struct-stop era
  R/trade and decisive WR are **unchanged**. Pre-reg bar: `|Δ R/trade| ≤ 0.01R` and
  `|Δ decisive WR| ≤ 1.0pp` on the struct-stop era (entries ≥ 2026-10-06 03:00)
  once re-costed — any divergence means the wiring is wrong, not the idea.
- **Deploy gate:** `python3 tools/smoke_test.py` → `SMOKE TEST PASSED`
  (Scenario U mirror pin intact, including the FOMC window added to `pressure.py`).
- **Skip behaviour:** on GOLD Standard the sizer rounds up to 0.01, so `trade_lots`
  = 0.01 whenever a trade is taken; the change only *adds skips* for dead-end
  setups. No trade is taken that the old fixed-0.01 code would have refused.
- **Untouched params:** `ATR_SL_MULT` / `RR_TARGET` / `SL_CLEAR_ATR` unchanged;
  the 1:2 target stays blocked until 2026-10-19 (§6.1).

## REVERT
Additive and R-invariant. Revert only if `smoke_test` fails or the struct-stop
metrics move beyond the bars above — then the wiring, not the concept, is at fault.

## Deferred (separate PRs)
- Weekend / flat-before-close gate → §6.3(h) (also reads wall clock → not hermetic).
- 1:2 ATR target (SL 1.5× / TP 3.0× ATR) → after the 2026-10-19 judgement.
