#!/usr/bin/env python3
import os
import csv
import json
import time
import sys
import requests
from collections import deque
from dotenv import load_dotenv
import MetaTrader5 as mt5

load_dotenv(dotenv_path="/opt/gold/.env")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- STRATEGY PARAMETERS ---
LOOKBACK_PERIOD = 20
WICK_RATIO_TARGET = 0.50
EMA_FAST = 50
EMA_SLOW = 200
RSI_PERIOD = 14
ATR_PERIOD = 14
FLOOR_BUFFER_PCT = 0.0015

ATR_SL_MULT = 1.5
ATR_TP_MULT = 3.0

REQUIRE_VOLUME_CONFIRM = False
VOLUME_SPIKE_MULTIPLIER = 0.9
REQUIRE_TREND_CONFIRM = True

# --- LIVE TRADING PARAMETERS ---
SYMBOL = "GOLD"       # Confirmed from your broker
LOT_SIZE = 0.01       # START SMALL for safety!
MAGIC_NUMBER = 987654

LOG_FILE_PATH = "/opt/gold/forward_test_log.csv"
STATUS_FILE_PATH = "/opt/gold/status.json"
TRADES_LOG_PATH = "/opt/gold/trades.csv"


class GoldEngineLive:
    def __init__(self):
        self.lows = deque(maxlen=EMA_SLOW)
        self.highs = deque(maxlen=EMA_SLOW)
        self.closes = deque(maxlen=EMA_SLOW)
        self.volumes = deque(maxlen=EMA_SLOW)
        self.tr_list = deque(maxlen=ATR_PERIOD)
        self.rsi_gains = deque(maxlen=RSI_PERIOD)
        self.rsi_losses = deque(maxlen=RSI_PERIOD)

        self.prev_close = None
        self.rsi = None
        self.ema_fast = None
        self.ema_slow = None
        self.atr = None

        self.k_fast = 2 / (EMA_FAST + 1)
        self.k_slow = 2 / (EMA_SLOW + 1)

        self.current_minute = None
        self.tick_pool = []

        self.total_trades = 0
        self.wins = 0
        self.losses = 0

        self.warmup_logged = False
        self.candles_evaluated = 0

        # Initialize MT5
        if not mt5.initialize():
            print(f"❌ MT5 Initialize failed: {mt5.last_error()}")
            sys.exit(1)
        
        account = mt5.account_info()
        print(f"✅ Connected to MT5 | Account: {account.login} | Balance: {account.balance} {account.currency}")
        
        # Ensure symbol is visible
        mt5.symbol_select(SYMBOL, True)

    def calculate_rsi(self):
        if len(self.rsi_gains) < RSI_PERIOD:
            self.rsi = None
            return
        avg_gain = sum(self.rsi_gains) / RSI_PERIOD
        avg_loss = sum(self.rsi_losses) / RSI_PERIOD
        if avg_loss == 0:
            self.rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            self.rsi = 100 - (100 / (1 + rs))

    def calculate_atr(self):
        if len(self.tr_list) < ATR_PERIOD:
            self.atr = None
            return
        self.atr = sum(self.tr_list) / ATR_PERIOD

    def update_indicators(self, high, low, close):
        if self.ema_fast is None:
            if len(self.closes) >= EMA_FAST:
                self.ema_fast = sum(list(self.closes)[-EMA_FAST:]) / EMA_FAST
        else:
            self.ema_fast = (close * self.k_fast) + (self.ema_fast * (1 - self.k_fast))

        if self.ema_slow is None:
            if len(self.closes) >= EMA_SLOW:
                self.ema_slow = sum(list(self.closes)[-EMA_SLOW:]) / EMA_SLOW
        else:
            self.ema_slow = (close * self.k_slow) + (self.ema_slow * (1 - self.k_slow))

        if self.prev_close is not None:
            change = close - self.prev_close
            self.rsi_gains.append(max(change, 0))
            self.rsi_losses.append(max(-change, 0))
            self.calculate_rsi()

            tr = max(high - low, abs(high - self.prev_close), abs(low - self.prev_close))
            self.tr_list.append(tr)
            self.calculate_atr()

        self.prev_close = close

    def send_telegram(self, text: str):
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            return
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": str(TELEGRAM_CHAT_ID), "text": text, "parse_mode": "Markdown"}
        try:
            requests.post(url, json=payload, timeout=4)
        except Exception as e:
            print(f"\n⚠️ Telegram failed: {e}")

    def evaluate_candle(self, o, h, l, c, tick_count):
        candle_range = h - l
        if candle_range <= 0:
            return

        body_bottom = min(o, c)
        lower_wick = body_bottom - l
        wick_ratio = lower_wick / candle_range
        valid_rejection = wick_ratio >= WICK_RATIO_TARGET

        dynamic_floor = None
        volume_ma = None
        tested_floor = False
        held_support = False
        volume_confirmed = False
        trend_confirmed = False

        self.candles_evaluated += 1

        if len(self.closes) >= LOOKBACK_PERIOD:
            dynamic_floor = min(list(self.lows)[-LOOKBACK_PERIOD:])
            volume_ma = sum(list(self.volumes)[-LOOKBACK_PERIOD:]) / LOOKBACK_PERIOD
            tested_floor = l <= (dynamic_floor * (1 + FLOOR_BUFFER_PCT))
            held_support = c > dynamic_floor
            volume_confirmed = tick_count >= (volume_ma * VOLUME_SPIKE_MULTIPLIER) if volume_ma else True

        if self.ema_fast is not None and self.ema_slow is not None:
            trend_confirmed = self.ema_fast > self.ema_slow
        elif self.ema_fast is not None:
            trend_confirmed = c > self.ema_fast
        else:
            trend_confirmed = False

        if len(self.closes) < EMA_SLOW:
            if not self.warmup_logged or len(self.closes) % 30 == 0:
                print(f"⏳ Warming up indicators... {len(self.closes)}/{EMA_SLOW}")
                self.warmup_logged = True
        else:
            rsi_str = f"{self.rsi:.1f}" if self.rsi is not None else "—"
            atr_str = f"{self.atr:.2f}" if self.atr is not None else "—"
            print(f"📊 Floor:${dynamic_floor:.2f} | EMA50:${self.ema_fast:.2f} EMA200:${self.ema_slow:.2f} | RSI:{rsi_str} ATR:{atr_str} | C:${c:.2f}")
            print(f"   Tested:{tested_floor} | Rej:{valid_rejection} ({wick_ratio:.0%}) | Held:{held_support} | Vol:{volume_confirmed} | Trend:{trend_confirmed}")

        # --- LIVE EXECUTION LOGIC ---
        vol_ok = volume_confirmed if REQUIRE_VOLUME_CONFIRM else True
        trend_ok = trend_confirmed if REQUIRE_TREND_CONFIRM else True

        if (dynamic_floor is not None and self.ema_slow is not None and self.atr is not None and
                tested_floor and valid_rejection and held_support and vol_ok and trend_ok):

            print("\n🚨 ALL CONDITIONS MET! PREPARING LIVE ORDER...")
            
            # 1. Calculate SL and TP
            sl_price = c - (self.atr * ATR_SL_MULT)
            tp_price = c + (self.atr * ATR_TP_MULT)
            
            # 2. Normalize prices to broker's digits
            symbol_info = mt5.symbol_info(SYMBOL)
            point = symbol_info.point
            sl_price = round(sl_price / point) * point
            tp_price = round(tp_price / point) * point
            
            # 3. Get current market price
            tick = mt5.symbol_info_tick(SYMBOL)
            if tick is None:
                print("⚠️ Failed to get tick data")
                return

            # 4. Build the MT5 Order Request
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": SYMBOL,
                "volume": LOT_SIZE,
                "type": mt5.ORDER_TYPE_BUY,
                "price": tick.ask,
                "sl": sl_price,
                "tp": tp_price,
                "deviation": 20,
                "magic": MAGIC_NUMBER,
                "comment": "Gold Engine Live",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_FOK, 
            }

            print(f"   ➡️ Sending: BUY {LOT_SIZE} {SYMBOL} @ {tick.ask:.2f}")
            print(f"   ➡️ SL: {sl_price:.2f} | TP: {tp_price:.2f}")

            # 5. Execute the order
            result = mt5.order_send(request)
            
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                print(f"❌ Order failed: {result.retcode} - {result.comment}")
                self.send_telegram(f"❌ *ORDER FAILED*\nCode: {result.retcode}\nMsg: {result.comment}")
            else:
                self.total_trades += 1
                print(f"✅ ORDER SUCCESS! Ticket: {result.order}")
                msg = (
                    f"🚨 *LIVE GOLD BUY EXECUTED*\n\n"
                    f"🎫 Ticket: `{result.order}`\n"
                    f"💰 Entry: `${tick.ask:.2f}`\n"
                    f"📊 RSI: `{self.rsi:.1f}` | ATR: `{self.atr:.2f}`\n"
                    f"🛑 SL: `${sl_price:.2f}`\n"
                    f"🎯 TP: `${tp_price:.2f}`"
                )
                self.send_telegram(msg)
                
            # Reset evaluation flags to prevent multiple entries on the same candle
            tested_floor = False 

        # Update deques for next iteration
        self.lows.append(l)
        self.highs.append(h)
        self.volumes.append(tick_count)
        self.closes.append(c)
        self.update_indicators(h, l, c)

    def run(self):
        print(f"🚀 Gold Engine LIVE starting for {SYMBOL}...")
        candles_fetched = 0
        
        while True:
            try:
                # Fetch the latest 250 M1 candles from MT5
                rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 250)
                
                if rates is None or len(rates) == 0:
                    print("⚠️ Failed to fetch rates. Retrying in 5s...")
                    time.sleep(5)
                    continue
                
                # Use the last CLOSED candle (index -2) to avoid repainting the current forming candle
                last_candle = rates[-2] 
                
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_candle['time']))
                o = float(last_candle['open'])
                h = float(last_candle['high'])
                l = float(last_candle['low'])
                c = float(last_candle['close'])
                vol = int(last_candle['tick_volume'])
                
                self.evaluate_candle(o, h, l, c, vol)
                
                if candles_fetched % 10 == 0:
                    print(f"💓 Heartbeat: Processed candle @ {timestamp} | Close: {c}")
                    
                candles_fetched += 1
                
                # Sleep until the next minute starts (MT5 M1 candles close at :00 seconds)
                # We sleep 60 seconds, but check every 5s in case of minor clock drift
                for _ in range(12):
                    time.sleep(5)
                
            except KeyboardInterrupt:
                print("\n⚙️ Shutting down gracefully...")
                mt5.shutdown()
                break
            except Exception as e:
                print(f"\n❌ Error in main loop: {e}")
                time.sleep(10)


if __name__ == "__main__":
    engine = GoldEngineLive()
    engine.run()
EOF
