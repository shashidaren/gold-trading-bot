"I'm working on my Gold trading bot. Here is my project log: [paste the contents of PROJECT_LOG.md]. Currently, I want to work on [X]."

# Gold Engine - Development & Strategy Log

## ️ Architecture Overview
The bot is split into two distinct files to separate signal generation from risk management:
1. **`engine.py`**: Handles data ingestion (Twelve Data / MT5), indicator calculation (EMA, RSI, ATR), and price-action signal generation (The "Funnel").
2. **`trade_filter.py`**: Acts as the final portfolio-level gatekeeper. Checks time blackouts, SL cooldowns, and ATR minimums before allowing execution.

## 🎯 Current Strategy Rules (The Funnel)
For a BUY signal to trigger, ALL of the following must be true:
1. **Tested Floor**: Price drops to the 20-candle low (with 0.20% buffer).
2. **Valid Rejection**: Lower wick is ≥ 38% of the total candle range.
3. **Held Support**: Candle closes *above* the dynamic floor.
4. **Trend Confirmed**: EMA 50 > EMA 200 (Uptrend only).
5. **RSI Filter**: RSI is between 30.0 and 68.0.
6. **ATR Filter**: ATR > 1.10.
7. **Trade Filter**: Passes `trade_filter.py` checks (No blackouts, no SL cooldown).

## ⚙️ Current Parameters
### engine.py
- `LOOKBACK_PERIOD` = 20
- `WICK_RATIO_TARGET` = 0.38
- `EMA_FAST` = 50, `EMA_SLOW` = 200
- `ATR_SL_MULT` = 2.0, `ATR_TP_MULT` = 3.0
- `REQUIRE_VOLUME_CONFIRM` = False
- `REQUIRE_TREND_CONFIRM` = True
- `MIN_ATR` = 1.10

### trade_filter.py
- `SL_COOLDOWN_MINUTES` = 30
- `MIN_ATR_TO_TRADE` = 1.10
- **Blackouts (UTC)**: London Open (07:55-08:15), NY Open (12:25-12:45), NY Volatility (13:55-14:15).

