# DECISION — B2: mirror the BE ratchet and the 240-min time stop at the broker

**Date:** 2026-10-28 ~19:10 UTC
**Plan step:** `docs/EXECUTION-PLAN.md` §3, Track B, **B2** ("any session"; the choice must be recorded
*before* coding, default = implement, do not diverge).
**Data at decision time:** collection 370, 737 closed trades, log through `2026-10-28 17:59:05 UTC`,
`status.json` `trade_active: false`, `next_trade_num: 738`. `check_data` 0 fail / 8 warn,
`check_structural_stop` PASS, `live_readiness` 9 PASS / 8 TODO / 3 MANUAL, gate **CLOSED**.

---

## 1. The decision

**Implement the broker-side mirror. Do not register a divergence.**

The plan offered a choice: implement `TRADE_ACTION_SLTP` at +0.75R plus a 240-minute broker-side close, *or*
write a dated registration explaining why LIVE may run a different strategy from the paper engine. The second
option is strictly worse for the only question that matters — whether this strategy has an edge:

- `BE_TRIGGER_R = 0.75` and `MAX_HOLD_MINUTES = 240` are **frozen strategy variables** in the open experiment
  (`docs/PREREG-2026-10-26-structstop1.5.md` §2). If LIVE silently drops them, the LIVE book is a *different*
  strategy, so paper evidence can never transfer to it and A7's independent forward window would measure
  something else.
- Both rules are **engine-side only** today. In LIVE the broker holds SL/TP, so `_maybe_arm_breakeven` /
  `_maybe_time_stop` are never reached by a real position: `run_live` only evaluates closed bars and never
  manages the broker position. A divergence would be permanent, not temporary.

Recorded default applied; no instruction from the owner to hold or diverge exists, and none is implied by
"Follow execution plan".

## 2. What exactly is being mirrored (paper → LIVE)

| Paper behaviour | Where it lives now | LIVE mirror added |
|---|---|---|
| At +0.75R, stop moves to **entry** (one-way, never wider) | `_maybe_arm_breakeven` → `_arm_breakeven` | `TRADE_ACTION_SLTP` on the open ticket, then the same `_arm_breakeven()` state/telegram/persist |
| At 240 min, close at market and book a `TIME` row | `_maybe_time_stop` | market `TRADE_ACTION_DEAL` with `position=<ticket>`, then the **same** `_maybe_time_stop()` booking (one ledger row, one counter, one message) |
| Position state (entry/SL/TP/time/number) drives both rules | `execute_simulated_trade` sets it | `execute_live_trade` now records it on a confirmed fill — today it sets only the trade number, so neither rule *can* fire in LIVE |

Both broker actions are **risk-reducing only**: the stop is moved to entry and never away from it, and the
time stop only closes. Nothing added here can open exposure, change a strategy parameter, or touch the paper
ledger.

## 3. Safety rules this implementation must keep

1. **Paper path untouched.** Every new branch is gated on `TRADING_MODE == "LIVE"`; the paper engine must be
   byte-for-byte unchanged (smoke A–AB + Scenario AC pin this).
2. **Never invent an outcome.** If the broker no longer holds the ticket (SL/TP fired while we were not
   looking), the engine does **not** guess an exit price or a P&L — that is B3's deal reconciliation. It stops
   managing, raises a loud `LIVE RECONCILE REQUIRED` alert, and sets `live_reconcile_pending`, which **blocks
   new LIVE entries** until an operator reconciles. Trading blind past a missing ledger row is worse.
3. **Confirm before believing.** `be_armed` / `stop_loss = entry` are only set after the broker returns
   `TRADE_RETCODE_DONE`. A rejection leaves state untouched and is retried on the next pass (bounded: one
   retry for market-moved rejections), with rate-limited alerts so a persistent reject cannot spam Telegram.
4. **Management survives the kill switch.** A disarmed process or a `LIVE_HALT` file must stop *new* exposure,
   not orphan an open position; the ratchet and the time stop therefore still run while disarmed. Both only
   reduce risk.
5. **Restart-safe.** Ticket, the risk the position was sized on, and the reconcile flag are persisted in
   `status.json` and restored, so a restart re-manages the same position instead of forgetting it.
6. **No new strategy variable.** No constant in the frozen list changes; `BE_TRIGGER_R`, `MAX_HOLD_MINUTES`,
   `SL_CLEAR_ATR`, geometry and gates are untouched. `TRADING_MODE` stays `FORWARD_TEST`.

## 4. Explicit non-goals (they stay TODO, with their own steps)

- **B3** — adopting an existing broker position on startup, duplicate-order refusal on restart, realised P&L
  from `history_deals_get`, ticket↔trade-number persistence beyond the single open position.
- **B4** — `terminal_info().connected`, `volume_max`/step/stops/freeze, spread-as-%-of-R veto.
- **B5/B6** — demo evidence, runbook. Nothing here is live-ready evidence; the gate stays **CLOSED**.

## 5. Completion test (what this session must produce)

- `tools/live_readiness.py` → `broker_be` **PASS** and `broker_time_stop` **PASS**, with the checks made
  *semantic*: a helper that is unreachable from `run_live` must not turn either check green.
- Hermetic fake-MT5 tests for: modify, close, rejection, retry, restart restore, "position gone", paper
  untouched, and "management runs while disarmed".
- `smoke_test.py` Scenario **AC**: a real `execute_live_trade` fill → BE modify at +0.75R → time close at
  240 min, all against a fake broker, with the ledger row and status keys asserted.
- A dated `REVIEW` recording the result; §3 of the plan, `docs/HANDOFF.md` and the readiness tab updated.
- **No order, no arming, no strategy change.** `TRADING_MODE` remains `FORWARD_TEST`.

## 6. Falsifiers (what would make this the wrong call)

- Any paper-path behavioural difference in the smoke suite (the change would be out of scope → revert).
- A reject path that books an exit or arms BE without broker confirmation (would fake an outcome).
- Any `live_readiness` check turning PASS on a construct the `run_live` loop cannot reach (would be
  scorecard theatre, not evidence).
