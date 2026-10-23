# gold-trading-bot

Forward-testing engine for a gold (XAU/USD) price-action strategy. All trades
are simulated (paper) until the strategy proves an edge. For a new session, the
owner can simply say **“Execute the plan.”** The ordered queue is in
`docs/EXECUTION-PLAN.md`; current state and operating rules are in
`docs/HANDOFF.md`. See `archive/PROJECT_LOG.md` for the full architecture,
strategy rules, and changelog.

## 📁 Where everything lives

| Path | What it is |
|---|---|
| `docs/EXECUTION-PLAN.md` | **Session execution queue and timeline.** In a new session, the owner can say “Execute the plan”; work the first eligible step only and preserve every registered gate. |
| `docs/HANDOFF.md` | **Current session handoff** — current state, definitions, evidence, next steps, and ops. Read it with the execution plan. §1 is current-state only. |
| `docs/HANDOFF-HISTORY.md` | Dated session archaeology — the per-session state blocks §1 replaced (append-only, newest first). Read it for the *why* behind a rule or the full record of an incident, **never for current numbers**. |
| `engine.py` | Data ingestion, indicators (EMA/RSI/ATR), the Buy/Sell signal funnel, trade execution. Includes `migrate_trades_csv()` — self-healing schema fix (see 09-10 review) — the **structural stop** (`SL_CLEAR_ATR = 0.5` + `RR_TARGET`, live **2026-10-06 03:00 UTC** — planned for 10-05 21:00, deployed by the 03:00 autosync: risk = `max(2·ATR, |entry − level| + 0.5·ATR)`, TP = 1.5 × that risk — see `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md`), and the breakeven stop ratchet (`BE_TRIGGER_R`: 0.30R since the 09-10 losing-trade analysis, **raised to 0.75R on 09-15** — the tight trigger was scratching 77% of trades; see `docs/REVIEW-2026-09-15.md`). |
| `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` | **Why the stop-loss rate is high, and the change that shipped for it** (structural stop, live 2026-10-06 03:00 UTC; the doc's own 10-05 21:00 cutover is corrected in its erratum): the inert `FLOOR_BUFFER_PCT` level test, the ~64–66% of trades whose stop sat *inside* the 20-bar level, the costed/stateful era-matched evidence, everything rejected, and the **pre-registered forward bar** (§7) that must be judged at n≥100 before anything else changes. |
| `docs/AUTOSYNC.md` | How the unattended data sync + auto-deploy works, how to read the Telegram digest, and **why the deploy time (not the plan) is the era cutover**. |
| `docs/ANALYSIS-2026-10-13-btc-port-assessment.md` | Which of the `bitcoin-trading-bot` improvements transfer to gold, which were ported, which were rejected and why, and what is queued behind the open struct-stop window. |
| `docs/ANALYSIS-2026-10-16-dashboard-pressure.md` | What the dashboard's market-context layer is, the composite's weights, and the **calibration** that keeps it honest: on the live book the buy/sell gauge is **collinear with side** (no `against` bucket on either side, in either era) — context, never a signal. |
| `docs/XM-LOGGER.md` | The **GOLD quote + contract-spec logger** (`tools/mt5_quotes.py`, `deploy/mt5quotes.service`, `tools/xm_quote_report.py`): service runbook, `xm_data/` schema, closed-market and DST handling, and limits on cost conclusions. |
| `docs/ACCELERATE-TESTING.md` | The **large-N history path**: dump M1 history → `tools/history_to_log.py` (proves the broker-server → UTC conversion against the live log, refuses rather than guesses) → `strategy_lab.py --bars`. How to read it, and why a result there is a hypothesis to pre-register, never a reason to change a rule. |
| `tools/pressure_report.py` | Prints the dashboard's read layer: tape pressure, the engine's gate read, location/risk, portfolio state, the §7 era verdict, feed health and the composite's **calibration** (does it separate outcomes, per side and era?). `--root DIR`, `--era …`, `--json`. Read-only, exits 0. |
| `docs/ANALYSIS-2026-10-19-signal-outlook.md` | **"Given a very strong (8/8) signal, where does price head?"** — measured on the bot's own taken signals: at 15–60 min the direction is a coin flip (≈49% [41–57] pooled @30m, live era), the target prints before the stop ~1/3 of decisive races vs the 40% the 1:1.5 geometry needs, and bigger wicks do not follow through better. The deliverable is a cone + base rates, never an arrow. |
| `docs/PROPOSAL-2026-10-23-manual-chart-tab.md` | **Which chart tools are worth putting on a dashboard, and where to place a manual trade.** Ranks the classic gold-trader toolkit against this repo's own measurements: tiers 1–2 ship (candles, boxes, entry/stop/target bands, the **cost ruler**, session shading, prior-day rails, EMA/RSI/ATR read-outs), tier 3 is refused as decoration (Fibonacci, pivots, round numbers — unmeasured; VWAP, volume profile — the feed carries *tick* volume; trendlines, H&S, Elliott — subjective). Includes the placement playbook (`R ≥ 10 × round-trip cost` → a ≥3 ATR stop on this tape) and the **🧭 Chart & Placement** tab (§3). |
| `tools/test_manual_chart.py` | 32 hermetic tests for `chart.py`: aggregation never invents a bar, the forming candle is flagged, pixel geometry stays inside its plot, shared box edges are merged not double-labelled, an off-range level is pinned rather than dropped, the cost ruler matches the $0.40/$0.55 models, the box chooser refuses a 70-ATR prior-day box, and a card is never `ready` on a sub-1R target or a >10%-of-R spread. |
| `docs/ANALYSIS-2026-10-20-box-theory-manual-trading.md` | **"Can I use box theory for manual gold trades?"** — measured on the repo's own tape: box breakouts and fades land **on or below the driftless reference** at both box sizes (20-bar: 56.8% vs 55.1% ref; 60-bar: 55.3% vs 53.0%), 74–75% of breaks close back inside within 15 min, and the only near-break-even geometry is the stop placed **outside the whole box**. Verdict: boxes are a place to put a **stop**, not a place to read a prediction. Includes the working manual rules, the bar to beat, and the dashboard **📦 Boxes & Timing** tab (§6). |
| `tools/signal_outlook.py` | That estimate, printable any time: forward walks after every taken signal (per side/era, Wilson CIs, MFE/MAE, barrier race vs the 40% driftless reference, trend-anywhere baseline) + the cone applied to the last bar when a side is 8/8. `--root DIR`, `--era structstop|075|all`, `--spread …`, `--json`. Read-only, exits 0. Core in `pressure.py` (`signal_outlook`/`outlook_now`); dashboard renders it as the 🧭 panel. |
| `tools/strategy_lab.py` | Canonical **costed, stateful, era-matched** full-strategy replay (funnel + exits + cooldown/breaker/blackouts). Read-only. This is what an exit or gate idea must be measured with; `exit_sims.py` / `pathwalk_sims.py` / `phantom_trades.py` predate it and are cascade-ignorant. `--bars FILE` replays today's rules over converted broker history (large-N mode; `docs/ACCELERATE-TESTING.md`). |
| `tools/box_report.py` | Live boxes (the engine's own 20-bar level, last 1h / 4h, prior trading day) with distance to each edge in $ and ATR, the structural stop/TP each edge implies, and cost as a share of risk — then the measured verdict: four breakout/fade geometries, target-first share vs the no-edge reference, Wilson CIs, sequential one-position sampling, censored at gaps/end. `--alert-scan` adds the chop/retest read and replays how many Telegram notices the current rule would have sent. `--root DIR`, `--spread $`, `--json`. Read-only, stdlib + `pressure`, exits 0. Tests: `tools/test_box_report.py`. |
| `docs/ANALYSIS-2026-10-21-box-chop-retest-alerts.md` | **"Is the market choppy, what is the last break doing, and when should the box watch say something?"** Adds the measured chop read (14/18 breaks in the last 24 h closed back inside = **78%** vs a **74%** baseline — normal chop, but efficiency 0.04 and a 3.0-vs-4.7 ATR compressed box), retest tracking on a box frozen at the break (94% retested within 30 bars, median 3; entering the held retest = **59.0% vs 57.2% ref**, no edge), and the optional Telegram notifier (**5.1 messages/day** measured). Includes the negative results: a 10 pp "chop filter" found on overlapping events **vanished and partly reversed** under the one-position convention. |
| `tools/box_alert.py` | **Optional, display-only** Telegram notifier: sends one rate-limited message when a box edge breaks with every condition green (fresh close beyond, feed/session/risk/volatility pass, spread ≤ 10% of R, no chase). The decision lives in `pressure.box_alert()`, so the sidecar, the dashboard preview and the `--alert-scan` replay share one implementation. Places no order, imports no engine module, writes only its own state (dedupe + the `--loop` heartbeat). Reads the Telegram pair and its `GOLD_BOX_ALERT*` knobs from the environment, then `/opt/gold/.env`. `--quiet` (the autosync `🔔` line) says whether it is configured **and running**. `--once/--loop/--dry-run/--test/--quiet/--json/--env-file`. Unit: `deploy/boxalert.service`. Tests: `tools/test_box_alert.py` (34). |
| `trade_filter.py` | Risk gatekeeper: direction-aware session blackouts (London blocks BUYs, allows SELLs), SL cooldowns, momentum-gated daily-loss breaker (trend-side-only after limit), ATR bounds. |
| `dashboard.py` | Flask bot dashboard: **Simple**, **Journal**, **📦 Boxes & Timing**, **🧭 Chart & Placement** (`?tab=chart`, `?tf=1|5|15`) and **Full**. The main page remains display-only and never drives trading. A separate **⚡ Manual Scalping** page lives at `/scalp`: M5 structure / optional M1 timing, the same box levels and health context, an editable costed risk/size calculator, and a self-reported manual journal. It has no auto-refresh and no order-placement route. |
| `docs/MANUAL-SCALPING.md` | Operating and safety guide for `/scalp`: calculator formulas, contract/cost assumptions, journal schema/statuses, atomic file behavior, routes, evidence limits and deployment. |
| `manual_scalp.py` + `scalp_template.py` | Manual scalping calculator, atomic host-local journal store (`manual_scalp_journal.json`, git-ignored; override with `GOLD_MANUAL_JOURNAL_FILE`) and page template. Spread is added to risk and subtracted from reward; lot size rounds **down** to the volume step. The server recalculates every ticket/close. OPEN/CLOSED rows are self-reported external activity, never broker-verified, and never enter `trades.csv`. Tests: `tools/test_manual_scalp.py` (stdlib) and `tools/test_scalp_dashboard.py` (Flask). |
| `pressure.py` | The read-only module behind those panels (stdlib only, no engine import — `tools/smoke_test.py` Scenario U pins its mirrored thresholds to `engine.py`/`trade_filter.py` and asserts it writes nothing). |
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
python3 tools/momentum_regime.py  # 9. falling-gold / side regime + the 09-28 registered bar
python3 tools/strategy_lab.py --calib-only  # 10. CANONICAL replay (costed, stateful, era-matched) —
                                            #     required before any exit/gate/param idea is judged
python3 tools/strategy_lab.py --table --only baseline,structstop  # 11. era x cost counterfactual grid
python3 tools/check_structural_stop.py      # 12. is the stop really beyond the tested level? (2026-10-05 rule;
                                            #     also proves WHEN the deploy happened from the ledger itself)
python3 tools/handoff_check.py              # 13. is docs/HANDOFF.md still telling the truth? (--update refreshes the block)
python3 tools/signal_outlook.py --root .    # 13c. where did full (8/8) signals head? cone + base rates per side/era
                                            #     (display-only; docs/ANALYSIS-2026-10-19-signal-outlook.md)
python3 tools/box_report.py                # 13d. box theory: live 1h/4h/day boxes + measured breakout/fade edge
                                            #     (read-only; docs/ANALYSIS-2026-10-20-box-theory-manual-trading.md)
python3 tools/box_report.py --alert-scan   # 13e. + is the tape choppy? what is the last break doing?
                                            #     + how many Telegram notices would the rule have sent
python3 tools/box_alert.py --once --dry-run # 13f. the box-watch Telegram notice, without sending it
python3 tools/pressure_report.py            # 13b. dashboard read layer: tape pressure, gate read, §7 era verdict,
                                            #     and the calibration of the pressure gauge (display-only)
python3 tools/win_rate_report.py --spread 0.40   # 14. the same report net of the assumed round-trip cost (default output unchanged)
python3 tools/xm_quote_report.py            # 15. what the quote logger measured: spreads, cost vs the assumed $0.40, server clock, spec
python3 tools/history_to_log.py mt5_history.csv --out history_utc.csv && python3 tools/strategy_lab.py --bars history_utc.csv
                                            # 16. large-N: broker history -> validated UTC -> replay (docs/ACCELERATE-TESTING.md)
```

All tools are read-only except the engine's own self-healing migration. Every
tool that re-walks 1-min bars must key BE geometry on the logged *shape*
(`Stop_Loss == Entry_Price` appears on scratches AND on winners that armed the
ratchet before TP printed), recover the pre-ratchet risk from the **reward leg**
(`|TP − Entry| / 1.5`) rather than from `2·ATR` — from 2026-10-05 the stop is
*structural* (it clears the 20-bar level) so the ATR multiple is only a floor —
and must treat a SELL's favourable bar extreme as its LOW — both of those were
wrong until 2026-09-15. `tools/exit_sims.py`, `pathwalk_sims.py`
and `phantom_trades.py` are **cascade-ignorant** (no
one-position/cooldown/breaker state, no costs): descriptive only. Use
`tools/strategy_lab.py` for anything that would change a rule.

## 🚀 Deploying to production

Production files live at `/opt/gold/` (paths hardcoded in `engine.py` /
`trade_filter.py`). Normal deploy is **unattended**: merge to `main` → next
`tools/autosync.sh` cron cycle (every 3h) pulls, smoke-tests on code changes,
and restarts the engine only if `engine.py` / `trade_filter.py` changed.
See `docs/HANDOFF.md` §10 and `docs/AUTOSYNC.md`. Manual path: `git pull` on the server + restart the
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

A second, **read-only** sidecar, `tools/mt5_quotes.py` (`deploy/mt5quotes.service`, installed as
`mt5quotes-gold`), logs the XM bid/ask spread every 30 s and the contract spec to `xm_data/`, so the assumed
$0.20/side cost can be measured; it never touches orders or the engine. See `docs/XM-LOGGER.md`.

## 🆕 Starting a new session / handing off to a new agent

1. **`docs/HANDOFF.md` first** — current ledger, definitions, next steps, ops
   (`docs/HANDOFF-HISTORY.md` only if you need the history behind something).
2. Latest `docs/REVIEW-*.md` / `docs/ANALYSIS-*.md` if the handoff points at them
   (current structural-stop decision: `docs/REVIEW-2026-10-19-struct-stop-judgement.md`; its
   binding thresholds remain in `docs/ANALYSIS-2026-10-05-stop-loss-geometry.md` §7. The
   earlier n=127 interim record is `docs/REVIEW-2026-10-19-struct-stop-screen.md`; display-only
   dashboard context and signal-outlook methods are documented in the two 2026-10-19 analysis files).
3. `git log --oneline` — what changed recently.
4. `python3 tools/check_data.py` before drawing conclusions from the CSVs.
5. Answer "does X look like Y?" questions with a dated `docs/ANALYSIS-*.md` (CIs,
   era split, side split) + a registered bar in the handoff — never with an
   ad-hoc parameter change, especially mid-isolation.

Document each review cycle as a new `docs/REVIEW-YYYY-MM-DD.md`, update
`docs/HANDOFF.md` §1/§4–§6, and add a changelog line to `archive/PROJECT_LOG.md`.
**§1 is current-state only** — rewrite it in place and move the block it replaced to
`docs/HANDOFF-HISTORY.md` (HANDOFF §11 rule 5; `handoff_check.py` fails on a truncated or
renamed section).
