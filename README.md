# gold-trading-bot

Forward-testing engine for a gold (XAU/USD) price-action strategy. All trades
are simulated (paper) until the strategy proves an edge. See
`archive/PROJECT_LOG.md` for the full architecture, strategy rules, and
changelog.

## 📁 Where everything lives

| Path | What it is |
|---|---|
| `engine.py` | Data ingestion, indicators (EMA/RSI/ATR), the Buy/Sell signal funnel, trade execution. Includes `migrate_trades_csv()` — self-healing schema fix (see 09-10 review) — and the breakeven stop ratchet (`BE_TRIGGER_R`, 09-10 losing-trade analysis). |
| `trade_filter.py` | Risk gatekeeper: direction-aware session blackouts (London blocks BUYs, allows SELLs), SL cooldowns, momentum-gated daily-loss breaker (trend-side-only after limit), ATR bounds. |
| `dashboard.py` | Web dashboard (funnel telemetry, equity, active trade). |
| `trades.csv` | **The ledger** — one row per closed trade (16-field schema with `Trade_Type`). |
| `forward_test_log.csv` | 1-minute candle log with all indicator values per bar. |
| `skipped_trades.csv` | Every full signal the risk layer blocked, with reason. |
| `status.json` | Live engine state (equity, funnel counters, daily losses). |
| `archive/PROJECT_LOG.md` | **Start here** — living changelog, current strategy rules, parameters, to-do list. |
| `docs/REVIEW-*.md` | Per-cycle data reviews (REVIEW-2026-09-09, REVIEW-2026-09-10, ...). |
| `archive/` | Historical backups, old engine versions, pre-fix data copies. |

## 🧰 Tools (run in this order on every new data drop)

```bash
python3 tools/check_data.py       # 1. integrity gate — run FIRST, trust nothing before it passes
python3 tools/validate_gates.py   # 2. replay entry gates against all historical trades
python3 tools/phantom_trades.py   # 3. what did the blocked (skipped) signals actually do?
python3 tools/pathwalk_sims.py    # 4. sequence-aware exit-rule replay (honest exit test)
python3 tools/analyze_losers.py   # 5. winner/loser features + entry-filter experiments
python3 tools/exit_sims.py        # 6. quick MFE exit scan (overstates — confirm via 4)
python3 tools/smoke_test.py       # 7. engine regression tests (gates, SELL, drift auto-fix)
```

All tools are read-only except the engine's own self-healing migration.

## 🚀 Deploying to production

Production files live at `/opt/gold/` (paths hardcoded in `engine.py` /
`trade_filter.py`). Deploy = `git pull` on the server + restart the engine.
On restart the engine auto-migrates `trades.csv` if needed (keeps a
`.bak-pre-migration` backup) and resyncs `status.json`.

## 📡 Forward-test data source

Default is the **Twelve Data WebSocket** (`TWELVE_DATA_API_KEY`). The free plan's
WebSocket access is a *trial* allotment — when it expires the endpoint accepts
the handshake and immediately closes the connection, so the log silently stops.
Check the plan/WS status at [api.twelvedata.com](https://api.twelvedata.com) if
`forward_test_log.csv` stops growing.

Alternative: `DATA_SOURCE=MT5` in `.env` sources closed M1 GOLD candles from the
local Wine MT5 terminal (broker feed, no plan limits). Architecture: the Linux
engine never imports `MetaTrader5` (the package has no Linux wheels) — instead a
small sidecar `tools/mt5_feed.py` runs under the Wine Python in the same prefix
as the terminal (the same pattern as the `mt5-balance` shell alias:
`WINEPREFIX=~/.mt5 xvfb-run wine C:/Python312/python.exe ...`) and publishes the
latest closed candle to `/opt/gold/mt5_last_candle.json`, which the engine reads.
Run the sidecar as a service: `sudo cp deploy/mt5feed.service /etc/systemd/system/
&& sudo systemctl daemon-reload && sudo systemctl enable --now mt5feed`.
Trading stays simulated either way. The engine auto-reconnects stale feeds and
alerts on Telegram (10-min silence threshold, muted during the daily break).

## 🆕 Starting a new session / handing off to a new agent

Read, in this order:
1. `archive/PROJECT_LOG.md` — changelog + current strategy state
2. the latest `docs/REVIEW-*.md` — most recent data findings and open hypotheses
3. `git log --oneline` — what changed recently

Then run `python3 tools/check_data.py` before drawing any conclusion from the
CSVs. Document each review cycle as a new `docs/REVIEW-YYYY-MM-DD.md` and add a
changelog line to `archive/PROJECT_LOG.md`.
