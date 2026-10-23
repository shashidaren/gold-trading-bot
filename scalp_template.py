"""HTML for the separate manual scalping workspace.

Template only: no market, account, engine, or journal I/O lives here.  Keeping
it separate from dashboard.py's auto-refreshing bot page also means an editing
manual ticket is not refreshed out from under the operator.
"""

SCALP_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Manual Scalping · Gold Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-950 text-slate-100 p-4 md:p-6">
<div class="max-w-7xl mx-auto">
    <header class="flex flex-col lg:flex-row lg:items-center justify-between gap-4 border-b border-slate-800 pb-5 mb-5">
        <div>
            <div class="text-xs text-slate-500 mb-1"><a href="/" class="hover:text-amber-300">← Gold Engine Dashboard</a> / manual workspace</div>
            <h1 class="text-2xl md:text-3xl font-bold text-amber-400">⚡ Manual Scalping</h1>
            <p class="text-sm text-slate-400 mt-1">M5 structure · optional M1 timing · costed risk · a separate self-reported journal</p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
            <span class="px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-900 text-xs text-slate-300">No order placement</span>
            <a href="/scalp?tf={{ tf }}" class="px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-xs font-semibold hover:bg-slate-700">↻ Refresh market data</a>
        </div>
    </header>

    {% if error %}
    <div role="alert" class="rounded-xl border border-rose-700 bg-rose-950/40 text-rose-200 p-4 mb-5 text-sm">
        <span class="font-semibold">Not recorded:</span> {{ error }} Your entries are still below so you can correct them.
    </div>
    {% endif %}
    {% if notice %}
    <div role="status" class="rounded-xl border border-emerald-700 bg-emerald-950/30 text-emerald-200 p-4 mb-5 text-sm">{{ notice }}</div>
    {% endif %}

    <div class="rounded-xl border border-amber-800/70 bg-amber-950/20 p-4 mb-5 text-xs text-amber-100/90 leading-relaxed">
        <span class="font-bold text-amber-300">Record, not execute.</span> This page never sends a trade to a broker.
        “Record externally taken” only journals what you say you did elsewhere. The bot’s engine, open position,
        <span class="font-mono">trades.csv</span> and equity are untouched. Levels are references, not forecasts; no manual scalping edge has been validated.
        This page deliberately has <span class="font-semibold">no auto-refresh</span>, so it cannot erase a ticket while you edit it.
    </div>

    {% if chart and chart.ok %}
    {% set c = chart %}
    {% set v = chart.view %}

    <!-- Market context -->
    <section id="market" class="rounded-2xl border border-slate-700 bg-slate-900/60 p-4 mb-5">
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
            <div class="rounded-xl bg-slate-800 border border-slate-700 p-3"><div class="text-[11px] text-slate-500">Last logged close</div><div class="font-mono text-xl mt-1">${{ "%.2f"|format(v.close) }}</div></div>
            <div class="rounded-xl bg-slate-800 border border-slate-700 p-3"><div class="text-[11px] text-slate-500">ATR</div><div class="font-mono text-xl mt-1">${{ "%.2f"|format(v.atr or 0) }}</div></div>
            <div class="rounded-xl bg-slate-800 border border-slate-700 p-3"><div class="text-[11px] text-slate-500">Cost model</div><div class="font-mono text-xl mt-1">${{ "%.2f"|format(boxes.spread_usd or 0.55) }}<span class="text-xs text-slate-500"> round trip</span></div></div>
            <div class="rounded-xl bg-slate-800 border border-slate-700 p-3"><div class="text-[11px] text-slate-500">Last bar (UTC)</div><div class="font-mono text-sm mt-2">{{ v.as_of }}</div></div>
        </div>
        <div class="flex flex-wrap gap-2">
            {% for check in boxes.checks if check.key in ['feed', 'session', 'risk_state', 'volatility', 'tape'] %}
            <div title="{{ check.detail }}" class="rounded-lg border px-3 py-2 text-xs
                {% if check.state == 'pass' %}border-emerald-800 bg-emerald-950/20 text-emerald-200
                {% elif check.state == 'fail' %}border-rose-800 bg-rose-950/20 text-rose-200
                {% elif check.state == 'warn' %}border-amber-800 bg-amber-950/20 text-amber-200
                {% else %}border-slate-700 bg-slate-800 text-slate-400{% endif %}">
                <span class="font-semibold">{{ check.label }}</span> · {{ check.state|upper }}
            </div>
            {% endfor %}
        </div>
        <p class="text-[11px] text-slate-500 mt-3">Hover a badge for detail. Feed/session/risk/volatility are current context; they do not approve your ticket. Your own stop, target and cost geometry are checked separately below.</p>
    </section>

    <!-- Shared chart read, separate non-refreshing page -->
    <section class="rounded-2xl border border-slate-700 bg-slate-900/60 p-4 mb-5">
        <div class="flex flex-wrap items-center gap-2 mb-3">
            <div class="mr-auto">
                <h2 class="text-sm font-semibold text-slate-200">Price and structural levels</h2>
                <p class="text-[11px] text-slate-500">Default M5 for structure; M1 is timing detail, not a signal.</p>
            </div>
            {% for g in chart.groups %}
            <a href="/scalp?tf={{ g }}" class="px-2.5 py-1 rounded text-[11px] font-semibold border
                {% if g == chart.group %}bg-amber-500 text-slate-900 border-amber-500{% else %}bg-slate-800 text-slate-400 border-slate-700 hover:bg-slate-700{% endif %}">M{{ g }}</a>
            {% endfor %}
        </div>
        <svg viewBox="0 0 {{ v.width }} {{ v.height }}" class="w-full h-auto" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Gold price chart with box levels and session shading">
            <rect x="0" y="0" width="{{ v.width }}" height="{{ v.height }}" fill="#0f172a"/>
            {% for b in v.bands %}
            <rect x="{{ b.x0 }}" y="{{ v.plot.t }}" width="{{ b.w }}" height="{{ v.plot.h }}" fill="{% if b.session == 'Asia' %}#334155{% elif b.session == 'London' %}#3730a3{% elif b.session == 'New York' %}#065f46{% else %}#78350f{% endif %}" opacity="0.30"/>
            {% if b.blackout %}<rect x="{{ b.x0 }}" y="{{ v.plot.t }}" width="{{ b.w }}" height="{{ v.plot.h }}" fill="#ef4444" opacity="{{ '0.18' if b.blackout == 'both' else '0.09' }}"/>{% endif %}
            {% endfor %}
            {% for t in v.ticks %}
            <line x1="{{ v.plot.l }}" x2="{{ v.plot.l + v.plot.w }}" y1="{{ t.y }}" y2="{{ t.y }}" stroke="#334155" stroke-width="0.5" stroke-dasharray="2 5"/>
            <text x="{{ v.plot.l + v.plot.w + 6 }}" y="{{ t.y + 3 }}" fill="#64748b" font-size="9" font-family="ui-monospace,monospace">{{ t.label }}</text>
            {% endfor %}
            {% for k in v.candles %}
            <line x1="{{ k.cx }}" x2="{{ k.cx }}" y1="{{ k.y_high }}" y2="{{ k.y_low }}" stroke="{% if k.up %}#34d399{% else %}#fb7185{% endif %}" stroke-width="0.9" opacity="{{ '0.4' if k.partial else '0.95' }}"/>
            <rect x="{{ k.bx }}" y="{{ k.y_top }}" width="{{ k.w }}" height="{{ k.body_h }}" fill="{% if k.up %}#34d399{% else %}#fb7185{% endif %}" opacity="{{ '0.4' if k.partial else '0.95' }}"/>
            {% endfor %}
            {% for l in v.levels if l.in_range %}
            <line x1="{{ v.plot.l }}" x2="{{ v.plot.l + v.plot.w }}" y1="{{ l.y }}" y2="{{ l.y }}" stroke="{% if l.kind == 'engine' %}#fbbf24{% elif l.kind == 'day' %}#22d3ee{% else %}#94a3b8{% endif %}" stroke-width="{{ '1.3' if l.kind == 'engine' else '0.8' }}" stroke-dasharray="{% if l.kind == 'engine' %}none{% elif l.kind == 'day' %}1 3{% else %}5 4{% endif %}" opacity="{{ '0.9' if l.kind == 'engine' else '0.6' }}"/>
            <text x="{{ v.plot.l + 4 }}" y="{{ l.y - 3 }}" fill="{% if l.kind == 'engine' %}#fbbf24{% elif l.kind == 'day' %}#67e8f9{% else %}#94a3b8{% endif %}" font-size="8.5" font-family="ui-monospace,monospace">{{ l.label }} {{ "%.2f"|format(l.price) }}</text>
            {% endfor %}
            <line x1="{{ v.plot.l }}" x2="{{ v.plot.l + v.plot.w }}" y1="{{ v.close_y }}" y2="{{ v.close_y }}" stroke="#e2e8f0" stroke-width="0.6" stroke-dasharray="1 3" opacity="0.5"/>
            <rect x="{{ v.plot.l + v.plot.w + 2 }}" y="{{ v.close_y - 6 }}" width="84" height="12" rx="2" fill="#e2e8f0"/>
            <text x="{{ v.plot.l + v.plot.w + 5 }}" y="{{ v.close_y + 3 }}" fill="#0f172a" font-size="8.5" font-weight="bold" font-family="ui-monospace,monospace">{{ "%.2f"|format(v.close) }}</text>
            {% for l in v.levels if not l.in_range %}
            <text x="{{ v.plot.l + 4 }}" y="{{ 10 if l.offscreen_above else v.height - 12 }}" fill="#67e8f9" font-size="8.5" opacity="0.75" font-family="ui-monospace,monospace">{{ '↑' if l.offscreen_above else '↓' }} {{ l.label }} {{ "%.2f"|format(l.price) }} (outside view)</text>
            {% endfor %}
            {% for t in v.times %}<text x="{{ t.x }}" y="{{ v.height - 3 }}" fill="#64748b" font-size="9" text-anchor="middle" font-family="ui-monospace,monospace">{{ t.label }}</text>{% endfor %}
        </svg>
        <div class="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-[11px] text-slate-400">
            <span><span class="text-amber-400">━━</span> 20-bar level</span><span><span class="text-slate-400">╌╌</span> 1h / 4h box</span><span><span class="text-cyan-400">┈┈</span> prior-day high/low</span><span><span class="inline-block w-2 h-3 bg-rose-800/60"></span> blackout / stand aside</span>
        </div>
        <p class="text-[11px] text-slate-500 mt-2">Broker demo GOLD feed, not spot XAUUSD; levels will not match TradingView tick-for-tick. The right-most candle can still be forming. Use the refresh link only when you are not editing a ticket.</p>
    </section>

    <div class="grid grid-cols-1 xl:grid-cols-3 gap-5 mb-6">
        <!-- Ticket + calculator -->
        <section id="ticket" class="xl:col-span-2 rounded-2xl border border-slate-700 bg-slate-900/70 p-4 md:p-5">
            <div class="flex items-start justify-between gap-3">
                <div><h2 class="text-lg font-semibold">Risk ticket</h2><p class="text-xs text-slate-500 mt-1">Editable arithmetic, not an entry recommendation.</p></div>
                <span class="text-[10px] px-2 py-1 rounded bg-slate-800 border border-slate-700 text-slate-400">server recalculates on save</span>
            </div>
            <form id="scalp-ticket" method="post" action="/scalp/journal" class="mt-4">
                <input type="hidden" name="timeframe" id="timeframe" value="{{ form.timeframe }}">
                <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <label class="text-xs text-slate-400">Side
                        <select name="side" id="side" class="mt-1 w-full rounded-lg bg-slate-800 border border-slate-600 px-3 py-2 text-sm text-slate-100">
                            <option value="BUY" {% if form.side == 'BUY' %}selected{% endif %}>BUY</option><option value="SELL" {% if form.side == 'SELL' %}selected{% endif %}>SELL</option>
                        </select>
                    </label>
                    <label class="text-xs text-slate-400">Entry
                        <input required name="entry" id="entry" value="{{ form.entry }}" inputmode="decimal" type="number" min="0" step="0.01" class="mt-1 w-full rounded-lg bg-slate-800 border border-slate-600 px-3 py-2 text-sm font-mono">
                    </label>
                    <label class="text-xs text-slate-400">Stop
                        <input required name="stop" id="stop" value="{{ form.stop }}" inputmode="decimal" type="number" min="0" step="0.01" class="mt-1 w-full rounded-lg bg-slate-800 border border-rose-800 px-3 py-2 text-sm font-mono">
                    </label>
                    <label class="text-xs text-slate-400">Target
                        <input required name="target" id="target" value="{{ form.target }}" inputmode="decimal" type="number" min="0" step="0.01" class="mt-1 w-full rounded-lg bg-slate-800 border border-emerald-800 px-3 py-2 text-sm font-mono">
                    </label>
                    <label class="text-xs text-slate-400">Account balance ($)
                        <input required name="account_balance" id="account_balance" value="{{ form.account_balance }}" inputmode="decimal" type="number" min="0" step="0.01" class="mt-1 w-full rounded-lg bg-slate-800 border border-slate-600 px-3 py-2 text-sm font-mono">
                    </label>
                    <label class="text-xs text-slate-400">Cash risk (%)
                        <input required name="risk_pct" id="risk_pct" value="{{ form.risk_pct }}" inputmode="decimal" type="number" min="0" max="100" step="0.05" class="mt-1 w-full rounded-lg bg-slate-800 border border-slate-600 px-3 py-2 text-sm font-mono">
                    </label>
                    <label class="text-xs text-slate-400">Round-trip spread ($/oz)
                        <input required name="spread" id="spread" value="{{ form.spread }}" inputmode="decimal" type="number" min="0" step="0.01" class="mt-1 w-full rounded-lg bg-slate-800 border border-slate-600 px-3 py-2 text-sm font-mono">
                    </label>
                    <div class="text-xs text-slate-400">Chart timeframe
                        <div class="mt-1 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm text-slate-300">M{{ chart.group }} <span class="text-[10px] text-slate-500">(journal tag)</span></div>
                    </div>
                </div>
                <details class="mt-3 rounded-lg border border-slate-800 bg-slate-950/40 p-3">
                    <summary class="cursor-pointer text-xs text-slate-400">Contract settings — verify against your broker</summary>
                    <div class="grid grid-cols-2 gap-3 mt-3">
                        <label class="text-xs text-slate-400">Oz per 1.00 lot
                            <input required name="contract_size" id="contract_size" value="{{ form.contract_size }}" type="number" min="0" step="1" class="mt-1 w-full rounded-lg bg-slate-800 border border-slate-600 px-3 py-2 text-sm font-mono">
                        </label>
                        <label class="text-xs text-slate-400">Volume step (lots)
                            <input required name="volume_step" id="volume_step" value="{{ form.volume_step }}" type="number" min="0" step="0.01" class="mt-1 w-full rounded-lg bg-slate-800 border border-slate-600 px-3 py-2 text-sm font-mono">
                        </label>
                    </div>
                    <p class="text-[11px] text-slate-500 mt-2">Defaults are GOLD Standard: 100 oz/lot and 0.01-lot steps. GOLDmicro can differ. The calculator is not connected to your broker specification.</p>
                </details>

                <div id="calc-error" role="alert" class="hidden mt-4 rounded-lg border border-rose-800 bg-rose-950/30 p-3 text-xs text-rose-200"></div>
                <div class="grid grid-cols-2 md:grid-cols-4 gap-2 mt-4" aria-live="polite">
                    <div class="rounded-lg bg-slate-800 border border-slate-700 p-3"><div class="text-[10px] text-slate-500">STOP / REWARD (gross)</div><div id="calc-legs" class="font-mono text-xs mt-1">—</div></div>
                    <div class="rounded-lg bg-slate-800 border border-slate-700 p-3"><div class="text-[10px] text-slate-500">COSTED R:R</div><div id="calc-rr" class="font-mono text-lg mt-0.5">—</div><div id="calc-cost" class="text-[10px] text-slate-500">—</div></div>
                    <div class="rounded-lg bg-slate-800 border border-slate-700 p-3"><div class="text-[10px] text-slate-500">SIZE (rounded down)</div><div id="calc-lots" class="font-mono text-lg mt-0.5">—</div><div id="calc-budget" class="text-[10px] text-slate-500">—</div></div>
                    <div class="rounded-lg bg-slate-800 border border-slate-700 p-3"><div class="text-[10px] text-slate-500">PLANNED NET RISK / REWARD</div><div id="calc-money" class="font-mono text-xs mt-1">—</div><div id="calc-be" class="text-[10px] text-slate-500">—</div></div>
                </div>
                <ul id="calc-warnings" class="mt-3 space-y-1 text-xs text-amber-200"></ul>
                <p class="text-[11px] text-slate-500 mt-3">Cost convention: spread is added to the stop leg and subtracted from the reward leg. Slippage, commission and swap are not included. Net R:R below 1:1 or spread above 10% of stop distance is a warning, not a prediction.</p>

                <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
                    <label class="text-xs text-slate-400">Setup / reason <span class="text-rose-300">required</span>
                        <input required name="setup" value="{{ form.setup }}" maxlength="160" placeholder="e.g. M5 edge retest — or why skipped" class="mt-1 w-full rounded-lg bg-slate-800 border border-slate-600 px-3 py-2 text-sm">
                    </label>
                    <label class="text-xs text-slate-400">Notes (optional)
                        <input name="notes" value="{{ form.notes }}" maxlength="2000" placeholder="What did you actually see?" class="mt-1 w-full rounded-lg bg-slate-800 border border-slate-600 px-3 py-2 text-sm">
                    </label>
                </div>
                <div class="flex flex-col md:flex-row gap-3 mt-4">
                    <button type="submit" name="decision" value="skipped" class="flex-1 rounded-lg border border-slate-600 bg-slate-800 hover:bg-slate-700 px-4 py-2.5 text-sm font-semibold text-slate-200">Log skipped idea</button>
                    <button type="submit" name="decision" value="taken" onclick="return confirm('Record a self-reported external trade? This will NOT place an order.')" class="flex-1 rounded-lg border border-amber-600 bg-amber-500 hover:bg-amber-400 px-4 py-2.5 text-sm font-semibold text-slate-950">Record externally taken</button>
                </div>
                <p class="text-[11px] text-slate-500 mt-2">Both buttons only write the separate manual journal. “Taken” creates an OPEN journal row; it does not mean this dashboard opened a broker position.</p>
            </form>
        </section>

        <!-- Existing reference geometry -->
        <aside class="rounded-2xl border border-slate-700 bg-slate-900/70 p-4 md:p-5">
            <h2 class="text-lg font-semibold">Reference geometry</h2>
            <p class="text-xs text-slate-500 mt-1">Copied from Chart &amp; Placement. A SKIP reference stays a SKIP when copied.</p>
            <div class="space-y-3 mt-4">
                {% for card in chart.plan %}
                <div class="rounded-xl border p-3 {% if card.verdict == 'skip' %}border-rose-800 bg-rose-950/20{% elif card.verdict == 'watch' %}border-amber-800 bg-amber-950/20{% else %}border-emerald-800 bg-emerald-950/20{% endif %}">
                    <div class="flex items-center justify-between gap-2"><span class="font-bold text-sm {% if card.side == 'BUY' %}text-emerald-300{% else %}text-rose-300{% endif %}">{{ card.side }}</span><span class="text-[10px] font-semibold">{{ card.verdict_text }}</span></div>
                    <div class="font-mono text-[11px] text-slate-300 mt-2">E ${{ "%.2f"|format(card.entry or 0) }} · S ${{ "%.2f"|format(card.stop or 0) }} · T ${{ "%.2f"|format(card.target or 0) }}</div>
                    <div class="text-[11px] text-slate-500 mt-1">costed {{ "%.2f"|format(card.rr or 0) }}:1 · spread {{ "%.0f"|format(card.cost_pct or 0) }}% of R</div>
                    <button type="button" onclick="useReference('{{ card.side }}')" class="mt-3 w-full rounded-lg border border-slate-600 bg-slate-800 hover:bg-slate-700 px-3 py-2 text-xs font-semibold">Copy {{ card.side }} numbers to calculator</button>
                </div>
                {% else %}
                <p class="text-xs text-slate-500">No reference cards are available. You can still use the calculator with your own structural levels.</p>
                {% endfor %}
            </div>
            <div class="rounded-xl border border-slate-800 bg-slate-950/50 p-3 mt-4 text-[11px] text-slate-500 leading-relaxed">
                <span class="text-slate-300 font-semibold">Before recording “taken”:</span> check actual bid/ask spread, contract size and stop/target at your broker. The dashboard uses logged bars and an assumed cost, not an executable quote.
            </div>
        </aside>
    </div>
    {% else %}
    <div class="rounded-2xl border border-rose-800 bg-rose-950/20 p-5 mb-6"><h2 class="font-semibold text-rose-200">Market read unavailable</h2><p class="text-sm text-slate-400 mt-1">{{ chart.reason if chart else 'The chart read layer did not load.' }} The journal below remains available; do not rely on stale levels.</p></div>
    {% endif %}

    <!-- Separate manual journal -->
    <section id="journal" class="rounded-2xl border border-slate-700 bg-slate-900/70 p-4 md:p-5">
        <div class="flex flex-col md:flex-row md:items-start justify-between gap-3">
            <div><h2 class="text-lg font-semibold">📓 Manual decision journal</h2><p class="text-xs text-slate-500 mt-1">Self-reported, separate from the bot ledger, and never broker-verified.</p></div>
            <span class="text-[10px] font-mono text-slate-500">manual_scalp_journal.json · host-local</span>
        </div>
        {% if journal_error %}
        <div role="alert" class="mt-4 rounded-lg border border-rose-800 bg-rose-950/30 p-4 text-sm text-rose-200">Journal read failed: {{ journal_error }} No rows or zero totals are inferred, and the file has not been reset.</div>
        {% else %}
        {% set s = journal.summary %}
        <div class="grid grid-cols-2 md:grid-cols-5 gap-2 mt-4">
            <div class="rounded-lg border border-slate-700 bg-slate-800 p-3"><div class="text-[10px] text-slate-500">OPEN ROWS</div><div class="text-xl font-mono mt-1">{{ s.open }}</div></div>
            <div class="rounded-lg border border-slate-700 bg-slate-800 p-3"><div class="text-[10px] text-slate-500">SKIPPED IDEAS</div><div class="text-xl font-mono mt-1">{{ s.skipped }}</div></div>
            <div class="rounded-lg border border-slate-700 bg-slate-800 p-3"><div class="text-[10px] text-slate-500">CLOSED OUTCOMES</div><div class="text-xl font-mono mt-1">{{ s.closed }}</div></div>
            <div class="rounded-lg border border-slate-700 bg-slate-800 p-3"><div class="text-[10px] text-slate-500">NET P&amp;L (self-reported)</div><div class="text-xl font-mono mt-1 {% if s.net_pnl > 0 %}text-emerald-300{% elif s.net_pnl < 0 %}text-rose-300{% endif %}">{{ "%+.2f"|format(s.net_pnl) }}</div></div>
            <div class="rounded-lg border border-slate-700 bg-slate-800 p-3"><div class="text-[10px] text-slate-500">AVERAGE R</div><div class="text-xl font-mono mt-1">{% if s.average_r is not none %}{{ "%+.2f"|format(s.average_r) }}R{% else %}—{% endif %}</div></div>
        </div>
        <p class="text-[11px] text-slate-500 mt-3">Do not judge a method from a handful of outcomes. The existing review bar is at least 100 closed manual trades with positive expectancy after measured costs; {{ s.review_remaining }} more closed outcomes remain before that count is reached. Skipped ideas are useful discipline records but do not count as trades.</p>
        <div class="space-y-3 mt-5">
            {% for row in journal.rows %}
            <article class="rounded-xl border border-slate-700 bg-slate-950/40 p-4">
                <div class="flex flex-col md:flex-row md:items-center justify-between gap-2">
                    <div class="flex flex-wrap items-center gap-2">
                        <span class="font-bold text-sm {% if row.side == 'BUY' %}text-emerald-300{% else %}text-rose-300{% endif %}">{{ row.side }}</span>
                        <span class="px-2 py-0.5 rounded text-[10px] font-bold {% if row.status == 'OPEN' %}bg-amber-900/60 text-amber-200{% elif row.status == 'CLOSED' %}bg-slate-700 text-slate-200{% else %}bg-slate-800 text-slate-400{% endif %}">{{ row.status }}</span>
                        <span class="text-[11px] text-slate-500">{{ row.timeframe }} · {{ row.created_utc }}</span>
                    </div>
                    <span class="text-[10px] font-mono text-slate-600">#{{ row.id }}</span>
                </div>
                <p class="text-sm text-slate-200 mt-2">{{ row.setup }}</p>
                {% if row.notes %}<p class="text-xs text-slate-500 mt-1">{{ row.notes }}</p>{% endif %}
                <div class="grid grid-cols-2 md:grid-cols-6 gap-2 mt-3 text-[11px]">
                    <div><span class="text-slate-500 block">Entry</span><span class="font-mono">${{ "%.2f"|format(row.entry) }}</span></div>
                    <div><span class="text-slate-500 block">Stop</span><span class="font-mono text-rose-300">${{ "%.2f"|format(row.stop) }}</span></div>
                    <div><span class="text-slate-500 block">Target</span><span class="font-mono text-emerald-300">${{ "%.2f"|format(row.target) }}</span></div>
                    <div><span class="text-slate-500 block">Lots</span><span class="font-mono">{{ "%.2f"|format(row.lots) }}</span></div>
                    <div><span class="text-slate-500 block">Costed R:R</span><span class="font-mono">{{ "%.2f"|format(row.net_rr) }}:1</span></div>
                    <div><span class="text-slate-500 block">Planned net risk</span><span class="font-mono">${{ "%.2f"|format(row.planned_risk_usd) }}</span></div>
                </div>
                {% if row.warnings %}<ul class="mt-2 text-[11px] text-amber-300/90">{% for warning in row.warnings %}<li>⚠ {{ warning }}</li>{% endfor %}</ul>{% endif %}

                {% if row.status == 'OPEN' %}
                <form method="post" action="/scalp/journal/{{ row.id }}/close" class="mt-4 rounded-lg border border-slate-700 bg-slate-900/70 p-3">
                    <input type="hidden" name="timeframe" value="{{ tf }}">
                    <div class="text-xs font-semibold text-slate-300 mb-2">Record the external close — this does not close a broker position</div>
                    <div class="grid grid-cols-1 md:grid-cols-5 gap-2">
                        <label class="text-[11px] text-slate-500">Exit price<input required name="exit_price" type="number" min="0" step="0.01" class="mt-1 w-full rounded bg-slate-800 border border-slate-600 px-2 py-1.5 text-xs font-mono text-slate-100"></label>
                        <label class="text-[11px] text-slate-500">Exit reason<select name="exit_reason" class="mt-1 w-full rounded bg-slate-800 border border-slate-600 px-2 py-1.5 text-xs text-slate-100"><option>MANUAL</option><option>SL</option><option>TP</option><option>SCRATCH</option><option>TIME</option></select></label>
                        <label class="text-[11px] text-slate-500 md:col-span-2">Close notes<input name="close_notes" maxlength="2000" class="mt-1 w-full rounded bg-slate-800 border border-slate-600 px-2 py-1.5 text-xs text-slate-100"></label>
                        <button type="submit" class="self-end rounded bg-slate-700 hover:bg-slate-600 border border-slate-600 px-3 py-2 text-xs font-semibold">Record close</button>
                    </div>
                </form>
                {% elif row.status == 'CLOSED' %}
                <div class="mt-3 rounded-lg border border-slate-800 bg-slate-900/60 p-3 text-xs">
                    <span class="text-slate-400">Exit {{ "%.2f"|format(row.exit_price) }} · {{ row.exit_reason }} · {{ row.closed_utc }}</span>
                    <span class="ml-2 font-mono {% if row.net_pnl > 0 %}text-emerald-300{% elif row.net_pnl < 0 %}text-rose-300{% else %}text-slate-300{% endif %}">net {{ "%+.2f"|format(row.net_pnl) }} · {{ "%+.2f"|format(row.result_r) }}R</span>
                    {% if row.close_notes %}<p class="text-slate-500 mt-1">{{ row.close_notes }}</p>{% endif %}
                </div>
                {% else %}
                <p class="text-[11px] text-slate-500 mt-3">Skipped — no position and no P&amp;L.</p>
                {% endif %}
            </article>
            {% else %}
            <div class="rounded-xl border border-dashed border-slate-700 p-6 text-center text-sm text-slate-500">No manual rows yet. Log a skipped idea or an externally taken trade above; nothing will be sent to a broker.</div>
            {% endfor %}
        </div>
        {% endif %}
    </section>

    <footer class="text-[11px] text-slate-500 leading-relaxed border-t border-slate-800 mt-5 pt-4 pb-8">
        <span class="text-slate-300 font-semibold">Measured, not assumed:</span> 8 box breakout/fade geometries tested, 0 cleared the no-edge reference; 74–75% of breaks closed back inside within 15 minutes.
        This workspace supports placement, cost discipline and journaling; it does not claim a scalping edge. P&amp;L and R are computed from self-reported prices and the saved spread/contract snapshot, excluding slippage, commission and swap.
    </footer>
