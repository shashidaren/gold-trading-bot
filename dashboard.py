import os
import csv
import json
from datetime import datetime, timezone
from flask import Flask, render_template_string, request

try:  # display-only helper library (see pressure.py's docstring)
    import pressure as PR
except Exception as _exc:  # never take the dashboard down over the read layer
    PR = None
    _PR_IMPORT_ERROR = str(_exc)
else:
    _PR_IMPORT_ERROR = ""

try:  # display-only chart + placement read (see chart.py's docstring)
    import chart as CH
except Exception as _exc:  # never take the dashboard down over the read layer
    CH = None
    _CH_IMPORT_ERROR = str(_exc)
else:
    _CH_IMPORT_ERROR = ""

try:  # display-only self-journal (see journal.py's docstring)
    import journal as JN
except Exception as _exc:  # never take the dashboard down over the read layer
    JN = None
    _JN_IMPORT_ERROR = str(_exc)
else:
    _JN_IMPORT_ERROR = ""

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
JOURNAL_CACHE_SECONDS = 120                  # rebuild the journal at most this often
JOURNAL_PERMUTATIONS = 120                   # the on-page noise floor (CLI uses 200)

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

        <!-- Simple / Details tabs -->
        <div class="flex items-center gap-2 mb-6 border-b border-slate-800 pb-2">
            <button id="tab-simple" onclick="showTab('simple')" class="px-4 py-2 rounded-t-lg text-sm font-semibold bg-amber-500 text-slate-900">✨ Simple Summary</button>
            <button id="tab-boxes" onclick="showTab('boxes')" class="px-4 py-2 rounded-t-lg text-sm font-semibold bg-slate-800 text-slate-400 hover:bg-slate-700">📦 Boxes &amp; Timing</button>
            <button id="tab-chart" onclick="showTab('chart')" class="px-4 py-2 rounded-t-lg text-sm font-semibold bg-slate-800 text-slate-400 hover:bg-slate-700">🧭 Chart &amp; Placement</button>
            <button id="tab-journal" onclick="showTab('journal')" class="px-4 py-2 rounded-t-lg text-sm font-semibold bg-slate-800 text-slate-400 hover:bg-slate-700">📓 Journal</button>
            <button id="tab-details" onclick="showTab('details')" class="px-4 py-2 rounded-t-lg text-sm font-semibold bg-slate-800 text-slate-400 hover:bg-slate-700">📊 Full Dashboard</button>
            <span class="ml-auto text-[11px] text-slate-500 hidden md:inline">Simple is the mood · Chart shows <em>where</em> a trade would go · Boxes is the checklist · Journal is the audit trail · Full shows every gate. All <span class="text-slate-300">paper only</span> — no real orders.</span>
        </div>

        <!-- ================= SIMPLE TAB ================= -->
        <div id="panel-simple">
            {% if ctx.simple %}
            <!-- Big verdict card -->
            {% set vg = ctx.volatility %}
            <div class="rounded-2xl border p-5 mb-6
                {% if vg.verdict == 'red' %} bg-rose-950/40 border-rose-700
                {% elif vg.verdict == 'amber' %} bg-amber-950/30 border-amber-700
                {% elif vg.verdict == 'green' %} bg-emerald-950/30 border-emerald-700
                {% else %} bg-slate-800 border-slate-700 {% endif %}">
                <div class="flex flex-col md:flex-row items-start gap-4">
                    <div class="text-4xl">{{ vg.icon if vg else '❓' }}</div>
                    <div class="flex-1">
                        <h2 class="text-xl font-bold
                            {% if vg.verdict == 'red' %} text-rose-300
                            {% elif vg.verdict == 'amber' %} text-amber-300
                            {% elif vg.verdict == 'green' %} text-emerald-300
                            {% else %} text-slate-200 {% endif %}">
                            {{ vg.headline if vg else 'Summary unavailable' }}
                        </h2>
                        <p class="text-sm text-slate-300 mt-1">{{ vg.sub if vg else ctx.simple.bot_next }}</p>
                        <p class="text-xs text-slate-400 mt-2">{{ vg.action if vg else '' }}</p>
                        {% if ctx.simple.trade_active %}
                        <p class="mt-3 text-sm font-semibold text-amber-300">🔥 Currently IN a {{ status.trade_type or 'position' }} — entry ${{ "%.2f"|format(status.entry_price or 0) }} · SL ${{ "%.2f"|format(status.stop_loss or 0) }} · TP ${{ "%.2f"|format(status.take_profit or 0) }}</p>
                        {% endif %}
                    </div>
                    <div class="text-right shrink-0">
                        <p class="text-xs text-slate-400">Equity (paper)</p>
                        <p class="text-2xl font-bold {{ 'text-emerald-400' if status.equity >= 500 else 'text-rose-400' }}">${{ "%.2f"|format(status.equity) }}</p>
                        <p class="text-xs {{ 'text-emerald-400' if (status.equity-500)>=0 else 'text-rose-400' }}">{{ equity_delta }} from $500 start</p>
                        <p class="text-[11px] text-slate-500 mt-1">{{ ctx.simple.today_line }}</p>
                    </div>
                </div>
            </div>

            <!-- Quick numbers -->
            <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
                <div class="bg-slate-800 p-3 rounded-xl border border-slate-700">
                    <p class="text-xs text-slate-400">Today P&amp;L</p>
                    <p class="text-lg font-bold {% if ctx.book and ctx.book.pnl > 0 %}text-emerald-400{% elif ctx.book and ctx.book.pnl < 0 %}text-rose-400{% else %}text-slate-200{% endif %}">{{ "%+.2f"|format(ctx.book.pnl) if ctx.book else "—" }}</p>
                    <p class="text-[11px] text-slate-500">{{ ctx.book.n if ctx.book else 0 }} closed today</p>
                </div>
                <div class="bg-slate-800 p-3 rounded-xl border border-slate-700">
                    <p class="text-xs text-slate-400">Win rate (decisive)</p>
                    <p class="text-lg font-bold text-blue-400">{{ status.win_rate }}% <span class="text-xs font-normal text-slate-500">all-in {{ "%.1f"|format(100 * (status.wins or 0) / (status.total_trades or 1)) }}%</span></p>
                    <p class="text-[11px] text-slate-500">{{ status.wins }}W / {{ status.losses }}L / {{ status.be_exits or 0 }}BE</p>
                </div>
                <div class="bg-slate-800 p-3 rounded-xl border border-slate-700">
                    <p class="text-xs text-slate-400">Next trade #</p>
                    <p class="text-lg font-bold text-cyan-400">{{ status.next_trade_num or '—' }}</p>
                    <p class="text-[11px] text-slate-500">Closed total: {{ status.total_trades }}</p>
                </div>
                <div class="bg-slate-800 p-3 rounded-xl border border-slate-700">
                    <p class="text-xs text-slate-400">Data freshness</p>
                    <p class="text-lg font-bold {% if stale %}text-rose-400{% else %}text-emerald-400{% endif %}">{% if stale %}STALE{% else %}Live{% endif %}</p>
                    <p class="text-[11px] text-slate-500">{{ stale_age }} · log rows: {{ total }}</p>
                </div>
            </div>

            <!-- Market now (plain English) -->
            <div class="bg-slate-800 rounded-xl border border-slate-700 p-4 mb-6">
                <h3 class="text-sm font-semibold text-slate-200 mb-2">🌤️ Market now — in plain English</h3>
                <ul class="space-y-1 text-sm text-slate-300">
                    {% for s in ctx.simple.market_sentences %}
                    <li class="flex gap-2"><span class="text-slate-500">•</span><span>{{ s }}</span></li>
                    {% endfor %}
                    {% if ctx.simple.stale_note %}
                    <li class="flex gap-2 text-amber-300"><span>⚠️</span><span>{{ ctx.simple.stale_note }}</span></li>
                    {% endif %}
                </ul>
                <p class="text-xs text-slate-500 mt-3">ATR = average bar size. Bigger ATR = more volatile. The bot needs ATR 1.10–4.50 to trade — outside that, it auto-skips.</p>
            </div>

            <!-- Volatility guard — should I trade? -->
            <div class="bg-slate-800 rounded-xl border border-slate-700 p-4 mb-6">
                <div class="flex items-baseline justify-between mb-3">
                    <h3 class="text-sm font-semibold text-slate-200">🛡️ Should I trade now? — Volatility guard</h3>
                    <span class="text-[11px] px-2 py-0.5 rounded font-semibold
                        {% if vg.verdict == 'red' %} bg-rose-900/60 text-rose-200
                        {% elif vg.verdict == 'amber' %} bg-amber-900/60 text-amber-200
                        {% elif vg.verdict == 'green' %} bg-emerald-900/60 text-emerald-200
                        {% else %} bg-slate-700 text-slate-300 {% endif %}">
                        {{ vg.label if vg else '—' }} · 🔴{{ vg.counts.red if vg else 0 }} 🟡{{ vg.counts.amber if vg else 0 }} 🟢{{ vg.counts.green if vg else 0 }}
                    </span>
                </div>
                <p class="text-xs text-slate-400 mb-3">If this is <span class="text-rose-300 font-semibold">red</span>, sit out new entries. If <span class="text-amber-300 font-semibold">yellow</span>, trade smaller / wait. The bot already auto-skips blocked rows — this just tells you whether <em>you</em> should add risk.</p>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
                    {% for f in vg.factors %}
                    <div class="flex gap-3 p-3 rounded-lg border
                        {% if f.level == 2 %} bg-rose-950/30 border-rose-800
                        {% elif f.level == 1 %} bg-amber-950/20 border-amber-800
                        {% else %} bg-slate-900/50 border-slate-700 {% endif %}">
                        <div class="text-lg">{{ f.icon }}</div>
                        <div class="flex-1 min-w-0">
                            <div class="flex items-baseline justify-between gap-2">
                                <span class="text-sm font-semibold text-slate-200">{{ f.name }}</span>
                                <span class="text-xs font-mono text-slate-400">{{ f.value }}</span>
                            </div>
                            <p class="text-xs text-slate-300 leading-snug">{{ f.detail }}</p>
                            <p class="text-[11px] text-slate-500 leading-snug mt-1">{{ f.advice }}</p>
                        </div>
                    </div>
                    {% endfor %}
                </div>
                <p class="text-[11px] text-slate-500 mt-3">Volatility guard is <strong class="text-slate-300">display-only</strong> — it never changes the bot's gates. Engine gates remain the authority (ATK bounds 1.10–4.50, spread block &gt;0.60, blackouts, cooldown, breaker). This translates them into "should <em>I</em> add manual risk?"</p>
            </div>

            <!-- What bot will do next -->
            <div class="bg-slate-800 rounded-xl border border-slate-700 p-4 mb-6">
                <h3 class="text-sm font-semibold text-slate-200 mb-2">🤖 What the bot will do next</h3>
                <p class="text-sm text-slate-300">{{ ctx.simple.bot_next }}</p>
                {% if ctx.setup and ctx.setup.ok %}
                <div class="mt-3 grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
                    {% for side in ['BUY', 'SELL'] %}
                    {% set s = ctx.setup[side] %}
                    <div class="rounded-lg border p-2 {% if s.ready %} border-emerald-700/50 bg-emerald-950/20 {% else %} border-slate-700 bg-slate-900/40 {% endif %}">
                        <span class="font-semibold {% if side == 'BUY' %}text-emerald-300{% else %}text-rose-300{% endif %}">{{ side }}</span>
                        <span class="ml-1 text-slate-400">{{ s.passed }}/{{ s.total }} gates</span>
                        {% if s.ready %}<span class="ml-1 text-emerald-400">✓ ready</span>{% else %}<span class="ml-1 text-slate-500">waiting</span>{% endif %}
                        <span class="block text-slate-500 mt-1">Level ${{ "%.2f"|format(s.level) }} · {{ "%.2f"|format(s.level_dist_atr) }} ATR away</span>
                    </div>
                    {% endfor %}
                </div>
                {% endif %}
                <p class="text-xs text-amber-300/90 mt-3">💡 {{ ctx.simple.human_tip }}</p>
                <p class="text-[11px] text-slate-500 mt-1">Paper only — no real orders. Bot runs FORWARD_TEST with simulated $500 start. No amount shown here is spendable or withdrawable.</p>
            </div>

            <!-- Mini glossary -->
            <div class="bg-slate-800/60 rounded-xl border border-slate-700 p-4 mb-6">
                <h3 class="text-sm font-semibold text-slate-300 mb-2">📖 Quick glossary</h3>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs text-slate-400">
                    <div><span class="text-slate-300 font-semibold">ATR</span> — average bar size in dollars. Low = quiet, high = volatile.</div>
                    <div><span class="text-slate-300 font-semibold">Spread</span> — broker cost to enter (ask − bid). Wide = expensive.</div>
                    <div><span class="text-slate-300 font-semibold">TP / SL</span> — take-profit / stop-loss levels. TP = 1.5× risk from entry.</div>
                    <div><span class="text-slate-300 font-semibold">BE</span> — breakeven scratch. Bot moved SL to entry at +0.75R, then got stopped flat.</div>
                    <div><span class="text-slate-300 font-semibold">Cooldown</span> — bot pauses 30–60 min after a stop-loss to avoid chasing.</div>
                    <div><span class="text-slate-300 font-semibold">Blackout</span> — known news/session window. Bot skips BUY or both sides there.</div>
                </div>
                <p class="text-[11px] text-slate-500 mt-2">Details, tests and the full evidence stay in <span class="font-mono">Full Dashboard</span> below. Nothing is hidden — just layered.</p>
            </div>
            {% else %}
            <div class="bg-rose-900/30 border border-rose-700 rounded-xl p-4 mb-6 text-sm text-rose-200">Simple summary unavailable — {{ ctx.error if ctx.error else 'no context yet' }}. Switch to Full Dashboard or refresh.</div>
            {% endif %}
        </div>
        <!-- ================= END SIMPLE TAB ================= -->

        <!-- ================= BOXES TAB ================= -->
        <div id="panel-boxes" class="hidden">
            {% if ctx.boxes and ctx.boxes.ok %}
            {% set bx = ctx.boxes %}
            {% set v = bx.verdict %}
            <!-- Verdict -->
            <div class="rounded-2xl border p-5 mb-5
                {% if v.tone == 'ok' %} bg-emerald-950/30 border-emerald-700
                {% elif v.tone == 'warn' %} bg-amber-950/30 border-amber-700
                {% elif v.tone == 'block' %} bg-rose-950/30 border-rose-700
                {% else %} bg-slate-800 border-slate-700 {% endif %}">
                <div class="flex flex-col md:flex-row md:items-center gap-4">
                    <div class="text-4xl">{% if v.tone == 'ok' %}📦{% elif v.tone == 'warn' %}⏳{% elif v.tone == 'block' %}⛔{% else %}💤{% endif %}</div>
                    <div class="flex-1">
                        <div class="text-xl font-semibold">{{ v.headline }}</div>
                        <div class="text-sm text-slate-300 mt-1">{{ v.detail }}</div>
                    </div>
                    <div class="text-right text-xs text-slate-400 space-y-1">
                        <div>last bar <span class="font-mono text-slate-200">{{ bx.geometry.as_of.strftime('%Y-%m-%d %H:%M') }}</span> UTC</div>
                        <div>close <span class="font-mono text-slate-200">${{ "%.2f"|format(bx.geometry.close) }}</span> · ATR <span class="font-mono text-slate-200">${{ "%.2f"|format(bx.geometry.atr) }}</span></div>
                        <div>assumed spread <span class="font-mono text-slate-200">${{ "%.2f"|format(bx.spread_usd) }}</span> round trip</div>
                    </div>
                </div>
            </div>

            <!-- Manual watch references: no orders, probability or entry recommendation. -->
            <div class="rounded-2xl border border-slate-700 bg-slate-800 p-4 mb-5">
                <h3 class="text-lg font-semibold">Manual trade watch — price levels</h3>
                <p class="text-xs text-slate-400 mt-1">Breakout watch only, not a buy/sell signal. Levels roll with each closed candle; rejection candidates in the checklist below are separate.</p>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                    {% for card in bx.watch_cards %}
                    <div class="rounded-xl border border-slate-600 bg-slate-900/50 p-4">
                        <div class="font-semibold {% if card.side == 'BUY' %}text-emerald-300{% else %}text-rose-300{% endif %}">{{ card.side }} WATCH {{ 'above' if card.side == 'BUY' else 'below' }} ${{ '%.2f'|format(card.threshold) }}</div>
                        <div class="text-xs text-slate-400 mt-1">{{ card.box }} · boundary ${{ '%.2f'|format(card.edge) }} · confirmation buffer ${{ '%.2f'|format((card.threshold - card.edge)|abs) }}</div>
                        <div class="text-sm text-amber-300 mt-2">{{ card.state }}</div>
                        <div class="text-xs text-slate-300 mt-2">Close {{ 'meets' if card.confirmed else 'has not met' }} the buffered boundary. Reference bar: {{ bx.geometry.as_of.strftime('%Y-%m-%d %H:%M') }} UTC · {{ card.age_seconds }}s old.</div>
                        <dl class="grid grid-cols-2 gap-3 mt-3 text-xs">
                            <div><dt class="text-slate-400">{{ 'Last close reference' if card.confirmed else 'Hypothetical trigger reference' }}</dt><dd class="font-mono">${{ '%.2f'|format(card.entry) }}</dd></div>
                            <div><dt class="text-slate-400">Invalidation / hypothetical stop</dt><dd class="font-mono">${{ '%.2f'|format(card.stop) }}</dd></div>
                            <div><dt class="text-slate-400">Measured-move target (1 box)</dt><dd class="font-mono">${{ '%.2f'|format(card.target) }}</dd></div>
                            <div><dt class="text-slate-400">Gross → costed reward/risk</dt><dd class="font-mono">{{ '%.2f'|format(card.gross_rr) }} → {{ '%.2f'|format(card.net_rr) }}:1</dd></div>
                        </dl>
                        <p class="text-xs text-slate-400 mt-3">Extension beyond edge: {{ '%.2f'|format(card.extension_atr) }} ATR. Do-not-chase warning above 1 ATR (unvalidated display heuristic).</p>
                        {% if card.limited_reward %}<p class="text-xs text-amber-300 mt-2">Limited reward: costed reward is less than risk.</p>{% endif %}
                        {% for reason in card.reasons %}<p class="text-xs text-rose-300 mt-2">{{ reason }}</p>{% endfor %}
                        {% if card.retest_state and card.retest_state != 'none' %}
                        <p class="text-xs text-slate-400 mt-2">Retest — box frozen at the break:
                            <span class="{% if card.retest_state == 'held' %}text-emerald-300{% elif card.retest_state == 'failed' %}text-rose-300{% else %}text-amber-300{% endif %}font-semibold">{{ card.retest_state }}</span>
                            — {{ card.retest_detail }}</p>
                        <p class="text-xs text-slate-500 mt-1">Measured: {{ '%.0f'|format(card.retest_measured.retested_within_30_bars_pct) }}% of breaks are retested within 30 bars (median {{ card.retest_measured.median_wait_bars }}); entering the held retest returned {{ card.retest_measured.entry_on_hold_tf_pct }}% vs a {{ card.retest_measured.entry_on_hold_ref_pct }}% reference and the same ${{ '%.2f'|format(card.retest_measured.entry_on_hold_e_usd|abs) }}/trade as entering the break — a status read, not a filter.</p>
                        {% else %}
                        <p class="text-xs text-slate-400 mt-2">Retest: no close beyond a box edge in the last 30 bars, so there is no break to retest yet.</p>
                        {% endif %}
                    </div>
                    {% endfor %}
                </div>
                <p class="text-xs text-slate-400 mt-3">Confirmation includes the existing box breakout ATR buffer, not a wick touch. Costed ratio = (reward − assumed round-trip spread) / (risk + spread), using ${{ '%.2f'|format(bx.spread_usd) }}/oz; excludes slippage, commission and swap. These are bar-close references, not current executable bid/ask quotes. Recheck actual price and spread before any manual decision. No edge has been validated.</p>
            </div>

            <!-- Telegram alert preview: the SAME decision the sidecar sends, shown not sent. -->
            {% if bx.alert %}
            <div class="rounded-2xl border p-4 mb-5 {% if bx.alert.fire %}border-emerald-700 bg-emerald-950/20{% else %}border-slate-700 bg-slate-800{% endif %}">
                <div class="flex flex-col md:flex-row md:items-center gap-3">
                    <div class="text-lg font-semibold">🔔 Telegram alert</div>
                    <div class="text-sm {% if bx.alert.fire %}text-emerald-300{% else %}text-slate-400{% endif %}">
                        {% if bx.alert.fire %}Would send now{% else %}Held{% endif %}
                    </div>
                    <div class="text-[11px] text-slate-500 md:ml-auto">
                        ≥{{ '%.0f'|format(bx.alert.global_cooldown_minutes) }} min between any two messages ·
                        1 per {{ '%.0f'|format(bx.alert.cooldown_minutes) }} min per box edge ·
                        {{ bx.alert.daily_cap }}/day cap — spam control, not an expectancy claim
                    </div>
                </div>
                {% if bx.alert.fire and bx.alert.text %}
                <pre class="text-[11px] leading-relaxed text-slate-300 bg-slate-900/70 rounded-lg p-3 mt-3 whitespace-pre-wrap font-mono">{{ bx.alert.text }}</pre>
                <p class="text-[11px] text-slate-500 mt-2">This is the exact text <span class="font-mono">tools/box_alert.py</span> sends when it is installed and <span class="font-mono">TELEGRAM_BOT_TOKEN</span>/<span class="font-mono">TELEGRAM_CHAT_ID</span> are set. The dashboard itself never sends anything.</p>
                {% else %}
                <ul class="text-xs text-slate-400 mt-2 space-y-1">
                    {% for b in bx.alert.blockers[:6] %}<li>· {{ b }}</li>{% endfor %}
                </ul>
                <p class="text-[11px] text-slate-500 mt-2">A notice fires only on a <span class="text-slate-300">fresh close beyond a box edge</span> with every condition green, a spread at or under {{ 10 }}% of R and no chase. It says the conditions line up — measured, {{ bx.measured.cells }} box geometries and {{ bx.measured.cleared }} cleared the no-edge reference.</p>
                {% endif %}
            </div>
            {% endif %}

            <div class="grid grid-cols-1 xl:grid-cols-2 gap-5">
                <!-- Boxes -->
                <div class="rounded-2xl border border-slate-700 bg-slate-800 p-4">
                    <div class="text-sm font-semibold text-slate-200 mb-1">📍 Where the boxes are</div>
                    <div class="text-[11px] text-slate-500 mb-3">Nearest edge highlighted. The 20-bar level is the one <span class="font-mono">engine.py</span> itself tests.</div>
                    <table class="w-full text-xs text-slate-300">
                        <thead class="text-slate-400">
                            <tr>
                                <th class="text-left pb-1">box</th>
                                <th class="text-right pb-1">high</th>
                                <th class="text-right pb-1">low</th>
                                <th class="text-right pb-1">width</th>
                                <th class="text-right pb-1">in-box</th>
                                <th class="text-right pb-1">to hi</th>
                                <th class="text-right pb-1">to lo</th>
                            </tr>
                        </thead>
                        <tbody>
                        {% for b in bx.geometry.boxes %}
                            <tr class="border-t border-slate-700/70 {% if b.name == bx.nearest.box %}bg-amber-500/10{% endif %}">
                                <td class="py-1.5 pr-2">{{ b.name }}</td>
                                <td class="text-right font-mono">{{ "%.2f"|format(b.high) }}</td>
                                <td class="text-right font-mono">{{ "%.2f"|format(b.low) }}</td>
                                <td class="text-right font-mono">{{ "%.2f"|format(b.width) }} <span class="text-slate-500">({{ "%.1f"|format(b.width_atr) }}a)</span></td>
                                <td class="text-right font-mono {% if b.pos_pct is not none and (b.pos_pct < 0 or b.pos_pct > 100) %}text-rose-400{% endif %}">
                                    {% if b.pos_pct is none %}—{% else %}{{ "%.0f"|format(b.pos_pct) }}%{% endif %}
                                </td>
                                <td class="text-right font-mono {% if b.dist_up_atr is not none and b.dist_up_atr|abs <= 0.5 %}text-amber-300{% endif %}">{{ "%.2f"|format(b.dist_up_usd) }}</td>
                                <td class="text-right font-mono {% if b.dist_down_atr is not none and b.dist_down_atr|abs <= 0.5 %}text-amber-300{% endif %}">{{ "%.2f"|format(b.dist_down_usd) }}</td>
                            </tr>
                        {% endfor %}
                        </tbody>
                    </table>
                    <div class="text-[11px] text-slate-500 mt-3">
                        in-box = where the close sits inside that box (0% = at the low, 100% = at the high; outside is flagged).
                        Distance columns are $ from the last close.
                    </div>
                </div>

                <!-- Checklist -->
                <div class="rounded-2xl border border-slate-700 bg-slate-800 p-4">
                    <div class="text-sm font-semibold text-slate-200 mb-1">🎯 When to trade — the check</div>
                    <div class="text-[11px] text-slate-500 mb-3">Every line is a measurement, not an order. A trade needs every one of them — and the last is the one that decides most box setups.</div>
                    <div class="space-y-2">
                    {% for c in bx.checks %}
                        <div class="flex gap-2 items-start text-xs">
                            <span class="text-base leading-none mt-[1px]">
                                {% if c.state == 'pass' %}✅{% elif c.state == 'warn' %}⚠️{% elif c.state == 'fail' %}🚫{% else %}–{% endif %}
                            </span>
                            <div class="flex-1">
                                <span class="font-semibold
                                    {% if c.state == 'pass' %}text-emerald-400{% elif c.state == 'warn' %}text-amber-300{% elif c.state == 'fail' %}text-rose-400{% else %}text-slate-400{% endif %}">{{ c.label }}</span>
                                <span class="text-slate-300"> — {{ c.detail }}</span>
                            </div>
                        </div>
                    {% endfor %}
                    </div>
                </div>
            </div>

            <!-- Tape regime: the measured chop read, with the measurement that says
                 it does NOT predict. Answers "is it choppy today?" with a number
                 instead of a feeling — and refuses to turn that number into a filter. -->
            <div class="rounded-2xl border border-slate-700 bg-slate-800 p-4 mt-5">
                <div class="flex flex-col md:flex-row md:items-center gap-2">
                    <div class="text-sm font-semibold text-slate-200">🌊 Is the tape choppy? (measured, not felt)</div>
                    {% if bx.chop and bx.chop.ok %}
                    <span class="text-[11px] px-2 py-0.5 rounded-full
                        {% if bx.chop.level == 'elevated' %}bg-rose-500/20 text-rose-300
                        {% elif bx.chop.level == 'clean' %}bg-emerald-500/20 text-emerald-300
                        {% elif bx.chop.level == 'thin' %}bg-slate-600/40 text-slate-300
                        {% else %}bg-amber-500/20 text-amber-300{% endif %}">{{ bx.chop.level }}</span>
                    {% endif %}
                </div>
                {% if bx.chop and bx.chop.ok %}
                <div class="text-sm text-slate-300 mt-1">{{ bx.chop.headline }} — {{ bx.chop.detail }}</div>
                <div class="grid grid-cols-2 md:grid-cols-6 gap-3 mt-3 text-xs">
                    <div><div class="text-slate-500">breaks, last 24 h</div><div class="font-mono text-slate-200">{{ bx.chop.recent_breaks }}</div></div>
                    <div><div class="text-slate-500">closed back inside</div><div class="font-mono text-slate-200">{{ bx.chop.recent_false_breaks }} ({{ '%.0f'|format(bx.chop.recent_false_break_pct) }}%)</div></div>
                    <div><div class="text-slate-500">baseline in view</div><div class="font-mono text-slate-200">{{ '%.0f'|format(bx.chop.baseline_false_break_pct) }}% <span class="text-slate-500">of {{ bx.chop.baseline_breaks }}</span></div></div>
                    <div><div class="text-slate-500">efficiency 60 / 240 bars</div><div class="font-mono text-slate-200">{{ '%.2f'|format(bx.chop.eff_60) if bx.chop.eff_60 is not none else '—' }} / {{ '%.2f'|format(bx.chop.eff_240) if bx.chop.eff_240 is not none else '—' }}</div></div>
                    <div><div class="text-slate-500">20-bar box now</div><div class="font-mono text-slate-200">{{ '%.1f'|format(bx.chop.box_width_atr) if bx.chop.box_width_atr else '—' }} ATR <span class="text-slate-500">vs {{ '%.1f'|format(bx.chop.box_width_median_atr) if bx.chop.box_width_median_atr else '—' }} median</span></div></div>
                    <div><div class="text-slate-500">span measured</div><div class="font-mono text-slate-200">{{ bx.chop.baseline_span_days }} days</div></div>
                </div>
                {% set cm = bx.regime_measured.chop %}
                <div class="text-[11px] text-slate-500 mt-3">
                    <span class="text-slate-300 font-semibold">And the honest part:</span> this read does not predict outcomes. Over {{ cm.sequential_breaks }} sequential breaks,
                    a <span class="text-slate-300">clean</span> prior day gave {{ cm.prior_day_chop_clean_tf_pct }}% target-first against a {{ cm.prior_day_chop_clean_ref_pct }}% reference and a
                    <span class="text-slate-300">choppy</span> prior day gave {{ cm.prior_day_chop_choppy_tf_pct }}% against {{ cm.prior_day_chop_choppy_ref_pct }}% — the wrong way round, inside noise.
                    Efficiency ratio and box compression did not clear their references either. Context, never a filter.
                </div>
                {% else %}
                <div class="text-sm text-slate-400 mt-1">{{ bx.chop.reason if bx.chop else 'chop read unavailable' }}</div>
                {% endif %}
                {% if bx.retest and bx.retest.state and bx.retest.state != 'none' %}
                <div class="text-xs text-slate-300 mt-3 border-t border-slate-700/70 pt-3">
                    <span class="font-semibold">Last break (frozen box):</span>
                    <span class="{% if bx.retest.state == 'held' %}text-emerald-300{% elif bx.retest.state == 'failed' %}text-rose-300{% else %}text-amber-300{% endif %}">{{ bx.retest.state }}</span>
                    — {{ bx.retest.detail }}
                </div>
                {% endif %}
            </div>

            <!-- The setup, if there is one -->
            {% if bx.setup %}
            <div class="rounded-2xl border border-slate-700 bg-slate-800 p-4 mt-5">
                <div class="flex flex-col md:flex-row md:items-center gap-3">
                    <div class="text-sm font-semibold text-slate-200">
                        If you take it — <span class="{% if bx.setup.side == 'BUY' %}text-emerald-400{% else %}text-rose-400{% endif %}">{{ bx.setup.side }}</span>
                        at the {{ bx.setup.box }} {{ bx.setup.edge_name if bx.setup.edge_name else '' }} <span class="text-slate-500">({{ bx.setup.state }})</span>
                    </div>
                    <div class="text-[11px] text-slate-500 md:ml-auto">stop past the far edge, target the measured move — the only geometry that came near break-even</div>
                </div>
                <div class="grid grid-cols-2 md:grid-cols-6 gap-3 mt-3 text-xs">
                    <div><div class="text-slate-500">entry</div><div class="font-mono text-slate-200 text-sm">{{ "%.2f"|format(bx.setup.entry) }}</div></div>
                    <div><div class="text-slate-500">stop</div><div class="font-mono text-slate-200 text-sm">{{ "%.2f"|format(bx.setup.stop) }}</div></div>
                    <div><div class="text-slate-500">target</div><div class="font-mono text-slate-200 text-sm">{{ "%.2f"|format(bx.setup.target) }}</div></div>
                    <div><div class="text-slate-500">risk</div><div class="font-mono text-slate-200 text-sm">${{ "%.2f"|format(bx.setup.risk_usd) }}</div></div>
                    <div><div class="text-slate-500">reward</div><div class="font-mono text-slate-200 text-sm">${{ "%.2f"|format(bx.setup.reward_usd) }} <span class="text-slate-500">({{ "%.1f"|format(bx.setup.rr) }}:1)</span></div></div>
                    <div><div class="text-slate-500">spread share of R</div>
                        <div class="font-mono text-sm {% if bx.setup.cost_share_pct > 20 %}text-rose-400{% elif bx.setup.cost_share_pct > 10 %}text-amber-300{% else %}text-emerald-400{% endif %}">{{ "%.0f"|format(bx.setup.cost_share_pct) }}%</div></div>
                </div>
                <div class="text-[11px] text-slate-500 mt-3">
                    The engine's own structural stop on that same edge would risk ${{ "%.2f"|format(bx.setup.engine_risk) }}
                    for a ${{ "%.2f"|format(bx.setup.engine_tp) }} target — with the spread at
                    {{ "%.0f"|format(bx.setup.engine_cost_share_pct) }}% of R.
                </div>
            </div>
            {% endif %}

            <!-- Honesty footer -->
            <div class="mt-5 rounded-xl border border-slate-700/60 bg-slate-900/60 p-3 text-[11px] text-slate-500">
                <span class="text-slate-300 font-semibold">Measured, not assumed:</span>
                on this log (2026-10-20) {{ bx.measured.cells }} breakout/fade geometries were tested and
                <span class="text-rose-400">{{ bx.measured.cleared }} cleared the no-edge reference</span>;
                {{ "%.0f"|format(bx.measured.false_break_pct_20) }}–{{ "%.0f"|format(bx.measured.false_break_pct_60) }}% of closes outside a box were back inside within 15 minutes.
                The checklist tells you when the <span class="text-slate-300">conditions</span> line up — it cannot make an edge appear.
                <span class="text-slate-300">A box answers WHERE, not WHEN: a place to put the stop, not a prediction.</span>
                Best measured geometry: {{ bx.measured.best }}.
                Display-only, paper only — no order is placed. Method: <span class="font-mono">docs/ANALYSIS-2026-10-20-box-theory-manual-trading.md</span>
            </div>
            {% else %}
            <div class="rounded-2xl border border-slate-700 bg-slate-800 p-5">
                <div class="text-lg font-semibold text-slate-200">📦 Box read unavailable</div>
                <div class="text-sm text-slate-400 mt-1">{{ ctx.boxes.reason if ctx.boxes else 'the read layer did not load' }}</div>
            </div>
            {% endif %}
        </div>
        <!-- ================= END BOXES TAB ================= -->


        <!-- ================= CHART & PLACEMENT TAB ================= -->
        <div id="panel-chart" class="hidden">
            {% if ctx.chart and ctx.chart.ok %}
            {% set c = ctx.chart %}
            {% set v = c.view %}
            {% set pv = c.verdict %}

            <!-- Plain-English verdict -->
            <div class="rounded-2xl border p-5 mb-5
                {% if pv.tone == 'ok' %} bg-emerald-950/30 border-emerald-700
                {% elif pv.tone == 'warn' %} bg-amber-950/30 border-amber-700
                {% elif pv.tone == 'block' %} bg-rose-950/30 border-rose-700
                {% else %} bg-slate-800 border-slate-700 {% endif %}">
                <div class="flex flex-col md:flex-row md:items-center gap-4">
                    <div class="text-4xl">{% if pv.tone == 'ok' %}🧭{% elif pv.tone == 'warn' %}⏳{% elif pv.tone == 'block' %}⛔{% else %}💤{% endif %}</div>
                    <div class="flex-1">
                        <div class="text-lg font-semibold">{{ pv.headline }}</div>
                        <div class="text-sm text-slate-300 mt-1">{{ pv.detail }}</div>
                        {% if pv.missing %}
                        <div class="text-xs text-slate-400 mt-2">Not met:
                            {% for m in pv.missing %}<span class="inline-block px-1.5 py-0.5 rounded bg-slate-900/70 border border-slate-700 mr-1 mb-1">{{ m }}</span>{% endfor %}
                        </div>
                        {% endif %}
                    </div>
                    <div class="text-right text-xs text-slate-400 space-y-1 shrink-0">
                        <div>close <span class="font-mono text-slate-100">${{ "%.2f"|format(v.close) }}</span></div>
                        <div>ATR <span class="font-mono text-slate-100">${{ "%.2f"|format(v.atr or 0) }}</span></div>
                        <div>last bar <span class="font-mono text-slate-200">{{ v.as_of }} UTC</span></div>
                    </div>
                </div>
            </div>

            <!-- The chart -->
            <div class="rounded-2xl border border-slate-700 bg-slate-900/60 p-4 mb-5">
                <div class="flex flex-wrap items-center gap-2 mb-3">
                    <h3 class="text-sm font-semibold text-slate-200 mr-auto">Price — the last {{ v.n_candles }} candles</h3>
                    <span class="text-[11px] text-slate-500">bar size</span>
                    {% for g in c.groups %}
                    <a href="?tab=chart&tf={{ g }}"
                       class="px-2 py-1 rounded text-[11px] font-semibold border
                       {% if g == c.group %} bg-amber-500 text-slate-900 border-amber-500
                       {% else %} bg-slate-800 text-slate-400 border-slate-700 hover:bg-slate-700 {% endif %}">M{{ g }}</a>
                    {% endfor %}
                </div>

                <svg viewBox="0 0 {{ v.width }} {{ v.height }}" class="w-full h-auto" preserveAspectRatio="xMidYMid meet" role="img"
                     aria-label="Gold price chart with box levels and session shading">
                    <rect x="0" y="0" width="{{ v.width }}" height="{{ v.height }}" fill="#0f172a"/>
                    <!-- session + stand-aside bands -->
                    {% for b in v.bands %}
                    <rect x="{{ b.x0 }}" y="{{ v.plot.t }}" width="{{ b.w }}" height="{{ v.plot.h }}"
                          fill="{% if b.session == 'Asia' %}#334155{% elif b.session == 'London' %}#3730a3{% elif b.session == 'New York' %}#065f46{% else %}#78350f{% endif %}" opacity="0.30"/>
                    {% if b.blackout %}
                    <rect x="{{ b.x0 }}" y="{{ v.plot.t }}" width="{{ b.w }}" height="{{ v.plot.h }}" fill="#ef4444"
                          opacity="{{ '0.18' if b.blackout == 'both' else '0.09' }}"/>
                    {% endif %}
                    {% endfor %}
                    <!-- grid -->
                    {% for t in v.ticks %}
                    <line x1="{{ v.plot.l }}" x2="{{ v.plot.l + v.plot.w }}" y1="{{ t.y }}" y2="{{ t.y }}"
                          stroke="#334155" stroke-width="0.5" stroke-dasharray="2 5"/>
                    <text x="{{ v.plot.l + v.plot.w + 6 }}" y="{{ t.y + 3 }}" fill="#64748b" font-size="9" font-family="ui-monospace,monospace">{{ t.label }}</text>
                    {% endfor %}
                    <!-- candles -->
                    {% for k in v.candles %}
                    <line x1="{{ k.cx }}" x2="{{ k.cx }}" y1="{{ k.y_high }}" y2="{{ k.y_low }}"
                          stroke="{% if k.up %}#34d399{% else %}#fb7185{% endif %}" stroke-width="0.9"
                          opacity="{{ '0.4' if k.partial else '0.95' }}"/>
                    <rect x="{{ k.bx }}" y="{{ k.y_top }}" width="{{ k.w }}" height="{{ k.body_h }}"
                          fill="{% if k.up %}#34d399{% else %}#fb7185{% endif %}"
                          opacity="{{ '0.4' if k.partial else '0.95' }}"/>
                    {% endfor %}
                    <!-- box / level lines -->
                    {% for l in v.levels %}
                    {% if l.in_range %}
                    <line x1="{{ v.plot.l }}" x2="{{ v.plot.l + v.plot.w }}" y1="{{ l.y }}" y2="{{ l.y }}"
                          stroke="{% if l.kind == 'engine' %}#fbbf24{% elif l.kind == 'day' %}#22d3ee{% else %}#94a3b8{% endif %}"
                          stroke-width="{{ '1.3' if l.kind == 'engine' else '0.8' }}"
                          stroke-dasharray="{% if l.kind == 'engine' %}none{% elif l.kind == 'day' %}1 3{% else %}5 4{% endif %}"
                          opacity="{{ '0.9' if l.kind == 'engine' else '0.6' }}"/>
                    <text x="{{ v.plot.l + 4 }}" y="{{ l.y - 3 }}"
                          fill="{% if l.kind == 'engine' %}#fbbf24{% elif l.kind == 'day' %}#67e8f9{% else %}#94a3b8{% endif %}"
                          font-size="8.5" font-family="ui-monospace,monospace"
                          opacity="{{ '0.95' if l.kind == 'engine' else '0.7' }}">{{ l.label }} {{ "%.2f"|format(l.price) }}</text>
                    {% endif %}
                    {% endfor %}
                    <!-- current price -->
                    <line x1="{{ v.plot.l }}" x2="{{ v.plot.l + v.plot.w }}" y1="{{ v.close_y }}" y2="{{ v.close_y }}"
                          stroke="#e2e8f0" stroke-width="0.6" stroke-dasharray="1 3" opacity="0.5"/>
                    <rect x="{{ v.plot.l + v.plot.w + 2 }}" y="{{ v.close_y - 6 }}" width="84" height="12" rx="2" fill="#e2e8f0"/>
                    <text x="{{ v.plot.l + v.plot.w + 5 }}" y="{{ v.close_y + 3 }}" fill="#0f172a" font-size="8.5"
                          font-weight="bold" font-family="ui-monospace,monospace">{{ "%.2f"|format(v.close) }}</text>
                    <!-- offscreen levels: never dropped, pinned to the edge -->
                    {% for l in v.levels if not l.in_range %}
                    <text x="{{ v.plot.l + 4 }}" y="{{ 10 if l.offscreen_above else v.height - 12 }}"
                          fill="#67e8f9" font-size="8.5" opacity="0.75" font-family="ui-monospace,monospace">
                        {{ '↑' if l.offscreen_above else '↓' }} {{ l.label }} {{ "%.2f"|format(l.price) }} ({{ 'above' if l.offscreen_above else 'below' }} this view)
                    </text>
                    {% endfor %}
                    <!-- times -->
                    {% for t in v.times %}
                    <text x="{{ t.x }}" y="{{ v.height - 3 }}" fill="#64748b" font-size="9" text-anchor="middle"
                          font-family="ui-monospace,monospace">{{ t.label }}</text>
                    {% endfor %}
                </svg>

                <div class="flex flex-wrap items-center gap-x-4 gap-y-1 mt-2 text-[11px] text-slate-400">
                    <span><span class="text-amber-400">━━</span> bot's 20-bar level</span>
                    <span><span class="text-slate-400">╌╌</span> 1h / 4h box</span>
                    <span><span class="text-cyan-400">┈┈</span> prior-day high/low</span>
                    <span><span class="inline-block w-2 h-3 bg-rose-800/60 align-middle"></span> stand aside (both sides)</span>
                    <span><span class="inline-block w-2 h-3 bg-rose-800/30 align-middle"></span> stand aside (buys only)</span>
                </div>
                <p class="text-[11px] text-slate-500 mt-2">
                    Older bars fade out — the right-most candle is still forming. Levels come from closed bars and roll every bar.
                    This is the broker's demo GOLD feed (≈$4,000 scale), <span class="text-slate-300">not spot XAUUSD</span>, so it will not match TradingView tick-for-tick.
                </p>
            </div>

            <!-- Placement -->
            <div class="mb-5">
                <div class="flex items-baseline gap-2 mb-2">
                    <h3 class="text-lg font-semibold">Where the trade would go</h3>
                    <span class="text-xs text-slate-500">three numbers — entry, stop, target — and whether they are worth taking</span>
                </div>
                {% if c.plan_box %}
                <p class="text-xs text-slate-400 mb-2">Built on the <span class="text-slate-200 font-semibold">{{ c.plan_box }}</span> box — the tightest one a stop can sit outside of.</p>
                {% endif %}
                {% if c.box_note %}
                <p class="text-[11px] text-amber-300/90 mb-2">⚠ {{ c.box_note }}</p>
                {% endif %}
                {% if c.plan %}
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {% for card in c.plan %}
                    <div class="rounded-xl border p-4
                        {% if card.verdict == 'skip' %} border-rose-800 bg-rose-950/20
                        {% elif card.verdict == 'watch' %} border-amber-700 bg-amber-950/20
                        {% else %} border-emerald-700 bg-emerald-950/20 {% endif %}">
                        <div class="flex items-center gap-2">
                            <span class="text-lg font-bold {% if card.side == 'BUY' %}text-emerald-300{% else %}text-rose-300{% endif %}">{{ card.side }}</span>
                            <span class="px-2 py-0.5 rounded text-[10px] font-bold tracking-wide
                                {% if card.verdict == 'skip' %} bg-rose-800 text-rose-100
                                {% elif card.verdict == 'watch' %} bg-amber-700 text-amber-50
                                {% else %} bg-emerald-700 text-emerald-50 {% endif %}">{{ card.verdict_text }}</span>
                        </div>
                        <p class="text-xs text-slate-300 mt-1">{{ card.headline }}</p>

                        <dl class="grid grid-cols-3 gap-2 mt-3">
                            <div class="bg-slate-900/60 rounded-lg p-2">
                                <dt class="text-[10px] text-slate-400 uppercase tracking-wide">Entry</dt>
                                <dd class="font-mono text-sm text-slate-100">${{ "%.2f"|format(card.entry or 0) }}</dd>
                            </div>
                            <div class="bg-slate-900/60 rounded-lg p-2">
                                <dt class="text-[10px] text-slate-400 uppercase tracking-wide">Stop</dt>
                                <dd class="font-mono text-sm text-rose-300">${{ "%.2f"|format(card.stop or 0) }}</dd>
                            </div>
                            <div class="bg-slate-900/60 rounded-lg p-2">
                                <dt class="text-[10px] text-slate-400 uppercase tracking-wide">Target</dt>
                                <dd class="font-mono text-sm text-emerald-300">${{ "%.2f"|format(card.target or 0) }}</dd>
                            </div>
                        </dl>

                        <div class="grid grid-cols-3 gap-2 mt-2 text-[11px] text-slate-400">
                            <div>risk <span class="font-mono text-slate-200">${{ "%.2f"|format(card.risk_usd or 0) }}</span></div>
                            <div>reward <span class="font-mono text-slate-200">${{ "%.2f"|format(card.reward_usd or 0) }}</span></div>
                            <div>R:R <span class="font-mono {% if (card.rr or 0) >= 1 %}text-emerald-300{% else %}text-rose-300{% endif %}">{{ "%.2f"|format(card.rr or 0) }}:1</span></div>
                        </div>
                        <div class="mt-1 text-[11px] text-slate-400">
                            spread is <span class="font-mono {% if (card.cost_pct or 0) > 10 %}text-rose-300{% else %}text-emerald-300{% endif %}">{{ "%.0f"|format(card.cost_pct or 0) }}%</span>
                            of your risk (${{ "%.2f"|format(card.cost_usd or 0) }} round trip)
                        </div>

                        {% if card.verdict == 'skip' %}
                        <ul class="mt-3 space-y-1">
                            {% for r in card.reasons %}
                            <li class="text-xs text-rose-200/90">✗ {{ r }}</li>
                            {% endfor %}
                        </ul>
                        <p class="text-[11px] text-slate-400 mt-2">No edge has been measured in this geometry either way — this is a <span class="text-slate-300">geometry check</span>, not a forecast.</p>
                        {% else %}
                        <p class="text-xs text-slate-300 mt-3">{{ card.stop_sentence }}</p>
                        <p class="text-xs text-slate-300 mt-1">{{ card.target_sentence }}</p>
                        {% endif %}
                        <p class="text-[11px] text-slate-500 mt-2">{{ card.state }}</p>
                    </div>
                    {% endfor %}
                </div>
                {% else %}
                <div class="rounded-xl border border-slate-700 bg-slate-800 p-4 text-sm text-slate-400">
                    No box to place a trade against right now — the feed is still warming up, or no box could be built from the recent bars.
                </div>
                {% endif %}
            </div>

            <!-- Cost ruler -->
            {% if c.cost and c.cost.ok %}
            <div class="rounded-2xl border border-slate-700 bg-slate-800 p-4 mb-5">
                <div class="flex items-baseline gap-2">
                    <h3 class="text-lg font-semibold">💸 The cost ruler</h3>
                    <span class="text-xs text-slate-500">why the stop distance decides the trade before you enter it</span>
                </div>
                <p class="text-xs text-slate-400 mt-1">
                    The spread is charged once on every trade, win or lose. A short stop makes it a big share of your risk.
                    At ATR ${{ "%.2f"|format(c.cost.atr or 0) }} you need a stop of at least
                    <span class="text-amber-300 font-semibold">{{ "%.1f"|format(c.cost.min_mult['0.55']) }} ATR</span>
                    (≈ ${{ "%.2f"|format(c.cost.min_mult['0.55'] * (c.cost.atr or 0)) }}) just to keep the cost under 10% of R.
                </p>
                <div class="mt-3 space-y-1.5">
                    {% for r in c.cost.rows %}
                    <div class="flex items-center gap-2 text-xs">
                        <span class="w-16 shrink-0 font-mono text-slate-400">{{ "%.1f"|format(r.mult) }} ATR</span>
                        <span class="w-16 shrink-0 font-mono text-slate-300">${{ "%.2f"|format(r.risk_usd) }}</span>
                        <span class="flex-1 bg-slate-900 rounded h-4 overflow-hidden">
                            <span class="block h-4 rounded
                                {% if r.zone == 'red' %} bg-rose-500/70
                                {% elif r.zone == 'amber' %} bg-amber-500/70
                                {% else %} bg-emerald-500/70 {% endif %}"
                                style="width: {{ [ (r.share['0.55'] / 40.0 * 100), 100 ] | min }}%"></span>
                        </span>
                        <span class="w-24 shrink-0 text-right font-mono
                            {% if r.zone == 'red' %} text-rose-300 {% elif r.zone == 'amber' %} text-amber-300 {% else %} text-emerald-300 {% endif %}">
                            {{ "%.0f"|format(r.share['0.55']) }}% of R
                        </span>
                    </div>
                    {% endfor %}
                </div>
                <p class="text-[11px] text-slate-500 mt-3">
                    % is the share of risk eaten by a $0.55 round trip (the quote logger's measured median). The registered model is $0.40 —
                    at that cost a 3 ATR stop pays 9.0%. Green ≤10%, amber ≤20%, red above. Rule of thumb:
                    <span class="text-slate-300">never take a trade whose stop is under ~3 ATR on this tape.</span>
                </p>
            </div>
            {% endif %}

            <!-- How to read -->
            <div class="rounded-2xl border border-slate-700 bg-slate-800/60 p-4 mb-5">
                <details>
                    <summary class="cursor-pointer text-sm font-semibold text-slate-200">📖 New to charts? Read this first (5 things, 60 seconds)</summary>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">
                        {% for title, body in c.how_to_read %}
                        <div class="text-xs text-slate-400 leading-snug">
                            <span class="text-slate-200 font-semibold block">{{ title }}</span>
                            {{ body }}
                        </div>
                        {% endfor %}
                    </div>
                    <p class="text-[11px] text-slate-500 mt-3">
                        That is the whole list on purpose — see the last item for what is deliberately absent and why.
                        The chart is a thinking aid, not a signal: nothing on it has been shown to predict direction.
                    </p>
                </details>
            </div>

            <!-- Honesty footer -->
            <div class="rounded-xl border border-slate-700/60 bg-slate-900/60 p-3 text-[11px] text-slate-500">
                <span class="text-slate-300 font-semibold">Measured, not assumed:</span>
                8 box breakout/fade geometries tested, <span class="text-rose-400">0 cleared the no-edge reference</span>;
                74–75% of closes outside a box are back inside within 15 minutes; the 8/8 signal is 50.4% [42–59] trade-way at 30 minutes.
                So this tab shows <span class="text-slate-300">where</span> a trade would sit and <span class="text-slate-300">what it costs</span> — it does not predict direction.
                Display-only, paper only: no order is placed, no gate changes, nothing is written.
                Method: <span class="font-mono">docs/PROPOSAL-2026-10-23-manual-chart-tab.md</span> ·
                <span class="font-mono">docs/ANALYSIS-2026-10-20-box-theory-manual-trading.md</span>
            </div>

            {% else %}
            <div class="rounded-2xl border border-slate-700 bg-slate-800 p-5">
                <div class="text-lg font-semibold text-slate-200">🧭 Chart read unavailable</div>
                <div class="text-sm text-slate-400 mt-1">{{ ctx.chart.reason if ctx.chart else 'the read layer did not load' }}</div>
                <div class="text-xs text-slate-500 mt-2">The other tabs still work — this panel needs <span class="font-mono">forward_test_log.csv</span> to hold enough recent bars.</div>
            </div>
            {% endif %}
        </div>
        <!-- ================= END CHART & PLACEMENT TAB ================= -->

        <!-- ================= JOURNAL TAB ================= -->
        <div id="panel-journal" class="hidden">
            {% if ctx.journal and ctx.journal.ok %}
            {% set j = ctx.journal %}
            {% set b = j.book %}
            {% set er = j.era %}

            <div class="rounded-2xl border border-slate-700 bg-slate-800 p-5 mb-5">
                <div class="flex flex-col md:flex-row md:items-start gap-4">
                    <div class="text-4xl">📓</div>
                    <div class="flex-1">
                        <h2 class="text-xl font-semibold text-slate-100">Self-journal — what the bot did, why, and how it ended</h2>
                        <p class="text-sm text-slate-400 mt-1">
                            Rebuilt from <span class="font-mono">trades.csv</span> + <span class="font-mono">forward_test_log.csv</span>:
                            the context is the last closed bar before each entry, the outcome is the ledger's own exit.
                            Nothing here is written, ordered or used by the engine.
                        </p>
                    </div>
                    <div class="text-right text-xs text-slate-400 space-y-1 shrink-0">
                        <div>data through <span class="font-mono text-slate-200">{{ j.as_of.strftime('%Y-%m-%d %H:%M') if j.as_of else '—' }}</span> UTC</div>
                        <div>cost model <span class="font-mono text-slate-200">${{ '%.2f'|format(j.cost) }}</span> round trip (assumed)</div>
                        <div>{{ j.era_label }}</div>
                    </div>
                </div>
            </div>

            <div class="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-5">
                <div class="rounded-2xl border border-slate-700 bg-slate-800 p-4">
                    <div class="text-[11px] uppercase tracking-wide text-slate-400">Decisive win rate — current rule</div>
                    <div class="text-3xl font-bold mt-1 {{ 'text-emerald-300' if (er.decisive_wr or 0) >= 39.3 else 'text-rose-300' }}">
                        {{ '%.1f'|format(er.decisive_wr) if er.decisive_wr is not none else '—' }}%
                    </div>
                    <div class="text-xs text-slate-400 mt-1">95% CI
                        {{ '%.1f'|format(er.decisive_ci[0]) if er.decisive_ci and er.decisive_ci[0] is not none else '—' }}–
                        {{ '%.1f'|format(er.decisive_ci[1]) if er.decisive_ci and er.decisive_ci[1] is not none else '—' }}%
                        · TP/(TP+SL)</div>
                    <div class="text-[11px] text-slate-500 mt-1">all-time {{ '%.1f'|format(b.decisive_wr) if b.decisive_wr is not none else '—' }}% at n={{ b.n }}</div>
                </div>
                <div class="rounded-2xl border border-slate-700 bg-slate-800 p-4">
                    <div class="text-[11px] uppercase tracking-wide text-slate-400">Record — current rule</div>
                    <div class="text-2xl font-bold mt-1">
                        <span class="text-emerald-300">{{ er.wins }}W</span> /
                        <span class="text-rose-300">{{ er.losses }}L</span> /
                        <span class="text-slate-300">{{ er.be }}BE</span> /
                        <span class="text-amber-300">{{ er.time }}TIME</span>
                    </div>
                    <div class="text-xs text-slate-400 mt-1">all-in rate {{ '%.1f'|format(er.all_in_pct) if er.all_in_pct is not none else '—' }}% (scratches count against)</div>
                    <div class="text-[11px] text-slate-500 mt-1">all-time {{ b.wins }}W/{{ b.losses }}L/{{ b.be }}BE/{{ b.time }}TIME</div>
                </div>
                <div class="rounded-2xl border border-slate-700 bg-slate-800 p-4">
                    <div class="text-[11px] uppercase tracking-wide text-slate-400">Net at the assumed cost</div>
                    <div class="text-3xl font-bold mt-1 {{ 'text-emerald-300' if (er.net or 0) >= 0 else 'text-rose-300' }}">
                        {{ '%+.2f'|format(er.net) if er.net is not none else '—' }}
                    </div>
                    <div class="text-xs text-slate-400 mt-1">current rule · ${{ '%.2f'|format(er.net_per_trade) if er.net_per_trade is not none else '—' }}/trade</div>
                    <div class="text-[11px] text-slate-500 mt-1">whole book {{ '%+.2f'|format(b.net) if b.net is not none else '—' }}</div>
                </div>
                <div class="rounded-2xl border border-slate-700 bg-slate-800 p-4">
                    <div class="text-[11px] uppercase tracking-wide text-slate-400">Expectancy</div>
                    <div class="text-3xl font-bold mt-1 {{ 'text-emerald-300' if (er.r_mean or 0) >= 0 else 'text-rose-300' }}">
                        {{ '%+.2f'|format(er.r_mean) if er.r_mean is not none else '—' }}R
                    </div>
                    <div class="text-xs text-slate-400 mt-1">per closed trade · payoff
                        {{ '%.2f'|format(b.payoff) if b.payoff is not none else '—' }} : 1 · breakeven
                        {{ '%.1f'|format(b.breakeven_wr_pct) if b.breakeven_wr_pct is not none else '—' }}%</div>
                    <div class="text-[11px] text-slate-500 mt-1">median hold {{ '%.0f'|format(b.hold_median) if b.hold_median is not none else '—' }} min ·
                        longest SL run {{ b.streak.longest_sl }}</div>
                </div>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-5">
                <div class="rounded-2xl border border-slate-700 bg-slate-800 p-4">
                    <div class="text-sm font-semibold text-slate-200">Since midnight — entry date {{ j.today.label }}</div>
                    <div class="text-sm text-slate-300 mt-1">
                        n={{ j.today.n }} · {{ j.today.wins }}W/{{ j.today.losses }}L/{{ j.today.be }}BE/{{ j.today.time }}TIME ·
                        decisive {{ '%.1f'|format(j.today.decisive_wr) if j.today.decisive_wr is not none else '—' }}% ·
                        R/trade {{ '%+.2f'|format(j.today.r_mean) if j.today.r_mean is not none else '—' }} ·
                        net <span class="{{ 'text-emerald-300' if (j.today.net or 0) >= 0 else 'text-rose-300' }}">{{ '%+.2f'|format(j.today.net) if j.today.net is not none else '—' }}</span>
                    </div>
                </div>
                <div class="rounded-2xl border border-slate-700 bg-slate-800 p-4">
                    <div class="text-sm font-semibold text-slate-200">Last 7 entry days</div>
                    <div class="text-sm text-slate-300 mt-1">
                        n={{ j.last7.n }} · {{ j.last7.wins }}W/{{ j.last7.losses }}L/{{ j.last7.be }}BE/{{ j.last7.time }}TIME ·
                        decisive {{ '%.1f'|format(j.last7.decisive_wr) if j.last7.decisive_wr is not none else '—' }}% ·
                        R/trade {{ '%+.2f'|format(j.last7.r_mean) if j.last7.r_mean is not none else '—' }} ·
                        net <span class="{{ 'text-emerald-300' if (j.last7.net or 0) >= 0 else 'text-rose-300' }}">{{ '%+.2f'|format(j.last7.net) if j.last7.net is not none else '—' }}</span>
                    </div>
                </div>
            </div>

            {% if j.open %}
            <div class="rounded-2xl border border-amber-700 bg-amber-950/20 p-4 mb-5">
                <div class="flex flex-col md:flex-row md:items-center gap-2">
                    <div class="text-lg font-semibold text-amber-300">🟡 Open page — #{{ j.open.num }} {{ j.open.side }}</div>
                    <div class="text-xs text-slate-400 md:ml-auto">not counted in any success rate until it closes</div>
                </div>
                <div class="grid grid-cols-2 md:grid-cols-5 gap-3 mt-3 text-xs">
                    <div><div class="text-slate-400">entry</div><div class="font-mono text-slate-200">${{ '%.2f'|format(j.open.entry) }}</div></div>
                    <div><div class="text-slate-400">stop / target</div><div class="font-mono text-slate-200">${{ '%.2f'|format(j.open.stop) }} / ${{ '%.2f'|format(j.open.tp) }}</div></div>
                    <div><div class="text-slate-400">last close</div><div class="font-mono text-slate-200">${{ '%.2f'|format(j.open.price_now) if j.open.price_now is not none else '—' }}</div></div>
                    <div><div class="text-slate-400">open P/L (last close)</div><div class="font-mono {{ 'text-emerald-300' if (j.open.r_now or 0) >= 0 else 'text-rose-300' }}">{{ '%+.2f'|format(j.open.r_now) if j.open.r_now is not none else '—' }}R</div></div>
                    <div><div class="text-slate-400">age</div><div class="font-mono text-slate-200">{{ '%.0f'|format(j.open.hold_min) if j.open.hold_min is not none else '—' }} min</div></div>
                </div>
                <div class="text-xs text-slate-300 mt-2">{{ j.open.thesis }}</div>
            </div>
            {% endif %}

            <div class="rounded-2xl border border-slate-700 bg-slate-800 p-4 mb-5">
                <div class="text-sm font-semibold text-slate-200">Newest pages</div>
                <div class="text-[11px] text-slate-500 mb-2">Context is the bar before entry; MFE/MAE are the best/worst excursions after it, in R. This is an audit trail, not a scoreboard of “good” calls.</div>
                <div class="overflow-x-auto">
                <table class="w-full text-xs text-slate-300">
                    <thead class="text-slate-400">
                        <tr>
                            <th class="text-left pb-1">#</th>
                            <th class="text-left pb-1">entry (UTC)</th>
                            <th class="text-left pb-1">side</th>
                            <th class="text-left pb-1">exit</th>
                            <th class="text-right pb-1">R</th>
                            <th class="text-right pb-1">MFE</th>
                            <th class="text-right pb-1">MAE</th>
                            <th class="text-right pb-1">hold</th>
                            <th class="text-left pb-1 pl-3">why (the bar the engine acted on)</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for e in j.recent %}
                        <tr class="border-t border-slate-700/60">
                            <td class="py-1 text-slate-500">#{{ e.num }}</td>
                            <td class="py-1 font-mono text-[11px]">{{ e.entry_time.strftime('%m-%d %H:%M') }}</td>
                            <td class="py-1 font-semibold {{ 'text-emerald-300' if e.side == 'BUY' else 'text-rose-300' }}">{{ e.side }}</td>
                            <td class="py-1 font-semibold {% if e.reason == 'TP' %}text-emerald-300{% elif e.reason == 'SL' %}text-rose-300{% elif e.reason == 'BE' %}text-slate-400{% else %}text-amber-300{% endif %}">{{ e.reason }}</td>
                            <td class="py-1 text-right font-mono {{ 'text-emerald-300' if (e.r or 0) > 0 else ('text-rose-300' if (e.r or 0) < 0 else 'text-slate-400') }}">{{ '%+.2f'|format(e.r) if e.r is not none else '—' }}</td>
                            <td class="py-1 text-right font-mono text-slate-400">{{ '%+.2f'|format(e.mfe_r) if e.mfe_r is not none else '—' }}</td>
                            <td class="py-1 text-right font-mono text-slate-400">{{ '%+.2f'|format(e.mae_r) if e.mae_r is not none else '—' }}</td>
                            <td class="py-1 text-right font-mono text-slate-400">{{ '%.0f'|format(e.hold_min) if e.hold_min is not none else '—' }}</td>
                            <td class="py-1 pl-3 text-[11px] text-slate-400">{{ e.thesis }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
                </div>
            </div>

            <div class="grid grid-cols-1 xl:grid-cols-2 gap-5 mb-5">
                <div class="rounded-2xl border border-slate-700 bg-slate-800 p-4">
                    <div class="text-sm font-semibold text-slate-200">By side — BUY and SELL are different strategies</div>
                    <table class="w-full text-xs text-slate-300 mt-2">
                        <thead class="text-slate-400"><tr>
                            <th class="text-left pb-1">side</th><th class="text-right pb-1">n</th>
                            <th class="text-right pb-1">W/L/BE/T</th><th class="text-right pb-1">decisive</th>
                            <th class="text-right pb-1">R/trade</th><th class="text-right pb-1">net</th>
                        </tr></thead>
                        <tbody>
                        {% for name, s in j.sides.items() %}
                        <tr class="border-t border-slate-700/60">
                            <td class="py-1 font-semibold {{ 'text-emerald-300' if name == 'BUY' else 'text-rose-300' }}">{{ name }}</td>
                            <td class="py-1 text-right">{{ s.n }}</td>
                            <td class="py-1 text-right">{{ s.wins }}/{{ s.losses }}/{{ s.be }}/{{ s.time }}</td>
                            <td class="py-1 text-right">{{ '%.1f'|format(s.decisive_wr) if s.decisive_wr is not none else '—' }}%</td>
                            <td class="py-1 text-right font-mono">{{ '%+.2f'|format(s.r_mean) if s.r_mean is not none else '—' }}</td>
                            <td class="py-1 text-right font-mono {{ 'text-emerald-300' if (s.net or 0) >= 0 else 'text-rose-300' }}">{{ '%+.2f'|format(s.net) if s.net is not none else '—' }}</td>
                        </tr>
                        {% endfor %}
                        </tbody>
                    </table>
                </div>
                <div class="rounded-2xl border border-slate-700 bg-slate-800 p-4">
                    <div class="text-sm font-semibold text-slate-200">By session — entry hour, UTC</div>
                    <table class="w-full text-xs text-slate-300 mt-2">
                        <thead class="text-slate-400"><tr>
                            <th class="text-left pb-1">session</th><th class="text-right pb-1">n</th>
                            <th class="text-right pb-1">W/L/BE/T</th><th class="text-right pb-1">decisive</th>
                            <th class="text-right pb-1">R/trade</th><th class="text-right pb-1">net</th>
                        </tr></thead>
                        <tbody>
                        {% for name, s in j.sessions.items() %}
                        <tr class="border-t border-slate-700/60">
                            <td class="py-1 text-slate-300">{{ name }}</td>
                            <td class="py-1 text-right">{{ s.n }}</td>
                            <td class="py-1 text-right">{{ s.wins }}/{{ s.losses }}/{{ s.be }}/{{ s.time }}</td>
                            <td class="py-1 text-right">{{ '%.1f'|format(s.decisive_wr) if s.decisive_wr is not none else '—' }}%</td>
                            <td class="py-1 text-right font-mono">{{ '%+.2f'|format(s.r_mean) if s.r_mean is not none else '—' }}</td>
                            <td class="py-1 text-right font-mono {{ 'text-emerald-300' if (s.net or 0) >= 0 else 'text-rose-300' }}">{{ '%+.2f'|format(s.net) if s.net is not none else '—' }}</td>
                        </tr>
                        {% endfor %}
                        </tbody>
                    </table>
                    <div class="text-[11px] text-slate-500 mt-2">Asia/rollover = 23:00–06:59 UTC; London/NY = 07:00–22:59 UTC. Sessions are descriptive — the 2026-10-05 review downgraded the session band as a gate.</div>
                </div>
            </div>

            <div class="rounded-2xl border border-slate-700 bg-slate-800 p-4 mb-5">
                <div class="text-sm font-semibold text-slate-200">The last 14 entry days</div>
                <div class="overflow-x-auto mt-2">
                <table class="w-full text-xs text-slate-300">
                    <thead class="text-slate-400"><tr>
                        <th class="text-left pb-1">date</th><th class="text-right pb-1">n</th>
                        <th class="text-right pb-1">W</th><th class="text-right pb-1">L</th><th class="text-right pb-1">BE</th>
                        <th class="text-right pb-1">TIME</th><th class="text-right pb-1">decisive</th>
                        <th class="text-right pb-1">R/trade</th><th class="text-right pb-1">net</th>
                        <th class="text-right pb-1">cum net</th>
                    </tr></thead>
                    <tbody>
                        {% for d in j.daily %}
                        <tr class="border-t border-slate-700/60">
                            <td class="py-1 font-mono text-[11px]">{{ d.label }}</td>
                            <td class="py-1 text-right">{{ d.n }}</td>
                            <td class="py-1 text-right text-emerald-300">{{ d.wins }}</td>
                            <td class="py-1 text-right text-rose-300">{{ d.losses }}</td>
                            <td class="py-1 text-right text-slate-400">{{ d.be }}</td>
                            <td class="py-1 text-right text-amber-300">{{ d.time }}</td>
                            <td class="py-1 text-right">{{ '%.1f'|format(d.decisive_wr) if d.decisive_wr is not none else '—' }}%</td>
                            <td class="py-1 text-right font-mono">{{ '%+.2f'|format(d.r_mean) if d.r_mean is not none else '—' }}</td>
                            <td class="py-1 text-right font-mono {{ 'text-emerald-300' if (d.net or 0) >= 0 else 'text-rose-300' }}">{{ '%+.2f'|format(d.net) if d.net is not none else '—' }}</td>
                            <td class="py-1 text-right font-mono text-slate-400">{{ '%+.2f'|format(d.cum_net) if d.cum_net is not none else '—' }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
                </div>
                <div class="text-[11px] text-slate-500 mt-2">Grouped by Entry_Time date (the repo's era convention). Cumulative starts at the first day in this window, not at $500.</div>
            </div>

            <div class="grid grid-cols-1 xl:grid-cols-2 gap-5 mb-5">
                <div class="rounded-2xl border border-slate-700 bg-slate-800 p-4">
                    <div class="text-sm font-semibold text-slate-200">What the journal noticed</div>
                    <div class="text-xs text-slate-300 mt-2">
                        <span class="font-semibold">{{ j.givebacks.was_ahead_n }}</span> of {{ b.n }} trades
                        ({{ '%.1f'|format(j.givebacks.was_ahead_pct) if j.givebacks.was_ahead_pct is not none else '—' }}%)
                        were at least +{{ '%.2f'|format(j.givebacks.heat_r_threshold) }}R ahead at some point and did not finish there:
                    </div>
                    <ul class="text-xs text-slate-300 mt-2 space-y-1">
                        <li>· <span class="text-slate-400">{{ j.givebacks.scratched_runners }}</span> scratched on the ratchet (BE)</li>
                        <li>· <span class="text-slate-400">{{ j.givebacks.stopped_after_profit }}</span> gave the gain back and hit the stop</li>
                        <li>· <span class="text-slate-400">{{ j.givebacks.winners_with_heat }}</span> winners first ran ≥0.5R against</li>
                        <li>· peak unrealised (median) <span class="font-mono">{{ '%+.2f'|format(j.givebacks.left_on_table_r_median) if j.givebacks.left_on_table_r_median is not none else '—' }}R</span>;
                            sum of peaks <span class="font-mono">{{ '%+.2f'|format(j.givebacks.left_on_table_r_sum) if j.givebacks.left_on_table_r_sum is not none else '—' }}R</span></li>
                    </ul>
                    {% if j.givebacks.worst %}
                    <div class="text-[11px] text-slate-500 mt-2">Largest pages:
                        {% for w in j.givebacks.worst %}#{{ w.num }} {{ w.side }} {{ w.reason }} +{{ '%.2f'|format(w.mfe_r) }}R→{{ '%+.2f'|format(w.r or 0) }}R{% if not loop.last %} · {% endif %}{% endfor %}
                    </div>
                    {% endif %}
                    <div class="text-[11px] text-slate-500 mt-2">A scratch is not a mistake — the 0.75R ratchet exists because the 0.30R version converted +$222 of runs into $0. This panel shows the trade-off; it does not argue for removing it.</div>
                </div>
                <div class="rounded-2xl border border-slate-700 bg-slate-800 p-4">
                    <div class="text-sm font-semibold text-slate-200">What the risk layer blocked</div>
                    <div class="text-xs text-slate-300 mt-2">
                        {{ j.skips.n_24h }} full signals in the last {{ j.skips.hours }} h of the skip log:
                    </div>
                    <ul class="text-xs text-slate-300 mt-2 space-y-1">
                        {% for reason, count in j.skips.reasons_24h.items() %}
                        <li>· {{ reason }}: <span class="font-mono">{{ count }}</span></li>
                        {% else %}
                        <li>· none</li>
                        {% endfor %}
                    </ul>
                    {% if j.skips.last %}
                    <div class="text-[11px] text-slate-500 mt-2">last: {{ j.skips.last.Timestamp }} · {{ j.skips.last.Reason }} · ${{ j.skips.last.Price }}</div>
                    {% endif %}
                    <div class="text-[11px] text-slate-500 mt-2">skipped_trades.csv logs no side, so these are counts, not a success rate. The blocked-signal research is <span class="font-mono">tools/phantom_trades.py</span>.</div>
                </div>
            </div>

            {% if j.board %}
            {% set bd = j.board %}
            <div class="rounded-2xl border border-slate-700 bg-slate-800 p-4 mb-5">
                <div class="flex flex-col md:flex-row md:items-center gap-2">
                    <div class="text-sm font-semibold text-slate-200">🎯 Candidate indicators — measured on the bot's own entries</div>
                    <div class="text-[11px] text-slate-500 md:ml-auto">{{ bd.n_entries }} closed · {{ bd.n_decisive }} decisive · {{ bd.permutations }} permutations</div>
                </div>
                <div class="rounded-lg px-3 py-2 mt-2 text-xs {{ 'bg-emerald-950/30 text-emerald-200 border border-emerald-800' if bd.verdict.startswith('1 ') or bd.verdict.startswith('2 ') else 'bg-slate-900/60 text-slate-300 border border-slate-700' }}">
                    {{ bd.verdict }}
                </div>
                <div class="overflow-x-auto mt-3">
                <table class="w-full text-xs text-slate-300">
                    <thead class="text-slate-400"><tr>
                        <th class="text-left pb-1">candidate</th><th class="text-left pb-1">split</th>
                        <th class="text-right pb-1">high WR (dec)</th><th class="text-right pb-1">low WR (dec)</th>
                        <th class="text-right pb-1">lift</th><th class="text-left pb-1 pl-3">verdict</th>
                    </tr></thead>
                    <tbody>
                        {% for row in bd.rows %}
                        <tr class="border-t border-slate-700/60">
                            <td class="py-1 text-slate-300">{{ row.label }}</td>
                            <td class="py-1 text-slate-500">{{ row.high_label }} / {{ row.low_label }}</td>
                            <td class="py-1 text-right font-mono">{{ '%.1f'|format(row.high.wr) if row.high.wr is not none else '—' }}% ({{ row.high.decisive }})</td>
                            <td class="py-1 text-right font-mono">{{ '%.1f'|format(row.low.wr) if row.low.wr is not none else '—' }}% ({{ row.low.decisive }})</td>
                            <td class="py-1 text-right font-mono">{{ '%+.1f'|format(row.lift) if row.lift is not none else '—' }} pp</td>
                            <td class="py-1 pl-3 {% if row.verdict.startswith('candidate') %}text-emerald-300{% elif row.verdict.startswith('inside noise') %}text-slate-500{% else %}text-amber-300{% endif %}">{{ row.verdict }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
                </div>
                <div class="text-[11px] text-slate-500 mt-2">
                    Best lift <span class="font-mono">{{ '%+.1f'|format(bd.observed_max_lift_pp) if bd.observed_max_lift_pp is not none else '—' }} pp</span>
                    vs the 95th percentile of random-label best lifts
                    <span class="font-mono">{{ '%+.1f'|format(bd.null_max_lift_95_pp) if bd.null_max_lift_95_pp is not none else '—' }} pp</span>
                    (global p={{ '%.3f'|format(bd.p_global_wr) if bd.p_global_wr is not none else '—' }}).
                    A candidate that clears this still needs a dated pre-registration — no engine gate changes from a dashboard panel.
                </div>
                {% for sk in bd.skipped %}
                <div class="text-[11px] text-slate-500 mt-1">Not testable on this book: {{ sk.label }} — {{ sk.reason }}.</div>
                {% endfor %}
            </div>
            {% endif %}

            <div class="rounded-2xl border border-slate-700 bg-slate-900/60 p-4 mb-5 text-[11px] text-slate-500">
                Definitions: {{ j.definitions.decisive_wr }} · {{ j.definitions.all_in }} · {{ j.definitions.r }} · {{ j.definitions.net }} · {{ j.definitions.mfe_mae }}.
                Terminal: <span class="font-mono text-slate-400">python3 tools/journal_report.py</span> ·
                indicator measurement: <span class="font-mono text-slate-400">python3 tools/indicator_lab.py</span> ·
                method: <span class="font-mono text-slate-400">docs/ANALYSIS-2026-10-23-indicators-and-self-journal.md</span>.
                Display-only: no order, no write, no engine import.
            </div>
            {% else %}
            <div class="rounded-2xl border border-slate-700 bg-slate-800 p-5">
                <div class="text-lg font-semibold text-slate-200">📓 Journal unavailable</div>
                <div class="text-sm text-slate-400 mt-1">{{ ctx.journal.reason if ctx.journal else 'the read layer did not load' }}</div>
                <div class="text-xs text-slate-500 mt-2">This tab needs <span class="font-mono">trades.csv</span> and <span class="font-mono">forward_test_log.csv</span>; the other tabs are unaffected.</div>
            </div>
            {% endif %}
        </div>
        <!-- ================= END JOURNAL TAB ================= -->



        <!-- ================= DETAILS TAB (original dashboard) ================= -->
        <div id="panel-details" class="hidden">

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

        {% if ctx.outlook and ctx.outlook.ok %}
        {% set o = ctx.outlook %}{% set n = o.now %}
        <div class="bg-slate-800 p-4 rounded-xl border border-slate-700 mb-6">
            <div class="flex flex-wrap items-baseline justify-between gap-2 mb-2">
                <h3 class="text-sm font-semibold text-slate-200">🧭 Strong-signal outlook — where did signals like this go?</h3>
                <span class="text-[11px] text-slate-400">{{ o.era_label }} · n={{ o.n }} taken signals · median hold {{ "%.0f"|format(o.hold_median_min) }} min</span>
            </div>
            {% if n and n.ready_side %}
            <p class="text-xs text-slate-300 mb-2">
                <span class="font-semibold {{ 'text-emerald-400' if n.ready_side == 'BUY' else 'text-rose-400' }}">{{ n.ready_side }} passed all 8 gates on the last bar — very strong signal.</span>
                Entry <span class="font-mono">${{ "%.2f"|format(n.entry) }}</span> ·
                stop <span class="font-mono text-rose-300">${{ "%.2f"|format(n.stop) }}</span> ·
                target <span class="font-mono text-emerald-300">${{ "%.2f"|format(n.target) }}</span> ·
                risk <span class="font-mono">${{ "%.2f"|format(n.risk) }}</span>
            </p>
            <table class="w-full text-xs">
                <thead class="text-slate-500">
                    <tr><th class="text-left font-normal py-1">after</th><th class="text-right font-normal">historical median</th><th class="text-right font-normal">middle-50% cone</th><th class="text-right font-normal">closed {{ n.ready_side }}'s way</th><th class="text-right font-normal">target before stop</th></tr>
                </thead>
                <tbody class="divide-y divide-slate-700/70">
                    {% for a in n.applied %}
                    <tr>
                        <td class="py-1.5">+{{ a.horizon }}m</td>
                        <td class="py-1.5 text-right font-mono">${{ "%.2f"|format(a.cone_median) }}</td>
                        <td class="py-1.5 text-right font-mono">${{ "%.2f"|format(a.cone_lo) }}–${{ "%.2f"|format(a.cone_hi) }}</td>
                        <td class="py-1.5 text-right font-mono">{{ "%.0f"|format(a.fav_pct) }}% <span class="text-slate-500">[{{ "%.0f"|format(a.fav_ci[0]) }}–{{ "%.0f"|format(a.fav_ci[1]) }}] n={{ a.n }}</span></td>
                        <td class="py-1.5 text-right font-mono">{% if a.tp_first_pct is none %}—{% else %}{{ "%.0f"|format(a.tp_first_pct) }}%{% endif %}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <p class="text-xs text-slate-300 mb-2">
                No 8/8 signal on the last bar{% if n and n.passed %} (BUY {{ n.passed.BUY }}/{{ n.total.BUY }} · SELL {{ n.passed.SELL }}/{{ n.total.SELL }} gates){% endif %}.
                When one prints, this is what followed historically in the first {{ o.primary_horizon }} minutes:
            </p>
            <table class="w-full text-xs">
                <thead class="text-slate-500">
                    <tr><th class="text-left font-normal py-1">signal</th><th class="text-right font-normal">closed its way @{{ o.primary_horizon }}m</th><th class="text-right font-normal">median move</th><th class="text-right font-normal">target before stop</th><th class="text-right font-normal">n</th></tr>
                </thead>
                <tbody class="divide-y divide-slate-700/70">
                    {% for side in ["BUY", "SELL"] %}{% set c = o.primary[side] %}
                    <tr>
                        <td class="py-1.5 {{ 'text-emerald-400' if side == 'BUY' else 'text-rose-400' }}">{{ side }} 8/8</td>
                        <td class="py-1.5 text-right font-mono">{% if c.get("n") %}{{ "%.0f"|format(c.fav_pct) }}% <span class="text-slate-500">[{{ "%.0f"|format(c.fav_ci[0]) }}–{{ "%.0f"|format(c.fav_ci[1]) }}]</span>{% else %}—{% endif %}</td>
                        <td class="py-1.5 text-right font-mono">{% if c.get("n") %}{{ "%+.2f"|format(c.drift_r_median) }}R{% else %}—{% endif %}</td>
                        <td class="py-1.5 text-right font-mono">{% if c.get("tp_first_pct") is not none and c.get("tp_first_pct") is not undefined %}{{ "%.0f"|format(c.tp_first_pct) }}%{% else %}—{% endif %}</td>
                        <td class="py-1.5 text-right font-mono">{{ c.get("n", 0) }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% endif %}
            <p class="text-[11px] text-slate-500 mt-2 leading-snug">
                Past frequencies of this bot's own taken (8/8) signals — <span class="text-slate-300">not a forecast</span>.
                ~50% with a wide interval = a coin flip the sample cannot call; read the cone, not the median.
                “Target before stop” compares to {{ "%.0f"|format(o.barrier_reference_pct) }}%, not 50% — the target sits 1.5× further than the stop.
                Cone = historical drift in R × today's risk. Full table: <span class="font-mono">tools/signal_outlook.py</span> · verdict: <span class="font-mono">docs/ANALYSIS-2026-10-19-signal-outlook.md</span>
            </p>
        </div>
        {% elif ctx.outlook %}
        <div class="bg-slate-800/60 border border-slate-700 rounded-xl p-4 mb-6 text-sm text-slate-400">
            🧭 Strong-signal outlook unavailable — {{ ctx.outlook.reason }}
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
        </div>
        <!-- ================= END DETAILS TAB ================= -->

    </div>
    <script>
    var TABS = ['simple', 'chart', 'boxes', 'journal', 'details'];
    function showTab(name) {
        TABS.forEach(function(t) {
            var panel = document.getElementById('panel-' + t);
            var btn = document.getElementById('tab-' + t);
            if (!panel || !btn) return;
            if (t === name) {
                panel.classList.remove('hidden');
                btn.className = "px-4 py-2 rounded-t-lg text-sm font-semibold bg-amber-500 text-slate-900";
            } else {
                panel.classList.add('hidden');
                btn.className = "px-4 py-2 rounded-t-lg text-sm font-semibold bg-slate-800 text-slate-400 hover:bg-slate-700";
            }
        });
        try { localStorage.setItem('gold_tab', name); } catch(e) {}
    }
    (function() {
        var start = 'simple';
        try {
            var saved = localStorage.getItem('gold_tab');
            if (TABS.indexOf(saved) >= 0) start = saved;
        } catch(e) {}
        // Also allow ?tab=simple|chart|boxes|journal|details deep links
        try {
            var params = new URLSearchParams(window.location.search);
            var wanted = params.get('tab');
            if (TABS.indexOf(wanted) >= 0) start = wanted;
            // ?tf=N keeps the chart timeframe when a tab link is shared
            var tf = params.get('tf');
            if (tf && ['1','5','15'].indexOf(tf) >= 0) {
                document.querySelectorAll('a[href^="?tab=chart"]').forEach(function(a) {
                    a.setAttribute('href', '?tab=chart&tf=' + tf);
                });
            }
        } catch(e) {}
        showTab(start);
    })();
    </script>
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


_outlook_cache = {"key": None, "value": None, "at": 0.0}


def _outlook_base():
    """Cached era base rates for the outlook panel (full-log walk, 10-min cache)."""
    import time as _time
    key = (_file_key(LOG_FILE_PATH), _file_key(TRADES_FILE_PATH))
    now = _time.time()
    if _outlook_cache["value"] and (key == _outlook_cache["key"]
                                     or (now - _outlook_cache["at"]) < CALIBRATION_CACHE_SECONDS):
        return _outlook_cache["value"]
    try:
        value = PR.signal_outlook(PR.read_rows(LOG_FILE_PATH), PR.read_rows(TRADES_FILE_PATH))
    except Exception as exc:
        value = {"ok": False, "reason": f"outlook failed: {exc}"}
    _outlook_cache.update({"key": key, "value": value, "at": now})
    return value


def outlook_context(setup):
    """Strong-signal base rates + the cone applied to the last bar (display-only)."""
    if PR is None:
        return {"ok": False, "reason": f"pressure.py unavailable: {_PR_IMPORT_ERROR}"}
    base = _outlook_base()
    if not base.get("ok"):
        return base
    h = PR.OUTLOOK_PRIMARY_HORIZON
    return {"ok": True, "era_label": base["era_label"], "n": base["n"],
            "hold_median_min": base["hold_median_min"],
            "barrier_reference_pct": base["barrier_reference_pct"],
            "primary_horizon": h,
            "primary": {s: base["sides"][s]["horizons"].get(h, {}) for s in ("BUY", "SELL")},
            "now": PR.outlook_now(setup or {}, base)}


def pressure_context():
    """One read-only snapshot of the tape / gates / book / feed for the page."""
    if PR is None:
        return {"error": f"pressure.py unavailable: {_PR_IMPORT_ERROR}"}
    try:
        ctx = PR.build()
    except Exception as exc:
        return {"error": f"context build failed: {exc}"}
    ctx["calibration"] = calibration_context()
    ctx["outlook"] = outlook_context(ctx.get("setup"))
    return ctx


_box_cache = {"key": None, "geom": None, "regime": None}
_chart_cache = {"key": None, "group": None, "view": None}


def box_context(portfolio=None, feed=None):
    """Boxes + the condition checklist (display-only, cached geometry).

    Geometry and the tape regime (chop + frozen-box retest) are rebuilt only when
    the log file changes — both are pure functions of the tape. The checklist is
    live (session, cooldown, feed age) because those move minute to minute, and so
    is the Telegram preview, which is the same pressure.box_alert() decision the
    sidecar runs. Nothing here is an entry rule — see pressure.box_status.
    """
    if PR is None:
        return {"ok": False, "reason": f"pressure.py unavailable: {_PR_IMPORT_ERROR}"}
    key = _file_key(LOG_FILE_PATH)
    if _box_cache["geom"] is None or key != _box_cache["key"]:
        try:
            rows = PR.tail_rows(LOG_FILE_PATH, 9000, window_bytes=1024 * 1024)
            _box_cache["geom"] = PR.box_geometry(rows)
            _box_cache["regime"] = PR.box_regime(rows)
            _box_cache["key"] = key
        except Exception as exc:
            return {"ok": False, "reason": f"box geometry failed: {exc}"}
    try:
        return PR.box_status(_box_cache["geom"], portfolio=portfolio, feed=feed,
                             now=datetime.now(timezone.utc).replace(tzinfo=None),
                             regime=_box_cache["regime"])
    except Exception as exc:
        return {"ok": False, "reason": f"box status failed: {exc}"}


def chart_context(group=None, boxes_status=None):
    """The price chart + placement read for the Chart tab (display-only).

    Geo is rebuilt only when the log file or the timeframe changes; the cost
    ruler and the plan cards are cheap and always fresh. Nothing here can place,
    size or block a trade — it is the same contract as pressure.py.
    """
    if CH is None:
        return {"ok": False, "reason": f"chart.py unavailable: {_CH_IMPORT_ERROR}"}
    group = group if group in CH.GROUPS else CH.DEFAULT_GROUP
    key = _file_key(LOG_FILE_PATH)
    geometry = (boxes_status or {}).get("geometry") or {}

    def plan_for(boxes_status):
        """Placement cards built from the *tightest usable* box, via pressure.

        The geometry maths stays in pressure.box_watch_cards (the tested source);
        chart.pick_box only decides which box a stop can sensibly be built on and
        says what it skipped. Narrowing the geometry is the whole trick: calling
        the same function with one box keeps both tabs from disagreeing.
        """
        if not geometry.get("ok"):
            return [], None, None
        chosen, note = CH.pick_box(geometry.get("boxes"), geometry.get("close"),
                                   geometry.get("atr"))
        if chosen is None:
            return [], note, None
        sub = dict(geometry)
        sub["boxes"] = [chosen]
        sub["nearest"] = {"box": chosen["name"],
                          "side": "BUY" if (chosen.get("dist_up_atr") or 0) <= (chosen.get("dist_down_atr") or 0) else "SELL",
                          "edge": chosen["high"] if (chosen.get("dist_up_atr") or 0) <= (chosen.get("dist_down_atr") or 0) else chosen["low"],
                          "distance_usd": min(abs(chosen.get("dist_up_usd") or 0),
                                              abs(chosen.get("dist_down_usd") or 0)),
                          "distance_atr": min(abs(chosen.get("dist_up_atr") or 0),
                                              abs(chosen.get("dist_down_atr") or 0)),
                          "width": chosen.get("width")}
        # A live break on a *different* box must not be relabelled as a break here.
        trig = dict(geometry.get("trigger") or {})
        if trig.get("box") != chosen["name"]:
            trig = {"state": "none", "side": None, "box": chosen["name"],
                    "detail": f"no edge tested on the last bar ({chosen['name']})"}
        sub["trigger"] = trig
        try:
            cards = PR.box_watch_cards(sub, (boxes_status or {}).get("checks") or [],
                                       datetime.now(timezone.utc).replace(tzinfo=None))
        except Exception:
            cards = []
        return cards, note, chosen["name"]
    if (_chart_cache["view"] is None or key != _chart_cache["key"]
            or group != _chart_cache["group"]):
        try:
            rows = PR.tail_rows(LOG_FILE_PATH, 4000, window_bytes=1024 * 1024)
            _chart_cache["view"] = CH.view(rows=rows, boxes=geometry.get("boxes"),
                                           group=group)
            _chart_cache["key"] = key
            _chart_cache["group"] = group
        except Exception as exc:
            return {"ok": False, "reason": f"chart build failed: {exc}"}
    view = _chart_cache["view"]
    try:
        atr = view.get("atr") or geometry.get("atr")
        cards, box_note, box_name = plan_for(boxes_status)
        return {
            "ok": bool(view.get("ok")),
            "reason": view.get("reason"),
            "view": view,
            "group": group,
            "groups": CH.GROUPS,
            "cost": CH.cost_ruler(atr),
            "plan": CH.plan_cards(cards, atr=atr),
            "plan_box": box_name,
            "box_note": box_note,
            "verdict": CH.plain_verdict(boxes_status),
            "how_to_read": CH.HOW_TO_READ,
            "spread_usd": (boxes_status or {}).get("spread_usd"),
        }
    except Exception as exc:
        return {"ok": False, "reason": f"chart read failed: {exc}"}


_journal_cache = {"trades_key": None, "at": 0.0, "report": None}


def journal_context(status=None, log_tail=None):
    """The self-journal read for the 📓 tab (display-only, cached ~2 min).

    The expensive part (join 695 ledger rows to 50k bars, compute 17 candidate
    series, run the permutation guard) is rebuilt only when a trade closes or
    the cache ages out. The open trade and the skip counts are refreshed on
    every request because they are cheap and move minute to minute.
    """
    if JN is None:
        return {"ok": False, "reason": f"journal.py unavailable: {_JN_IMPORT_ERROR}"}
    if PR is None:
        return {"ok": False, "reason": "journal needs pressure.py for the shared parsers"}
    import time as _time
    now = _time.time()
    key = _file_key(TRADES_FILE_PATH)
    cached = _journal_cache["report"]
    fresh = (cached is not None and key == _journal_cache["trades_key"]
             and (now - _journal_cache["at"]) < JOURNAL_CACHE_SECONDS)
    if not fresh:
        try:
            report = JN.build(PR.read_rows(LOG_FILE_PATH), PR.read_rows(TRADES_FILE_PATH),
                              None,
                              PR.read_rows(SKIP_FILE_PATH) if os.path.isfile(SKIP_FILE_PATH) else [],
                              cost=JN.COST_USD, permutations=0)
            scored = [e for e in report["entries"] if e["era"] == "struct-stop"]
            report["board"] = JN.indicator_board(scored, permutations=JOURNAL_PERMUTATIONS)
            _journal_cache.update({"trades_key": key, "at": now, "report": report})
            cached = report
        except Exception as exc:
            return {"ok": False, "reason": f"journal build failed: {exc}"}
    report = dict(cached)
    try:
        report["skips"] = JN.skips(PR.read_rows(SKIP_FILE_PATH) if os.path.isfile(SKIP_FILE_PATH) else [])
    except Exception:
        pass
    price = None
    for row in (log_tail or []):          # newest first from the page's tail read
        price = PR.parse_float(row.get("Close"))
        if price:
            break
    try:
        report["open"] = JN.open_entry(report.get("series"), status or {}, JN.COST_USD, price=price)
    except Exception:
        report["open"] = None
    return JN.dashboard_view(report)


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
    chart_tf = None
    try:
        chart_tf = int(request.args.get("tf") or 0) or None
    except (TypeError, ValueError):
        chart_tf = None
    if PR and not ctx.get("error"):
        ctx["boxes"] = box_context(ctx.get("portfolio"), ctx.get("feed"))
        ctx["chart"] = chart_context(chart_tf, ctx.get("boxes"))
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        quotes = PR.tail_rows(os.path.join(DATA_DIR, "xm_data", "quotes-" + now.strftime("%Y-%m-%d") + ".csv"), 240)
        ctx["risk_now"] = PR.risk_read(status, quotes, now)
        # Simple tab: volatility guard + plain-English summary (display-only, never a gate)
        try:
            # ATR median needs the raw tail; reuse the rows we already have plus a longer tail for median
            log_tail_60 = PR.tail_rows(LOG_FILE_PATH, 400)
            ctx["volatility"] = PR.volatility_guard(
                log_rows=log_tail_60,
                portfolio=ctx.get("portfolio"),
                feed=ctx.get("feed"),
                risk=ctx.get("risk_now"),
                mkt=ctx.get("map"),
                setup=ctx.get("setup"),
                now=now,
            )
            ctx["simple"] = PR.simple_summary(status, ctx, ctx["volatility"], now)
        except Exception as exc:
            ctx["volatility"] = {"verdict": "unknown", "label": "Check unavailable", "icon": "❓", "headline": f"Simple summary failed: {exc}", "sub": "", "action": "", "factors": [], "counts": {"red":0,"amber":0,"green":0}, "volatile": False, "should_avoid": False, "as_of": ""}
            ctx["simple"] = {"mode": "paper", "equity": status.get("equity"), "market_sentences": [f"Simple summary failed: {exc}"], "bot_next": "—", "today_line": "—", "human_tip": "—", "stale_note": None, "as_of": ""}
    try:
        ctx["journal"] = journal_context(status, recent_rows)
    except Exception as exc:
        ctx["journal"] = {"ok": False, "reason": f"journal context failed: {exc}"}
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