## 📝 Changelog & Recent Fixes
- **[2026-09-10 analysis → rules]** Losing-trade study (`docs/ANALYSIS-2026-09-10-losing-trades.md`, tools: `analyze_losers.py` / `exit_sims.py` / `pathwalk_sims.py`) on 45 trades (8W/37L, −$82.51): expectancy ≈ −0.5R at every TP placement (exits can't create edge), but **blocked signals replayed 47.5–65% WR (+41 phantom raw) while taken signals went 17.8%** — the risk layer was adversely selecting. Adopted (smoke A–J green):
  - **Breakeven stop ratchet** `BE_TRIGGER_R = 0.30` in engine.py (tick + candle paths, status.json persistence, exit reason `BE` = scratch, new `be_exits` counter; replay −82.51 → −62.36). LIVE-mode broker-side SL modify is still future work.
  - **Direction-aware London blackout**: 07:55–09:00 UTC blocks BUYs only — SELL phantoms there went 5W/1L (+20.09) since the SELL side went live; other windows unchanged.
  - **Daily-loss breaker degrades to trend-side-only** instead of halting: after `MAX_DAILY_LOSSES` (kept at 10; the live "(11/3)" rows were from the older 3-limit build), entries must agree with 60-min momentum from the price log (15-min staleness guard, legacy hard-halt fallback). Post-halt phantoms had gone 7W/0L (+27.71).
- **[2026-09-10]** `DATA_SOURCE=MT5` feed option for forward testing. After the Twelve Data WebSocket began refusing connections (handshake OK, immediate close — WS-trial expiry on the free plan suspected), the engine can now source closed M1 GOLD candles from the local Wine MT5 terminal (broker feed, no plan limits). `MetaTrader5` has no Linux wheels, so the Linux engine never imports it: a sidecar `tools/mt5_feed.py` runs under the Wine Python in the same prefix as the terminal (same pattern as the `mt5-balance` alias: `WINEPREFIX=~/.mt5 xvfb-run wine C:/Python312/python.exe Z:/opt/gold/tools/mt5_feed.py`) and atomically publishes the latest closed candle to `/opt/gold/mt5_last_candle.json`; `run_mt5_test()` reads that file — one row per closed minute, deduped by candle timestamp (a restart never re-logs the boundary candle; worst case one minute lost), same stale-feed guard + Telegram alerts. Trading stays simulated. Default remains `TWELVEDATA` — switch by adding `DATA_SOURCE=MT5` to `/opt/gold/.env` + installing `deploy/mt5feed.service` (`systemctl enable --now mt5feed`) + restarting the engine. `smoke_test.py` Scenario H covers file read/normalization/dedup.
- **[2026-09-10]** Stale-feed guard for the Twelve Data WebSocket: the feed stalled silently at 00:47 and again after the 02:05 restart (2.5h+ of missing candles, zero alerts) — a zombie WebSocket delivers no events and `heartbeat()` never raises, so the engine idled forever. `run_forward_test()` now force-reconnects when no price event arrives for `STALE_FEED_SECONDS` (10 min) and sends a rate-limited Telegram alert (30-min cooldown, suppressed during the broker daily break ~21:00-02:00 UTC and weekends via `is_market_quiet()`). `smoke_test.py` Scenario G covers detection, quiet-hour classification, and alert rate-limiting. **Deploy note**: add `Environment=PYTHONUNBUFFERED=1` to `goldbot.service` (`sudo systemctl edit goldbot.service`) so engine prints reach the journal unbuffered — the 02:05 stall was invisible in `journalctl` because Python block-buffers stdout.
- **[2026-09-10 post-review]** trades.csv schema-drift fix + learning tooling (see `docs/REVIEW-2026-09-10.md`):
  - **Critical**: SELL rows were appended under the pre-SELL 15-field header, misaligning every field (`Exit_Reason` read as a price) and silently disabling the daily-loss breaker, cooldowns and stat reload for SELL trades. `engine.migrate_trades_csv()` now self-heals the file on startup and before every append (backup kept); `trade_filter` has a loud drift tripwire; repo data migrated (raw copy: `archive/trades.csv.bak.20260910_pre_schema_fix`).
  - **New tools**: `tools/check_data.py` (integrity gate: schema/ledger/gaps/cross-file), `tools/phantom_trades.py` (replays blocked skip-log signals as phantom trades — reconstruction validated 99–100% vs logged indicators), `tools/validate_gates.py` now direction-aware (SELL mirrors, both schemas).
  - `tools/smoke_test.py` Scenario F: regression test reproducing the drift incident.
- **[2026-09-10]** Bidirectional Trading + Capital Protection Upgrade:
  - **Added Short-Selling (SELL) Funnel**: Symmetric Bearish setup when `EMA50 < EMA200`, testing 20-bar ceiling, upper-wick rejection $\ge 38\%$, holding resistance, falling EMA50 slope, and close near EMA50.
  - **Added Daily Loss Circuit Breaker (`MAX_DAILY_LOSSES = 3`)**: Automatically halts trading for the rest of the UTC day upon reaching 3 Stop Losses to prevent drawdown spirals during trend days / chop.
  - **Added Escalating SL Cooldowns**: 30 min cooldown after 1 SL, escalating to 60 min after 2 consecutive SLs, and halting on 3 SLs.
  - **Expanded High-Impact Blackout Windows**: London Open (07:55–09:00 UTC), NY Open & US Macro Data (13:25–15:15 UTC), and Daily Rollover Spread Spikes (21:45–22:30 UTC).
  - **Updated Web Dashboard**: Dual Long/Short funnel telemetry, active trade direction badges, and real-time daily loss tracking.
- **[2026-09-09]** Added regime gates from win-rate review: EMA50 slope lookback (30 candles) and max distance below EMA50 ($0.3 \times \text{ATR}$).
- **[2026-09-04]** Removed restrictive `MIN_EMA_GAP` filter from `trade_filter.py`. It was blocking valid pullbacks because the EMA gap naturally shrinks during pullbacks.
- **[2026-09-04]** Aligned ATR thresholds. `engine.py` `MIN_ATR` changed from 0.70 to 1.10 to match `trade_filter.py`.
- **[2026-09-04]** Fixed funnel diagnostics in `engine.py`. Added `self.hit_... += 1` counters so `status.json` accurately tracks where signals drop off.
- **[2026-09-04]** Updated `datetime.utcnow()` to `datetime.now(timezone.utc)` in `trade_filter.py` to prevent Python 3.12+ deprecation warnings.

## 📊 Forward Test Observations (Sep 4–10, 2026)
- **Review Findings**: Without daily circuit breakers, bad days (Sept 8 grind-down and Sept 9 afternoon news dump) resulted in 20 Stop Losses across 2 days. The new daily cap and US macro blackout directly protect against these scenarios.
- **Funnel Stats**: System now monitors both dynamic floor (Long) and dynamic ceiling (Short) with slope and proximity confirmation.

## 🚀 Future Tweaks / To-Do
- [x] Add Short-Selling logic for when `EMA50 < EMA200`.
- [x] Add Daily Loss limit (`MAX_DAILY_LOSSES = 3`) to `trade_filter.py`.
- [x] Implement escalating SL cooldown (30 min -> 60 min on consecutive SLs).
- [ ] Multi-Timeframe (15m/1h) higher-timeframe trend integration.
- [ ] Live spread filter check before order dispatch.