</div>

<script>
const REFERENCES = {{ references|tojson }};
const money = value => Number.isFinite(value) ? '$' + value.toFixed(2) : '—';
const number = id => {
    const raw = document.getElementById(id).value;
    if (raw === '') return null;
    const value = Number(raw);
    return Number.isFinite(value) ? value : null;
};
function useReference(side) {
    const ref = REFERENCES[side];
    if (!ref) return;
    document.getElementById('side').value = side;
    ['entry', 'stop', 'target'].forEach(key => { document.getElementById(key).value = ref[key].toFixed(2); });
    calculateTicket();
    document.getElementById('ticket').scrollIntoView({behavior: 'smooth', block: 'start'});
}
function clearTicketOutputs() {
    ['calc-legs', 'calc-rr', 'calc-cost', 'calc-lots', 'calc-budget', 'calc-money', 'calc-be'].forEach(id => document.getElementById(id).textContent = '—');
}
function calculateTicket() {
    const side = document.getElementById('side').value;
    const entry = number('entry'), stop = number('stop'), target = number('target');
    const balance = number('account_balance'), riskPct = number('risk_pct'), spread = number('spread');
    const contract = number('contract_size'), step = number('volume_step');
    const error = document.getElementById('calc-error');
    const warnings = document.getElementById('calc-warnings');
    error.classList.add('hidden'); warnings.innerHTML = '';
    if ([entry, stop, target, balance, riskPct, spread, contract, step].some(x => x === null)) {
        clearTicketOutputs();
        return;
    }
    let message = '';
    if (entry <= 0 || stop <= 0 || target <= 0 || balance <= 0 || riskPct <= 0 || riskPct > 100 || spread < 0 || contract <= 0 || step <= 0) message = 'Check the numeric fields: prices, balance, risk, contract and step must be valid.';
    const grossRisk = side === 'BUY' ? entry - stop : stop - entry;
    const grossReward = side === 'BUY' ? target - entry : entry - target;
    if (!message && grossRisk <= 0) message = 'For ' + side + ', the stop must be ' + (side === 'BUY' ? 'below' : 'above') + ' entry.';
    if (!message && grossReward <= 0) message = 'For ' + side + ', the target must be ' + (side === 'BUY' ? 'above' : 'below') + ' entry.';
    if (message) {
        error.textContent = message; error.classList.remove('hidden');
        clearTicketOutputs();
        return;
    }
    const netRisk = grossRisk + spread, netReward = grossReward - spread;
    const budget = balance * riskPct / 100, rawLots = budget / (netRisk * contract);
    const lots = Math.max(0, Math.floor((rawLots + 1e-12) / step) * step);
    const plannedRisk = lots * netRisk * contract, plannedReward = lots * netReward * contract;
    const rr = netReward / netRisk, costPct = 100 * spread / grossRisk;
    document.getElementById('calc-legs').textContent = money(grossRisk) + ' / ' + money(grossReward) + ' per oz';
    document.getElementById('calc-rr').textContent = rr.toFixed(2) + ':1';
    document.getElementById('calc-rr').className = 'font-mono text-lg mt-0.5 ' + (rr < 1 ? 'text-rose-300' : 'text-emerald-300');
    document.getElementById('calc-cost').textContent = 'spread ' + costPct.toFixed(1) + '% of stop · gross ' + (grossReward / grossRisk).toFixed(2) + ':1';
    document.getElementById('calc-lots').textContent = lots.toFixed(2) + ' lots';
    document.getElementById('calc-budget').textContent = 'budget ' + money(budget) + ' · raw ' + rawLots.toFixed(4) + ' lots';
    document.getElementById('calc-money').textContent = money(plannedRisk) + ' / ' + money(plannedReward);
    document.getElementById('calc-be').textContent = netReward > 0 ? 'costed breakeven hit rate ' + (100 * netRisk / (netRisk + netReward)).toFixed(1) + '%' : 'reward does not cover spread';
    const notes = [];
    if (lots <= 0) notes.push('Size is below one volume step; do not round up beyond your cash-risk budget.');
    if (costPct > 10) notes.push('Spread is ' + costPct.toFixed(1) + '% of gross stop distance (above the 10% guide).');
    if (netReward <= 0) notes.push('The round-trip spread is greater than or equal to the gross reward.');
    else if (rr < 1) notes.push('Costed reward/risk is only ' + rr.toFixed(2) + ':1; potential loss exceeds potential gain.');
    warnings.innerHTML = notes.map(text => '<li>⚠ ' + text + '</li>').join('');
}
const ticketForm = document.getElementById('scalp-ticket');
if (ticketForm) {
    ticketForm.addEventListener('input', calculateTicket);
    ticketForm.addEventListener('change', calculateTicket);
    calculateTicket();
}
</script>
</body>
</html>
"""
