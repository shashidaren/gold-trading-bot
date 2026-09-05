#!/usr/bin/env python3
"""
MT5-via-Wine connectivity test — READ ONLY.

Connects to the mt5linux bridge server (running on the Windows/Wine side,
started via `wine python -m mt5linux <path-to-windows-python.exe>`) and
prints account balance/equity as proof of connection. Does NOT place,
modify, or close any order.

Requires:
  pip install --break-system-packages mt5linux

The MT5 terminal must already be running under Wine and logged in
(see WINE_MT5_SETUP.md Step 3) before this will connect successfully.
"""
import sys

try:
    from mt5linux import MetaTrader5
except ImportError:
    print("❌ mt5linux not installed on the Linux side.")
    print("   Run: pip install --break-system-packages mt5linux")
    sys.exit(1)

# Default mt5linux bridge port is 18812 — change host/port if you started
# the bridge server differently.
BRIDGE_HOST = "localhost"
BRIDGE_PORT = 18812

print(f"🔌 Connecting to mt5linux bridge at {BRIDGE_HOST}:{BRIDGE_PORT}...")

try:
    mt5 = MetaTrader5(host=BRIDGE_HOST, port=BRIDGE_PORT)
except Exception as e:
    print(f"❌ Could not reach the bridge server: {e}")
    print("   Is the Wine-side bridge running? (Step 5 in WINE_MT5_SETUP.md)")
    sys.exit(1)

if not mt5.initialize():
    print(f"❌ mt5.initialize() failed: {mt5.last_error()}")
    print("   Check the MT5 terminal is running and logged in under Wine (Step 3).")
    sys.exit(1)

print("✅ Initialized.\n")

info = mt5.account_info()
if info is None:
    print(f"❌ account_info() returned None: {mt5.last_error()}")
    mt5.shutdown()
    sys.exit(1)

print("── Account Snapshot (read-only) ──")
print(f"  Login       : {info.login}")
print(f"  Server      : {info.server}")
print(f"  Currency    : {info.currency}")
print(f"  Balance     : {info.balance}")
print(f"  Equity      : {info.equity}")
print(f"  Leverage    : 1:{info.leverage}")
print(f"  Trade allowed (account-level): {info.trade_allowed}")
print("───────────────────────────────────")
print("\nNo orders were placed. This was a connectivity check only.")

mt5.shutdown()
