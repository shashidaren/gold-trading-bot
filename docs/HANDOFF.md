# HANDOFF — current state and operating rules

**One-line prompt for a new session:** “Execute the plan.” Read
`docs/EXECUTION-PLAN.md` for the ordered queue, then use this file and the live
repository data to verify the current state before acting. Exact experiment
thresholds remain in their dated pre-registration/review documents; this
handoff or the plan must never replace or relax them.

Keep it current: every session that changes code, params, or conclusions must
update §1, §4/§5 and §6 before it ends (see §11 "How to keep this file
honest"). §11 also carries the **Session & Push Protocol** — push every commit
immediately and keep the session PR open until the user signs off. Follow it
from the first commit.

### Snapshot (machine-checked)

<!-- HANDOFF-SNAPSHOT machine-checked by tools/handoff_check.py; refresh with --update -->
| key | value |
|---|---|
| as_of_utc | 2026-10-19 02:59 |
| data_collection | 279 |
| closed_trades | 624 |
| outcomes | 122W/271L/229BE/2TIME |
| decisive_wr_pct | 31.0 |
| engine_ledger_usd | 150.69 |
| true_equity_usd | 133.71 |
| cost_usd_per_side | 0.20 |
| net_pnl_usd_at_cost | -615.89 |
| cutover_utc | 2026-10-06 03:00 |
| structstop_era_trades | 127 |
| structstop_era_outcomes | 37W/60L/29BE/1TIME |
| log_bars | 43907 |
| log_last_bar_utc | 2026-10-19 02:59 |
| skip_rows | 1433 |
| open_trade | SELL #626 @ 4175.02 |
<!-- /HANDOFF-SNAPSHOT -->

This block is the **only machine-checked part of the file**: `python3 tools/handoff_check.py`
recomputes every key from `trades.csv` / `forward_test_log.csv` / `status.json` and says
**FRESH** or **STALE** (tolerance 30 closed trades / 48 h — about two trading days at gold's
10–18 trades a weekday). Autosync prints the verdict in every digest (`📝 handoff:`), advisory only.
`python3 tools/handoff_check.py --update` rewrites the block and nothing else; the prose numbers in
§1/§4/§6 still have to be rewritten by hand (§11). **Numbers convention:** the ledger and every
P/L in the prose are **gross of costs** unless the line says `net` — the paper engine books no
spread. `net_pnl_usd_at_cost` charges the assumed `cost_usd_per_side` on every trade, scratches
included (the same model as `strategy_lab.py`); that cost is **assumed, not yet measured** — the active quote logger (`docs/XM-LOGGER.md`) must meet its 14-day/two-weekend sample target before it can inform a replacement (§6).
`cutover_utc` must equal `strategy_lab.LIVE_CUTOVER` — the check fails if the doc and the tool
disagree about when the structural stop went live.
**The check now covers the file's structure too (2026-10-15):** every `## 1.`–`## 11.` section must be
present, no placeholder markers are allowed, and every `§N` reference must resolve to a section — because on
10-15 the daily doc job truncated the file to its front matter and the freshness check, reading only the
snapshot block, still said FRESH.

### Start here (30 seconds)

1. Read **§1** (stance + numbers) and **Definitions** below it.
2. Run integrity + era report:
   ```bash
   python3 tools/check_data.py          # expect "0 fail"
   python3 tools/handoff_check.py       # is THIS file still true AND still whole? STALE -> `--update`, then rewrite §1/§4/§6 (§11)
   python3 tools/win_rate_report.py
   python3 tools/momentum_regime.py     # regime/side + the 09-28 hypothesis & its bar
   python3 tools/check_structural_stop.py   # struct-stop guard: must PASS (it also proves the deploy boundary)
   python3 tools/check_gap_rides.py     # §7 closure-gap revert trigger: the count + the damage facts
   ```
   **Read §1 first**: the struct-stop cutover is **2026-10-06 03:00 UTC** (era **n=127** as of
   2026-10-19, not 82) and the guard is green, but the pre-registered screen is **NOT met**
   (SL share 47.24% vs the strict ≤47.0% bar) and the **§7 closure-gap revert trigger is at its
   threshold (2 of 2 rides)** — both are first items of the **2026-10-19 21:00 UTC** judgement:
   `docs/REVIEW-2026-10-19-struct-stop-screen.md`. The BTC-port verdicts are in
   `docs/ANALYSIS-2026-10-13-btc-port-assessment.md` §3 (context: the 10-13 block in `docs/HANDOFF-HISTORY.md`).
   The quote logger is now collecting in the synced `xm_data/` files; check
   `python3 tools/xm_quote_report.py` for its current sample (as of 2026-10-19:
   5.5 days, 5 complete UTC days, 1/2 complete weekends — not enough to replace
   the cost assumption). The large-N history dump/convert/replay is still a
   first-run-on-the-box task: `docs/ACCELERATE-TESTING.md` §2.
   The dashboard now carries that read layer itself (`🌡️ Tape pressure`, `🎯 Setup read`, `📍 Location`,
   `🧪 Live experiment`, `📡 Feed health`) — **display-only**, calibrated in
   `docs/ANALYSIS-2026-10-16-dashboard-pressure.md`, CLI equivalent `tools/pressure_report.py`.
   A dashboard change only restarts the dashboard, never the engine (`docs/AUTOSYNC.md`).

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
| **§7 closure-gap revert trigger (count + damage)** | `python3 tools/check_gap_rides.py` (`--root DIR`, `--since`, `--json`, `--strict` → exit 1 at the trigger) |
| **Is this handoff stale?** | `python3 tools/handoff_check.py` (`--update` rewrites only the snapshot block) |
| Net-of-cost view of the ledger | `python3 tools/win_rate_report.py --spread 0.40` (round-trip $; the default output is unchanged without it) |
| **Measured spreads / cost / server clock / contract spec** (once `mt5quotes-gold` runs) | `python3 tools/xm_quote_report.py` (`--quiet` = the digest line) |
| **Large-N replay over broker M1 history** | `python3 tools/history_to_log.py mt5_history.csv --out history_utc.csv`, then `python3 tools/strategy_lab.py --bars history_utc.csv` |
| **Market context (tape / gates / §7 era / calibration)** | `python3 tools/pressure_report.py` (`--root DIR`, `--era structstop|maxhold|075|all`, `--json`) — the same read-only layer the dashboard renders |
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
- Quote replay numbers from before 2026-10-15 without noting the harness fix (blackout end boundary, §8).
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
| 2026-10-13 | **Tooling/docs session (no runtime change):** cutover corrected, replay level window 19→20 bars, `handoff_check.py` + `docs/AUTOSYNC.md`, `win_rate_report.py --spread`, the **GOLD quote + contract-spec logger** (`docs/XM-LOGGER.md`, install pending) and the **large-N history path** (`docs/ACCELERATE-TESTING.md`, first dump pending), BTC-port assessment (`docs/ANALYSIS-2026-10-13-btc-port-assessment.md`). On a branch, **no PR yet** (owner asked to finalise first) |
| 2026-10-15 | **Data refresh (no runtime change):** struct-stop era n=109 (past n=100 screen); metrics still inside most bars (SL share marginal); quote logger collecting (median spread $0.55); handoff snapshot + §1 updated. Scheduled 10-19 review next. |
| 2026-10-15 (tooling) | **Replay-vs-live gap fixed** (`strategy_lab.py` blackout end boundary, end exclusive; the live check is on the full timestamp). Struct-stop era: replay 39.3% decisive vs live 39.1%. Older replay numbers move by ~0.02–0.1R/trade. **Level-test 0.25 ATR pre-registered on paper** (`PREREG-2026-10-15-level-test-0.25.md`), not deployed. No runtime change |
| 2026-10-15 (docs) | **HANDOFF restored + consolidated** (no runtime change): the daily doc job truncated the file at 14:06 UTC (`43884e1` wrote `PLACEHOLDER - will replace`), losing **§2–§11**; content recovered from `712d106`, §1 history split out to `docs/HANDOFF-HISTORY.md`, `handoff_check.py` now checks section structure, not just freshness. |
| 2026-10-16 | **Dashboard market-context layer (display-only, no runtime change):** `pressure.py` + `tools/pressure_report.py` + `smoke_test.py` Scenario U; buy/sell pressure gauge, the engine's gates read back on the last bar, location/risk, §7 era card, feed health. Calibration says the composite is **collinear with side — not a signal**. `engine.py`/`trade_filter.py`/deploy path untouched; autosync restarts the dashboard only |
| 2026-10-17 (merge 10-16 22:54:47; **deploy 10-16 23:01:54**) | **Risk sizer + gates (PR #34) deployed into a closed market** (624 closed, no trade affected), then **corrected in place the same session**: `size_lots` is LIVE-only (the ledger-based version skipped 76–91% of M1 setups and would have sized 0.02 lots at the $500 start), the trade is committed atomically after the sizer accepts (the old order logged phantom trades), LIVE never sizes off the paper ledger, and the **FOMC 17:55–18:30 blackout is reverted** (blackouts frozen, §6.1; it moved era R/trade by ~0.023R). Struct-stop window un-stacked; smoke Scenario V added |
| 2026-10-19 (docs/tools only, **no runtime change**) | **Struct-stop interim screen at n=127** (`docs/REVIEW-2026-10-19-struct-stop-screen.md`): A1–A5, B1, B3, C1, C2 pass, **B2 47.24% vs ≤47.0% fails → SCREEN NOT MET**; era −$47.48 gross / −$98.30 at $0.40. **The §7 closure-gap revert trigger is AT its threshold (2 of 2 post-cutover rides over a daily closure: #595, #610)** — first item of the 21:00 judgement. New read-only `tools/check_gap_rides.py` makes that trigger measurable (count + damage facts) + smoke **Scenario W**. Quote logger 5/14 days, 1/2 weekends (median $0.55). An earlier 04:41 UTC draft of the review was PR #38 — **closed unmerged**, so nothing of it reached `main` |

## 1. Where things stand (as of **2026-10-19 — data collection 279**)

**Current stance (2026-10-19, ~06:00 UTC):** paper-only; `engine.py` remains `TRADING_MODE = "FORWARD_TEST"`.

**The book:** **624 closed trades** (122W/271L/229BE/2TIME; 31.0% decisive), engine ledger **$150.69**,
true equity $133.71, net **−$615.89** at the assumed $0.40 round trip. The quote logger has **5/14
complete days, 1/2 weekends** collected (first-look median spread $0.55) — **not enough to replace the
$0.40 assumption**, which therefore stands.

**The only open experiment** is the un-stacked **structural stop** (entries ≥ **2026-10-06 03:00 UTC**),
now **n=127 closed** (37W/60L/29BE/1TIME) over 10 entry dates. Its mechanical guard is green
(`check_structural_stop.py` **PASS** — **0 stops inside their level**, median clearance +0.50 ATR;
replay recall 100.0/100.0), but the pre-registered **screen is NOT met**: **SL share 47.24% against the
strict ≤47.0% bar**; the other four screen measures pass (SL/day 6.00 ≤ 6.5, scratch 22.83% ≤ 35%,
R/trade −0.065R ≥ −0.10R, decisive WR 38.14% [29.1–48.1] ≥ 36%). A PASS is unreachable at n=127
(Wilson LB 29.1% < the required 32.1%), and the era is negative after costs (−$98.30, −0.135R at $0.40).

**The §7 closure-gap revert trigger is AT its threshold — 2 of 2 post-cutover rides over a daily market
closure** (#595 on 10-14, #610 on 10-15; no weekend closure has been ridden, neither stop gapped
through, $0.00 of gap damage so far). It is the **first item of the 21:00 judgement**, and the counting
rule must be recorded there. Evidence and the decision procedure:
`docs/REVIEW-2026-10-19-struct-stop-screen.md` §3; the count is reproducible with
`python3 tools/check_gap_rides.py` (new, read-only).

**Next eligible action:** the confirmatory judgement at **2026-10-19 21:00 UTC** (or n=150, whichever
comes first), in §7 order — **(0)** resolve the gap trigger, **(a)** re-run the guard + `--calib-only` +
`check_gap_rides.py`, **(b)** judge B/C, **(c)** only then consider the already-registered 0.25 ATR level
test. **No runtime rule was changed in the 10-19 sessions**; the level test stays blocked behind it.

**Accounting incident reconciled (2026-10-19):** twenty invalid rows (#626–645, 2026-10-18 23:05 –
2026-10-19 02:23 UTC) had blank Entry_Time and zero Take_Profit, covering BUY TP and SELL TP/BE/SL
variants; raw equity **−$58,393.96** was phantom accounting (twenty rows booked **−$58,544.65** from the
$150.69 reference). Last valid ledger balance: **$150.69** after #625. Raw counts were 644 rows / 138 TP;
the valid subset **624 rows / 122 TP** is restored via quarantine. The 20-row suffix was quarantined with
continuity + status/numbering checks (`tools/repair_phantom_ledger.py`); the reconciled ledger passes
`check_data.py` (0 fail) and `check_structural_stop.py` PASS (n=127) still holds. See `incident_backups/`
for the quarantined evidence and `docs/REVIEW-2026-10-19-negative-balance.md` for the incident record.
**Host-side verification is still open and operator-only**: the checked-in risk-sizer correction passes
the smoke tests, but production deployment/process identity is **unverified** — do not assume the forward
stream is healthy.

**The dashboard pressure composite remains a side proxy, not a signal** (calibration: collinear with
side, no within-side contrast). The owner's manual pressure/hold observation is a separate, unmeasured
research hypothesis; do not change engine behavior from it.

### Definitions (binding)

| Term | Meaning |
|------|---------|
| **Decisive WR** | TP / (TP + SL). **Excludes** BE and TIME. |
| **BE exit** | Scratch: SL was ratcheted to entry; P&L ≈ $0. Neutral for WR, cooldown, daily breaker. |
| **TIME exit** | Max-hold close (`MAX_HOLD_MINUTES`). Neutral bucket like BE (own counter; excluded from decisive WR; ignored by SL streak / daily breaker). |
| **0.75R era** | Entries with `Entry_Time ≥ 2026-09-15 06:00 UTC` (PR #9 deploy). |
| **Max-hold era** | Entries after max-hold deploy (~2026-09-21 06:00 UTC autosync). **No counter reset** — falsification bar stays on the whole 0.75R book. |
| **Ratchet geometry** | Reconstruct original SL/TP from `ATR_At_Entry` when `Stop_Loss == Entry_Price` (never key only on `Exit_Reason == "BE"` — some TPs also show that geometry). |
| **R/trade (Rmult)** | `Profit ÷ actual risk`. Actual risk = \|Entry − Stop\|, recovered from the **reward leg** (`\|TP − Entry\| ÷ 1.5`) on rows whose stop was ratcheted to entry — never from `Exit_Reason == "BE"` alone. `tools/strategy_lab.py` and `tools/win_rate_report.py` both do this. **Backward-compatible:** before 2026-10-05 the engine always set risk = 2·ATR, so `Profit ÷ (2·ATR_At_Entry)` gives the identical number on every historical row (that was the definition used in REVIEW-2026-10-05); the two only diverge once `SL_CLEAR_ATR` can bind. |
| **Structural stop / level-bound** | The stop is set by the 20-bar level rather than by `ATR_SL_MULT·ATR` (replay share under the new rule: **80.2%**). Checkable on any era with `tools/check_structural_stop.py`. |
| **Clearance** | ATR by which the stop sits BEYOND the tested level (positive = the level must break for the stop to print). Pre-2026-10-05 median was **−0.42 ATR** (i.e. inside, stop fires on a retest); the rule requires ≥ 0 always and ≥ `SL_CLEAR_ATR` when level-bound. |
| **Session band** | Entry hour in UTC: "Asia/rollover" = 23:00–06:59; "London/NY" = 07:00–22:59. Named 2026-10-05 §5a; **downgraded later the same day** — costed/cascade-aware replay shows the gap collapses from 0.268R to 0.085R once the stop is structural (it was a proxy for stop geometry). Never a live gate. |
| **Struct-stop era** | Entries ≥ **2026-10-06 03:00 UTC** (`strategy_lab.LIVE_CUTOVER` — the autosync deploy time; the 10-05 21:00 in older text was the plan, corrected 10-13). A real isolation window (the rule changed), unlike the max-hold deploy which did not reset the counter. Judge per `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` §7 at n≥100; n<60 is not a result in either direction. |

## 2. Bot in one paragraph

Simulated XAUUSD scalper on 1-min candles. BUY at the 20-bar floor /
SELL at the 20-bar ceiling after a ≥38% wick rejection, trend-gated by
EMA50 vs EMA200 (+30-bar slope, one-sided 0.3·ATR EMA50 buffer),
RSI BUY 30–68 / SELL 32–70, ATR 1.10–4.50.
Exits: SL = entry ∓ **max(2·ATR, distance to the tested level + 0.5·ATR)**, TP = entry ∓
1.5 × that risk (1:1.5 held against the *actual* stop; identical to the old 3·ATR whenever the
level does not bind — 2026-10-05, §4/§5), plus a breakeven ratchet
that moves SL to entry once the trade is +0.75R ahead (`BE_TRIGGER_R`, 0.30R
from 09-10 to 09-15 — see §4). `engine.py` = signals +
execution/state; `trade_filter.py` = portfolio risk gates; `dashboard.py` =
Flask status page. Trading is FORWARD-TEST simulated (no real orders);
`TRADING_MODE=LIVE` path exists but the BE stop (below) is engine-side only there.
Because the trend gate keys side on EMA50 vs EMA200, **direction and side are
nearly collinear in the data** (94% of falling-60m entries are SELLs, 96% of
rising-60m are BUYs) — never read a "momentum" claim without splitting by side
(ANALYSIS-2026-09-28).

## 3. Data feed: Twelve Data → MT5 sidecar (configured 2026-09-10)

`DATA_SOURCE` env var in `/opt/gold/.env` picks the feed; default in code is
`TWELVEDATA`. **The deployed engine runs `DATA_SOURCE=MT5`**.

How MT5 works (feed-only, trading stays simulated):
- MT5 terminal runs **under Wine** in prefix `~/.mt5`, logged in.
- Sidecar `tools/mt5_feed.py` runs under the **Wine** Python and atomically
  publishes the latest **closed** M1 GOLD candle to `/opt/gold/mt5_last_candle.json`.
- Engine reads that file each poll, dedupes by candle timestamp.

**Tool (2026-09-11):** `tools/mt5_history_dump.py`
- Pulls historical bars (M1/M5/H1/etc.) from the same MT5 connection.
- Useful later for faster offline filter research / walk-forward tests.
- Does **not** affect the live engine.
- Example:
  ```bash
  export WINEPREFIX=~/.mt5
  xvfb-run --auto-servernum \
    wine C:/Python312/python.exe Z:/opt/gold/tools/mt5_history_dump.py \
      --days 365 --timeframe M1 --out Z:/opt/gold/history_m1.csv
  ```
- Remember: broker history ≠ live feed. Live forward-test remains the authority.

Stale-feed guard still active. Feed price scale is the **broker demo GOLD
feed** (~4.4k), not spot XAUUSD.

## 4. Current risk gates (trade_filter.py)

**Recovery PR (2026-10-19):** candle/tick paper exits reject invalid/nonfinite/zero
position geometry before booking P&L; startup retains finite negative/zero balances
honestly. Backup-first `tools/repair_phantom_ledger.py` is dry-run by default and
requires stopped engine/autosync before apply. No strategy thresholds changed.

**2026-10-19 incident:** no gates or parameters changed. Invalid zero-target TP rows
evade the SL-based breaker; that breaker is not a data-integrity safeguard.

**Source of truth for live params** (do not change without a pre-registered bar + REVIEW/ANALYSIS doc):

| Param | Value | File |
|-------|-------|------|
| `BE_TRIGGER_R` | 0.75 | `engine.py` |
| `MAX_HOLD_MINUTES` | 240 | `engine.py` |
| `ATR_SL_MULT` / `ATR_TP_MULT` | 2.0 / 3.0 (TP = `RR_TARGET` × **actual** risk) | `engine.py` |
| `SL_CLEAR_ATR` / `RR_TARGET` | **0.5 / 1.5** (live **2026-10-06 03:00** UTC — planned 10-05 21:00; pre-cutover books have neither) | `engine.py` |
| `RSI_MIN` / `RSI_MAX` | BUY 30 / 68; SELL mirrored 32 / 70 | `engine.py` |
| `MIN_ATR` (engine) | 1.10 | `engine.py` |
| `MIN_ATR_TO_TRADE` / `MAX_ATR_TO_TRADE` | 1.10 / 4.50 | `trade_filter.py` |
| `MAX_DAILY_LOSSES` | 10 | `trade_filter.py` |
| `SL_COOLDOWN_BASE/ESCALATED` | 30 / 60 min | `trade_filter.py` |
| London blackout | 07:55–09:00 UTC, **BUY only** | `trade_filter.py` `BLACKOUT_WINDOWS` |
| NY / rollover blackouts | both sides | `trade_filter.py` `BLACKOUT_WINDOWS` |

**Mirrored, and pinned:** the read-only dashboard layer needs some of these thresholds, so it keeps its own
copies in `pressure.py` (`docs/ANALYSIS-2026-10-16-dashboard-pressure.md`) — it must not import the engine, and
it must not drift from it either: `tools/smoke_test.py` Scenario U asserts every mirror **equals** the
`engine.py`/`trade_filter.py` value, so a param change here has to move the mirror in the same commit or the
deploy gate goes red. Nothing in the dashboard can change trading behaviour.

- SL cooldown: 30 min, escalating to 60 min after 2 consecutive SLs (BE
  scratches neither count toward nor break the streak — see the engine note
  below and §6 item 2b).
- Daily breaker: after `MAX_DAILY_LOSSES = 10` SLs → trend-side-only mode.
- Blackouts (UTC): London 07:55–09:00 **blocks BUYs only**; NY windows and
  rollover block both sides.
- ATR bounds: <1.10 or >4.50 → skip (high-ATR bound validated live).

Engine: **BE stop ratchet** at +`BE_TRIGGER_R = 0.75`·risk → SL moves to entry
(raised from 0.30 on 2026-09-15: at 0.30R = 0.6·ATR the trigger was one noisy
1-min bar, 77% of new-regime trades scratched with a median lifetime of 1.5 min
and the ratchet was converting +$222 of runs into $0 — docs/REVIEW-2026-09-15.md).
Exit reason `BE` = scratch (excluded from wins/losses/cooldown/daily tally).
Still true after the change: **a BE exit neither triggers nor breaks the SL
streak** (`get_consecutive_sl_count` breaks on TP, counts SL, ignores BE), so
escalation to 60 min is the norm and a scratch can be followed by an instant
re-entry into the same dying setup (27 of 58 0.75R-era entries came <10 min
after the previous exit). Both are open items in §6. Note the counterweight
that FOMC day surfaced: escalating cooldown is what kept 17:28–18:28 UTC dark
on 09-16, so it is no longer an unambiguous leak.

Engine: **structural stop** (live **2026-10-06 03:00 UTC**, planned 10-05 21:00 — `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md`, erratum at its top).
`risk = max(ATR_SL_MULT·ATR, |entry − level| + SL_CLEAR_ATR·ATR)` where `level` is the same
20-bar floor/ceiling the rejection gate was measured against; `take_profit = RR_TARGET·risk`.
Why: the level test's tolerance is price-% (`FLOOR_BUFFER_PCT = 0.0020` ≈ $8.30 ≈ **4.5×** the
median ATR) so it passes on 86.9% of bars, entries fill a median **2.42 ATR** from the level,
and a plain 2·ATR stop therefore sat **inside** the range on **63.8%** of the 0.75R master book
— 63.8% of SL exits needed no structural break at all (median SL lifetime 7.2 min). Guarded by
`tools/smoke_test.py` Scenario N and checkable on any era with
`python3 tools/check_structural_stop.py` (**post-cutover it must print 0** — and it now prints the boundary evidence that dates
the deploy from the ledger). Costed, era-matched
replay (10-05 figures, harness since corrected to the 20-bar level — see the erratum): master era n 326→217, 32.1→37.4% decisive, −0.217→−0.106R/trade, −$13.90→−$5.83/day at
$0.15/side, SL/day 8.2→5.4, maxDD $255→$175; **better in 3 of 4 eras** (worse pre-ratchet — it
needs the ratchet), and **still negative at every cost tested**. §7 of that doc is the
pre-registered bar (judge at n≥100, ~2026-10-19).

Engine: **max-hold time stop** (deployed 2026-09-21, fallback step 1 —
`docs/REVIEW-2026-09-21.md` §2): any open trade older than
`MAX_HOLD_MINUTES = 240` closes at market with reason `TIME`, whatever the
P&L. Price exits take priority (a simultaneous TP/SL wins); checked on both
the tick path and the MT5 candle path (at close); wall-clock, so across a
closure the trade exits on the first candle/tick back. TIME is a **neutral
bucket like BE**: own `time_exits` counter (in `total_trades`), P&L-signed
into the balance and era P&L/trade, but **excluded from decisive WR math and
ignored by the SL streak / daily breaker**. Engine-side only (LIVE caveat as
for the ratchet).
**Post-10-05 re-review:** the cap never bound an in-session trade in its first
14 days (longest non-TIME hold 68.0 min; n=209). It **cannot fire while the
market is closed**, so a position opened before a closure rides it — the only
TIME exit so far is #476, held 49.1 h across the 10-02→10-04 weekly close.
In LIVE mode that stop is not broker-protected across the gap; a pre-close
entry guard / flat-before-close policy is a named candidate (§5a/REVIEW-10-05
§5b), not adopted.

- **Engine: risk sizer (2026-10-17, deployed then corrected — LIVE-only).** `size_lots(stop_usd)`
  enforces `RISK_PCT = 1.0` of the **broker** balance and skips the trade when the sized lot is
  below `volume_min`. `CONTRACT_SIZE=100` (GOLD Standard; `1` for GOLDmicro) and `VOLUME_STEP=0.01`
  are explicit constants. **Paper returns `LOT_SIZE`** (no broker account to size off — the
  ledger-based version skipped 76–91% of M1 setups, see §1), so the forward-test book and the open
  struct-stop window are unchanged. The trade is committed **after** the sizer accepts, so a skip
  leaves no armed state (the old order logged phantom trades on the next candle). LIVE sizes off
  `account_info().balance`, refuses when that is unavailable, and logs the sized volume.
  See `docs/PREREG-2026-10-17-risk-sizer.md` (erratum at the top).


## 5. Evidence base (don't re-derive)

Key documents:
- `docs/ANALYSIS-2026-10-16-dashboard-pressure.md` (**latest, display-only**): what the dashboard's
  market-context layer is (`pressure.py`, `tools/pressure_report.py`), the composite's weights, the
  **calibration** (n=120 struct-stop era + n=347 max-hold era: *collinear with side — not separable
  within-side*; no `against` bucket on either side, in either era), what the rest of the panel answers,
  and what it does **not** authorize (no gate, no change to the open struct-stop window).
- `docs/PREREG-2026-10-15-level-test-0.25.md` (**pre-registration, not deployed**): the 0.25 ATR level test, its bars and REVERT rules. Binding only after the 10-19 judgement.
- `docs/ANALYSIS-2026-10-15-stop-loss-rate.md` (**latest analysis, no runtime change**): "too many stop losses" —
  live struct-stop book 39.1% decisive vs 42.0% breakeven at the live payoff; the replay-vs-live gap is **found and fixed**
  (a blackout end-minute bug in `strategy_lab.py`, tooling only); `tol0.25` is still the strongest queued lever.
- `docs/REVIEW-2026-10-05.md` (**latest, analysis-only — the scheduled formal
  re-review**): max-hold isolation closed (n=209, 1 TIME, cap never bound
  in-session, −$0.570/trade) → **fallback step-2 trigger MET** (eligible, not
  approved: needs the costed harness + pre-registration + sign-off);
  `H-side-awareness` **DROPPED** (27 decisive counter-trend ✔ but within-SELL
  60-min gap −6.4 pp and the failing side flips at 240 min; no rising-gold
  sub-period supports it); candidate refresh era-correct + risk-normalized
  (RSI≥45 dropped; MAX_ATR tighten normalized-rejected; post-BE fast re-entry
  −0.325R vs −0.104R remains the strongest queued, still observational);
  **new named candidate: London/NY session-band bleed** (39.8% vs 25.4% dec,
  p=0.034, holds in-side/in-ATR/in-era/5-of-5 chunks; proposed bar 4/6, not
  registered); #476 weekend-gap finding; two analysis-tool labels corrected.
- `docs/ANALYSIS-2026-10-01-stop-loss-rate.md` (still the **cost/tooling
  reference**; its ledger numbers are that snapshot's — current numbers are §1):
  448 closed; SL/all 41.1% versus SL/decisive 70.5%; current 0.75R n=273,
  −$0.467/trade, max-hold n=178, −$0.488/trade / 0 TIME. Geometry/labels and
  current-rule replay verified; smoke A–M passed, integrity 0 fail / 8 warn.
  **No bot change justified by the percentage alone.** Next-session queue:
  verify host/feed, repair/calibrate research tools, formal isolation review,
  costed stateful ratchet-off only if approved, separate post-BE-pause test.
  Replaces stale candidate headlines, not historical review records.
- `docs/REVIEW-2026-09-29-feed-outage.md` (6-h silent starvation after
  the 08:29 reboot: evidence chain, the guard bug that hid it, the undocumented
  09-28 precursor, detection fix + ops runbook)
- `docs/ANALYSIS-2026-09-28-falling-gold-win-rate.md` ("WR improves
  when gold falls?" → **wrong cause, no adoption**: real 30.7% vs 25.0% pooled
  gap but day-level null (27.9% vs 28.1%), side-coupled (94/96%), within-BUY
  refuted (13 falling-tape BUYs = worst bucket, 15.4%), whole gap 3 days old and
  inverted in the 09-17/09-18 up-leg (BUY 45.0% vs SELL 12.5%). Registered
  `H-side-awareness` + pre-registered bar — **scored at the 10-05 re-review:
  DROPPED** (fails bar (b) within-SELL and (c) rising-gold).
  Tool: `tools/momentum_regime.py`)
- `docs/ANALYSIS-2026-09-21-revert-or-maintain.md` (whole book before
  vs after the recent parameter changes on 281 trades → **MAINTAIN, revert
  nothing**: new-regime stack −5.7× bleed, 0.30R→0.75R replay −$116 → +$29
  (never back), max-hold exonerated by 0 fires at longest hold 24.9 min;
  today's −$22 trend-day bleed is noise within the pre-registered fallback)
- `docs/ANALYSIS-2026-09-21-win-rate-drop-check.md` ("did the win rate
  just drop?" → **no**: pooled 27.3% at n=271, era 32.3% at n=96, 0 TIME exits,
  ratchet verified firing at ≥0.76R; the recent 0W/4L run is sampled noise +
  the known cooldown leak. Also relabels the dashboard Win-Rate tile
  "**(decisive)** — all eras · excl. BE/TIME · all-in 14.0%", because the bare
  27.3% tile is era-blind and reads like a collapse; the era rate is 32.3%.
  **§2b: the era table** — 271 trades partitioned into 4 non-overlapping books
  (all 27.3%/−$0.625, pre-ratchet n=45 17.8%/−$1.834, 0.30R era n=130
  31.2%/−$0.321, master 0.75R book n=96 32.3%/−$0.471, of which max-hold era
  n=1) — **plus the no-reset decision (binding):** the max-hold deploy resets
  nothing; "closes at deploy" = the sub-period stops receiving trades; the
  falsification bar stays judged on the whole 0.75R book)
- `docs/REVIEW-2026-09-21.md` (max-hold time stop deployment record
  + 90-trade 0.75R close-out)
- `docs/REVIEW-2026-09-18.md` (falsification bar formally tripped; fallback
  starts; auto-trade timeline framework in §5)
- `docs/REVIEW-2026-09-15.md` (last full review — 164 trades; read it for
  the ratchet rationale, it supersedes several older conclusions below)
- `docs/ANALYSIS-2026-09-10-losing-trades.md`
- `docs/REVIEW-2026-09-10-PM.md`

Historical headlines (2026-09-15, 164 trades / 119 new-regime; superseded
for current decisions by the dated reviews above and §6):
- 19.4% decisive (14/72), CI 12.0–30.0; 56% of all trades are $0 scratches.
  Needs 40% decisive to break even at 1:1.5.
- **The ratchet, not the entries, was crushing the win rate.** Same 119 entries
  re-walked at +0.75R: ~45% decisive, +$0.40/trade (cascade-aware). At 0.30R the
  replay reproduces live exactly, which is what makes that comparison valid.
- "Expectancy ≈ −0.5R at every TP placement — entries are the problem" (09-10)
  no longer holds as stated: with the looser ratchet the entry stream replays
  ~50/50. Blocked signals replay 64% decisive (+$198 sequential) vs 19.4%
  taken — cooldown escalation + ratchet explain both sides of that gap.
- RSI < 45 **now meets its pre-registered adoption bar** (new regime: 47 trades,
  10.0% decisive, −$32.22 vs 29.4% for the rest) — candidate #1, adopt next
  cycle.
- ATR ≥ 2.5 (new regime): 0W/4L/13BE, −$27.11 — MAX_ATR tightening is eligible
  but held one cycle so it isn't confounded with the ratchet change.
- ⚠️ Sequence-aware numbers in `docs/REVIEW-2026-09-10-PM.md` §3 used
  `pathwalk_sims.py`, which had its SELL bar extremes inverted (fixed 09-15).
  Anything pathwalk said about SELL trades before this cycle is unreliable.
- **Interim 2026-09-17** (`docs/REVIEW-2026-09-17.md`, 58 trades at +0.75R):
  30.6% dec (CI 18–47), −$0.557/trade — **falsification bar (−$0.40)
  breached in P&L, n=58 < 60**. FOMC 09-16 (+25bp → 3.75–4.00%, 18:00 UTC)
  produced a −$118 (−2.7%) cascade that hit no open trade (escalated cooldown
  17:28–18:28 → MAX_ATR wall 18:02–20:01); 09-16 was already a bleed day
  pre-release, so the breach is not a news fluke. RSI ≥ 45 now ~dropped
  (skip bucket 36.0% dec, −$18.79 vs 27.9% kept); BE-resets-streak
  down-graded (escalation just protected the FOMC hour); ~4h max-hold time
  stop promoted to front of queue. Next check: if P&L/trade ≤ −$0.40 at
  n ≥ 60 → max-hold first, ratchet-off second. Era boundary unchanged:
  09-15 06:00 UTC (PR #9 merged 03:00:23Z, deployed by the 06:00 run).
- **2026-09-28 (380 trades) — "gold falls → WR improves?"** (see the
  ANALYSIS-2026-09-28 doc): the pooled falling-tape gap is real but small and
  insignificant (30.7% vs 25.0%, p=0.37; 240-min p=0.072) and structurally
  confounded with side. Day-level null; within-BUY refuted (falling-tape BUYs
  15.4% vs 23.2% — the worst bucket); the whole gap is 3 trading days old and
  inverts in the 09-17/09-18 up-leg (BUY 45.0% / SELL 12.5%). What survives: the
  recent bleed is the BUY side (max-hold era BUY 14.3% dec / −$84.07 vs SELL
  36.5% / +$10.69), consistent across eras but only nominal (pooled p=0.070,
  p→0.16 without 09-28) and possibly just the −6.7% slide we happen to be in.
  Registered hypothesis + bar; **no gate adopted**.

### 5z. `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` — why the SL rate is high, and the one change that fixes it

**Read this before touching any exit parameter.** Headline findings (all reproducible, §10 of
that doc):

- The level test is **inert**: `FLOOR_BUFFER_PCT = 0.0020` is a *price-%* tolerance, ≈ $8.30 on
  a $4,150 market ≈ **4.5× the median ATR (1.83)**. `Tested_Floor` is true on 86.9% of logged
  bars and 44.5% of the bars that pass it close >2 ATR *above* the level.
- Therefore the stop is **not structural**: median |entry − level| = **2.42 ATR**, so a 2·ATR
  stop sits inside the range (median 0.42 ATR short of it) on **63.8%** of the 0.75R master
  book, and **63.8% of its SL exits** were that class. Median SL lifetime **7.2 min**
  (46% ≤ 7 min, 97.6% ≤ 30 min of a 240-min budget); only 22.3% of trades touched +1·ATR first.
- **Shipped:** stop must clear the level (`SL_CLEAR_ATR = 0.5`), TP = 1.5 × the actual risk.
  Costed replay (master era, $0.15/side): −0.217 → **−0.106R**/trade, −$13.90 → −$5.83/day,
  decisive 32.1 → 37.4%, SL/day 8.2 → 5.4, scratches 33 → 25%, maxDD $255 → $175, 3 of 4 eras
  better (worse pre-ratchet: it needs the ratchet). 0 of 217 post-change trades have a stop
  inside their level (210 of 326 before).
- **Costs of it:** −33% trade flow (occupancy/cooldown, not a gate change), avg SL −$4.20 →
  −$6.80, holds 10 → 22 min (TIME 1 → 7, so more closure-gap exposure), the daily-loss breaker
  fires less (it counts SLs), and expectancy is **still negative at every cost level tested**.
- **Rejected on this data (do not re-derive):** ATR-rescaling the level test (era-unstable,
  0 winners of 21 decisive in the 0.30R slice; and the near-miss bucket is the *worst* of all at
  14.3% dec / −0.409R), stop-only widening that degrades the ratio (49.1% WR but −0.107R),
  min-SL 2.5/3.0/3.5 ATR with RR held (WR up to 50.7%, expectancy flat-to-worse), min-SL
  1.5/1.0 (−0.257/−0.425R), ratchet-off (≈breakeven gross, 61.7% SL share, redundant next to
  the stop fix), the session band (§1), and stacking the entry tolerance on top (≡ the stop fix
  alone).

## 6. Next steps (in order)

**Priority incident blocker (2026-10-19):** recovery tool and safeguards are prepared
for owner merge; full smoke + repair tests pass. Merge alone does not repair the host.
 operator should pause the paper engine,
preserve host CSV/status/journal and verify the running executable/revision before
restarting corrected code. Reconcile/quarantine invalid rows only from backed-up evidence;
do not reset to $500 or interpret raw negative equity as a broker loss. No live files
were repaired in this session. See `docs/REVIEW-2026-10-19-negative-balance.md`.

**Session execution queue:** `docs/EXECUTION-PLAN.md` is the concise, chronological
sequence to follow when the owner says “Execute the plan.” This section retains
the detailed evidence and backlog. Dated pre-registrations/reviews are the source
of truth for experiment thresholds; always refresh from current data.

0. **Ops verification first (still open):** CSV collection advances through
   10-05 02:59 and shows no new outage signature (only the normal daily break,
   one 8-min gap and the weekly close), but confirm the heartbeat/alerts/dedup
   deployment and `mt5.service` hardening **on the production host**. Runbook +
   drop-in in `docs/REVIEW-2026-09-29-feed-outage.md` §7 (`Restart=always`,
   `TimeoutStopSec=30`, `KillMode=control-group`, `systemctl enable`). Recover
   the terminal only if it is stalled; do not infer a fresh outage from a
   cloned snapshot's age. Check `mt5_last_candle.json` mtime/`updated_at`, live
   status/log progression, `📈 candles: ok` and journal recovery/health lines.
   Server access/deployment was **not** verified in 10-01 or 10-05.
   **Research prerequisite (DELIVERED 10-05):** `tools/strategy_lab.py` is the costed,
   stateful, era-matched, direction-aware replay the 10-01 §4 list demanded (funnel recall
   99.7–100% per era; cost on every exit incl. BE; production cooldown/breaker semantics).
   Era/pooling labels in `win_rate_report.py` and the false long-hold warning in `check_data.py`
   were fixed earlier the same day. Remaining §4 items are cosmetic-for-decisions (MFE/MAE
   alignment in `analyze_losers.py`, decisive-WR labels in `pathwalk_sims.py`/`phantom_trades.py`)
   but those tools stay **descriptive only**.
   Calibrate each era's actual rule before trusting any hypothetical P&L.
   Tools-only validation does not authorise runtime/strategy changes.
1. **🔒 STRUCT-STOP WINDOW IS OPEN — do not touch exits until it is judged.** The only live
   experiment: entries ≥ **2026-10-06 03:00 UTC** (the deploy; planned 10-05 21:00) use
   `SL_CLEAR_ATR = 0.5` + `RR_TARGET` TP. **At n=127 the screen is NOT met** (SL share
   **47.24%** vs the strict ≤47.0% bar; the other four measures pass) and the **§7 closure-gap
   revert trigger is AT its threshold (2 of 2 post-cutover rides over a daily closure: #595,
   #610)** — `python3 tools/check_gap_rides.py`. **Both are first items of the 2026-10-19 21:00 UTC
   judgement**, in this order: **(0)** resolve the gap trigger and **record the counting rule used**
   (the registered action if it is judged fired is a single-commit revert of the structural stop,
   **gap guard first** — and the 0.25 ATR level test does not proceed); then **(a)** re-run
   `check_structural_stop.py` (PASS), `--calib-only` (recall 100.0/100.0) and `check_gap_rides.py`;
   **(b)** judge expectancy
   only at **n ≥ 100** (≈8 trading days at the expected 12 trades/day; **n < 60 is not a result**);
   **SCREEN** = R/trade ≥ −0.10R **and** decisive WR ≥ 36% **and all B1–B3 hold**: SL/day ≤ 6.5,
   SL share ≤ 47%, and scratch share ≤ 35%. **PASS** additionally needs **n ≥ 150 with the WR's Wilson
   95% LB > 32.1%** (≈40% WR — the uncosted 1:1.5 breakeven). REVERT (single-commit `git revert`) if R/trade ≤ −0.20R, or avg SL loss
   > 2.2× pre-change, or the era drawdown exceeds $250, or 2+ trades ride a closure gap.
   Re-review **2026-10-19 21:00 UTC** or n=150, whichever comes first. No other strategy/param
   change inside this window (that includes the session band and the level-test re-scale).
2. **Max-hold isolation: CLOSED 10-05** (`docs/REVIEW-2026-10-05.md`). Verdict:
   n=209, 1 TIME exit (the 49.1-h weekend-gap hold #476), **the cap never bound
   an in-session trade** (longest non-TIME hold 68.0 min) → keep it as cheap
   insurance, it is **not** the cause of the SL cluster. Era result −$0.570/trade,
   −$8.64/calendar day.
   **Fallback step-2 (ratchet-off): trigger was MET (n=223, −$0.646/trade), the harness
   prerequisite is now delivered, and the measured answer is NO.** It is *not* worse than the
   live baseline in isolation (−0.162R vs −0.245R pooled master, $0.20/side) — but it buys
   that only by **deleting the scratch bucket: 61.7% of trades become full stop-outs** (45.4%
   today), its gross expectancy is ≈ breakeven (−0.052R), and **stacked on the shipped
   structural stop it adds nothing: −0.131R vs −0.124R** (`--only structstop,structstop+nord`).
   Spending an isolation slot on a variant that is redundant once the stop is fixed is not
   worth 2+ weeks. **Recommendation: close step 2.** Owner may override with a pre-registered
   bar; **never** back to 0.30R either way.
3. **Queued strategy changes** — refreshed 10-05; candidates only, no adoption
   (all numbers 0.75R master / max-hold era; `R` = Profit ÷ 2·ATR, which equals actual risk
   on every pre-2026-10-05 row — see Definitions):
   - (a) **RSI ≥45 — remains DROPPED.** keep 31.0% dec / −0.151R vs skip
     32.5% / −0.135R (max-hold: −0.175R vs −0.135R). The skip bucket is better
     in both books. Do not reopen without a new era-correct pre-registration.
   - (b) **BE resets the SL streak** (cooldown de-escalation) — still queued,
     still **down-graded** (FOMC escalation covered 17:28–18:28 UTC). Needs the
     calibrated cascade tool first; do not combine with a post-BE pause.
   - (c) **RISE120 entry gate — REJECTED / dropped.**
   - (d) **MAX_ATR 4.50→2.50 — NORMALIZED-REJECTED 10-05.** ATR<2.5 −0.146R vs
     ATR≥2.5 −0.143R (max-hold: −0.174R vs −0.092R); the dollar gap was
     position risk. ATR<2.0 also loses (keep −0.197R vs skip −0.063R). Drop
     unless a costed harness says otherwise.
   - (e) **Momentum / `H-side-awareness` — DROPPED 10-05** (fails bar (b) and
     (c); see REVIEW-2026-10-05 §3). No BUY ban / SELL-only / momentum gate.
     The BUY-side bleed is observation only (max-hold BUY −$1.306/trade,
     p=0.2031 — weaker than the 10-01 p=0.1137).
   - (f) **Session-band gate (London/NY bleed) — DOWNGRADED 10-05 (same day), do not
     adopt or stack.** Measured with the costed stateful harness: baseline Asia +0.022R vs
     London/NY −0.246R (gap 0.268R), but under the shipped structural stop the same split is
     +0.001R vs −0.084R (**gap 0.085R**) — the band was largely a **proxy for the stop-geometry
     defect**, so it fails REVIEW-2026-10-05 §5a's independence clause (b). Ledger-only
     description (39.8% vs 25.4% dec, pooled p=0.034) stands as history, not as a gate.
   - (g) **Post-BE <5-min same-side re-entry pause — strongest queued
     entry candidate.** master −0.325R vs −0.104R (n=57); max-hold −0.389R vs
     −0.111R (n=36). Observational only: needs the stateful cascade replay and
     a pre-registered bar; separate from the SL-streak change.
   - (i) **Level-test re-scale to 0.25 ATR — pre-registered 10-15 and owner-approved, NOT deployed**
     (`docs/PREREG-2026-10-15-level-test-0.25.md`). This is the next single-variable candidate only
     after the struct-stop judgement and only if that review permits it; never stack the two windows.
     The dated pre-registration owns the exact cutover and bars. It predicts a borderline master-book
     result at the assumed $0.20/side (−0.062R/trade), is era-unstable, and expects about 6.3 trades/day
     (~16 trading days to n=100; ~24 to n=150). It is an experiment, not a claim of profitability.
     Reproduce with `tools/strategy_lab.py --grid level`; do not re-register or tune it after seeing data.
   - (h) **Pre-close entry guard / flat-before-close** — NEW, named 10-05 from
     the #476 weekend hold (§REVIEW-10-05 §5b). Pair with the LIVE-mode work;
     not adopted. A **scheduled-news gate** remains a named unadopted candidate.
   - Ratchet falsification: **TRIPPED** (09-17, −$0.595 at n=60; now −$0.581 at
     n=318 master). Max-hold fallback delivered **no** improvement to blame or
     credit (§1). Step 2 (ratchet-off) measured 10-05 and **rejected** — see above.

4. Historical research — **path BUILT 2026-10-13, first run on the box pending** (`docs/ACCELERATE-TESTING.md`):
   dump M1 with `tools/mt5_history_dump.py`, convert with `tools/history_to_log.py` (it **proves** the
   server-time → UTC conversion against the live log's MT5 era, picks the DST rule from the data, drops the
   forming bar and refuses rather than guesses), then `python3 tools/strategy_lab.py --bars history_utc.csv`
   (today's rules, constant 0.75R ratchet by default, OOS vs in-sample split at 2026-09-04, monthly windows, cost
   sensitivity). It buys ~14.5 weeks of replay (100k bars), ~9 of them out-of-sample for the rules. A result there is
   a **hypothesis to pre-register**, never a reason to change anything inside an open window; the live forward
   test stays the authority. **Two traps, both handled by the converter:** the dump's `Timestamp` is the broker-server
   epoch labelled UTC (+3 h today, flips on the broker's DST — Sunday 2026-10-25) and its last row is the
   still-forming bar. Do **not** port BTC's UTC `ts` change into the live `mt5_feed.py`: the persisted
   `mt5_last_candle_ts` watermark would make the engine's dedup drop ~3 h of candles (assessment F4).

5. LIVE-mode broker-side BE modify — only if/when switching to real orders.
   Note the ratchet level is now +0.75R, and the engine-side-only caveat still
   applies.

6. **BTC-port queue (assessed 2026-10-13, `docs/ANALYSIS-2026-10-13-btc-port-assessment.md` §3–§4).**
   *Done (on the branch):* machine-checked handoff + digest line, `docs/AUTOSYNC.md`, the guard/harness fixes,
   `win_rate_report.py --spread`, the GOLD quote + spec logger and report, the large-N history path.
   *Owner decided:* leave `NOTIFY` as it is.
   *Quote logger in progress (synced data, checked 2026-10-17):* `python3 tools/xm_quote_report.py` reports
   3.7 days collected, 3 complete UTC days and 0/2 complete weekends; first-look median spread/round trip is
   about $0.55. Keep the $0.40 assumption until the report reaches 14 complete days including 2 weekends, then
   re-cost with `win_rate_report.py --spread` / `strategy_lab.py --cost`. Spread alone does not measure all
   slippage/commission. Verify the observed server offset around the 2026-10-25 DST change; do not guess.
   *Still pending on the box (tooling only):* one history dump → convert → replay (`docs/ACCELERATE-TESTING.md` §2).
   *After the struct-stop judgement, one runtime PR with its own pre-registration:* gap-aware stop fills (BTC PR #14:
   fill at the candle open if the bar opens through the stop), whole-day daily-breaker window
   (`load_recent_trades(n=400)`; latent, never bitten), the pre-close guard (item 3(h)) — measure each on the
   large-N path first.
   *Not for gold now:* `live_readiness` / `live_path_probe` / order executor / GO-LIVE window (no positive point
   estimate to stage), `reconcile_stale_trade` (no stuck trade; #577 verified).

7. **Dashboard read layer (2026-10-16) — display-only, keep it that way.** `pressure.py` mirrors
   `engine.py`/`trade_filter.py` constants instead of importing them, and **Scenario U pins every
   mirror** (plus the §7 thresholds and `LIVE_CUTOVER`) so a change to either side fails the deploy gate
   — if a threshold moves, move it in both places in the same commit. The panel's era card reports the
   §7 bar; it never judges it, and its R/trade is `win_rate_report.py`'s cost-view scale
   ($/trade ÷ mean 1R, rebuilt from the reward leg) so the two cannot disagree. Refreshing the printed
   calibration is `python3 tools/pressure_report.py`; the dashboard re-joins the ledger itself every
   10 min. **No dashboard number may become an entry condition without a pre-registered bar (§11).**

8. **Risk sizer + gates (2026-10-17) — deployed, corrected the same session; paper-inert now.**
   The sizer is **LIVE-only** (`size_lots` returns `LOT_SIZE` with no broker account), the trade is
   committed atomically after the sizer accepts, LIVE refuses to size without `account_info()`, and
   the **FOMC 17:55–18:30 window is reverted** (blackouts frozen by §6.1; it moved era R/trade by
   ~0.023R on 3 entries — re-register after 10-19). `MIN_SPREAD_POINTS` stays, LIVE-only.
   Pre-registration + erratum: `docs/PREREG-2026-10-17-risk-sizer.md`; deploy gate: smoke
   **Scenario V**. **Weekend / flat-before-close stays deferred** to a separate PR after 10-19
   (§6.3(h) — it reads the wall clock, so it is not hermetic). The **1:2 target (SL 1.5× / TP 3.0×
   ATR)** stays blocked until the 2026-10-19 judgement (§6.1) — nothing here touches
   `ATR_SL_MULT` / `RR_TARGET` / `SL_CLEAR_ATR`.


## 7. How to verify code changes (always)

```bash
python3 tools/smoke_test.py          # must print "SMOKE TEST PASSED"
python3 -m py_compile engine.py trade_filter.py
python3 tools/check_data.py          # expect "0 fail"
python3 -m py_compile tools/*.py     # analysis tools must at least import
python3 tools/win_rate_report.py     # must run end-to-end on current data
python3 tools/momentum_regime.py     # same, plus prints the registered bar
python3 tools/strategy_lab.py --calib-only        # funnel recall must stay ~100% per era
python3 tools/check_structural_stop.py            # stop-vs-level invariant (post-cutover: 0, PASS) + boundary evidence
python3 tools/check_gap_rides.py                   # §7 closure-gap trigger: rides over a closure + the damage facts
python3 tools/handoff_check.py                    # this file vs the data (FRESH); --update after a refresh
python3 tools/xm_quote_report.py --quiet          # "not collecting yet" until mt5quotes-gold is installed; never errors
python3 tools/pressure_report.py                 # dashboard read layer end to end (tape/gates/§7 era/calibration)
                                                  #   smoke Scenario U pins its mirrors to engine/trade_filter
python3 tools/strategy_lab.py --bars forward_test_log.csv > /dev/null   # history mode still runs end to end on real bars
```

Note: `tools/` scripts are NOT covered by smoke_test.py and several of them
have historically crashed or lied on new data shapes (2026-09-15: ZeroDivision
on ratcheted-stop rows, inverted SELL bars in pathwalk). Run them after every
data drop, not just after code changes.

- **Exit / stop / TP geometry changes** must additionally (a) be replayed costed and stateful
  with `python3 tools/strategy_lab.py --table --only baseline,<new-variant>` across **all four
  parameter eras** — a variant that wins in one era is noise, and `exit_sims.py` /
  `pathwalk_sims.py` / `phantom_trades.py` are cascade-ignorant and must not
  decide them; (b) carry a mechanical invariant checkable from the ledger alone
  (`tools/check_structural_stop.py` for stop-vs-level) — a code fact is a far stronger early
  signal than expectancy at n=20; and (c) be mirrored in a smoke Scenario. Bar shape:
  `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` §7.
- **A runtime change's cutover is its deploy time, not its plan.** Read it from the host's
  `autosync: merge upstream` commit (`git log --grep 'autosync: merge upstream' --format='%H %cI'`;
  `docs/AUTOSYNC.md` §2), set the era constant from that, and let the invariant check confirm it from the
  ledger *before* anyone reads a P&L row (10-13: the struct-stop cutover was dated 6 h early). Build the
  boundary evidence into the invariant check of any new runtime change.
- **Smoke scenarios are the deploy gate (autosync rolls back on a red one) — keep them hermetic.** Synthetic data
  in a temp dir, never the live CSVs (they change every 3 h), no wall clock, no dependence on a constant that a
  later legitimate change will move (Scenario O pins `LIVE_CUTOVER` for this reason).
- **Smoke tests must not read the wall clock.** Scenario L (`mt5_feed_problem` quiet-hours) did;
  it passed in market hours and failed at 00:09 UTC on 10-05 on a *clean* checkout. It is now
  pinned inside the scenario. If a scenario goes red only between 21:00–01:59 UTC or at a
  weekend, suspect the test before the code.

## 8. Data gotchas (hard-won)

- `trades.csv` has historical Trade_Num resets — dedupe by timestamp.
- **Ratcheted rows** log the *live* stop: at the 10-01 snapshot,
  `Stop_Loss == Entry_Price` on **256 rows: 187 BE + 69 TP**. Reconstruct the original
  geometry from the **reward leg**, not from the ATR multiple: `risk = |TP − Entry| ÷ 1.5`
  (the ratchet never touches TP). That is exact in **both** regimes — pre-2026-10-05 it
  reproduces risk = 2·ATR, after it the level-bound risk (median 3.07 ATR) — whereas
  `entry ∓ 2·ATR` silently *understates* risk on every level-bound trade and would inflate
  apparent R. `win_rate_report.py`, `check_structural_stop.py` and `strategy_lab.py` all use the
  TP-leg rule. For exact baseline calibration, preserve the logged target and account for
  ATR/price rounding; see ANALYSIS-2026-10-01 §4.
- **A %-expressed price tolerance is not a constant in ATR terms.** `FLOOR_BUFFER_PCT = 0.0020`
  looked like "0.2%, basically at the level" but on a $4,150 metal that is ~$8.30 ≈ 4.5× the
  median ATR, and it silently disabled the entry gate (86.9% of bars pass) — see
  ANALYSIS-2026-10-05 §2. Every threshold in this funnel must be ATR-scaled; the corollary is
  that a change whose *benefit* comes from an ATR-relative distance will read differently as
  the metal's price drifts, so re-check these numbers after a large regime/price move.
- `status.json` `win_rate` is decisive (TP/(TP+SL)); dashboard tile now labels it.
- Balance vs sum(Profit) drift is known (~$10–25); order of magnitude is the authority.
- Entry times are UTC; local session labels (London/NY) use UTC windows in code.
- **Momentum at entry must be measured strictly before the entry bar** (the
  price log lags `trades.csv` by ~1 min — `tools/momentum_regime.py` uses
  `entry − 1 min` for "now" and the same offset for the window start). Never
  include the entry minute's close in a pre-entry feature.
- **A frozen `mt5_last_candle.json` is not a quiet market.** The sidecar
  rewrites the file every 5 s even when the market is closed, so a stale mtime
  means the *publisher* died (terminal logged out/stuck) — the only reliable
  signal, because with a frozen file no candle is ever accepted and
  `feed_stale_seconds()` stays `0.0` (2026-09-29). The engine now checks the
  heartbeat before the dedup; see `mt5_feed_problem()`. Full incident record (6 h of silent
  starvation, the invisible `0.0` staleness, the ~283-minute precursor) in
  `docs/HANDOFF-HISTORY.md` and `docs/REVIEW-2026-09-29-feed-outage.md`.
- **Never read a momentum/regime claim without a side split**: the trend gate
  makes falling tape ≈ SELL and rising tape ≈ BUY (94%/96% in the book), so
  pooled momentum numbers are side numbers in disguise (2026-09-28).
- **Dollars measure position size, not signal.** ATR varies 1.10–4.50, so a
  $/trade gap can be pure risk-sizing (the MAX_ATR candidate died exactly this
  way on 10-05). Normalize: `R = Profit ÷ (2·ATR_At_Entry)` before comparing
  buckets, and still cost the result.
- **The 240-min TIME stop cannot fire while the market is closed** and closes
  on the first candle/tick back: a position can ride a daily/weekly closure
  (#476: 49.1 h wall-clock, −$1.52 on the Sunday reopen). Do not read a long
  hold as "the cap failed", and do not assume the stop is enforceable across a
  gap in LIVE.
- `tools/analyze_losers.py` prints "Skip 23:00-06:59 UTC (Asia/rollover)" with
  keep = the **London/NY** book. Read keep/skip labels carefully — the *skipped*
  199-trade bucket was the better one (10-05 §5a).

- **Blackout end boundary (fixed in the replay 2026-10-15).** `trade_filter.is_in_blackout` is `start <= now.time() <= end`
  on the full timestamp. A bar stamped HH:MM is evaluated seconds after the minute opens, so the end minute is **not**
  blocked. `strategy_lab.py` used an inclusive minute and blocked 09:00 and 15:15 wrongly; that alone made the
  struct-stop era look 4–5 pp too good. Replays from before 10-15 carry that error.

## 9. Architecture quick map

```
engine.py          signals + structural stop + BE ratchet + max-hold TIME + state machine
trade_filter.py    portfolio gates (cooldown, daily breaker, blackouts, ATR)
dashboard.py       Flask status page (read-only)
pressure.py        read-only market-context layer for the dashboard (tape pressure, engine-gate read,
                   location/risk, portfolio state, §7 era card, feed health) — stdlib only, no writes
tools/strategy_lab.py   canonical costed/stateful/era-matched replay (exit+gate decisions)
tools/check_structural_stop.py  ledger-side invariant guard for the 2026-10-05 change (+ deploy-boundary evidence)
tools/handoff_check.py  machine-checks the snapshot block at the top of THIS file (autosync digest: 📝 handoff)
tools/pressure_report.py  what the dashboard shows, printed (--root/--era/--json): tape, gates, location,
                   portfolio, §7 verdict, CALIBRATION (does the pressure composite separate outcomes?)
tools/mt5_quotes.py     read-only Wine sidecar: 30 s XM quotes + contract spec -> xm_data/ (deploy/mt5quotes.service)
tools/xm_quote_report.py  what the logger measured: spreads, cost vs the assumed $0.40, server clock, spec (digest: 📡)
tools/broker_time.py    the EU/US DST rule for XM's server clock (verified only by observed offsets)
tools/history_to_log.py broker-history (server time) -> validated UTC bars for `strategy_lab --bars`
tools/             other analysis / integrity / report scripts (not on the hot path)
/opt/gold/         live deploy root (autosync from main; never hand-edit)
```

## 10. Deploy & ops

- **Source of truth for live code:** `main` on GitHub.
- Autosync: every 3 h from `/opt/gold` (`tools/autosync.sh`); refuses if local
  dirty. Force: `sudo /opt/gold/tools/autosync.sh`.
- A "daily Grok job" is documented to refresh `docs/HANDOFF.md` §1 from `status.json` + `trades.csv`; the last
  refresh PR is **#22 (2026-09-25)** and §1 was 8 days stale on 10-13 — do not rely on it. The snapshot block
  is machine-checked instead (`tools/handoff_check.py`; the digest line `📝 handoff:` is advisory and never
  blocks a deploy), and `--update` is the deterministic way for any job or session to refresh it.
- Full autosync runbook, digest legend and the "deploy time = cutover" rule: **`docs/AUTOSYNC.md`**.
- Autosync digest now carries `📈 candles: ok (N open min) | STALE N open min`
  (phase 4b, added 2026-09-29): open-market minutes since the last logged candle,
  weekend/daily break excluded, shouts at > 90. A green digest with `no new
  data` no longer means "all fine" on its own.
- Services: `goldbot.service` (engine), `mt5feed.service` (Wine MT5 sidecar), and — once installed per
  `docs/XM-LOGGER.md` — `mt5quotes-gold.service` (read-only quote/spec logger; autosync commits its `xm_data/` and
  the digest shows `📡 xm logger: …`; a ⚠️ means the logger is down, not that gold is shut).
- A `dashboard.py` / `pressure.py` change is a **dashboard-only** deploy (`DASH_CHANGED`): the dashboard
  service restarts, `goldbot` does not. For a local render, point the reader at a checkout instead of the
  live root: `GOLD_DATA_DIR=. python3 dashboard.py` (also `GOLD_LOG_FILE`, `GOLD_TRADES_FILE`,
  `GOLD_SKIP_FILE`, `GOLD_STATUS_FILE`); defaults stay `/opt/gold/*`.
- Logs: `journalctl -u goldbot -f`; autosync log `/var/log/gold_autosync.log`.

## 11. How to keep this file honest

**Session & Push Protocol**
1. Push every commit immediately (do not batch).
2. Keep a session PR open until the user signs off.
3. Before ending: run `python3 tools/handoff_check.py --update`, then update §1 numbers, §4/§5 if
   params/evidence moved, §6 next steps, the
   era-timeline table (top of file) and `archive/PROJECT_LOG.md`. A runtime change is not
   "done" until its **pre-registered bar exists in a dated doc** — write the bar before any
   post-change trade can be judged, and never re-slice eras afterwards to rescue it.
4. Never leave conclusions in chat only — land them in this file or a dated REVIEW.
5. **§1 is current-state only — never prepend a new dated block to it.** Rewrite §1 in place and move the
   block it replaced to `docs/HANDOFF-HISTORY.md` (append-only, newest first). The 10-15 truncation began as
   §1 bloat: 223 of the file's 886 lines were §1, 92% of it history no session had pruned — and this file is
   rewritten by an automated daily job, so size is a reliability risk, not just a reading chore. If a required
   section goes missing, `python3 tools/handoff_check.py` now says STALE (and `--update` refuses to run).

**Forward-test milestones (canonical session queue: `docs/EXECUTION-PLAN.md`)**

| Gate | Action |
|---|---|
| Now | Edge not confirmed — remain paper-only. |
| **2026-10-19 21:00 UTC or n=150, whichever comes first** | Judge the structural-stop window (n=127 as of 2026-10-19; current SCREEN is not met because SL share is 47.24% vs the strict ≤47.0% bar, **and the §7 closure-gap revert trigger is at its threshold — 2 of 2 rides**). Follow `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` §7, **resolve the gap trigger first and record the counting rule**, and re-check the invariant first. |
| After an eligible judgement | Run only the already-registered 0.25 ATR level-test experiment, per `docs/PREREG-2026-10-15-level-test-0.25.md`; do not stack a pressure/hold change. |
| ~2–4 months | Seek 100+ trades across multiple regimes for the first serious edge assessment. |
| 6–12 months | Consider a separate live-readiness review only if durable positive expectancy after realistic costs is demonstrated and the owner explicitly approves. |

Do **not** treat the bot as supplementary income until positive expectancy
after realistic costs is clearly demonstrated on a meaningful live sample.
