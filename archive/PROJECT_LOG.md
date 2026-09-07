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
- **[2026-09-04]** Removed restrictive `MIN_EMA_GAP` filter from `trade_filter.py`. It was blocking valid pullbacks because the EMA gap naturally shrinks during pullbacks.
- **[2026-09-04]** Aligned ATR thresholds. `engine.py` `MIN_ATR` changed from 0.70 to 1.10 to match `trade_filter.py`.
- **[2026-09-04]** Fixed funnel diagnostics in `engine.py`. Added `self.hit_... += 1` counters so `status.json` accurately tracks where signals drop off.
- **[2026-09-04]** Updated `datetime.utcnow()` to `datetime.now(timezone.utc)` in `trade_filter.py` to prevent Python 3.12+ deprecation warnings.

## 📊 Forward Test Observations (Sep 4, 2026)
- **Initial Run**: Bot took 8 consecutive SLs. Root cause: Market was transitioning from uptrend to downtrend. EMAs lagged, so `trend_ok` was still True while price was dropping.
- **Filter Success**: After the 8 SLs, the bot correctly stopped taking trades because `EMA50 < EMA200` (downtrend).
- **Capital Protection**: Bot took 1 TP (+$6.12) and 1 SL (-$3.75). After the SL, `trade_filter.py` successfully blocked 7 subsequent valid setups for 30 minutes to prevent revenge trading.
- **Funnel Stats (248 candles)**: 135 tested floor -> 67 valid rejection -> 10 all_confirmed. 4% hit rate is healthy for this strict strategy.

## 🚀 Future Tweaks / To-Do
- [ ] Add Short-Selling logic for when `EMA50 < EMA200`.
- [ ] Consider adding a "Max Trades Per Day" limit to `trade_filter.py`.
- [ ] Implement escalating SL cooldown (e.g., 60 mins after 2 consecutive SLs).
- [ ] Enable `REQUIRE_VOLUME_CONFIRM` and tune `VOLUME_SPIKE_MULTIPLIER`.
