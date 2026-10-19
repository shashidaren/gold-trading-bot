import os
import csv
import json
from datetime import datetime, timezone
from flask import Flask, render_template_string

try:  # display-only helper library (see pressure.py's docstring)
    import pressure as PR
except Exception as _exc:  # never take the dashboard down over the read layer
    PR = None
    _PR_IMPORT_ERROR = str(_exc)
else:
    _PR_IMPORT_ERROR = ""

app = Flask(__name__)

DATA_DIR = os.getenv("GOLD_DATA_DIR", "/opt/gold")
LOG_FILE_PATH = os.getenv("GOLD_LOG_FILE", os.path.join(DATA_DIR, "forward_test_log.csv"))
STATUS_FILE_PATH = os.getenv("GOLD_STATUS_FILE", os.path.join(DATA_DIR, "status.json"))
TRADES_FILE_PATH = os.getenv("GOLD_TRADES_FILE", os.path.join(DATA_DIR, "trades.csv"))
SKIP_FILE_PATH = os.getenv("GOLD_SKIP_FILE", os.path.join(DATA_DIR, "skipped_trades.csv"))

# Display-only mirrors of live engine constants (do not drive trading).
# The gate thresholds live in pressure.py, which smoke Scenario U pins to
# engine.py / trade_filter.py so the dashboard cannot drift from the engine.
MAX_HOLD_MINUTES = 240
DEFAULT_MAX_DAILY_LOSSES = 10
STALE_AFTER_SECONDS = 300
ERA_075_START = datetime(2026, 9, 15, 6, 0)  # UTC, PR #9
ERA_MH_START = datetime(2026, 9, 21, 6, 0)   # UTC, PR #15 ~autosync
CALIBRATION_CACHE_SECONDS = 600              # the ledger-join scan is O(log size)

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
            {% if trade_read %}
            <div class="mt-3 pt-3 border-t border-slate-700 grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                <div>
                    <span class="text-slate-400">Price now <span class="text-slate-600">(last log bar)</span></span><br>
                    <span class="text-lg font-semibold">${{ "%.2f"|format(trade_read.price) }}</span>
                </div>
                <div>
                    <span class="text-slate-400">Open P&amp;L / progress</span><br>
                    <span class="text-lg font-semibold {{ 'text-emerald-400' if trade_read.r_now > 0 else 'text-rose-400' if trade_read.r_now < 0 else 'text-slate-300' }}">
                        {{ "%+.2f"|format(trade_read.pnl) }} ({{ "%+.2f"|format(trade_read.r_now) }}R)
                    </span>
                    <span class="text-[11px] text-slate-500 block">risk ${{ "%.2f"|format(trade_read.risk) }} (reward-leg)</span>
                </div>
                <div>
                    <span class="text-slate-400">BE ratchet at +{{ "%.2f"|format(trade_read.be_trigger_r) }}R</span><br>
                    <span class="text-lg font-semibold {{ 'text-amber-300' if status.be_armed else 'text-slate-200' }}">
                        ${{ "%.2f"|format(trade_read.be_price) }}
                    </span>
                    <span class="text-[11px] text-slate-500 block">{{ 'armed — SL now at entry' if status.be_armed else 'not armed yet' }}</span>
                </div>
                <div>
                    <span class="text-slate-400">Distance to TP / SL</span><br>
                    <span class="text-lg font-semibold">
                        {{ "%+.2f"|format(trade_read.to_tp) }} / {{ "%+.2f"|format(trade_read.to_sl) }}
                    </span>
                    <span class="text-[11px] text-slate-500 block">$ of price left in each geometry</span>
                </div>
            </div>
            {% endif %}
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

        {# ───────── read-only context layer: pressure / setup / book ───────── #}
        {% if ctx.error %}
        <div class="bg-rose-900/40 border border-rose-700 text-rose-200 rounded-xl px-4 py-3 mb-6 text-sm">
            Market-context layer unavailable — {{ ctx.error }}. The rest of the page is unaffected.
        </div>
        {% endif %}

        {% if ctx.pressure %}
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <div class="flex items-baseline justify-between mb-3">
                    <h3 class="text-sm font-semibold text-slate-200">🌡️ Tape pressure — last {{ ctx.pressure.window }} closed bars</h3>
                    <span class="text-[11px] text-slate-500">as of {{ ctx.pressure.as_of or '—' }}</span>
                </div>
                <div class="space-y-3">
                    <div>
                        <div class="flex justify-between text-xs mb-1">
                            <span class="text-emerald-400 font-semibold">BUY pressure</span>
                            <span class="font-mono text-emerald-300">{{ "%.1f"|format(ctx.pressure.buy_pct) }}%</span>
                        </div>
                        <div class="h-3 bg-slate-900 rounded-full overflow-hidden border border-slate-700">
                            <div class="h-full bg-gradient-to-r from-emerald-700 to-emerald-400"
                                 style="width: {{ '%.1f'|format(ctx.pressure.buy_pct) }}%"></div>
                        </div>
                    </div>
                    <div>
                        <div class="flex justify-between text-xs mb-1">
                            <span class="text-rose-400 font-semibold">SELL pressure</span>
                            <span class="font-mono text-rose-300">{{ "%.1f"|format(ctx.pressure.sell_pct) }}%</span>
                        </div>
                        <div class="h-3 bg-slate-900 rounded-full overflow-hidden border border-slate-700">
                            <div class="h-full bg-gradient-to-r from-rose-400 to-rose-700"
                                 style="width: {{ '%.1f'|format(ctx.pressure.sell_pct) }}%"></div>
                        </div>
                    </div>
                </div>
                <p class="mt-3 text-sm font-semibold
                    {{ 'text-emerald-300' if ctx.pressure.tone in ('up','up-strong')
                       else 'text-rose-300' if ctx.pressure.tone in ('down','down-strong')
                       else 'text-slate-300' }}">
                    {{ ctx.pressure.label }}
                </p>
                <p class="text-[11px] text-slate-500 mt-1 leading-snug">
                    Buy/sell are two ends of one dial (they sum to 100). Context only — the engine's trend
                    gate means BUYs print with high buy-pressure by construction, so this is <em>not</em> an
                    entry signal. What it is measured to do is in the note below the components.
                </p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <h3 class="text-sm font-semibold text-slate-200 mb-3">Components (buy-share of each)</h3>
                <table class="w-full text-xs">
                    <tbody class="divide-y divide-slate-700/70">
                    {% for c in ctx.pressure.components %}
                    <tr>
                        <td class="py-1.5 pr-2 text-slate-300">{{ c.label }}<span class="text-slate-500"> · {{ c.unit }}</span></td>
                        <td class="py-1.5 pr-2 font-mono text-right text-slate-200">{{ c.raw }}</td>
                        <td class="py-1.5 w-28">
                            <div class="h-1.5 bg-slate-900 rounded-full overflow-hidden">
                                <div class="h-full {{ 'bg-emerald-500' if c.buy_share >= 0.55 else 'bg-rose-500' if c.buy_share <= 0.45 else 'bg-slate-400' }}"
                                     style="width: {{ '%.0f'|format(c.buy_share * 100) }}%"></div>
                            </div>
                        </td>
                        <td class="py-1.5 pl-2 text-right text-slate-500">w {{ "%.2f"|format(c.weight) }}</td>
                    </tr>
                    {% endfor %}
                    </tbody>
                </table>
                {% if ctx.calibration and ctx.calibration.ok %}
                <div class="mt-3 pt-3 border-t border-slate-700 text-[11px] leading-snug
                    {{ 'text-amber-300' if ctx.calibration.degenerate else 'text-slate-400' }}">
                    <span class="font-semibold">Measured on the live book ({{ ctx.calibration.era_label }}, n={{ ctx.calibration.n }}):</span>
                    {{ ctx.calibration.verdict }} — {{ ctx.calibration.reason }}.
                    {% for side, w in ctx.calibration.within_side.items() %}
                    {{ side }} entries spanned {{ "%.0f"|format(w.min) }}–{{ "%.0f"|format(w.max) }} (median {{ "%.0f"|format(w.median) }}){% if not loop.last %}; {% endif %}
                    {% endfor %}.
                    Refresh: <span class="font-mono">python3 tools/pressure_report.py</span>
                </div>
                {% elif ctx.calibration %}
                <div class="mt-3 pt-3 border-t border-slate-700 text-[11px] text-slate-500">
                    Calibration unavailable — {{ ctx.calibration.reason }}
                </div>
                {% endif %}
            </div>
        </div>
        {% endif %}

        {% if ctx.setup and ctx.setup.ok %}
        <div class="bg-slate-800 rounded-xl border border-slate-700 p-4 mb-6">
            <div class="flex flex-wrap items-baseline justify-between gap-2 mb-3">
                <h3 class="text-sm font-semibold text-slate-200">🎯 Setup read — the engine's own gates on the last closed bar ({{ ctx.setup.as_of or '—' }})</h3>
                {% if ctx.setup.floor_mismatch %}
                <span class="text-[11px] bg-amber-900/60 text-amber-300 px-2 py-0.5 rounded">
                    ⚠️ recomputed floor ≠ logged Dynamic_Floor — level math needs a look
                </span>
                {% endif %}
            </div>
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {% for side in ['BUY', 'SELL'] %}
                {% set s = ctx.setup[side] %}
                <div class="border {{ 'border-emerald-700/50' if side == 'BUY' else 'border-rose-700/50' }} rounded-lg overflow-hidden">
                    <div class="px-3 py-2 flex items-center justify-between {{ 'bg-emerald-900/30' if side == 'BUY' else 'bg-rose-900/30' }}">
                        <span class="text-sm font-semibold {{ 'text-emerald-300' if side == 'BUY' else 'text-rose-300' }}">
                            {{ side }} — {{ s.passed }}/{{ s.total }} gates
                        </span>
                        {% if s.ready %}
                        <span class="text-[11px] bg-emerald-600/40 text-emerald-100 px-2 py-0.5 rounded font-semibold">SETUP READY</span>
                        {% else %}
                        <span class="text-[11px] bg-slate-700 text-slate-300 px-2 py-0.5 rounded">no setup</span>
                        {% endif %}
                    </div>
                    <table class="w-full text-xs">
                        <tbody class="divide-y divide-slate-700/70">
                        {% for g in s.gates %}
                        <tr class="{{ 'opacity-60' if g.inactive else '' }}">
                            <td class="px-3 py-1.5 text-slate-300">{{ g.name }}</td>
                            <td class="px-3 py-1.5 font-mono text-slate-200">{{ g.value }}</td>
                            <td class="px-3 py-1.5 text-slate-500">{{ g.threshold }}</td>
                            <td class="px-3 py-1.5 text-right">
                                {% if g.inactive %}
                                <span class="text-slate-500">n/a</span>
                                {% elif g.ok %}
                                <span class="bg-emerald-900/50 text-emerald-400 px-1.5 py-0.5 rounded">PASS</span>
                                {% else %}
                                <span class="bg-rose-900/50 text-rose-300 px-1.5 py-0.5 rounded">FAIL</span>
                                {% endif %}
                            </td>
                        </tr>
                        {% endfor %}
                        </tbody>
                    </table>
                    <div class="px-3 py-2 bg-slate-900/40 text-[11px] text-slate-400">
                        {% if s.ready %}All gates pass — the portfolio gates below still decide.{% else %}
                        Waiting on: {{ ctx.setup.nearest_miss[side] or '—' }}{% endif %}
                        · level ${{ "%.2f"|format(s.level) }} ({{ "%.2f"|format(s.level_dist_atr) }} ATR away)
                    </div>
                </div>
                {% endfor %}
            </div>
            {% if ctx.portfolio %}
            <div class="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                <div class="bg-slate-900/50 rounded-lg p-3 border border-slate-700">
                    <p class="text-slate-400 font-semibold mb-1">Portfolio gates (state, not price)</p>
                    <p class="text-slate-300">
                        Blackout now:
                        {% if ctx.portfolio.blackout_any %}
                        <span class="text-amber-300">
                            {% for sd in ['BUY','SELL'] %}{% if ctx.portfolio.sides_blocked[sd] %}{{ sd }} blocked — {{ ctx.portfolio.sides_blocked[sd] }}{% if not loop.last %}; {% endif %}{% endif %}{% endfor %}
                        </span>
                        {% else %}
                        <span class="text-emerald-400">none (both sides open)</span>
                        {% endif %}
                    </p>
                    {% if ctx.portfolio.next_window %}
                    <p class="text-slate-500 mt-1">Next window: {{ ctx.portfolio.next_window[0] }} at {{ ctx.portfolio.next_window[2] }} UTC
                        → blocks {{ ctx.portfolio.next_window[1]|join(', ') }}</p>
                    {% endif %}
                    <p class="text-slate-500 mt-1">
                        SL cooldown:
                        {% if ctx.portfolio.cooldown_minutes_left %}<span class="text-amber-300">{{ ctx.portfolio.cooldown_minutes_left }} min left ({{ ctx.portfolio.cooldown_note }})</span>
                        {% else %}clear{% endif %}
                        · 60-min momentum side: {{ ctx.portfolio.momentum_side or '—' }}
                    </p>
                </div>
                <div class="bg-slate-900/50 rounded-lg p-3 border border-slate-700">
                    <p class="text-slate-400 font-semibold mb-1">Skips (blocked setups, last {{ ctx.skips.hours }}h)</p>
                    {% if ctx.skips.total %}
                    <p class="text-slate-300">{{ ctx.skips.total }} blocked —
                        {% for name, count in ctx.skips.buckets %}{{ name }} {{ count }}{% if not loop.last %}, {% endif %}{% endfor %}
                    </p>
                    <p class="text-slate-500 mt-1">Last: {{ ctx.skips.last or '—' }}. A skip is the risk layer, not the signal layer — blocked setups still moved somewhere.</p>
                    {% else %}
                    <p class="text-slate-500">none logged in the window</p>
                    {% endif %}
                </div>
            </div>
            {% endif %}
        </div>
        {% elif ctx.setup and not ctx.setup.ok %}
        <div class="bg-slate-800 rounded-xl border border-slate-700 p-4 mb-6 text-sm text-slate-400">
            🎯 Setup read unavailable — {{ ctx.setup.reason }}
        </div>
        {% endif %}

        {% if ctx.location %}
        {% set l = ctx.location %}
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <h3 class="text-sm font-semibold text-slate-200 mb-3">📍 Location in the 20-bar range</h3>
                <div class="flex justify-between text-xs text-slate-400 mb-1">
                    <span>floor ${{ "%.2f"|format(l.floor) }}</span>
                    <span>ceiling ${{ "%.2f"|format(l.ceiling) }}</span>
                </div>
                <div class="relative h-4 bg-slate-900 rounded-full border border-slate-700 overflow-hidden">
                    <div class="absolute inset-y-0 left-0 bg-rose-900/40" style="width: 15%"></div>
                    <div class="absolute inset-y-0 right-0 bg-emerald-900/40" style="width: 15%"></div>
                    {% set pos = 0 if l.range_pos_pct is none else (l.range_pos_pct if l.range_pos_pct < 100 else 100) %}
                    <div class="absolute inset-y-0 w-1 bg-amber-300" style="left: {{ '%.1f'|format(pos) }}%"></div>
                </div>
                <p class="mt-2 text-xs text-slate-300">
                    Price ${{ "%.2f"|format(l.close) }} sits at
                    <span class="font-semibold">
                        {% if l.range_pos_pct is none %}n/a{% else %}{{ "%.0f"|format(l.range_pos_pct) }}% of the range{% endif %}
                    </span>
                    {% if l.range_pos_pct is not none and l.range_pos_pct > 100 %}<span class="text-emerald-400">(above the ceiling — broken out)</span>
                    {% elif l.range_pos_pct is not none and l.range_pos_pct < 0 %}<span class="text-rose-400">(below the floor — broken down)</span>{% endif %}
                </p>
                <p class="text-xs text-slate-500 mt-1">{{ l.floor_desc }} · {{ l.ceiling_desc }}</p>
                <p class="text-[11px] text-slate-500 mt-2 leading-snug">
                    The strategy only buys AT a tested floor (+) and sells AT a tested ceiling (+), after a
                    ≥38% rejection wick — the shaded bands are the 15% zones where a level test is plausible.
                </p>
            </div>
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <h3 class="text-sm font-semibold text-slate-200 mb-3">🧮 If the engine entered this bar</h3>
                <table class="w-full text-xs">
                    <thead class="text-slate-500">
                        <tr><th class="text-left font-normal py-1">side</th><th class="text-right font-normal">stop</th><th class="text-right font-normal">target</th><th class="text-right font-normal">risk</th></tr>
                    </thead>
                    <tbody class="divide-y divide-slate-700/70">
                        <tr>
                            <td class="py-1.5 text-emerald-400">BUY @ ${{ "%.2f"|format(l.close) }}</td>
                            <td class="py-1.5 text-right font-mono text-rose-300">${{ "%.2f"|format(l.close - l.buy.risk) }}</td>
                            <td class="py-1.5 text-right font-mono text-emerald-300">${{ "%.2f"|format(l.close + l.buy.risk * 1.5) }}</td>
                            <td class="py-1.5 text-right font-mono">${{ "%.2f"|format(l.buy.risk) }} ({{ "%.2f"|format(l.buy.risk / ctx.setup.atr) }} ATR)</td>
                        </tr>
                        <tr>
                            <td class="py-1.5 text-rose-400">SELL @ ${{ "%.2f"|format(l.close) }}</td>
                            <td class="py-1.5 text-right font-mono text-rose-300">${{ "%.2f"|format(l.close + l.sell.risk) }}</td>
                            <td class="py-1.5 text-right font-mono text-emerald-300">${{ "%.2f"|format(l.close - l.sell.risk * 1.5) }}</td>
                            <td class="py-1.5 text-right font-mono">${{ "%.2f"|format(l.sell.risk) }} ({{ "%.2f"|format(l.sell.risk / ctx.setup.atr) }} ATR)</td>
                        </tr>
                    </tbody>
                </table>
                <p class="text-[11px] text-slate-500 mt-2 leading-snug">
                    Structural stop (live 2026-10-06 03:00 UTC): risk = max(2×ATR, |entry − level| + 0.5×ATR),
                    TP = 1.5 × risk. {% if l.buy.level_bound %}BUY risk is level-bound; {% endif %}{% if l.sell.level_bound %}SELL risk is level-bound; {% endif %}
                    $1 of price = $1 P&amp;L at 0.01 lots. R/trade is read from this risk, not from ATR.
                </p>
            </div>
        </div>
        {% endif %}

        {% if ctx.era or ctx.book or ctx.feed %}
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-8">
            {% if ctx.era %}
            {% set e = ctx.era %}
            <div class="bg-slate-800 p-4 rounded-xl border border-slate-700 lg:col-span-2">
                <div class="flex flex-wrap items-baseline justify-between gap-2 mb-2">
                    <h3 class="text-sm font-semibold text-slate-200">🧪 Live experiment — structural stop ({{ e.label }})</h3>
                    <span class="text-[11px] px-2 py-0.5 rounded font-semibold
                        {{ 'bg-rose-900/60 text-rose-200' if e.revert_fired
                           else 'bg-emerald-900/60 text-emerald-200' if e.pass_ok
                           else 'bg-amber-900/60 text-amber-200' if e.screen_ok
                           else 'bg-slate-700 text-slate-300' }}">{{ e.status }}</span>
                </div>
                <p class="text-[11px] text-slate-500 mb-2">
                    entries ≥ {{ e.cutover.strftime('%Y-%m-%d %H:%M') }} UTC · n={{ e.n }} ({{ e.sessions }} session dates) ·
                    judgement due {{ '2026-10-19 21:00' }} UTC or n=150 ({{ e.trades_to_pass }} to go)
                </p>
                <div class="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs mb-3">
                    <div><span class="text-slate-400 block">Decisive WR</span>
                        <span class="font-bold text-lg {{ 'text-emerald-400' if e.checks.C2.ok else 'text-rose-400' }}">{{ "%.1f"|format(e.wr) }}%</span>
                        <span class="text-slate-500 block">CI {{ "%.1f"|format(e.wr_ci[0]) }}–{{ "%.1f"|format(e.wr_ci[1]) }} (≥36 bar)</span></div>
                    <div><span class="text-slate-400 block">R/trade (gross)</span>
                        <span class="font-bold text-lg {{ 'text-emerald-400' if e.checks.C1.ok else 'text-rose-400' }}">{{ "%+.3f"|format(e.r_per_trade) }}</span>
                        <span class="text-slate-500 block">bar ≥ −0.10R gross ($/trade ÷ mean 1R, win_rate_report scale) · decisive-only {{ "%+.3f"|format(e.r_per_trade_decisive) }}R</span></div>
                    <div><span class="text-slate-400 block">SL / day</span>
                        <span class="font-bold text-lg {{ 'text-emerald-400' if e.checks.B1.ok else 'text-rose-400' }}">{{ "%.1f"|format(e.sl_per_day) }}</span>
                        <span class="text-slate-500 block">bar ≤ 6.5 (baseline 8.2)</span></div>
                    <div><span class="text-slate-400 block">Scratch / SL share</span>
                        <span class="font-bold text-lg text-slate-200">{{ "%.0f"|format(e.scratch_pct) }}% / {{ "%.0f"|format(e.sl_share_pct) }}%</span>
                        <span class="text-slate-500 block">bars ≤35% / ≤47%</span></div>
                </div>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-3 text-[11px]">
                    <ul class="space-y-0.5">
                    {% for key, c in e.checks.items() %}
                        <li class="{{ 'text-slate-300' if c.ok else 'text-rose-300' }}">
                            {{ '✔' if c.ok else '✘' }} {{ key }} {{ c.name }}:
                            {% if c.value is not none %}{{ "%.2f"|format(c.value) }}{{ c.unit }}{% else %}—{% endif %}
                            {{ c.cmp }} {{ c.bar }}{{ c.unit if c.unit != 'R' else 'R' }}
                            <span class="text-slate-500">(baseline {{ c.baseline }})</span>
                        </li>
                    {% endfor %}
                    </ul>
                    <ul class="space-y-0.5">
                    {% for key, g in e.geometry.items() %}
                        <li class="{{ 'text-slate-300' if g.ok else 'text-amber-300' }}">
                            {{ '✔' if g.ok else '•' }} {{ key }} {{ g.name }}:
                            {% if g.value is not none %}{{ "%.1f"|format(g.value) }}{{ g.unit }}{% else %}—{% endif %} <span class="text-slate-500">(target {{ g.lo }}–{{ g.hi }}, {{ g.baseline }})</span>
                        </li>
                    {% endfor %}
                    {% for key, r in e.reverts.items() %}
                        <li class="{{ 'text-rose-300 font-semibold' if r.fired else 'text-slate-400' }}">
                            {{ '⚠' if r.fired else '·' }} {{ key }} revert if {{ r.name }}
                            <span class="text-slate-500">(now {{ "%.2f"|format(r.value) if r.value is not none else '—' }})</span>
                        </li>
                    {% endfor %}
                    </ul>
                </div>
                <p class="text-[11px] text-slate-500 mt-2 leading-snug">
                    Bar written before the change: <span class="font-mono">docs/ANALYSIS-2026-10-05-stop-loss-geometry.md</span> §7.
                    A1 (stop never inside the level) is a separate code check —
                    <span class="font-mono">python3 tools/check_structural_stop.py</span> must print 0.
                    This card reports; it never changes a rule.
                </p>
            </div>
            {% endif %}

            <div class="space-y-4">
                {% if ctx.book %}
                {% set b = ctx.book %}
                <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                    <h3 class="text-sm font-semibold text-slate-200 mb-2">📅 Today (UTC {{ b.today }})</h3>
                    <p class="text-xs text-slate-300">
                        {{ b.n }} closed — <span class="text-emerald-400">{{ b.counts.TP }}W</span> /
                        <span class="text-rose-400">{{ b.counts.SL }}L</span> /
                        <span class="text-slate-300">{{ b.counts.BE }}BE</span>{% if b.counts.TIME %} / <span class="text-violet-300">{{ b.counts.TIME }} TIME</span>{% endif %}
                        · P&amp;L <span class="{{ 'text-emerald-400' if b.pnl > 0 else 'text-rose-400' if b.pnl < 0 else 'text-slate-300' }} font-semibold">{{ "%+.2f"|format(b.pnl) }}</span>
                    </p>
                    <p class="text-xs text-slate-500 mt-1">
                        Daily SLs {{ ctx.portfolio.daily_sls if ctx.portfolio else '—' }} / {{ status.max_daily_losses or 10 }}
                        {% if ctx.portfolio and ctx.portfolio.breaker_on %}<span class="text-amber-300">→ trend-side-only</span>{% endif %}
                    </p>
                    {% if b.last %}
                    <p class="text-[11px] text-slate-500 mt-2">
                        Last closed: #{{ b.last.Trade_Num }} {{ b.last.Trade_Type }} {{ b.last.Exit_Reason }} {{ b.last.Profit }} @ {{ b.last.Exit_Time }}
                    </p>
                    {% endif %}
                    <p class="text-[11px] text-slate-500 mt-1">Last 20 exits (newest right): <span class="font-mono text-slate-300">{{ b.last_20 }}</span>
                        — W/L/·(BE)/T(TIME). A short run of L is normal at a ~39% decisive WR (P(4 straight L) ≈ 14%).</p>
                </div>
                {% endif %}
                {% if ctx.feed %}
                {% set fd = ctx.feed %}
                <div class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                    <h3 class="text-sm font-semibold text-slate-200 mb-2">📡 Feed &amp; log health</h3>
                    {% if fd.ok %}
                    <p class="text-xs text-slate-300">
                        Last bar {{ fd.last_bar.strftime('%H:%M:%S') if fd.last_bar else '—' }} UTC
                        ({{ (fd.age_seconds // 60) }}m {{ fd.age_seconds % 60 }}s old) ·
                        {{ fd['bars_60m'] }} bars in the last 60 logged minutes
                    </p>
                    <p class="text-[11px] text-slate-500 mt-1">
                        {{ fd.rows }} rows in the tail window ·
                        {% if fd.gaps %}
                        <span class="text-amber-300">{{ fd.gaps }} open-market gap(s) ≥ 5 min (largest {{ "%.0f"|format(fd.largest_gap_minutes) }} open min)</span> —
                        that is the 2026-09-29 signature; check <span class="font-mono">journalctl -u mt5feed</span> before trusting a quiet tape.
                        {% else %}
                        0 open-market gaps ≥ 5 min (daily/weekly breaks excluded; {{ fd.micro_gaps }} jitter gap(s) of 2–5 min).
                        {% endif %}
                    </p>
                    {% else %}
                    <p class="text-xs text-slate-500">unavailable — {{ fd.reason }}</p>
                    {% endif %}
                </div>
                {% endif %}
            </div>
        </div>
        {% endif %}

        {% if ctx and not ctx.error %}
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-8">
            <section class="bg-slate-800 p-4 rounded-xl border border-amber-800">
                <h3 class="font-semibold text-amber-300 mb-3">🛡️ Risk now</h3>
                {% set rn = ctx.risk_now %}
                {% if rn %}
                <p class="text-sm">Indicative next closure: {{ rn.close }} UTC ({{ rn.minutes }} min).</p>
                {% if rn.quiet %}<p class="text-amber-300 text-sm">Quiet-window heuristic active; verify broker market status.</p>{% endif %}
                {% if rn.remaining is not none %}<p class="text-sm">Hold cap remaining: {{ '%.0f'|format(rn.remaining) }} min.
                {% if rn.spans %}<strong class="text-amber-300">Position could span closure.</strong>{% endif %}</p>{% endif %}
                {% if rn.quote %}
                <p class="text-sm mt-2">Latest valid logged spread: ${{ '%.2f'|format(rn.quote.spread) }}
                    <span class="{{ 'text-amber-300' if rn.quote.stale else 'text-slate-400' }}">{{ 'STALE' if rn.quote.stale else 'recent' }} · {{ rn.quote.age }}s old</span></p>
                <p class="text-xs text-slate-400">{{ rn.quote.as_of }} UTC · spread-only, not total execution cost.</p>
                {% else %}<p class="text-amber-300 text-sm mt-2">Spread unavailable — no valid quote in today's tail.</p>{% endif %}
                {% endif %}
                {% if trade_read %}<p class="text-sm mt-2">Open trade: {{ '%+.2f'|format(trade_read.r_now) }}R at last logged close · SL ${{ '%.2f'|format(trade_read.to_sl) }} away.</p>{% endif %}
                <p class="text-xs text-slate-400 mt-3">Closure uses existing 21:00 UTC quiet-window heuristic, not a verified broker schedule (DST/holidays may differ). Stops and hold caps cannot enforce a fill while closed. No automatic exit.</p>
            </section>
            <section class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <h3 class="font-semibold text-slate-200 mb-3">🗺️ Market map</h3>
                {% if ctx.map %}
                <p class="text-xs text-slate-400">Log as of {{ ctx.map.as_of }} UTC</p>
                {% for tf in ctx.map.trends %}
                <p class="text-sm mt-2">{{ tf.tf }} 4-close momentum:
                    {% if tf.delta is not none %}<strong>{{ 'UP' if tf.delta > 0 else 'DOWN' if tf.delta < 0 else 'FLAT' }}</strong> (${{ '%+.2f'|format(tf.delta) }})
                    {% else %}unavailable (requires four consecutive complete buckets){% endif %}</p>
                {% endfor %}
                {% for level in ctx.map.levels %}<p class="text-sm mt-2">{{ level.label }}: ${{ '%.2f'|format(level.price) }}
                    {% if level.distance is not none %}· price {{ '%+.2f'|format(level.distance) }} ATR from level{% endif %}</p>{% else %}<p class="text-sm mt-2">Prior trading-day levels unavailable in read window.</p>{% endfor %}
                {% else %}<p class="text-sm">Market data unavailable.</p>{% endif %}
                <p class="text-xs text-slate-400 mt-3">UTC M15/H1 buckets from logged M1 bars; incomplete buckets excluded. Prior-day levels are observed log ranges, not guaranteed full broker sessions. Direction is context, not an entry/hold signal.</p>
            </section>
            <section class="bg-slate-800 p-4 rounded-xl border border-slate-700">
                <h3 class="font-semibold text-slate-200 mb-3">📊 Costed evidence</h3>
                <p class="text-xs text-slate-400 mb-2">Structural-stop era · entries since 2026-10-06 03:00 UTC · assumed $0.40 round trip on every exit, including BE.</p>
                {% for group in ctx.evidence %}
                <div class="text-sm border-t border-slate-700 py-2">
                    <strong>{{ group.side }}</strong> · n={{ group.n }} · net ${{ '%+.2f'|format(group.net) }}<br>
                    Expectancy {{ '%+.3fR'|format(group.expectancy) if group.expectancy is not none else '—' }} · PF {{ '%.2f'|format(group.pf) if group.pf is not none else '— (no losses)' }}<br>
                    Max closed-trade drawdown ${{ '%.2f'|format(group.dd) }}{% if group.excluded %} · {{ group.excluded }} invalid rows excluded{% endif %}
                </div>
                {% endfor %}
                <p class="text-xs text-slate-400 mt-2">R uses original TP-leg risk. All exits included; drawdown starts at zero and follows exit order. No open P/L, commissions or slippage beyond the assumption. Small, clustered samples are descriptive—not proof of edge.</p>
            </section>
        </div>
        {% endif %}

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


# ── read-only context layer (pressure / setup / book) ───────────────────────
# Everything below is display-only: no writes, no engine import, no effect on
# trading. The modules are wrapped so a data problem degrades the panel, never
# the page (2026-09-29 lesson: a partial/absent file must not blank the status).

_cal_cache = {"key": None, "value": None, "at": 0.0}


def _file_key(path):
    try:
        st = os.stat(path)
        return (st.st_size, int(st.st_mtime))
    except OSError:
        return None


def calibration_context():
    """Ledger-joined calibration of the pressure composite (cached 10 min).

    The join needs the whole log, so this is the one piece of the page that is
    not free; the cache keeps 15 s refreshes from re-scanning a multi-MB file.
    """
    if PR is None:
        return {"ok": False, "reason": f"pressure.py unavailable: {_PR_IMPORT_ERROR}"}
    import time as _time
    key = (_file_key(LOG_FILE_PATH), _file_key(TRADES_FILE_PATH))
    now = _time.time()
    if key != _cal_cache["key"] and (now - _cal_cache["at"]) < CALIBRATION_CACHE_SECONDS and _cal_cache["value"]:
        return _cal_cache["value"]  # unchanged files, still fresh enough
    try:
        value = PR.calibration(PR.read_rows(LOG_FILE_PATH), PR.read_rows(TRADES_FILE_PATH))
    except Exception as exc:
        value = {"ok": False, "reason": f"calibration failed: {exc}"}
    _cal_cache.update({"key": key, "value": value, "at": now})
    return value


def pressure_context():
    """One read-only snapshot of the tape / gates / book / feed for the page."""
    if PR is None:
        return {"error": f"pressure.py unavailable: {_PR_IMPORT_ERROR}"}
    try:
        ctx = PR.build()
    except Exception as exc:
        return {"error": f"context build failed: {exc}"}
    ctx["calibration"] = calibration_context()
    return ctx


def open_trade_read(status, log_tail):
    """Unrealized progress of the open trade in $ and R (last logged close as price)."""
    if PR is None or not status.get("trade_active"):
        return None
    price = None
    for row in log_tail:  # newest first
        price = PR.parse_float(row.get("Close"))
        if price:
            break
    return PR.open_trade_read(status, price)



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
    ctx = pressure_context()
    if PR and not ctx.get("error"):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        quotes = PR.tail_rows(os.path.join(DATA_DIR, "xm_data", "quotes-" + now.strftime("%Y-%m-%d") + ".csv"), 240)
        ctx["risk_now"] = PR.risk_read(status, quotes, now)
    trade_read = open_trade_read(status, recent_rows)
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
        ctx=ctx,
        trade_read=trade_read,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
