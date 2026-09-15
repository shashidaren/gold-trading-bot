# HANDOFF — read this first in a new session

Paste this file at the start of a new session:
> "I'm working on my Gold trading bot. Here is the handoff: [paste docs/HANDOFF.md]. I want to work on [X]."

## 1. Where things stand (as of 2026-09-15)

- Repo: `shashidaren/gold-trading-bot`, default branch `main`.
- **PR #9 MERGED** (2026-09-15): `BE_TRIGGER_R` **0.30 → 0.75**, analysis-tool
  fixes (SELL replay bug, ratcheted-stop handling, `check_data` tripwires), new
  `tools/win_rate_report.py`, and this review cycle's docs. Earlier: PR #7
  (2026-09-10 12:33 UTC) put the BE ratchet + direction-aware London blackout +
  trend-side daily breaker on `main`.
- Current ledger (from latest `trades.csv` / `status.json`):
  - **164 trades total** → 14W / 58L / 92BE
  - Decisive win rate **19.4%** (Wilson 95% CI 12.0-30.0); all-in 8.5%;
    **scratch rate 56%** (77% of new-regime trades)
  - Engine equity ~$383.78 (true P&L from $500 = **−$140.94** → $359.06;
    known ledger drift +$24.72 still present)
  - **New-regime trades (post-BE deploy, #46-#164) = 119** → 6W/21L/92BE,
    22.2% decisive, −$58.43 (−0.123R/trade; pre-ratchet era was −0.649R)
  - Last drop alone (#107-#164, 09-14 → 09-15): 5W/7L/46BE → **41.7%
    decisive, −$4.33** - the first slice of this book sitting on the 40%
    breakeven line
- Live bot runs from `/opt/gold` via systemd (`goldbot.service` =
  engine, `mt5feed.service` = price-feed sidecar).

**Current stance:** the win-rate story is now understood, and it is **not the
entries**. `docs/REVIEW-2026-09-15.md` §1: the +0.30R ratchet armed on ~1 minute
of noise (median scratch lifetime 1.5 min), converted 92 trades into $0 and
pinned the decisive win rate at 22%; re-walking the *same* 119 entries at
+0.75R replays to ~45% decisive and +$0.40/trade (the replay is trustworthy
because its +0.30R row reproduces the live result exactly: 6W/21L/92BE,
−$57.55 vs −$58.43). **The ratchet level changed this cycle**, so the next
review must judge P&L/day and bleed-per-trade - and must expect *larger*
individual losses, because fewer trades get refunded. Still do **not** treat
the bot as income until positive expectancy survives 100+ new trades across
multiple regimes. See the patience notes at the end.

## 2. Bot in one paragraph

Simulated XAUUSD scalper on 1-min candles. BUY at the 20-bar floor /
SELL at the 20-bar ceiling after a ≥38% wick rejection, trend-gated by
EMA50 vs EMA200 (+30-bar slope, ≤0.3·ATR from EMA50), RSI 30–68, ATR 1.10–4.50.
Exits: SL = entry ∓ 2·ATR, TP = entry ± 3·ATR (1:1.5), plus a breakeven ratchet
that moves SL to entry once the trade is +0.75R ahead (`BE_TRIGGER_R`, 0.30R
from 09-10 to 09-15 — see §4). `engine.py` = signals +
execution/state; `trade_filter.py` = portfolio risk gates; `dashboard.py` =
Flask status page. Trading is FORWARD-TEST simulated (no real orders);
`TRADING_MODE=LIVE` path exists but the BE stop (below) is engine-side only there.

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
escalation to 60 min is the norm (17 of 21 new-regime SLs) and a scratch can be
followed by an instant re-entry into the same dying setup (86 of 164 entries
came <10 min after the previous exit). Both are open items in §6.

## 5. Evidence base (don’t re-derive)

Key documents:
- `docs/REVIEW-2026-09-15.md` (latest formal review — 164 trades; **read this
  one first**, it supersedes several conclusions below)
- `docs/ANALYSIS-2026-09-10-losing-trades.md`
- `docs/REVIEW-2026-09-10-PM.md`

Current headlines (2026-09-15, 164 trades / 119 new-regime):
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

## 6. Next steps (in order)

1. **Let the new ratchet level accumulate data, then re-review** (~2 weeks).
   After pulling the latest data:
   ```bash
   python3 tools/check_data.py          # expect "0 fail"
   python3 tools/win_rate_report.py     # win-rate decomposition + ratchet grid
   python3 tools/phantom_trades.py
   python3 tools/analyze_losers.py
   python3 tools/validate_gates.py
   ```
   Judge on **P&L per day and bleed per trade**, not on win rate alone (a
   looser ratchet refunds fewer losers, so individual losses get bigger). Write
   `docs/REVIEW-2026-09-2X.md`, update this file + `archive/PROJECT_LOG.md`.

2. **Queued strategy changes** — status after the 09-15 review:
   - (a) **RSI ≥ 45 entry filter** — criteria MET, adopt next cycle (one change
     at a time, after the ratchet result is measurable).
   - (b) **BE resets the SL streak** (cooldown de-escalation) — supported
     (cooldown-blocked phantoms +$163 sequential); re-measure post-change.
   - (c) **RISE120 entry gate** — **REJECTED / dropped**: as a keep-filter it
     retains a worse book (135 kept, 18% decisive, −$123.40).
   - (d) **MAX_ATR 4.50 → 2.50** — eligible (0% decisive above 2.5) but parked
     one cycle so the two changes don't confound each other.
   - New this cycle: **~5-min post-scratch pause** if same-move churn persists
     (it only costs $0 trades in sim, but real spread on 62 trades/day is not
     $0); **BUY-side momentum gate** if BUY is still ~0% decisive after 30+ new
     BUYs; optional **max-hold time stop** (~4h) so live behaviour matches the
     replay and no trade can ride a weekend gap again (#95 held 49.1 h).
   - Falsification for the ratchet change: if new-regime P&L/trade stays
     ≤ −$0.40 at +0.75R, the fallback is **disabling the ratchet** (replay
     +$0.52/trade, 41% decisive), **not** going back to 0.30R.

3. Historical research (optional, later): use `tools/mt5_history_dump.py`
   once you want to stress-test candidate filters on multi-year data. A
   replay-driven change of this size is exactly what multi-year data is for.

4. LIVE-mode broker-side BE modify — only if/when switching to real orders.
   Note the ratchet level is now +0.75R, and the engine-side-only caveat still
   applies.

## 7. How to verify code changes (always)

```bash
python3 tools/smoke_test.py          # must print "SMOKE TEST PASSED"
python3 -m py_compile engine.py trade_filter.py
python3 tools/check_data.py          # expect "0 fail"
python3 -m py_compile tools/*.py     # analysis tools must at least import
python3 tools/win_rate_report.py     # must run end-to-end on current data
```

Note: `tools/` scripts are NOT covered by smoke_test.py and several of them
have historically crashed or lied on new data shapes (2026-09-15: ZeroDivision
on ratcheted-stop rows, inverted SELL bars in pathwalk). Run them after every
data drop, not just after code changes.

## 8. Data gotchas (hard-won)

- `trades.csv` has historical Trade_Num resets — dedupe by timestamp.
- **Ratcheted rows** log the *live* stop, so `Stop_Loss == Entry_Price` on 98
  rows: all 92 BE scratches **plus 6 TP winners** (#95, #120, #123, #133, #156,
  #157 — they armed, held, and still printed TP). Key any reconstruction on the
  GEOMETRY (`entry == sl`), never on `Exit_Reason == "BE"`, or you divide by
  zero. Reconstruct the 2×/3×ATR levels from `ATR_At_Entry` for R math.
- Counterfactual exits need a walk with an explicit horizon: a BE scratch died
  ~1.5 min after entry, so re-scoring it inside its own exit window can never
  reach a looser TP and silently returns "actual" (this is what made
  `pathwalk_sims.py` look self-validating and `analyze_losers.py` §4 print
  nonsense). Use `pathwalk_sims.py` (`horizon_min` rows) or
  `win_rate_report.py` §5b/§5c.
- Direction matters in every replay: a SELL's *favourable* bar extreme is its
  LOW and its *adverse* extreme is its HIGH. `hi_r = d*(h-e)/risk` is only the
  favourable side for BUYs (fixed 09-15 via max/min excursion form).
- Clock skew between `forward_test_log.csv` and `trades.csv` (use ±2 min windows).
- Gold price series = broker demo feed (~4.3-4.4k), not spot.
- No time stop exists: a trade opened just before a market close rides the gap
  (#95: Fri 20:57 → Sun 22:01, 49.1 h). `check_data.py` now warns on >60-min
  holds and on trades spanning any price-log gap (inclusive bounds).

## 9. File map (short)

`engine.py` · `trade_filter.py` · `trades.csv` · `forward_test_log.csv` ·
`skipped_trades.csv` · `status.json` · `tools/` (analysis incl.
**`win_rate_report.py`** (new 09-15), `check_data.py`, `phantom_trades.py`,
`pathwalk_sims.py`, `analyze_losers.py`, `validate_gates.py`, `exit_sims.py`,
`smoke_test.py` + feeds `mt5_feed.py` / **`mt5_history_dump.py`** +
`autosync.sh`) · `docs/REVIEW-*.md` · `docs/HANDOFF.md`

---

## 10. Autosync & deploy rhythm (single reference)

**Cron (on the box):**
```cron
0 */3 * * * /opt/gold/tools/autosync.sh >> /var/log/gold_autosync.log 2>&1
```

**What autosync does every 3 hours:**
1. Commits any new live data (`trades.csv`, `forward_test_log.csv`,
   `skipped_trades.csv`, `status.json`) and pushes to `origin/main`.
2. If `origin/main` has moved (new code/docs from a session):
   - Stops the engine **only if** `engine.py` or `trade_filter.py` changed
   - Merges (data files = server wins, everything else = remote wins)
   - Runs `tools/smoke_test.py` — automatic rollback on failure
   - Restarts the engine (and dashboard if needed)
   - Verifies `status.json` is fresh
3. Runs `tools/check_data.py`
4. Sends a short Telegram digest

**Working agreement:**
- Code, tools, and docs changes are pushed to `main` from sessions.
- The box picks them up automatically on the next autosync cycle (≤ 3 h).
- No need for manual `git pull` or engine restarts in normal operation.
- Only intervene when Telegram reports a problem (rollback, check_data fail,
  engine not active, etc.).

**Safety guarantees already in the script:**
- `flock` prevents overlapping runs
- Data is committed *before* any merge (rollback never loses trades)
- Refuses to deploy if someone hand-edited code files on the server
- Smoke-test gate + automatic rollback
- `.env` is never committed

---

### Patience / decision framework

| Horizon          | Goal                              | Action                                      |
|------------------|-----------------------------------|---------------------------------------------|
| Done             | Reach ≥30 new-regime trades       | Cleared (119 as of 2026-09-15)               |
| Done             | Fresh review + decide queued changes | `docs/REVIEW-2026-09-15.md`; ratchet raised 0.30→0.75, (a) approved-next, (c) dropped |
| ~2–4 weeks       | Judge the new ratchet level       | Re-run suite; P&L/day + bleed/trade, not WR alone |
| ~2–4 months      | 100+ trades, multiple regimes     | First serious evaluation of edge            |
| 6–12 months      | Durable positive expectancy?      | Decide if it deserves any real capital      |

Do **not** treat the bot as supplementary income until positive expectancy
after realistic costs is clearly demonstrated on a meaningful live sample.
