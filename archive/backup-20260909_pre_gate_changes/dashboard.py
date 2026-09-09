import os
import csv
import json
from flask import Flask, render_template_string

app = Flask(__name__)

LOG_FILE_PATH = "/opt/gold/forward_test_log.csv"
STATUS_FILE_PATH = "/opt/gold/status.json"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Gold Trading Engine Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <meta http-equiv="refresh" content="5">
</head>
<body class="bg-slate-900 text-slate-100 font-sans p-6">
    <div class="max-w-7xl mx-auto">

        <!-- Header -->
        <header class="flex flex-col md:flex-row justify-between items-start md:items-center mb-8 border-b border-slate-800 pb-4 gap-4">
            <div>
                <h1 class="text-3xl font-bold text-amber-400">🪙 Gold Forward Test Dashboard</h1>
                <p class="text-slate-400 text-sm">
                    XAU/USD • Auto-refreshes every 5s • Last status: {{ status.last_update or '—' }}
                </p>
            </div>
            <div class="bg-slate-800 px-5 py-3 rounded-xl border border-slate-700 text-right">
                <span class="text-xs text-slate-400 block">Simulated Equity</span>
                <span class="text-3xl font-semibold {{ 'text-emerald-400' if status.equity >= 500 else 'text-rose-400' }}">
                    ${{ "%.2f"|format(status.equity) }}
                </span>
            </div>
        </header>

        <!-- Main Stats -->
        <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-7 gap-4 mb-6">
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">Closed Trades</p>
                <p class="text-2xl font-bold text-amber-400">{{ status.total_trades }}</p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">Wins</p>
                <p class="text-2xl font-bold text-emerald-400">{{ status.wins }}</p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">Losses</p>
                <p class="text-2xl font-bold text-rose-400">{{ status.losses }}</p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">Win Rate</p>
                <p class="text-2xl font-bold text-blue-400">{{ status.win_rate }}%</p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">Next Trade #</p>
                <p class="text-2xl font-bold text-cyan-400">{{ status.next_trade_num or '—' }}</p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">Open Trade</p>
                <p class="text-2xl font-bold {{ 'text-emerald-400' if status.trade_active else 'text-slate-500' }}">
                    {{ 'YES' if status.trade_active else 'No' }}
                </p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">Total Candles</p>
                <p class="text-2xl font-bold">{{ total }}</p>
            </div>
        </div>

        <!-- Active Trade Panel -->
        {% if status.trade_active %}
        <div class="bg-slate-800 border border-amber-700/50 rounded-xl p-4 mb-6">
            <p class="text-sm text-amber-400 font-semibold mb-2">🔥 Active Virtual Trade</p>
            <div class="grid grid-cols-3 gap-4 text-sm">
                <div>
                    <span class="text-slate-400">Entry</span><br>
                    <span class="text-lg font-semibold">${{ "%.2f"|format(status.entry_price or 0) }}</span>
                </div>
                <div>
                    <span class="text-slate-400">Stop Loss</span><br>
                    <span class="text-lg font-semibold text-rose-400">${{ "%.2f"|format(status.stop_loss or 0) }}</span>
                </div>
                <div>
                    <span class="text-slate-400">Take Profit</span><br>
                    <span class="text-lg font-semibold text-emerald-400">${{ "%.2f"|format(status.take_profit or 0) }}</span>
                </div>
            </div>
        </div>
        {% endif %}

        <!-- Indicator Snapshot -->
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">EMA 50</p>
                <p class="text-xl font-bold text-cyan-400">
                    {% if status.ema_fast %}{{ "%.2f"|format(status.ema_fast) }}{% else %}—{% endif %}
                </p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">EMA 200</p>
                <p class="text-xl font-bold text-blue-400">
                    {% if status.ema_slow %}{{ "%.2f"|format(status.ema_slow) }}{% else %}—{% endif %}
                </p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">RSI (14)</p>
                <p class="text-xl font-bold text-purple-400">
                    {% if status.rsi %}{{ "%.1f"|format(status.rsi) }}{% else %}—{% endif %}
                </p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">ATR (14)</p>
                <p class="text-xl font-bold text-amber-400">
                    {% if status.atr %}{{ "%.2f"|format(status.atr) }}{% else %}—{% endif %}
                </p>
            </div>
        </div>

        <!-- Funnel Stats (from status.json when available, else candle log) -->
        <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4 mb-8">
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">Candles Eval</p>
                <p class="text-xl font-bold">{{ funnel.candles_evaluated }}</p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">Tested Floor</p>
                <p class="text-xl font-bold text-blue-400">{{ funnel.tested_floor }}</p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">Valid Rejection</p>
                <p class="text-xl font-bold text-amber-400">{{ funnel.valid_rejection }}</p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">Held Support</p>
                <p class="text-xl font-bold text-emerald-400">{{ funnel.held_support }}</p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">Volume OK</p>
                <p class="text-xl font-bold text-purple-400">{{ funnel.volume_confirmed }}</p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">Trend OK</p>
                <p class="text-xl font-bold text-cyan-400">{{ funnel.trend_confirmed }}</p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">All Confirmed</p>
                <p class="text-xl font-bold text-rose-400">{{ funnel.all_confirmed }}</p>
            </div>
        </div>

        <!-- Candle Log -->
        <div class="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
            <div class="px-6 py-4 border-b border-slate-700 font-semibold text-slate-200">
                Recent Candle Log (last 30)
            </div>
            <div class="overflow-x-auto">
                <table class="w-full text-left text-sm text-slate-300">
                    <thead class="bg-slate-900/50 text-slate-400 uppercase text-xs">
                        <tr>
                            <th class="px-3 py-3">Timestamp</th>
                            <th class="px-3 py-3">Close</th>
                            <th class="px-3 py-3">Wick %</th>
                            <th class="px-3 py-3">Floor</th>
                            <th class="px-3 py-3">EMA50</th>
                            <th class="px-3 py-3">EMA200</th>
                            <th class="px-3 py-3">RSI</th>
                            <th class="px-3 py-3">Trend</th>
                            <th class="px-3 py-3">Tested</th>
                            <th class="px-3 py-3">Held</th>
                            <th class="px-3 py-3">Rejection</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-700">
                        {% for row in rows %}
                        <tr class="hover:bg-slate-700/40">
                            <td class="px-3 py-2 font-mono text-xs">{{ row.Timestamp or '—' }}</td>
                            <td class="px-3 py-2 font-semibold">
                                {% if not row.Close or row.Close == 'Calculating' %}—{% else %}${{ row.Close }}{% endif %}
                            </td>
                            <td class="px-3 py-2">{{ row.Wick_Ratio or '—' }}</td>
                            <td class="px-3 py-2">
                                {% if not row.Dynamic_Floor or row.Dynamic_Floor == 'Calculating' %}—{% else %}${{ row.Dynamic_Floor }}{% endif %}
                            </td>
                            <td class="px-3 py-2">
                                {% if not row.EMA_50 or row.EMA_50 == 'Calculating' %}—{% else %}${{ row.EMA_50 }}{% endif %}
                            </td>
                            <td class="px-3 py-2">
                                {% if not row.EMA_200 or row.EMA_200 == 'Calculating' %}—{% else %}${{ row.EMA_200 }}{% endif %}
                            </td>
                            <td class="px-3 py-2">
                                {% if not row.RSI or row.RSI == 'Calculating' %}—{% else %}{{ row.RSI }}{% endif %}
                            </td>
                            <td class="px-3 py-2">
                                <span class="px-2 py-0.5 rounded text-xs 
                                    {{ 'bg-emerald-900/50 text-emerald-400' if row.Trend_Confirmed == 'True' else 'bg-rose-900/50 text-rose-400' }}">
                                    {{ row.Trend_Confirmed or 'False' }}
                                </span>
                            </td>
                            <td class="px-3 py-2">
                                <span class="px-2 py-0.5 rounded text-xs 
                                    {{ 'bg-blue-900/50 text-blue-400' if row.Tested_Floor == 'True' else 'bg-slate-700 text-slate-500' }}">
                                    {{ row.Tested_Floor or 'False' }}
                                </span>
                            </td>
                            <td class="px-3 py-2">
                                <span class="px-2 py-0.5 rounded text-xs 
                                    {{ 'bg-emerald-900/50 text-emerald-400' if row.Held_Floor == 'True' else 'bg-slate-700 text-slate-500' }}">
                                    {{ row.Held_Floor or 'False' }}
                                </span>
                            </td>
                            <td class="px-3 py-2">
                                <span class="px-2 py-0.5 rounded text-xs 
                                    {{ 'bg-amber-900/50 text-amber-400' if row.Valid_Rejection == 'True' else 'bg-slate-700 text-slate-500' }}">
                                    {{ row.Valid_Rejection or 'False' }}
                                </span>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>

    </div>
