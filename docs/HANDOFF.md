# HANDOFF — read this first in a new session

Paste this file at the start of a new session:
> "I'm working on my Gold trading bot. Here is the handoff: [paste docs/HANDOFF.md]. I want to work on [X]."

## 1. Where things stand (as of 2026-09-11 morning)

- Repo: `shashidaren/gold-trading-bot`, default branch `main`.
- **PR #7 MERGED** (2026-09-10 12:33 UTC): BE ratchet + direction-aware London
  blackout + trend-side daily breaker are on `main` and **live since the
  ~12:34 UTC engine restart**.
- Current ledger (from latest `trades.csv` / `status.json`):
  - **63 trades total** → 8W / 40L / 15BE
  - Decisive win rate still ~16.7%
  - Engine equity ≈ $429.94 (true P&L from $500 ≈ −$94.77; known ledger drift +$24.71)
  - **New-regime trades (post-BE deploy) ≈ 18** (0W / 3L / 15BE)
- Live bot runs from `/opt/gold` via systemd (`goldbot.service` =
  engine, `mt5feed.service` = price-feed sidecar).

**Current stance:** Keep collecting live data. Do **not** change strategy
parameters until ≥30 new-regime trades (ideally 100+ before treating as
income). See §6 and the patience notes at the end.

## 2. Bot in one paragraph

Simulated XAUUSD scalper on 1-min candles. BUY at the 20-bar floor /
SELL at the 20-bar ceiling after a ≥38% wick rejection, trend-gated by
EMA50 vs EMA200 (+30-bar slope, ≤0.3·ATR from EMA50), RSI 30–68, ATR 1.10–4.50.
Exits: SL = entry ∓ 2·ATR, TP = entry ± 3·ATR (1:1.5). `engine.py` = signals +
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

**New tool (2026-09-11):** `tools/mt5_history_dump.py`
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

- SL cooldown: 30 min, escalating to 60 min after 2 consecutive SLs.
  (BE scratches neither count toward nor break the streak — still queued.)
- Daily breaker: after `MAX_DAILY_LOSSES = 10` SLs → trend-side-only mode.
- Blackouts (UTC): London 07:55–09:00 **blocks BUYs only**; NY windows and
  rollover block both sides.
- ATR bounds: <1.10 or >4.50 → skip (high-ATR bound validated live).

Engine: **BE stop ratchet** at +`BE_TRIGGER_R = 0.30`·risk → SL moves to entry.
Exit reason `BE` = scratch (excluded from wins/losses/cooldown/daily tally).

## 5. Evidence base (don’t re-derive)

Key documents:
- `docs/ANALYSIS-2026-09-10-losing-trades.md`
- `docs/REVIEW-2026-09-10-PM.md`
- Latest analysis (2026-09-11): losers die fast (median ~4 min), high early
  MAE (~1.0R), RSI < 45 still the strongest negative separator, only 3 pure
  SLs in the new-regime window so far.

Headlines (63 trades):
- Expectancy still ≈ −0.5R at every TP placement — entries are the problem.
- Blocked signals continue to outperform taken signals (cooldown especially).
- RSI < 45 remains candidate #1; BE already converts many weak entries to scratches.
- New-regime sample still too small for parameter changes.

## 6. Next steps (in order)

1. **Keep collecting live data** (target ≥30 new-regime trades, ideally 100+
   before any income discussion).
   After each data-collection commit:
   ```bash
   python3 tools/check_data.py
   python3 tools/phantom_trades.py
   python3 tools/pathwalk_sims.py
   python3 tools/analyze_losers.py
   python3 tools/validate_gates.py
   ```

2. **Queued strategy changes** (adopt only at n≥30 new-regime unless a clear
   trigger fires earlier):
   - (a) **RSI ≥ 45 entry filter**
   - (b) **BE resets the SL-streak** (cooldown de-escalation)
   - (c) **RISE120 entry gate**
   - (d) MAX_ATR tightening — parked while BE contains high-ATR damage

3. Historical research (optional, later): use `tools/mt5_history_dump.py`
   once you want to stress-test candidate filters on multi-year data.

4. LIVE-mode broker-side BE modify — only if/when switching to real orders.

## 7. How to verify code changes (always)

```bash
python3 tools/smoke_test.py          # must print "SMOKE TEST PASSED"
python3 -m py_compile engine.py trade_filter.py
python3 tools/check_data.py          # expect "0 fail"
```

## 8. Data gotchas (hard-won)

- `trades.csv` has historical Trade_Num resets — dedupe by timestamp.
- BE rows log the ratcheted stop (SL == entry). Reconstruct original 2×/3×ATR
  geometry from `ATR_At_Entry` for any R-multiple math.
- Clock skew between `forward_test_log.csv` and `trades.csv` (use ±2 min windows).
- Gold price series = broker demo feed (~4.4k), not spot.

## 9. File map (short)

`engine.py` · `trade_filter.py` · `trades.csv` · `forward_test_log.csv` ·
`skipped_trades.csv` · `status.json` · `tools/` (analysis + `mt5_feed.py` +
**`mt5_history_dump.py`** + `autosync.sh`) · `docs/REVIEW-*.md` · `docs/HANDOFF.md`

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

### Patience / decision framework (added 2026-09-11)

| Horizon          | Goal                              | Action                                      |
|------------------|-----------------------------------|---------------------------------------------|
| Next 3–6 weeks   | Reach ~30–40 new-regime trades    | Let it run, weekly review only              |
| ~2–4 months      | 100+ trades, multiple regimes     | First serious evaluation of edge            |
| 6–12 months      | Durable positive expectancy?      | Decide if it deserves any real capital      |

Do **not** treat the bot as supplementary income until positive expectancy
after realistic costs is clearly demonstrated on a meaningful live sample.
