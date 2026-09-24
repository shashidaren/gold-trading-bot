import os
import csv
import json
from datetime import datetime, timezone
from flask import Flask, render_template_string

app = Flask(__name__)

LOG_FILE_PATH = "/opt/gold/forward_test_log.csv"
STATUS_FILE_PATH = "/opt/gold/status.json"
TRADES_FILE_PATH = "/opt/gold/trades.csv"

# Display-only mirrors of live engine constants (do not drive trading).
MAX_HOLD_MINUTES = 240
DEFAULT_MAX_DAILY_LOSSES = 10
STALE_AFTER_SECONDS = 300
ERA_075_START = datetime(2026, 9, 15, 6, 0)  # UTC, PR #9
ERA_MH_START = datetime(2026, 9, 21, 6, 0)   # UTC, PR #15 ~autosync

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Gold Trading Engine Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <meta http-equiv="refresh" content="15">
</head>
<body class="bg-slate-900 text-slate-100 font-sans p-6">
    <div class="max-w-7xl mx-auto">

        <header class="flex flex-col md:flex-row justify-between items-start md:items-center mb-8 border-b border-slate-800 pb-4 gap-4">
            <div>
                <h1 class="text-3xl font-bold text-amber-400">🪙 Gold Engine Dashboard</h1>
                <p class="text-slate-400 text-sm">
                    XAU/USD Bidirectional • Auto-refreshes every 15s • Last update: {{ status.last_update or '—' }}
                    {% if stale %}
                    <span class="ml-2 text-xs bg-rose-900/70 text-rose-200 px-2 py-0.5 rounded font-semibold">STALE</span>
                    <span class="text-xs text-rose-300">{{ stale_age }}</span>
                    {% endif %}
                </p>
                <p class="text-slate-500 text-xs mt-1">
                    Δ from $500 start: {{ equity_delta }}
                    {% if status.trade_active %}
                    · live forward-test (no real orders)
                    {% endif %}
                </p>
            </div>
            <div class="flex items-center gap-4">
                <div class="bg-slate-800 px-4 py-2 rounded-xl border border-slate-700 text-right">
                    <span class="text-xs text-slate-400 block">Daily SLs (Max {{ status.max_daily_losses or 10 }})</span>
                    <span class="text-xl font-bold {{ 'text-rose-400' if (status.daily_losses or 0) >= (status.max_daily_losses or 10) else 'text-slate-200' }}">
                        {{ status.daily_losses or 0 }} / {{ status.max_daily_losses or 10 }}
                        {% if (status.daily_losses or 0) >= (status.max_daily_losses or 10) %}
                        <span class="text-xs bg-amber-900/60 text-amber-300 px-2 py-0.5 rounded ml-1 font-semibold">TREND-ONLY</span>
                        {% endif %}
                    </span>
                </div>
                <div class="bg-slate-800 px-5 py-3 rounded-xl border border-slate-700 text-right">
                    <span class="text-xs text-slate-400 block">Simulated Equity</span>
                    <span class="text-3xl font-semibold {{ 'text-emerald-400' if status.equity >= 500 else 'text-rose-400' }}">
                        ${{ "%.2f"|format(status.equity) }}
                    </span>
                </div>
            </div>
        </header>

        <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-9 gap-4 mb-6">
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
                <p class="text-xs text-slate-400">BE Scratches</p>
                <p class="text-2xl font-bold text-slate-300">{{ status.be_exits or 0 }}</p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">Time Stops</p>
                <p class="text-2xl font-bold text-violet-300">{{ status.time_exits or 0 }}</p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">Win Rate <span class="text-slate-500">(decisive)</span></p>
                <p class="text-2xl font-bold text-blue-400">{{ status.win_rate }}%</p>
                <p class="text-[11px] text-slate-500 leading-tight mt-1">
                    all eras · excl. BE/TIME · all-in
                    {{ "%.1f"|format(100 * (status.wins or 0) / (status.total_trades or 1)) }}%
                </p>
                <p class="text-[11px] text-slate-400 leading-tight mt-1">
                    0.75R {{ eras.r075.wr }}% (n={{ eras.r075.n }})
                </p>
                <p class="text-[11px] text-slate-400 leading-tight">
                    max-hold {{ eras.mh.wr }}% (n={{ eras.mh.n }})
                </p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">Next Trade #</p>
                <p class="text-2xl font-bold text-cyan-400">{{ status.next_trade_num or '—' }}</p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">Active Trade</p>
                <p class="text-2xl font-bold {{ 'text-emerald-400' if status.trade_active else 'text-slate-500' }}">
                    {% if status.trade_active %}
                        {{ status.trade_type or 'BUY' }}
                    {% else %}
                        No
                    {% endif %}
                </p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <p class="text-xs text-slate-400">Log rows (tailed)</p>
                <p class="text-2xl font-bold">{{ total }}</p>
            </div>
        </div>

        {% if status.trade_active %}
        <div class="bg-slate-800 border {{ 'border-emerald-600/50' if status.trade_type == 'BUY' else 'border-rose-600/50' }} rounded-xl p-4 mb-6">
            <div class="flex items-center justify-between mb-2">
                <p class="text-sm font-semibold {{ 'text-emerald-400' if status.trade_type == 'BUY' else 'text-rose-400' }}">
                    🔥 Active {{ status.trade_type or 'BUY' }} Position (#{{ status.current_trade_num or '—' }})
                </p>
                <span class="text-xs text-slate-400">Entered: {{ status.entry_time or '—' }}</span>
            </div>
            <div class="grid grid-cols-2 md:grid-cols-6 gap-4 text-sm">
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
                <div>
                    <span class="text-slate-400">BE armed</span><br>
                    <span class="text-lg font-semibold {{ 'text-amber-300' if status.be_armed else 'text-slate-500' }}">
                        {{ 'YES' if status.be_armed else 'no' }}
                    </span>
                </div>
                <div>
                    <span class="text-slate-400">Hold / max</span><br>
                    <span class="text-lg font-semibold {{ 'text-violet-300' if hold_minutes is not none and hold_minutes >= 180 else 'text-slate-200' }}">
                        {% if hold_minutes is not none %}{{ hold_minutes }} / {{ max_hold }} min{% else %}—{% endif %}
                    </span>
                </div>
                <div>
                    <span class="text-slate-400">Entry RSI / ATR</span><br>
                    <span class="text-lg font-semibold">
                        {{ status.entry_rsi or '—' }} / {{ status.entry_atr or '—' }}
                    </span>
                </div>
            </div>
        </div>
        {% endif %}

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

        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <h3 class="text-sm font-semibold text-emerald-400 mb-3">📈 Buy (Long) Funnel</h3>
                <div class="grid grid-cols-3 gap-2 text-xs">
                    <div><span class="text-slate-400">Candles:</span> <span class="font-bold">{{ funnel.candles_evaluated or 0 }}</span></div>
                    <div><span class="text-slate-400">Tested Floor:</span> <span class="font-bold text-blue-400">{{ funnel.tested_floor or 0 }}</span></div>
                    <div><span class="text-slate-400">Valid Rej:</span> <span class="font-bold text-amber-400">{{ funnel.valid_rejection or 0 }}</span></div>
                    <div><span class="text-slate-400">Held Floor:</span> <span class="font-bold text-emerald-400">{{ funnel.held_support or 0 }}</span></div>
                    <div><span class="text-slate-400">Volume OK:</span> <span class="font-bold text-slate-200">{{ funnel.volume_confirmed or 0 }}</span></div>
                    <div><span class="text-slate-400">Near EMA:</span> <span class="font-bold text-slate-200">{{ funnel.price_near_ema or 0 }}</span></div>
                    <div><span class="text-slate-400">Trend OK:</span> <span class="font-bold text-cyan-400">{{ funnel.trend_confirmed or 0 }}</span></div>
                    <div><span class="text-slate-400">Slope OK:</span> <span class="font-bold text-purple-400">{{ funnel.slope_confirmed or 0 }}</span></div>
                    <div><span class="text-slate-400">All Confirmed:</span> <span class="font-bold text-emerald-300">{{ funnel.all_confirmed or 0 }}</span></div>
                </div>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <h3 class="text-sm font-semibold text-rose-400 mb-3">📉 Sell (Short) Funnel</h3>
                <div class="grid grid-cols-3 gap-2 text-xs">
                    <div><span class="text-slate-400">Candles:</span> <span class="font-bold">{{ funnel.candles_evaluated or 0 }}</span></div>
                    <div><span class="text-slate-400">Tested Ceil:</span> <span class="font-bold text-blue-400">{{ funnel.sell_tested_ceiling or 0 }}</span></div>
                    <div><span class="text-slate-400">Valid Rej:</span> <span class="font-bold text-amber-400">{{ funnel.sell_valid_rejection or 0 }}</span></div>
                    <div><span class="text-slate-400">Held Ceil:</span> <span class="font-bold text-rose-400">{{ funnel.sell_held_resistance or 0 }}</span></div>
                    <div><span class="text-slate-400">Near EMA:</span> <span class="font-bold text-slate-200">{{ funnel.sell_price_near_ema or 0 }}</span></div>
                    <div><span class="text-slate-400">Trend OK:</span> <span class="font-bold text-cyan-400">{{ funnel.sell_trend_confirmed or 0 }}</span></div>
                    <div><span class="text-slate-400">Slope OK:</span> <span class="font-bold text-purple-400">{{ funnel.sell_slope_confirmed or 0 }}</span></div>
                    <div><span class="text-slate-400">All Confirmed:</span> <span class="font-bold text-rose-300">{{ funnel.sell_all_confirmed or 0 }}</span></div>
                </div>
            </div>
        </div>

        <div class="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden mb-8">
            <div class="px-6 py-4 border-b border-slate-700 font-semibold text-slate-200">
                Recent closed trades (last 20)
            </div>
            <div class="overflow-x-auto">
                <table class="w-full text-left text-sm text-slate-300">
                    <thead class="bg-slate-900/50 text-slate-400 uppercase text-xs">
                        <tr>
                            <th class="px-3 py-3">#</th>
                            <th class="px-3 py-3">Side</th>
                            <th class="px-3 py-3">Entry</th>
                            <th class="px-3 py-3">Exit</th>
                            <th class="px-3 py-3">Reason</th>
                            <th class="px-3 py-3">Profit</th>
                            <th class="px-3 py-3">Balance</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-700">
                        {% for t in trades %}
                        <tr class="hover:bg-slate-700/40">
                            <td class="px-3 py-2 font-mono text-xs">{{ t.Trade_Num }}</td>
                            <td class="px-3 py-2 {{ 'text-emerald-400' if t.Trade_Type == 'BUY' else 'text-rose-400' }}">{{ t.Trade_Type }}</td>
                            <td class="px-3 py-2 font-mono text-xs">{{ t.Entry_Time }}</td>
                            <td class="px-3 py-2 font-mono text-xs">{{ t.Exit_Time }}</td>
                            <td class="px-3 py-2">
                                <span class="px-2 py-0.5 rounded text-xs
                                    {{ 'bg-emerald-900/50 text-emerald-400' if t.Exit_Reason == 'TP'
                                       else 'bg-rose-900/50 text-rose-400' if t.Exit_Reason == 'SL'
                                       else 'bg-violet-900/50 text-violet-300' if t.Exit_Reason == 'TIME'
                                       else 'bg-slate-700 text-slate-300' }}">
                                    {{ t.Exit_Reason }}
                                </span>
                            </td>
                            <td class="px-3 py-2 {{ 'text-emerald-400' if (t.Profit|float) > 0 else 'text-rose-400' if (t.Profit|float) < 0 else 'text-slate-400' }}">
                                {{ t.Profit }}
                            </td>
                            <td class="px-3 py-2">{{ t.Balance_After }}</td>
                        </tr>
                        {% endfor %}
                        {% if not trades %}
                        <tr><td class="px-3 py-3 text-slate-500" colspan="7">No trades.csv yet</td></tr>
                        {% endif %}
                    </tbody>
                </table>
            </div>
        </div>

        <div class="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
            <div class="px-6 py-4 border-b border-slate-700 font-semibold text-slate-200">
                Recent Candle Log (last 30, tailed)
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


def _parse_ts(value):
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _stale_info(last_update):
    ts = _parse_ts(last_update)
    if ts is None:
        return True, "no last_update"
    age = datetime.now(timezone.utc).replace(tzinfo=None) - ts
    seconds = int(age.total_seconds())
    if seconds < 0:
        seconds = 0
    stale = seconds > STALE_AFTER_SECONDS
    if seconds < 120:
        label = f"{seconds}s ago"
    else:
        label = f"{seconds // 60}m ago"
    return stale, label


def _hold_minutes(entry_time):
    ts = _parse_ts(entry_time)
    if ts is None:
        return None
    delta = datetime.now(timezone.utc).replace(tzinfo=None) - ts
    mins = int(delta.total_seconds() // 60)
    return max(0, mins)


def _era_bucket():
    return {"n": 0, "tp": 0, "sl": 0, "wr": "—"}


def _finalize_era(bucket):
    dec = bucket["tp"] + bucket["sl"]
    bucket["wr"] = f"{100.0 * bucket['tp'] / dec:.1f}" if dec else "—"
    return bucket


def compute_era_stats(path):
    r075 = _era_bucket()
    mh = _era_bucket()
    if not os.path.isfile(path):
        return {"r075": _finalize_era(r075), "mh": _finalize_era(mh)}
    try:
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                entry = _parse_ts(row.get("Entry_Time"))
                if entry is None:
                    continue
                reason = (row.get("Exit_Reason") or "").strip()
                for bucket, start in ((r075, ERA_075_START), (mh, ERA_MH_START)):
                    if entry >= start:
                        bucket["n"] += 1
                        if reason == "TP":
                            bucket["tp"] += 1
                        elif reason == "SL":
                            bucket["sl"] += 1
    except Exception as exc:
        print(f"Error reading trades for era stats: {exc}")
    return {"r075": _finalize_era(r075), "mh": _finalize_era(mh)}


def tail_csv_rows(path, n=30):
    """Return (last n rows newest-first, approximate row count from file size)."""
    if not os.path.isfile(path):
        return [], 0
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as raw:
            raw.seek(0)
            header_line = raw.readline()
            if not header_line:
                return [], 0
            header = header_line.decode("utf-8", errors="replace").strip().split(",")
            # Read a tail chunk large enough for ~n rows (log rows are wide).
            chunk = 256 * 1024
            if size > chunk:
                raw.seek(max(len(header_line), size - chunk))
                data = raw.read().decode("utf-8", errors="replace")
                # Drop partial first line.
                nl = data.find("\n")
                if nl >= 0:
                    data = data[nl + 1 :]
            else:
                raw.seek(len(header_line))
                data = raw.read().decode("utf-8", errors="replace")
        rows = list(csv.DictReader(data.splitlines(), fieldnames=header))
        recent = list(reversed(rows))[:n]
        # Approximate total data rows from file size vs first full file is expensive;
        # count newlines in a cheap way only for display.
        approx = max(len(rows), 0)
        if size > chunk:
            # Rough estimate: keep prior behaviour of showing a number; prefer exact
            # if the file is small. For large files estimate via average line size.
            avg = max(80, size // max(1, data.count("\n") + len(rows)))
            approx = max(approx, size // max(80, len(header_line)))
        return recent, approx
    except Exception as exc:
        print(f"Error tailing log: {exc}")
        return [], 0


def recent_trades(path, n=20):
    if not os.path.isfile(path):
        return []
    try:
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        return list(reversed(rows))[:n]
    except Exception as exc:
        print(f"Error reading trades: {exc}")
        return []


@app.route("/")
def index():
    status = {
        "equity": 500.00,
        "total_trades": 0,
        "next_trade_num": None,
        "wins": 0,
        "losses": 0,
        "be_exits": 0,
        "time_exits": 0,
        "win_rate": 0.0,
        "trade_active": False,
        "trade_type": None,
        "daily_losses": 0,
        "max_daily_losses": DEFAULT_MAX_DAILY_LOSSES,
        "entry_price": None,
        "stop_loss": None,
        "take_profit": None,
        "be_armed": None,
        "entry_time": None,
        "entry_rsi": None,
        "entry_atr": None,
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

    if status.get("max_daily_losses") is None:
        status["max_daily_losses"] = DEFAULT_MAX_DAILY_LOSSES

    funnel = status.get("funnel") or {}
    recent_rows, total_rows = tail_csv_rows(LOG_FILE_PATH, n=30)
    trades = recent_trades(TRADES_FILE_PATH, n=20)
    eras = compute_era_stats(TRADES_FILE_PATH)
    stale, stale_age = _stale_info(status.get("last_update"))
    hold_minutes = _hold_minutes(status.get("entry_time")) if status.get("trade_active") else None
    try:
        equity = float(status.get("equity") or 0)
    except (TypeError, ValueError):
        equity = 0.0
    delta = equity - 500.0
    equity_delta = f"{delta:+.2f}"

    return render_template_string(
        HTML_TEMPLATE,
        rows=recent_rows,
        status=status,
        total=total_rows,
        funnel=funnel,
        trades=trades,
        eras=eras,
        stale=stale,
        stale_age=stale_age,
        hold_minutes=hold_minutes,
        max_hold=MAX_HOLD_MINUTES,
        equity_delta=equity_delta,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
