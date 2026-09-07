# 📓 Gold Price Action Engine — Project Journal & Blueprint

This document serves as the master engineering blueprint and systemic log for the automated trading architecture established inside the `metatrade` container workspace. It provides a complete reference for future scaling, optimization, and transition to live capital.

---

## 🏗️ 1. Infrastructure & Environment Topology

### System Architecture

| Item | Detail |
|---|---|
| **Host Platform** | Proxmox VE (PVE Node) |
| **Target Container** | Debian 12 (Bookworm) Standard LXC (Unprivileged) |
| **Container Internal IP** | `192.168.0.147` |
| **Compute Resources** | 2 CPU Cores / 1.00 GiB RAM / 30 GiB Bootdisk |
| **Sandbox Workspace Path** | `/opt/gold` |
| **Python Virtual Environment** | `/opt/gold/venv/bin/python3` |

### Environment Configuration (`/opt/gold/.env`)

The system depends on strict variable separation inside a hidden environmental layer structured precisely as follows:

```env
TELEGRAM_BOT_TOKEN="8706787487:AA..."
TELEGRAM_CHAT_ID="YOUR_CHAT_ID_STRING"
XM_PASSWORD="your_custom_mt5_master_password"
TWELVE_DATA_API_KEY="e3a6e613e63e468889d1231afaae460d"
```

---

## 📐 2. The Algorithmic Strategy Logic

The core processing loop interprets the high-speed spot Gold chart data (`XAU/USD`) on a strict **1-minute (`1m`)** interval based on three price action conditions:

1. **Dynamic Support Floor Calculation**
   The algorithm maintains a sliding memory queue tracking the lowest point reached across the last 20 completed minutes (`LOOKBACK_PERIOD = 20`).

2. **The Floor Test**
   The current active 1-minute candle must push down to aggressively test or slice below this dynamic support price floor (`c_low <= dynamic_floor`).

3. **The Lower Wick Rejection Math**
   The lower wick (distance from the bottom of the solid candle body to its absolute lowest tail) must measure equal to or greater than 50% of the entire candle's trading range (`lower_wick / candle_range >= 0.50`). This proves a massive presence of institutional buying pressure.

4. **The Support Defense Confirmation**
   The 1-minute candle must execute its closing transaction safely back above the calculated dynamic support line (`c_close > dynamic_floor`).

---

## 💻 3. Complete Source Code Blueprint (`engine.py`)

This production script runs natively on Linux under an asynchronous event driver loop utilizing the official Twelve Data client libraries. It handles data aggregation, strategy calculations, CSV persistence logging, and mobile Telegram push messaging.

