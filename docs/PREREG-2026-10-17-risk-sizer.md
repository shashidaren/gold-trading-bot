# Pre-registration — Risk sizer + gates (2026-10-17)

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
