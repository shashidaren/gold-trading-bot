# HANDOFF — read this first in a new session

Paste this file at the start of a new session:
> "I'm working on my Gold trading bot. Here is the handoff: [paste docs/HANDOFF.md]. I want to work on [X]."

## 1. Where things stand (as of 2026-09-10)

- Repo: `shashidaren/gold-trading-bot`, default branch `main`.
- Work branch: `arena/01a08b27-gold-trading-bot` → open **PR #7** (`arena/...` → `main`).
  Check `gh pr status` / `gh pr merge` first: if #7 is still open, the new
  risk rules below are NOT live on `main` yet.
- Live bot runs from `/opt/gold` via systemd (`goldbot.service` =
  engine, `mt5feed.service` = price-feed sidecar, see §3). Deploy = merge
  PR → pull on the box → `sudo systemctl restart goldbot`. Restarts are
  safe mid-trade (open trade + BE-armed state restore from `status.json`).

## 2. Bot in one paragraph

Simulated XAUUSD scalper on 1-min candles. BUY at the 20-bar floor /
SELL at the 20-bar ceiling after a ≥38% wick rejection, trend-gated by
EMA50 vs EMA200 (+30-bar slope, ≤0.3·ATR from EMA50), RSI 30–68, ATR 1.10–4.50.
Exits: SL = entry ∓ 2·ATR, TP = entry ± 3·ATR (1:1.5). `engine.py` = signals +
execution/state; `trade_filter.py` = portfolio risk gates; `dashboard.py` =
Flask status page. Trading is FORWARD-TEST simulated (no real orders);
`TRADING_MODE=LIVE` path exists but the BE stop (below) is engine-side only there.

## 3. Data feed: Twelve Data → MT5 sidecar (configured 2026-09-10)

`DATA_SOURCE` env var in `/opt/gold/.env` picks the feed; default in code is
`TWELVEDATA`. **The deployed engine runs `DATA_SOURCE=MT5`** (proof:
`status.json` → `mt5_last_candle_ts` is live-updated; last write
2026-09-10 11:43 UTC).

Why the switch: the Twelve Data free-plan WebSocket began refusing
connections (handshake OK, immediate close — suspected WS-trial expiry) and
earlier stalled *silently* (00:47 and 02:05 on 09-10, 2.5h of missing
candles, zero alerts — a zombie WS never raises). Twelve Data remains the
code default; the stale-feed guard below applies to both.

How MT5 works (feed-only, trading stays simulated):
- MT5 terminal runs **under Wine** in prefix `~/.mt5`, logged in
  (`ps aux | grep terminal64.exe`; setup guide: `archive/wine_mt5_setup.md`).
- `MetaTrader5` has no Linux wheels, so the Linux engine never imports it.
  Sidecar `tools/mt5_feed.py` runs under the **Wine** Python
  (`pip install MetaTrader5` inside the prefix) and atomically publishes the
  latest **closed** M1 GOLD candle to `/opt/gold/mt5_last_candle.json`.
- Engine (`DATA_SOURCE=MT5`) reads that file each poll, dedupes by candle
  timestamp (a restart never re-logs the boundary candle; worst case one
  minute lost). Same stale-feed guard + Telegram alerts as Twelve Data.

Manual sidecar start (or use systemd):

export WINEPREFIX=~/.mt5 && xvfb-run --auto-servernum
wine C:/Python312/python.exe Z:/opt/gold/tools/mt5_feed.py

Service install: `sudo cp deploy/mt5feed.service /etc/systemd/system/ &&
sudo systemctl daemon-reload && sudo systemctl enable --now mt5feed`.
Env overrides: `MT5_FEED_FILE`, `MT5_FEED_SYMBOL` (default GOLD),
`MT5_FEED_POLL`. Ops: `systemctl status mt5feed goldbot`,
`cat /opt/gold/mt5_last_candle.json | jq .updated_at` (should be ≤2 min old).

Stale-feed guard (either source): `STALE_FEED_SECONDS` = 600 without a price
event → force reconnect / re-poll; Telegram alert rate-limited to 30 min,
suppressed during broker quiet hours (~21:00–02:00 UTC + weekends,
`is_market_quiet()`). Deploy note: `Environment=PYTHONUNBUFFERED=1` in
`goldbot.service`, else engine prints are block-buffered out of journalctl.
Feed price scale is the **broker demo GOLD feed** (~4.4k), not spot XAUUSD —
never mix analyses across feeds. Smoke Scenario H covers the feed-file
read/normalize/dedup path.