```python
import os
import csv
import time
import sys
import requests
from dotenv import load_dotenv
from twelvedata import TDClient

# Load parameters safely from path
load_dotenv(dotenv_path="/opt/gold/.env")

ACCOUNT_ID = "420568040"
TWELVE_DATA_KEY = os.getenv("TWELVE_DATA_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- STRATEGY PARAMETERS ---
LOOKBACK_PERIOD = 20
WICK_RATIO_TARGET = 0.50

# --- FORWARD TEST ENVIRONMENT VARIABLES ---
VIRTUAL_BALANCE = 500.00
SIMULATED_TRADE_ACTIVE = False
VIRTUAL_ENTRY_PRICE = 0.00
VIRTUAL_STOP_LOSS = 0.00
VIRTUAL_TAKE_PROFIT = 0.00
TOTAL_SIM_TRADES = 0
SIM_WINS = 0
SIM_LOSSES = 0

Recently added: 
MAX_ATR_TO_TRADE    = 4.50   

 # 3b. Maximum ATR (Block extreme news volatility)
    if current_atr is not None and current_atr > MAX_ATR_TO_TRADE:
        reason = f"ATR too high - News volatility ({current_atr:.2f} > {MAX_ATR_TO_TRADE})"
        log_skip(reason, current_price, current_atr)
        return False, reason

Let's turn it off. Open trade_filter.py and comment out the call to analyze_recent:

    # 4. Recent SL pattern (Circuit breaker) - DISABLED FOR NOW
    # skip, reason = analyze_recent(trades)
    # if skip:
    #     log_skip(reason, current_price, current_atr)
    #     return False, reason

# --- DATA STORAGE QUEUES ---
minute_tick_pool = []
current_candle_minute = None
completed_lows_cache = []
LOG_FILE_PATH = "/opt/gold/forward_test_log.csv"


def send_telegram_notification(text_message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": str(TELEGRAM_CHAT_ID),
        "text": text_message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=3)
    except Exception as e:
        print(f"\n⚠️ Telegram alert delivery failed: {e}")


def log_candle_to_csv(timestamp, c_open, c_high, c_low, c_close,
                      ratio, dynamic_floor, tested, rejected, held):
    file_exists = os.path.isfile(LOG_FILE_PATH)
    with open(LOG_FILE_PATH, mode='a', newline='') as csv_file:
        fieldnames = [
            'Timestamp', 'Open', 'High', 'Low', 'Close',
            'Wick_Ratio', 'Dynamic_Floor', 'Tested_Floor',
            'Valid_Rejection', 'Held_Floor'
        ]
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            'Timestamp': timestamp,
            'Open': f"{c_open:.2f}",
            'High': f"{c_high:.2f}",
            'Low': f"{c_low:.2f}",
            'Close': f"{c_close:.2f}",
            'Wick_Ratio': f"{ratio:.1%}",
            'Dynamic_Floor': f"{dynamic_floor:.2f}" if dynamic_floor else "Calculating",
            'Tested_Floor': str(tested),
            'Valid_Rejection': str(rejected),
            'Held_Floor': str(held)
        })


def evaluate_price_action_rules(c_open, c_high, c_low, c_close):
    global TOTAL_SIM_TRADES, SIMULATED_TRADE_ACTIVE
    global VIRTUAL_ENTRY_PRICE, VIRTUAL_STOP_LOSS, VIRTUAL_TAKE_PROFIT
    global completed_lows_cache

    candle_range = c_high - c_low
    if candle_range <= 0:
        return

    body_bottom = min(c_open, c_close)
    lower_wick = body_bottom - c_low
    calculated_ratio = lower_wick / candle_range

    if len(completed_lows_cache) < LOOKBACK_PERIOD:
        print(f"⏳ Accumulating historical lookup data... "
              f"({len(completed_lows_cache)}/{LOOKBACK_PERIOD} minutes filled)")
        dynamic_floor = None
        tested_floor, held_support = False, False
    else:
        dynamic_floor = min(completed_lows_cache)
        tested_floor = c_low <= dynamic_floor
        held_support = c_close > dynamic_floor

    valid_rejection = calculated_ratio >= WICK_RATIO_TARGET

    if dynamic_floor:
        print(f"📊 Dynamic Floor: ${dynamic_floor:.2f} | "
              f"Current Candle Low: ${c_low:.2f}")
        print(f"📐 Metrics Analysis -> Range: ${candle_range:.2f} | "
              f"Wick: ${lower_wick:.2f} (Ratio: {calculated_ratio:.1%})")
        print(f"🧐 Condition Evaluation -> Tested Floor: {tested_floor} | "
              f"Rejection Valid: {valid_rejection} | Held Floor: {held_support}")

    formatted_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    log_candle_to_csv(
        formatted_time, c_open, c_high, c_low, c_close,
        calculated_ratio,
        dynamic_floor if dynamic_floor else 0.0,
        tested_floor, valid_rejection, held_support
    )

    completed_lows_cache.append(c_low)
    if len(completed_lows_cache) > LOOKBACK_PERIOD:
        completed_lows_cache.pop(0)

    if dynamic_floor and tested_floor and valid_rejection and held_support:
        if not SIMULATED_TRADE_ACTIVE:
            SIMULATED_TRADE_ACTIVE = True
            TOTAL_SIM_TRADES += 1
            VIRTUAL_ENTRY_PRICE = c_close
            VIRTUAL_STOP_LOSS = c_close - 2.50
            VIRTUAL_TAKE_PROFIT = c_close + 5.00
            msg = (
                f"🚨 *PRICE ACTION SETUP RECOGNIZED*\n\n"
                f"📥 Virtual Position #{TOTAL_SIM_TRADES} Opened\n"
                f"💰 Entry Price: ${VIRTUAL_ENTRY_PRICE:.2f}\n"
                f"🛑 Protection SL: ${VIRTUAL_STOP_LOSS:.2f}\n"
                f"🎯 Target TP: ${VIRTUAL_TAKE_PROFIT:.2f}"
            )
            send_telegram_notification(msg)
            print(f"\n🤖 Alert dispatched to phone for Trade #{TOTAL_SIM_TRADES}\n")


def aggregate_ticks_into_candle(live_price):
    global minute_tick_pool, current_candle_minute

    current_time = time.localtime()
    minute_now = current_time.tm_min

    if current_candle_minute is None:
        current_candle_minute = minute_now

    if minute_now != current_candle_minute:
        if len(minute_tick_pool) > 0:
            candle_open = minute_tick_pool[0]
            candle_high = max(minute_tick_pool)
            candle_low = min(minute_tick_pool)
            candle_close = minute_tick_pool[-1]
            print(f"\n⏰ [CANDLE CLOSED] Time: {current_time.tm_hour}:"
                  f"{current_candle_minute:02d} | "
                  f"O: {candle_open:.2f} H: {candle_high:.2f} "
                  f"L: {candle_low:.2f} C: {candle_close:.2f}")
            evaluate_price_action_rules(
                candle_open, candle_high, candle_low, candle_close
            )
        minute_tick_pool.clear()
        current_candle_minute = minute_now

    minute_tick_pool.append(live_price)


def check_virtual_position(current_price):
    global SIMULATED_TRADE_ACTIVE, VIRTUAL_BALANCE, SIM_WINS, SIM_LOSSES

    if not SIMULATED_TRADE_ACTIVE:
        return

    if current_price >= VIRTUAL_TAKE_PROFIT:
        VIRTUAL_BALANCE += 5.00
        SIM_WINS += 1
        SIMULATED_TRADE_ACTIVE = False
        win_rate = (SIM_WINS / TOTAL_SIM_TRADES) * 100
        msg = (
            f"✅ *VIRTUAL PROFIT TARGET HIT*\n\n"
            f"💰 Exit Price: ${current_price:.2f} (+ $5.00)\n"
            f"💳 Account Equity: ${VIRTUAL_BALANCE:.2f}\n"
            f"🎯 Active Win Rate: {win_rate:.1f}%"
        )
        send_telegram_notification(msg)
        print_ledger_summary()

    elif current_price <= VIRTUAL_STOP_LOSS:
        VIRTUAL_BALANCE -= 2.50
        SIM_LOSSES += 1
        SIMULATED_TRADE_ACTIVE = False
        win_rate = (SIM_WINS / TOTAL_SIM_TRADES) * 100
        msg = (
            f"❌ *VIRTUAL STOP LOSS HIT*\n\n"
            f"📉 Exit Price: ${current_price:.2f} (- $2.50)\n"
            f"💳 Account Equity: ${VIRTUAL_BALANCE:.2f}\n"
            f"🎯 Active Win Rate: {win_rate:.1f}%"
        )
        send_telegram_notification(msg)
        print_ledger_summary()


def print_ledger_summary():
    win_rate = (SIM_WINS / TOTAL_SIM_TRADES) * 100 if TOTAL_SIM_TRADES > 0 else 0
    print("📊 --- LIVE FORWARD TESTING SCORECARD ---")
    print(f"📈 Total Tracked Positions: {TOTAL_SIM_TRADES}")
    print(f"✅ Successful Wins: {SIM_WINS}  |  ❌ Risk Failures: {SIM_LOSSES}")
    print(f"🎯 Strategy Win Rate: {win_rate:.1f}%")
    print(f"💳 Simulated Account Equity: ${VIRTUAL_BALANCE:.2f}")
    print("────────────────────────────────────────\n")


def on_event(event):
    if event.get("event") == "price":
        live_price = float(event["price"])
        check_virtual_position(live_price)
        aggregate_ticks_into_candle(live_price)
        print(f"⏱️ Live Tick: ${live_price:.2f} "
              f"(Active Pool: {len(minute_tick_pool)} ticks)", end="\r")
        sys.stdout.flush()


def main():
    print("🚀 Initializing Native Linux Cloud Engine via Twelve Data SDK...")
    if not TWELVE_DATA_KEY:
        return
    send_telegram_notification(
        "🤖 Gold Engine Sandbox Initialized Successfully\n\n"
        "Tracking dynamic 20-minute floors on Proxmox LXC Container."
    )
    td = TDClient(apikey=TWELVE_DATA_KEY)
    ws = td.websocket(symbols="XAU/USD", on_event=on_event)
    ws.connect()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        ws.disconnect()


if __name__ == "__main__":
    main()
```

