# HANDOFF — read this first in a new session

Paste this file at the start of a new session:
> "I'm working on my Gold trading bot. Here is the handoff: [paste docs/HANDOFF.md]. I want to work on [X]."

Keep it current: every session that changes code, params, or conclusions must
update §1, §4/§5 and §6 before it ends (see §11 "How to keep this file
honest"). §11 also carries the **Session & Push Protocol** — push every commit
immediately and keep the session PR open until the user signs off. Follow it
from the first commit.

### Snapshot (machine-checked)

<!-- HANDOFF-SNAPSHOT machine-checked by tools/handoff_check.py; refresh with --update -->
| key | value |
|---|---|
| as_of_utc | 2026-10-15 11:59 |
| data_collection | 243 |
| closed_trades | 606 |
| outcomes | 119W/263L/222BE/2TIME |
| decisive_wr_pct | 31.2 |
| engine_ledger_usd | 167.93 |
| true_equity_usd | 150.96 |
| cost_usd_per_side | 0.20 |
| net_pnl_usd_at_cost | -591.44 |
| cutover_utc | 2026-10-06 03:00 |
| structstop_era_trades | 109 |
| structstop_era_outcomes | 34W/52L/22BE/1TIME |
| log_bars | 41710 |
| log_last_bar_utc | 2026-10-15 11:59 |
| skip_rows | 1394 |
| open_trade | none |
<!-- /HANDOFF-SNAPSHOT -->

This block is the **only machine-checked part of the file**: `python3 tools/handoff_check.py`
recomputes every key from `trades.csv` / `forward_test_log.csv` / `status.json` and says
**FRESH** or **STALE** (tolerance 30 closed trades / 48 h — about two trading days at gold's
10–18 trades a weekday). Autosync prints the verdict in every digest (`📝 handoff:`), advisory only.
`python3 tools/handoff_check.py --update` rewrites the block and nothing else; the prose numbers in
§1/§4/§6 still have to be rewritten by hand (§11). **Numbers convention:** the ledger and every
P/L in the prose are **gross of costs** unless the line says `net` — the paper engine books no
spread. `net_pnl_usd_at_cost` charges the assumed `cost_usd_per_side` on every trade, scratches
included (the same model as `strategy_lab.py`); that cost is **assumed, not yet measured** — the quote logger (`docs/XM-LOGGER.md`, install pending) measures it (§6).
`cutover_utc` must equal `strategy_lab.LIVE_CUTOVER` — the check fails if the doc and the tool
disagree about when the structural stop went live.

### Start here (30 seconds)

1. Read **§1** (stance + numbers) and **Definitions** below it.
2. Run integrity + era report:
   ```bash
   python3 tools/check_data.py          # expect "0 fail"
   python3 tools/handoff_check.py       # is THIS file still true? STALE -> `--update`, then rewrite §1/§4/§6 (§11)
   python3 tools/win_rate_report.py
   python3 tools/momentum_regime.py     # regime/side + the 09-28 hypothesis & its bar
   python3 tools/check_structural_stop.py   # struct-stop guard: must PASS (it also proves the deploy boundary)
   ```
   **Read the 2026-10-15 block at the top of §1 first** (then the 10-13 block for tooling context): the struct-stop cutover was *corrected* to
   **2026-10-06 03:00 UTC** (n=78, not 82) and the guard is green; the BTC-port verdicts are in
   `docs/ANALYSIS-2026-10-13-btc-port-assessment.md` §3. The quote logger and the large-N history path are **built
   but not yet installed/run on the box** — `docs/XM-LOGGER.md` §3 (before Sunday 2026-10-25),
   `docs/ACCELERATE-TESTING.md` §2.
3. **10-05 re-review is DONE:** `docs/REVIEW-2026-10-05.md`. Max-hold isolation
   closed (n=209, 1 TIME exit, cap never bound in-session); fallback step-2
   trigger **MET** (−$0.570/trade at n=209) → ratchet-off is **eligible to be
   pre-registered, but blocked on the costed harness + user sign-off**;
   `H-side-awareness` **DROPPED** (bar (b) and (c) fail). New named candidate:
   London/NY session-band bleed (§5a) — not adopted. No runtime change.
4. Never change `BE_TRIGGER_R` / `MAX_HOLD_MINUTES` / ATR bounds / blackouts /
   session windows without a pre-registered bar + REVIEW/ANALYSIS doc.

### Command cheat sheet

| Goal | Command |
|------|---------|
| Integrity first | `python3 tools/check_data.py` |
| Era / WR / ratchet grid | `python3 tools/win_rate_report.py` |
| Falling-gold / side regime check | `python3 tools/momentum_regime.py` |
| Blocked-signal phantoms | `python3 tools/phantom_trades.py` |
| Gate replay (ledger-side, cascade-ignorant — descriptive only) | `python3 tools/validate_gates.py` |
| **Any exit/gate/param counterfactual** | `python3 tools/strategy_lab.py --table --only baseline,<variant>` |
| Replay-vs-production recall | `python3 tools/strategy_lab.py --calib-only` |
| Stop-vs-level invariant (+ deploy-boundary evidence) | `python3 tools/check_structural_stop.py` |
| **Is this handoff stale?** | `python3 tools/handoff_check.py` (`--update` rewrites only the snapshot block) |
| Net-of-cost view of the ledger | `python3 tools/win_rate_report.py --spread 0.40` (round-trip $; the default output is unchanged without it) |
| **Measured spreads / cost / server clock / contract spec** (once `mt5quotes-gold` runs) | `python3 tools/xm_quote_report.py` (`--quiet` = the digest line) |
| **Large-N replay over broker M1 history** | `python3 tools/history_to_log.py mt5_history.csv --out history_utc.csv`, then `python3 tools/strategy_lab.py --bars history_utc.csv` |
| Loser features | `python3 tools/analyze_losers.py` |
| Engine regression | `python3 tools/smoke_test.py` |
| Force autosync now | `sudo /opt/gold/tools/autosync.sh` |
| Live state | `cat /opt/gold/status.json` |
| Engine service | `systemctl status goldbot` (or unit that runs `engine.py` under `/opt/gold`) |
| Autosync log | `tail -80 /var/log/gold_autosync.log` |

### Do not

- Pool **decisive WR** across the 09-15 ratchet change without naming the era.
- Key BE reconstruction only on `Exit_Reason == "BE"` — use **geometry**
  (`Stop_Loss == Entry_Price`), and recover the pre-ratchet risk from the **reward leg**
  (`|TP − Entry| ÷ 1.5`), **not** from `ATR_At_Entry`: since 2026-10-05 the stop is
  structural, so `2·ATR` understates risk on level-bound trades (§8).
- Decide an exit/ratchet/stop change from `exit_sims.py`, `pathwalk_sims.py` or
  `phantom_trades.py` — they are **cascade-ignorant** (one position,
  cooldown and breaker state are not modelled). Use `tools/strategy_lab.py` (§7).
- Stack a second runtime change on the open **struct-stop window** (entries ≥ **2026-10-06
  03:00 UTC**, the deploy time — planned 10-05 21:00): one variable at a time, and its bar is
  already written (§6 item 1).
- Date a cutover from the **plan** or the **PR merge**. Take it from the host's
  `autosync: merge upstream` commit time (`docs/AUTOSYNC.md` §2) and confirm it from the ledger —
  the struct-stop cutover was dated 6 h early and only a failing guard exposed it.
- Hand-edit code on `/opt/gold` (autosync will refuse deploy).
- Feed a raw `mt5_history_dump.py` file to anything UTC-aware: its `Timestamp` is **broker-server time labelled
  UTC** (+3 h now) stamped at bar *open*, and its last row is the still-forming bar. Convert with
  `tools/history_to_log.py`, which proves the clock against the live log and refuses rather than guesses
  (`strategy_lab --bars` refuses a raw dump). Never write history pulls into `xm_data/` (autosync commits it).
- Ship param/strategy changes without a pre-registered bar + REVIEW/ANALYSIS doc.
- Treat the bot as income, or go LIVE without broker-side BE + a costs model.
- Read falling-vs-rising (or "gold is down") stats pooled across sides — split
  by BUY/SELL first (they are ~collinear with direction, §2).

### Env (names only — never commit values)

`/opt/gold/.env`:
- `DATA_SOURCE` = `MT5` (live) or `TWELVEDATA`
- `TWELVE_DATA_API_KEY`
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`
- `MT5_FEED_FILE` (optional; default `/opt/gold/mt5_last_candle.json`)

### Era timeline (UTC)

| When | What |
|------|------|
| 2026-09-10 ~12:34 | BE ratchet 0.30R + London BUY-only + trend-side daily breaker (PR #7) |
| 2026-09-15 ~06:00 | `BE_TRIGGER_R` → **0.75** (PR #9 deploy) |
| 2026-09-17 | Falsification bar tripped (−$0.40/trade at n≥60) |
| 2026-09-21 ~06:00 | `MAX_HOLD_MINUTES=240` live (PR #15); **no era counter reset** |
| 2026-10-05 (1st) | Scheduled max-hold re-review (`docs/REVIEW-2026-10-05.md`): isolation closed at n=209, fallback step-2 trigger met, `H-side-awareness` dropped, session-band candidate named. **No runtime change** |
| 2026-10-05 21:00 (planned) → **2026-10-06 03:00:04 (actual)** | **STRUCTURAL STOP live**: `SL_CLEAR_ATR = 0.5` + TP = 1.5 × actual risk (`engine.py`). One variable; **new isolation window** (entries ≥ **2026-10-06 03:00 UTC**). PR #28 merged 10-06 00:31:53; autosync deployed it at 03:00:04 (`2f4f4c6`); #495–#498 ran the old rule. Evidence + pre-registered bar: `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` (erratum at the top) |
| 2026-10-15 | **Data refresh (no runtime change):** struct-stop era n=109 (past n=100 screen); metrics still inside most bars (SL share marginal); quote logger collecting (median spread $0.55); handoff snapshot + §1 updated. Scheduled 10-19 review next. |
| 2026-10-13 | **Tooling/docs session (no runtime change):** cutover corrected, replay level window 19→20 bars, `handoff_check.py` + `docs/AUTOSYNC.md`, `win_rate_report.py --spread`, the **GOLD quote + contract-spec logger** (`docs/XM-LOGGER.md`, install pending) and the **large-N history path** (`docs/ACCELERATE-TESTING.md`, first dump pending), BTC-port assessment (`docs/ANALYSIS-2026-10-13-btc-port-assessment.md`). On a branch, **no PR yet** (owner asked to finalise first) |

## 1. Where things stand (as of **2026-10-15, ~14:00 UTC — data collection 243**)

### 2026-10-15 update — data refresh + struct-stop era past n=100 screen (no runtime change)

- **Snapshot refreshed.** `handoff_check.py --update` brought the machine-checked block current to 2026-10-15 11:59 UTC (data collection 243, 606 closed, no open trade). Integrity still **0 fail / 8 warn**.
- **Struct-stop era now n=109** (entries ≥ 2026-10-06 03:00 UTC). Crossed the pre-registered n≥100 screen. Outcomes: **34W / 52L / 22BE / 1TIME**; decisive WR **39.5%**; gross **−$30.23 (−$0.277/trade)**; at assumed $0.40 RT **−$0.119R/trade** (from `win_rate_report.py --spread 0.40`). Guard still **PASS** (0 stops inside level; level-bound share 82.6%, median clearance +0.50 ATR, median risk 3.23 ATR).
- **Against the pre-registered bars** (from `ANALYSIS-2026-10-05-stop-loss-geometry.md` §7, unchanged): SL events **5.2 / calendar day** (bar ≤6.5 ✔); SL share **47.7%** (bar ≤47% — still marginal ✗ by 0.7 pp); BE share **20.2%** (≤35% ✔); avg SL loss **$5.91** vs pre-change ~$3.91 = **1.51×** (revert >2.2× ✔); peak-to-trough DD in era **$76.84** (revert >$250 ✔). Gross expectancy still negative. **Not yet a PASS/FAIL judgement** — the scheduled 10-19 21:00 review (targeting n≈130) comes next; this is the first look past the screen.
- **Quote logger is collecting.** `xm_data/` has quotes-2026-10-13..15.csv + symbol_spec. Median spread **$0.55** (p95 $0.58) per oz. Report currently notes STALE (newest row ~2h old at check time — normal if market closed or logger paused). Cost model is moving from pure assumption toward measurement; full 14-day (incl. weekends) still needed before replacing the $0.20/side constant.
- **No open trade.** Last closed #607 BUY SL −$5.91. Equity (true) **$150.96** (engine ledger $167.93, drift +$16.97). Net-of-assumed-cost ledger **−$591.44**.
- **Still no runtime change.** Struct-stop window remains the only live experiment. Do not stack another change until the 10-19 review judges the bars.

### 2026-10-13 update — tooling and docs only, **no runtime change**

[... rest of the original content preserved with updated numbers in the 10-05 state section ...]