</body>
</html>
"""

@app.route("/")
def index():
    status = {
        "equity": 500.00,
        "total_trades": 0,
        "next_trade_num": None,
        "wins": 0,
        "losses": 0,
        "win_rate": 0.0,
        "trade_active": False,
        "entry_price": None,
        "stop_loss": None,
        "take_profit": None,
        "last_update": None,
        "rsi": None,
        "ema_fast": None,
        "ema_slow": None,
        "atr": None,
        "funnel": {},
    }

    if os.path.isfile(STATUS_FILE_PATH):
        try:
            with open(STATUS_FILE_PATH) as f:
                status.update(json.load(f))
        except Exception:
            pass

    # Prefer live funnel from status.json; fall back to scanning the candle log
    funnel = status.get("funnel") or {}
    rows = []
    total_rows = 0
    trend_count = 0
    vol_count = 0
    rejection_count = 0

    if os.path.isfile(LOG_FILE_PATH):
        try:
            with open(LOG_FILE_PATH, mode="r") as f:
                reader = csv.DictReader(f)
                for line in reader:
                    rows.append(line)
                    total_rows += 1
                    if line.get("Trend_Confirmed") == "True":
                        trend_count += 1
                    if line.get("Vol_Confirmed") == "True":
                        vol_count += 1
                    if line.get("Valid_Rejection") == "True":
                        rejection_count += 1
        except Exception as e:
            print(f"Error reading log: {e}")

    # Fill missing funnel keys from log scan if needed
    funnel.setdefault("candles_evaluated", total_rows)
    funnel.setdefault("tested_floor", 0)
    funnel.setdefault("valid_rejection", rejection_count)
    funnel.setdefault("held_support", 0)
    funnel.setdefault("volume_confirmed", vol_count)
    funnel.setdefault("trend_confirmed", trend_count)
    funnel.setdefault("all_confirmed", 0)

    recent_rows = list(reversed(rows))[:30]

    return render_template_string(
        HTML_TEMPLATE,
        rows=recent_rows,
        status=status,
        total=total_rows,
        funnel=funnel,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