## 4. Current risk gates (trade_filter.py)

- SL cooldown: 30 min, escalating to 60 min after 2 consecutive SLs.
- Daily breaker: after `MAX_DAILY_LOSSES = 10` SLs (UTC day) → **trend-side-only
  mode** (entries must agree with 60-min momentum from the price log; legacy
  hard halt if momentum unavailable). Older live skips show "(N/3)" — that was
  the pre-bump build, not a bug.
- Blackouts (UTC): London 07:55–09:00 **blocks BUYs only** (SELLs allowed —
  phantom evidence 5W/1L +20.09); NY 12:25–12:45 and 13:25–15:15, rollover
  21:45–22:30 block both sides. `side=None` callers get legacy block-everything.
- ATR bounds: <1.10 or >4.50 → skip.

Engine (engine.py): **BE stop ratchet** — at +`BE_TRIGGER_R = 0.30`·risk, SL
moves to entry; exit reason `BE` = scratch (new `be_exits` counter in
status.json; excluded from wins/losses, cooldown, daily tally). Replay impact
on the 45-trade sample: −82.51 → −62.36 (5W/28L/12BE).

## 5. Evidence base (don't re-derive)

`docs/ANALYSIS-2026-09-10-losing-trades.md` = full study. Headline numbers
from 45 trades (2026-09-04 → 09-10), 8W/37L, −$82.51 ($500 → $417.49):
- Expectancy ≈ **−0.5R at every TP placement (0.33R–1.5R)** — exits can't
  create edge; entries are the problem long-term.
- **Blocked signals beat taken ones**: 80 gate-blocked signals replay
  47.5% WR / +41 raw (sequential 65% / +64) vs 17.8% taken → gates were
  adversely selecting; the three rules above fix the worst of that.
- Losers avg MAE in first ~3 min = −1.12R vs winners −0.37R:
  trades that die early never recover (grounds for future time-stop study).
- Re-entry <5 min after an exit: 0W/9L, −23.32 (validates the SL cooldown).
- RSI<45 entries: 1W/14L (7%) — candidate filter, NOT adopted yet (needs data).
- Prior reviews: `docs/REVIEW-2026-09-09.md`, `docs/REVIEW-2026-09-10.md`.

## 6. Next steps (in order)

1. **Validate live** (~2 weeks from deploy): after each data-collection

commit run the three read-only tools and compare against section 5:
python3 tools/phantom_trades.py # are the gates LEAVING money now?
python3 tools/pathwalk_sims.py # exit-rule replay vs actual P/L
python3 tools/analyze_losers.py # winner/loser feature drift

2. **RSI<45 entry skip**: revisit with the post-rule-change data (target
≥30 trades in the new regime before judging anything).
3. **LIVE-mode broker-side BE modify** (mt5 order SL update) — only needed
if/when `TRADING_MODE=LIVE` is switched on.
4. Study a **time-stop / early scratch-cut** (losers die in ~6 min median;
pathwalk D-tier shows only ~$4–8 of edge — low priority).

## 7. How to verify code changes (always)

python3 tools/smoke_test.py # must print "SMOKE TEST PASSED" (scenarios A–J)
python3 -m py_compile engine.py trade_filter.py
python3 tools/check_data.py # expect "0 fail" (gaps warnings are normal)



## 8. Data gotchas (hard-won — read before analyzing)

- `trades.csv` has 3 batches (`Trade_Num` resets on 09-04 due to balance
  resets) — dedupe by timestamp. Schema is 16-field with `Trade_Type`;
  `engine.migrate_trades_csv()` self-heals drift (the 09-10 SELL-row incident).
- **Clock skew**: `forward_test_log.csv` bar timestamps lag `trades.csv` by up
  to ~1 min (different feeds). Any per-trade replay MUST use ±2 min windows,
  or MFE/MAE invert (winners appear to never reach TP).
- `phantom_trades.py` reconstruction notes (pre/post gate-change engines,
  reconstruction tolerance) are documented in its docstring.
- Gold price series here is the broker demo feed (~4.4k), not spot.

## 9. File map (short)

`engine.py` signals/execution · `trade_filter.py` risk gates ·
`trades.csv` ledger · `forward_test_log.csv` 1-min bars ·
`skipped_trades.csv` blocked signals (+reason) · `status.json` live state ·
`tools/` analysis+tests · `docs/REVIEW-*.md` data reviews ·
`archive/PROJECT_LOG.md` full history (this file is the executive summary).







