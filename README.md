# gold-trading-bot

Forward-testing engine for a gold (XAU/USD) price-action strategy. All trades
are simulated (paper) until the strategy proves an edge. See
`docs/HANDOFF.md` for the current session handoff (start here), and
`archive/PROJECT_LOG.md` for the full architecture, strategy rules, and
changelog.

## 📁 Where everything lives

| Path | What it is |
|---|---|
| `docs/HANDOFF.md` | **Start here for any new session** — current state, definitions, next steps, ops. |
| `engine.py` | Data ingestion, indicators (EMA/RSI/ATR), the Buy/Sell signal funnel, trade execution. Includes `migrate_trades_csv()` — self-healing schema fix (see 09-10 review) — and the breakeven stop ratchet (`BE_TRIGGER_R`: 0.30R since the 09-10 losing-trade analysis, **raised to 0.75R on 09-15** — the tight trigger was scratching 77% of trades; see `docs/REVIEW-2026-09-15.md`). |
| `trade_filter.py` | Risk gatekeeper: direction-aware session blackouts (London blocks BUYs, allows SELLs), SL cooldowns, momentum-gated daily-loss breaker (trend-side-only after limit), ATR bounds. |
| `dashboard.py` | Web dashboard (funnel telemetry, equity, active trade). |
| `trades.csv` | **The ledger** — one row per closed trade (16-field schema with `Trade_Type`). |
| `forward_test_log.csv` | 1-minute candle log with all indicator values per bar. |
| `skipped_trades.csv` | Every full signal the risk layer blocked, with reason. |
| `status.json` | Live engine state (equity, funnel counters, daily losses). |
| `archive/PROJECT_LOG.md` | Living changelog, architecture notes, longer history. |
| `docs/REVIEW-*.md` | Per-cycle data reviews (REVIEW-2026-09-09, REVIEW-2026-09-10, ...). |
| `archive/` | Historical backups, old engine versions, pre-fix data copies. |

## 🧰 Tools (run in this order on every new data drop)

```bash
python3 tools/check_data.py       # 1. integrity gate — run FIRST, trust nothing before it passes
python3 tools/win_rate_report.py  # 2. win-rate decomposition (era/side/day, ratchet grid)
python3 tools/validate_gates.py   # 3. replay entry gates against all historical trades
python3 tools/phantom_trades.py   # 4. what did the blocked (skipped) signals actually do?
python3 tools/pathwalk_sims.py    # 5. sequence-aware exit-rule replay (honest exit test)
python3 tools/analyze_losers.py   # 6. winner/loser features + entry-filter experiments
python3 tools/exit_sims.py        # 7. quick MFE exit scan (overstates — confirm via 5)
python3 tools/smoke_test.py       # 8. engine regression tests (gates, SELL, drift auto-fix)
```

All tools are read-only except the engine's own self-healing migration. Every
tool that re-walks 1-min bars must key BE geometry on the logged *shape*
(`Stop_Loss == Entry_Price` appears on scratches AND on winners that armed the
ratchet before TP printed) and must treat a SELL's favourable bar extreme as its
LOW — both of those were wrong until 2026-09-15.

## 🚀 Deploying to production

Production files live at `/opt/gold/` (paths hardcoded in `engine.py` /
`trade_filter.py`). Normal deploy is **unattended**: merge to `main` → next
`tools/autosync.sh` cron cycle (every 3h) pulls, smoke-tests on code changes,
and restarts the engine only if `engine.py` / `trade_filter.py` changed.
See `docs/HANDOFF.md` §10. Manual path: `git pull` on the server + restart the
engine. On restart the engine auto-migrates `trades.csv` if needed (keeps a
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

1. **`docs/HANDOFF.md` first** — current ledger, definitions, next steps, ops.
2. Latest `docs/REVIEW-*.md` / `docs/ANALYSIS-*.md` if the handoff points at them.
3. `git log --oneline` — what changed recently.
4. `python3 tools/check_data.py` before drawing conclusions from the CSVs.

Document each review cycle as a new `docs/REVIEW-YYYY-MM-DD.md`, update
`docs/HANDOFF.md` §1/§4–§6, and add a changelog line to `archive/PROJECT_LOG.md`.
