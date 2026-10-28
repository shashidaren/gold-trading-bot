# REVIEW — 2026-10-28 · B2: broker-side BE ratchet + 240-min time stop

**Step:** `docs/EXECUTION-PLAN.md` §3, Track B, **B2** (first eligible step this session — see §6 for why
A2 was not run).
**Decision record (written before the code):** `docs/DECISION-2026-10-28-b2-broker-be-and-time-stop.md`.
**Data snapshot:** collection **370**, **737 closed trades** (146W/322L/266BE/3TIME, decisive 31.2%), engine
ledger **$89.04**, true equity **$72.11**, net **−$722.69** at the registered $0.40 round trip, log
**54 333 bars** through `2026-10-28 17:59:05 UTC`, `next_trade_num: 738`, **no open trade**.
`check_data` **0 fail / 8 warn**, `handoff_check` FRESH (2 advisory), `check_structural_stop` **PASS**,
`check_gap_rides` unchanged (3/2 rides, 0 gapped through), `pressure_report` era n=240.

**Result: B2 is DONE. `broker_be` and `broker_time_stop` moved TODO → PASS. LIVE gate still CLOSED
(11 PASS / 6 TODO / 3 MANUAL). No order, no arming, no strategy change, `TRADING_MODE` still
`FORWARD_TEST`.**

---

## 1. What the gap was

`BE_TRIGGER_R = 0.75` and `MAX_HOLD_MINUTES = 240` are frozen strategy variables
(`docs/PREREG-2026-10-26-structstop1.5.md` §2). Both were implemented **only** in the engine:

- `_maybe_arm_breakeven()` → `_arm_breakeven()` mutated `self.stop_loss` and sent a Telegram message. It never
  talked to the broker, so a real position kept its original stop.
- `_maybe_time_stop()` was reached only from `check_position()` (tick path) and
  `resolve_open_trade_on_candle()` (MT5 paper feed). `run_live()` calls **neither**.
- Worse, a confirmed LIVE fill set only `current_trade_num`, `next_trade_num` and `be_armed`. It never set
  `trade_active`, `entry_price`, `stop_loss`, `take_profit` or `entry_time`, so even if the rules had been
  reachable they had no position state to act on.

Consequence: on a LIVE switch-over the strategy would have silently been *different* from the paper book —
wider effective exits (no ratchet), no maximum hold — and no paper evidence could have transferred to it.

## 2. What changed

| File | Change |
|---|---|
| `engine.py` | New LIVE-only block: `LIVE_MGMT_*` constants, `live_mt5_module`, `live_retcode_done`, `live_retcode_retryable`, `live_sltp_request`, `live_close_request`, `live_position`; methods `_live_send`, `_live_mgmt_failed`, `_live_reconcile_required`, `live_close_price`, `live_manage_open_position`. |
| `engine.py` | `execute_live_trade` records the filled position (ticket, sizing risk, entry/SL/TP/time/context), persists it, and refuses new exposure while `live_reconcile_pending`. |
| `engine.py` | `run_live` calls `live_manage_open_position()` every pass (5 s) inside its own try/except, so management matches the paper tick cadence and a management bug cannot kill the loop. |
| `engine.py` | `save_status` / `restore_open_trade_from_status` carry `live_ticket`, `live_risk`, `live_reconcile_pending`, so the position is still managed after a restart. |
| `tools/live_readiness.py` | `broker_be` / `broker_time_stop` are now **call-graph** checks: a construct only counts if it is reachable from `run_live`, and evidence must be real AST usage (a name, an attribute, a dict key) — never a comment or docstring. Added `_callable_sources`, `_calls`, `_reachable`, `_uses_name`, `_dict_has_key`. |
| `tools/test_live_manage.py` | **New**: 19 hermetic fake-MT5 tests (modify, close, rejection, retry, restart, gone-position, failed-query, paper inert, disarmed management). |
| `tools/test_live_readiness.py` | Expectations updated; added call-graph tests and a "docstrings never satisfy a check" test (20 tests). |
| `tools/smoke_test.py` | **Scenario AC** (12 checks): real `execute_live_trade` + real manager against a fake broker — fill → state → ratchet at +0.75R → 240-min close → one `TIME` row; gone-position blocking; paper inert. |

**Behaviour of the two rules in LIVE, stated plainly**

- **BE ratchet:** at `gain ≥ 0.75 × risk`, send `TRADE_ACTION_SLTP` with `position=<ticket>`, `sl=entry`,
  `tp` unchanged. `be_armed` and `stop_loss = entry` are set **only after** `TRADE_RETCODE_DONE`. If the broker
  already holds `sl == entry` (a restart between the modify and the persist), it is adopted with no second
  order. The stop is only ever moved **to** entry, never wider.
- **Time stop:** at `held ≥ 240 min`, send a market `TRADE_ACTION_DEAL` closing `position=<ticket>` with the
  broker's own `volume`, then book the exit through the **same** `_maybe_time_stop()` used by paper — one
  ledger row, one `time_exits` counter, one Telegram message. No duplicated accounting.
- **Rejections:** one retry only when the reject is a market move (requote / price changed / price off /
  timeout / connection). A logic reject (invalid stops, no money, trade disabled) is never retried; it leaves
  state untouched and alerts once, then every 15th failure.