---

## 4. Operation Runbook & System Control

The script runs safely as an integrated daemon background task managed by Debian's core initialization network managers.

### Administrative Control Commands

| Action | Command |
|---|---|
| **Check System Status** | `systemctl status goldbot.service` |
| **Force Manual Stop** | `systemctl stop goldbot.service` |
| **Trigger Service Restart** | `systemctl restart goldbot.service` |
| **Tail Real-time Logs** | `journalctl -u goldbot.service -f -n 50` |
| **Read Raw Candle Logs** | `cat /opt/gold/forward_test_log.csv` |

---

## 5. Future Scope: Phase 4 — Live Execution Layout

When forward testing yields a safe win metrics profile (suggested testing interval: **3–5 market days**), transitioning the script to open live **0.01 micro lot** positions automatically on your **XM Global MT5 Account (420568040)** can be integrated directly within the rule evaluation block using the custom `metaapi-cloud-sdk` layer.

### Code Staging for Live Execution (Future Integration)

The function below represents the exact structure to replace the mock virtual trading flags in the final project iteration:

```python
from metaapi_cloud_sdk import MetaApi

async def execute_live_xm_order(action_side, close_price):
    """Executes live 0.01 lot market entries directly via the MetaApi cloud engine bridge."""
    api = MetaApi("YOUR_METAAPI_PRODUCTION_TOKEN")
    try:
        account = await api.metatrader_account_api.get_account(
            "YOUR_METADATA_ACCOUNT_GUID"
        )
        connection = account.get_rpc_connection()
        await connection.connect()

        # Structure a live 0.01 Micro lot order using custom risk protective thresholds
        order_payload = {
            "actionType": "ORDER_TYPE_BUY" if action_side == "BUY" else "ORDER_TYPE_SELL",
            "volume": 0.01,
            "symbol": "XAUUSD",
            "stopLoss": close_price - 2.50,
            "takeProfit": close_price + 5.00
        }
        print(f"💸 TRANSMITTING LIVE ORDER TO XM SERVERS: {order_payload}")

        # result = await connection.create_market_buy_order(
        #     "XAUUSD", 0.01, close_price - 2.50, close_price + 5.00
        # )
    except Exception as e:
        print(f"❌ Live broker transmission failed: {e}")
```
