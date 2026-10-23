# Manual Scalping workspace (2026-10-23)

**Status:** built; dashboard/tooling only. No engine, filter, gate, parameter,
exit, sizing, or broker-execution change. No deployment is claimed by this doc.

## 1. What it is

`/scalp` is a separate page linked from the main dashboard's **⚡ Manual
Scalping** navigation item. It is deliberately outside the main page's
auto-refreshing tab switcher, so a refresh cannot erase a ticket being edited.
The page itself has **no auto-refresh**; use **Refresh market data** when the
form is not in use.

It contains:

- the existing server-rendered M1/M5/M15 chart and box/session levels, default
  **M5 for structure**, with M1 available as timing detail rather than a signal;
- feed, session, engine-risk-state, volatility and measured-chop **context**;
- existing Chart & Placement BUY/SELL geometry that can be copied into the
  calculator without changing its SKIP/WATCH meaning;
- an editable entry/stop/target, cash-risk, spread and contract calculator;
- a separate journal for skipped ideas and self-reported external trades and
  closes.

The page has **no order-placement route**. “Record externally taken” means
“write an OPEN journal row for something the operator says they did elsewhere.”
It does not send, verify, modify or close a broker position. The bot's
`trades.csv`, `status.json`, equity and open-position state are never read as
manual fills and are never written by this feature.

## 2. Calculator arithmetic

Defaults are a **$500 calculation balance**, **1% cash risk**, **$0.55/oz
round-trip spread**, **100 oz per 1.00 lot**, and **0.01-lot volume steps**.
The balance is not read from a broker. Verify the actual spread, contract size
and volume step at the broker; GOLDmicro can differ from GOLD Standard.

For a structurally valid BUY or SELL ticket:

```text
gross_risk_oz    = abs(entry - stop)
gross_reward_oz  = abs(target - entry)
net_risk_oz      = gross_risk_oz + round_trip_spread
net_reward_oz    = gross_reward_oz - round_trip_spread
net_R:R          = net_reward_oz / net_risk_oz
cash_budget      = account_balance * risk_pct / 100
raw_lots         = cash_budget / (net_risk_oz * contract_size)
lots             = floor(raw_lots / volume_step) * volume_step
planned_net_risk = lots * net_risk_oz * contract_size
planned_reward   = lots * net_reward_oz * contract_size
spread_share     = round_trip_spread / gross_risk_oz * 100%
```

Size is rounded **down**, never up beyond the cash-risk budget. Spread is added
to the risk leg and subtracted from the reward leg, matching the existing
costed placement cards. Slippage, commission and swap are not included.

The browser preview is convenience only. `manual_scalp.calculate()` repeats
the arithmetic on every server write; client-supplied lots or P&L are ignored.
Wrong-side stops/targets, nonfinite/nonpositive values and derived overflow are
validation errors. A TAKEN row whose size rounds to zero is rejected; a SKIPPED
idea can still be recorded at zero size.

Warnings for spread above 10% of gross stop distance, net R:R below 1:1, reward
not covering spread, or sub-step size do **not** pretend to be a forecast. A
valid but warned-about externally taken trade can still be logged because the
journal's job is to record what actually happened, not rewrite history.

For a close, using the saved ticket snapshot:

```text
gross_P&L = direction * (exit_price - entry) * lots * contract_size
net_P&L   = gross_P&L - spread * lots * contract_size
result_R  = net_P&L / planned_net_risk
```

The exit price is self-reported; the dashboard does not infer a fill from a
wick or claim that SL/TP executed at a particular price.

## 3. Journal file and statuses

Default path: `$GOLD_DATA_DIR/manual_scalp_journal.json` (normally
`/opt/gold/manual_scalp_journal.json`). Override with
`GOLD_MANUAL_JOURNAL_FILE`. The filename is git-ignored. It is host-local,
not merged by autosync, and is not part of the checked-in evidence ledger.

JSON schema version 1 has a top-level `version` and `entries`. Every row stores
its calculation snapshot (prices, side, spread, balance/risk %, contract/step,
lots, gross/net legs, costed R:R and planned cash risk/reward), plus:

| Field/group | Meaning |
|---|---|
| `id`, `created_utc`, `source` | Random row id, UTC timestamp, `manual-self-reported` |
| `timeframe`, `setup`, `notes`, `warnings` | User context and the calculator warnings shown at entry |
| `SKIPPED` | Final no-position idea; no P&L |
| `OPEN` | Self-reported external trade awaiting a journal close |
| `CLOSED` | Has `closed_utc`, `exit_price`, `exit_reason`, `close_notes`, `gross_pnl`, `net_pnl`, `result_r` |

Exit reasons are `MANUAL`, `SL`, `TP`, `SCRATCH`, or `TIME`. Only OPEN rows can
be closed, and a close cannot be replayed. There is no delete/edit API in this
version.

Writes use one dashboard-process thread lock and a same-directory temporary
file followed by atomic `os.replace`; new files are mode `0600`. A missing file
is an empty journal. A corrupt or unsupported file raises an error and is
**never silently reset**. The UI hides totals/rows on a read failure rather
than presenting the failure as zero activity. Back up the host-local file if
the journal matters; git/autosync is not its backup.

## 4. Evidence boundary

This is a workflow tool, not a newly measured strategy. The existing box result
still stands: 8 tested breakout/fade geometries, 0 cleared the no-edge
reference, and 74–75% of breaks closed back inside within 15 minutes. Chart
levels answer **where**, not **when**.

The summary's P&L/R totals are descriptive calculations from self-reported
prices, not broker-verified performance. Skipped ideas do not count as trades.
Do not claim an edge from a handful of rows. The existing manual review bar is
at least **100 closed manual trades with positive expectancy after measured
costs**, followed by proper review rather than automatic adoption.

## 5. Routes and deployment

- `GET /scalp?tf=1|5|15` — page; responses are `Cache-Control: no-store`.
- `POST /scalp/journal` — validate/recalculate and record `taken` or `skipped`.
- `POST /scalp/journal/<id>/close` — record an external close for an OPEN row.

Validation errors return HTTP 400 and preserve the ticket inputs. Successful
writes redirect back to the journal. No route imports or calls the engine, MT5,
or a broker order API.

Autosync's `DASH_CHANGED` now covers `dashboard.py`, `pressure.py`, `chart.py`,
`manual_scalp.py`, and `scalp_template.py`, so helper-only changes restart the
dashboard too. `CORE_CHANGED` is unchanged and still covers only
`engine.py`/`trade_filter.py`: this feature never requires an engine restart.
The manual journal is not a deploy artifact.

## 6. Verification

```bash
python3 tools/test_manual_scalp.py             # pure arithmetic + atomic journal
.venv/bin/python tools/test_scalp_dashboard.py # Flask page/routes + ledger isolation
.venv/bin/python tools/test_dashboard_context.py
python3 tools/test_manual_chart.py
python3 -m py_compile manual_scalp.py scalp_template.py dashboard.py
bash -n tools/autosync.sh
```

The route tests use a temporary journal and hash `trades.csv` before/after the
skip → taken → close flow to prove the bot ledger is unchanged. For a local
render, use `GOLD_DATA_DIR=.` and optionally point
`GOLD_MANUAL_JOURNAL_FILE` at a temporary file.
