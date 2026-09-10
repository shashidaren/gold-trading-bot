# gold-trading-bot

Forward-testing engine for a gold (XAU/USD) price-action strategy. All trades
are simulated (paper) until the strategy proves an edge. See
`archive/PROJECT_LOG.md` for the full architecture, strategy rules, and
changelog.

## 📁 Where everything lives

| Path | What it is |
|---|---|
| `engine.py` | Data ingestion, indicators (EMA/RSI/ATR), the Buy/Sell signal funnel, trade execution. Includes `migrate_trades_csv()` — self-healing schema fix (see 09-10 review). |
| `trade_filter.py` | Risk gatekeeper: session blackouts, SL cooldowns, daily-loss circuit breaker, ATR bounds. |
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
python3 tools/smoke_test.py       # 4. engine regression tests (gates, SELL, drift auto-fix)
```

All tools are read-only except the engine's own self-healing migration.

## 🚀 Deploying to production

Production files live at `/opt/gold/` (paths hardcoded in `engine.py` /
`trade_filter.py`). Deploy = `git pull` on the server + restart the engine.
On restart the engine auto-migrates `trades.csv` if needed (keeps a
`.bak-pre-migration` backup) and resyncs `status.json`.

## 🆕 Starting a new session / handing off to a new agent

Read, in this order:
1. `archive/PROJECT_LOG.md` — changelog + current strategy state
2. the latest `docs/REVIEW-*.md` — most recent data findings and open hypotheses
3. `git log --oneline` — what changed recently

Then run `python3 tools/check_data.py` before drawing any conclusion from the
CSVs. Document each review cycle as a new `docs/REVIEW-YYYY-MM-DD.md` and add a
changelog line to `archive/PROJECT_LOG.md`.
