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
- `BE_TRIGGER_R` = 0.75 (breakeven ratchet: SL -> entry at +0.75R; was 0.30 from
  2026-09-10 to 2026-09-15 — raised after the 164-trade review)
- `REQUIRE_VOLUME_CONFIRM` = False
- `REQUIRE_TREND_CONFIRM` = True
- `MIN_ATR` = 1.10

### trade_filter.py
- `SL_COOLDOWN_MINUTES` = 30
- `MIN_ATR_TO_TRADE` = 1.10
- **Blackouts (UTC)**: London Open (07:55-08:15), NY Open (12:25-12:45), NY Volatility (13:55-14:15).

## 📝 Changelog & Recent Fixes
- **[2026-09-15 docs]** Session & Push Protocol added to `docs/HANDOFF.md` (new §11 "How to keep this file honest", ported from bitcoin-trading-bot PR #5): one session = one scope = one PR at the end (merge → `origin/main` → the next `tools/autosync.sh` run, ≤ 3 h, deploys to the live box — so merging stays the last click); push after every logical step — the sandbox filesystem is ephemeral and unpushed commits are unrecoverable (no cherry-picking from dead workspaces); the session PR stays open as a draft until the agent reports all tasks complete + `tools/smoke_test.py` SMOKE TEST PASSED + `tools/check_data.py` 0 fail **and** the user confirms; hand off via `docs/HANDOFF.md` + this changelog, not chat. Also: per-session update ritual written down (§11) and the current work branch recorded in §1's header. Docs-only — no code, params, or strategy logic touched; nothing to re-run.
- **[2026-09-15 review → rule change]** 164-trade review (`docs/REVIEW-2026-09-15.md`; ledger 14W/58L/92BE = 19.4% decisive, CI 12.0–30.0, true P&L −$140.94 → equity $359.06, drift +$24.72; new regime #46–164 = 119 trades, 6W/21L/92BE, −$58.43 = −0.123R/trade vs −0.649R pre-ratchet). **Finding: the win rate was an exit problem.** `BE_TRIGGER_R = 0.30` is 0.6·ATR ≈ $1.2 on a $4300 market — one noisy minute; median scratch lifetime 1.5 min and 77% of new-regime trades ended as $0 scratches (09-14 alone: 62 trades, 49 of them scratches, 9 entries in 43 min because a BE exit triggers no cooldown). Re-walking the SAME 119 entries with an explicit 240-min horizon (replay validated: at +0.30R it reproduces 6W/21L/92BE, −$57.55 vs −$58.43 actual) gives: +0.30R 22.2% dec −$0.49/trade (live) | +0.75R **44.7% dec +$0.40/trade** | ratchet off 41.0% dec +$0.52/trade, cascade-aware. The 92 scratches alone would have replayed 55W/36L for +$221.74. **Adopted: `BE_TRIGGER_R` 0.30 → 0.75** (only strategy change; engine restart via autosync). Queue: (a) RSI≥45 MET its adoption bar (new regime: 47 skip-bucket trades at 10.0% dec / −$32.22 vs 29.4% kept) — adopt next cycle; (b) BE resets the SL streak — supported (cooldown-blocked phantoms 48W/28L +$163 sequential; 17 of 21 SLs escalate because scratches don't break the streak); (c) RISE120 — **REJECTED** (135 kept, 18% dec, −$123.40); (d) MAX_ATR 4.5→2.5 — eligible (ATR≥2.5: 0W/4L/13BE, −$27.11), parked one cycle to avoid confounding. BUY side: 0W/5L/26BE in the new regime (0% decisive in 31 trades). Phantom total still says the risk layer adversely selects: 99 sequential blocked signals → 63W/36L (64%), +$198.20 vs 19.4% taken. **Tooling bug hunt**: 3 of 5 analysis tools were broken on this data — `pathwalk_sims.py` had SELL bar extremes inverted (`hi_r = d*(h-e)/risk` is the favourable side only for BUYs) so it under-detected every short's TP/BE arm and *looked* self-validating by falling back to actual; ratcheted-stop rows (`Stop_Loss == Entry_Price`, 98 of them — 92 BE **plus 6 TP winners**) divided by zero in `analyze_losers.py`/`exit_sims.py`/`pathwalk_sims.py`; `analyze_losers.py`'s naive §4 exit table (which cannot see past a 2-min window) was deleted in favour of horizon-aware replay. All fixed, plus `check_data.py` gap-span bounds (`<` → `<=`, it had missed a trade held 49.1 h across the weekend: #95 Fri 20:57 → Sun 22:01) and two new tripwires (ratcheted-stop rows = INFO, >60-min holds = WARN). New read-only tool **`tools/win_rate_report.py`** (win-rate decomposition with Wilson CIs, era/side/day/hour splits, hold-time table, ratchet counterfactual, cascade-aware trigger grid, queued filters by era). `smoke_test.py` Scenario I now derives its labels from `BE_TRIGGER_R` and gained a **"must NOT arm below the trigger"** assertion. Suite green: smoke PASSED (A–J), `check_data.py` 0 fail / 8 warn.
- **[2026-09-10 PM review]** First 15 trades on the merged PR #7 stack (`docs/REVIEW-2026-09-10-PM.md`, 60 trades total: 8W/39L/13BE, −$92.05 true, equity $407.95). BE ratchet live: 13/15 scratches (−$9.54, −65% bleed vs pre-BE); counterfactual says it saved ~$30 of SLs and killed 5 trend TPs (~$34) — P&L-neutral, variance-reducing. ATR>4.5 bound validated live (12 blocked, all would-be SL); London direction-aware fix not yet live-tested (deployed 12:34, after the window). RSI<45 deepens to 1W/15L/3BE (6% dec, −$44.01) — queued as change candidate #1 behind the 30-new-regime-trade bar (15/30). **Strategy unchanged.** Tooling-only cycle: all `tools/` made BE-aware (BE rows reconstruct 2×/3×ATR geometry from `ATR_At_Entry` since logged SL==entry), `check_data.py` gains same-minute INFO check (part-2 to-do, done: 18 min / 19 extra rows, benign) + BE tripwires, dashboard gains BE tile + TREND-ONLY badge. Suite green (smoke A–J, 0 fail). Also rescued `docs/REVIEW-2026-09-10-part2.md` from stale PR #5 (closed as included). No engine restart required.
- **[2026-09-10]** Data review part 2 (`docs/REVIEW-2026-09-10-part2.md`, "data collection 11", rescued from PR #5): 79 new log rows, trade #42 (BUY SL −$3.33, passes all gates incl. rejected PROX pair), true equity $422.35. Stall recovered as one 293.5-min hole (00:47→05:41, no trade open across it); drift fix survived the ~06:33 restart (`daily_losses: 2` correct).
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

## 📊 Forward Test Observations (Sep 4–15, 2026)
- **Ledger at 2026-09-15**: 164 trades, 14W/58L/92BE → **19.4% decisive** (8.5% all-in), true P&L −$140.94 ($500 → $359.06). Needs 40% decisive to break even at 1:1.5. New regime since the 09-10 stack: 119 trades, −0.123R/trade (was −0.649R pre-ratchet).
- **Interim 2026-09-16**: 214 trades; 39 at +0.75R → 7W/14L/18BE, 33.3% dec (CI 17–55), −$0.36/trade. Mechanism confirmed (scratch 75%→46%, BE hold 1.9→9 min, BUY winning again), edge unproven. RSI≥45 case reversed (parked); cooldown leak +$209 (candidate b first in queue, held); ATR≥2.5 still 0% (held). No changes; full re-review ≈ 09-29+.
- **Win-rate diagnosis (09-15)**: the decisive rate is low mostly because the +0.30R breakeven ratchet harvested 77% of new-regime trades into $0 scratches — the entry stream itself replays near 50/50. Raised the trigger to 0.75R.
- **Blocked > taken, still**: the risk layer replayed its own rejects at 64% decisive (+$198.20 sequential across 99 deduped signals) while taken trades won 19.4%. Cooldown escalation is the biggest leak (+$163).
- **Review Findings**: Without daily circuit breakers, bad days (Sept 8 grind-down and Sept 9 afternoon news dump) resulted in 20 Stop Losses across 2 days. The new daily cap and US macro blackout directly protect against these scenarios.
- **Funnel Stats**: System now monitors both dynamic floor (Long) and dynamic ceiling (Short) with slope and proximity confirmation.

## 🚀 Future Tweaks / To-Do
- [x] Add Short-Selling logic for when `EMA50 < EMA200`.
- [x] Add Daily Loss limit (`MAX_DAILY_LOSSES = 3`) to `trade_filter.py`.
- [x] Implement escalating SL cooldown (30 min -> 60 min on consecutive SLs).
- [ ] Judge the +0.75R ratchet after ~2 weeks (P&L/day and bleed per trade, not WR alone); fallback = disable ratchet, NOT back to 0.30R.
- [ ] Adopt RSI ≥ 45 entry gate once the ratchet change is measured (criteria met 2026-09-15).
- [ ] Cooldown semantics: BE should reset the SL streak; consider a ~5-min post-scratch pause to stop same-move re-entry churn.
- [ ] No time stop exists — a trade opened before a market close rides the gap (#95, 49.1 h). Consider a max-hold close (~4h) so live behaviour matches the research replay.
- [ ] Multi-Timeframe (15m/1h) higher-timeframe trend integration.
- [ ] Live spread filter check before order dispatch.