- **Gone position vs failed query:** an authoritative empty `positions_get(ticket=...)` is treated as gone, and
  nothing is booked (no invented exit price, no
  guessed P&L — that is B3's deal history), one loud alert fires, `live_reconcile_pending` is set, and **new
  LIVE entries are refused** until an operator reconciles. A *failed* query (dead terminal, connection drop) is a
  different fact: it changes no state and blocks nothing, because one transient error must not halt the bot.
- **Disarmed process:** both actions still run. The kill switch stops new exposure; orphaning an open
  position is the more dangerous failure.

## 3. Verification (all re-run on this commit)

| Check | Result |
|---|---|
| `python3 tools/smoke_test.py` | **PASSED** — A–AB unchanged, **AC 12/12**, paper scenarios byte-identical |
| `python3 tools/test_live_manage.py` | **19 tests OK** (new) |
| `python3 tools/test_live_readiness.py` | **20 tests OK** |
| `python3 -m unittest discover -s goldbot/tests -t .` | **64 tests OK** |
| `python3 -m py_compile engine.py trade_filter.py tools/live_readiness.py tools/test_live_manage.py` | OK |
| `python3 tools/live_readiness.py` | **11 PASS / 6 TODO / 3 MANUAL**, gate **CLOSED**, `--strict` exits 1 |
| `python3 tools/check_data.py` | 0 fail / 8 warn (unchanged) |
| `python3 tools/check_structural_stop.py` | **PASS** (n=240, 0 stops inside the level) |
| `python3 tools/check_gap_rides.py` | unchanged: 3/2 rides, 0 gapped through, 0 worse exits |
| `git diff` on the frozen variables | **none** — `SL_CLEAR_ATR` 0.5, `BE_TRIGGER_R` 0.75, `MAX_HOLD_MINUTES` 240, `ATR_SL_MULT` 2.0, `RR_TARGET` 1.5, `GUARD_CUTOFF_MIN` 30 |

The two checks now read, from the tool itself:

```
PASS broker_be        TRADE_ACTION_SLTP modify reachable from run_live (live_manage_open_position, live_sltp_request)
PASS broker_time_stop MAX_HOLD_MINUTES closes the position from run_live (live_manage_open_position)
```

## 4. What this does NOT prove (explicit gaps)

1. **No demo evidence.** Every check here is source inspection + hermetic fakes. A real terminal's
   `TRADE_ACTION_SLTP` semantics, stops-level rejection, and fill behaviour remain untested — that is **B5**
   and it needs a DEMO account on the host.
2. **No reconciliation.** A broker SL/TP exit is still not booked; the new flag only makes the gap loud and
   stops new exposure. Real P&L needs `history_deals_get` and ticket↔trade persistence — **B3**.
3. **Single position.** The manager handles exactly the one ticket the engine opened. Adoption, partial
   fills, manual intervention and duplicate-order refusal are **B3**.
4. **Process-downtime blind spot.** If the process is down when +0.75R or 240 min is crossed, the broker's own
   SL/TP still protects the position, but the ratchet and the time stop cannot fire until it is back. This is
   inherent to an in-process rule; only broker-side server orders (or a mounted EA) close it.
5. **Cadence.** LIVE management runs every 5 s pass; paper's tick path can be finer. The difference is
   sub-minute and in the risk-reducing direction (later arming, not earlier).
6. **Not a live-readiness signal.** 11/20 PASS with 6 TODO + 3 MANUAL keeps the gate **CLOSED**; B2 alone
   changes nothing about whether this strategy should trade real money.

## 5. Would revert this if…

- the paper suite changed behaviour (it did not — A–AB green before and after);
- a rejection could arm BE or book a `TIME` row (pinned false by tests);
- the stop could widen (pinned: only `sl = entry`, only once, only after `DONE`);
- `live_readiness` could PASS on a construct `run_live` cannot reach (pinned by the new call-graph tests).

## 6. Why this step and not A2

**A2 remains the lowest-numbered eligible step and was not executed**, because its only remaining condition is
a host action that this session cannot perform or verify:

1. the one-line `SL_CLEAR_ATR = 0.5 → 1.5` must land **while the host has no open position** — the 10-27
   review's condition; `status.json` is flat *now* (18:54:49 UTC), but the deploy fires from the host's
   `0 */3 * * *` autosync cron hours later, and the sandbox cannot see the host at that moment;
2. the cutover is the host's `autosync: merge upstream` **commit time**, which exists only after that merge;
3. nothing here can push to `main` or restart the engine on the host.

Per §0.3 of the plan the blocker is reported rather than faked, and per §6 a blocked Track-A step does not
block Track B. **A2 is unchanged and still next**: the engine still has `SL_CLEAR_ATR = 0.5` and
`CLEAR15_CUTOVER = None`, and Scenario AB still proves the window has not started.

## 7. Next eligible steps

- **A2** — owner/host deploy at the next flat moment; then record the cutover and re-run
  `check_structural_stop.py --era clear15`.
- **B3** — reconciliation (adoption, duplicate refusal, `history_deals_get`, ticket↔trade persistence,
  restart proof). This is now the natural next Track-B step and it closes the gap B2 deliberately left open.
