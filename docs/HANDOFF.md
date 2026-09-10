# HANDOFF — read this first in a new session

Paste this file at the start of a new session:
> "I'm working on my Gold trading bot. Here is the handoff: [paste docs/HANDOFF.md]. I want to work on [X]."

## 1. Where things stand (as of 2026-09-10 PM, 60 trades)

- Repo: `shashidaren/gold-trading-bot`, default branch `main`.
- **PR #7 MERGED** (2026-09-10 12:33 UTC): BE ratchet + direction-aware London
  blackout + trend-side daily breaker are on `main` and **live since the
  ~12:34 UTC engine restart** (15 new-regime trades so far: 0W/2L/13BE).
  Work branch: `arena/01a08d75-gold-trading-bot` → **PR #8** (PM review +
  BE-aware tooling; merge → pull on the box; engine restart NOT required).
- Live bot runs from `/opt/gold` via systemd (`goldbot.service` =
  engine, `mt5feed.service` = price-feed sidecar, see §3). Deploy = merge
  PR → pull on the box → `sudo systemctl restart goldbot`. Restarts are
  safe mid-trade (open trade + BE-armed state restore from `status.json`).
  Tooling/docs-only changes need no engine restart.

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
  (BE scratches neither count toward nor break the streak — queued for
  review, see §6.)
- Daily breaker: after `MAX_DAILY_LOSSES = 10` SLs (UTC day) → **trend-side-only
  mode** (entries must agree with 60-min momentum from the price log; legacy
  hard halt if momentum unavailable). Older live skips show "(N/3)" — that was
  the pre-bump build, not a bug. Has not engaged live yet (09-10 peaked at 6).
- Blackouts (UTC): London 07:55–09:00 **blocks BUYs only** (SELLs allowed —
  phantom evidence 5W/1L +20.09); first live test is the next London open
  (deployed 12:34, after the window). NY 12:25–12:45 and 13:25–15:15, rollover
  21:45–22:30 block both sides. `side=None` callers get legacy block-everything.
- ATR bounds: <1.10 or >4.50 → skip. The >4.50 bound validated live on 09-10
  (12 blocked news-spike SELLs, all would-be SLs).

Engine (engine.py): **BE stop ratchet** — at +`BE_TRIGGER_R = 0.30`·risk, SL
moves to entry; exit reason `BE` = scratch (new `be_exits` counter in
status.json; excluded from wins/losses, cooldown, daily tally). Live: 13 BE
in the first 15 new-stack trades (−$9.54 total, −65% bleed vs pre-BE);
counterfactual says it saved ~$30 of SLs and killed 5 trend TPs (~$34) —
P&L-neutral, variance-reducing in a trend window. Don't retune below n=30.

## 5. Evidence base (don't re-derive)

`docs/ANALYSIS-2026-09-10-losing-trades.md` = full study (45 trades);
`docs/REVIEW-2026-09-10-PM.md` = first 15 trades on the new stack (60 total).
Headlines from 60 trades (2026-09-04 → 09-10), 8W/39L/**13BE**, −$92.05
($500 → $407.95; engine ledger $432.66, drift +$24.71 from the old resets):
- Expectancy ≈ **−0.5R at every TP placement (0.33R–1.5R)** — exits can't
  create edge; entries are the problem long-term. (Pathwalk re-validated on
  all 60: TP-1.5R replay −$90.80 ≈ actual −$92.05.)
- **Blocked signals beat taken ones**: 112 gate-blocked signals replay
  51W/60L raw (sequential 70% / +$127, cooldown-driven) vs 17.0% decisive
  taken → cooldown harshness is the open question; the ATR bound and (pending
  live test) London direction-awareness fixed the clearest cases.
- Losers avg MAE in first ~3 min = −0.98R vs winners −0.28R and BE 0.37R:
  trades that die early never recover (grounds for future time-stop study).
- Re-entry <5 min after an exit: 0W/9L, −23.32 (validates the SL cooldown).
- **RSI<45 entries: 1W/15L/3BE (6% decisive), −$44.01** — nearly half the
  all-time loss from 32% of trades. Candidate filter #1, NOT adopted yet:
  needs the 30-new-regime-trade bar (at 15/30), and BE now converts most
  weak entries to scratches, so incremental value must be re-measured.
- ATR≥2.0 entries: 0W/5L/7BE (0% decisive) — candidate #2, same caveat.
- Prior reviews: `docs/REVIEW-2026-09-09.md`, `docs/REVIEW-2026-09-10.md`,
  `docs/REVIEW-2026-09-10-part2.md`, `docs/REVIEW-2026-09-10-PM.md`.

## 6. Next steps (in order)

1. **Validate live** (~2 weeks from 09-10 deploy; 15/30 new-regime trades
   banked). After each data-collection commit run the read-only tools and
   compare against section 5:
python3 tools/check_data.py # FIRST: 0 fail or stop (BE-aware since PM review)
python3 tools/phantom_trades.py # are the gates LEAVING money now?
python3 tools/pathwalk_sims.py # exit-rule replay vs actual P/L
python3 tools/analyze_losers.py # winner/loser feature drift
python3 tools/validate_gates.py # gate replay incl. RISE120 watch
2. **Queued strategy changes** (evidence order; adopt only at n≥30 new-regime
   trades unless the trigger fires earlier):
   - (a) **RSI≥45 entry filter** (skip RSI<45): adopt if the 6%-vs-23%
     decisive gap holds at n≥30, or sooner if the next decisive low-RSI
     trades keep losing while RSI≥45 holds ≥20%.
   - (b) **BE resets the SL-streak** (cooldown de-escalation): adopt if the
     60-min cooldown keeps blocking trend-side TP clusters.
   - (c) **RISE120 entry gate** (floor rising / ceiling falling): adopt if it
     keeps blocking only losers/scratches with zero blocked wins.
   - (d) **MAX_ATR 4.50→~2.5**: parked; BE already contains high-ATR damage.
3. **LIVE-mode broker-side BE modify** (mt5 order SL update) — only needed
   if/when `TRADING_MODE=LIVE` is switched on.
4. Study a **time-stop / early scratch-cut** (losers die in ~6 min median;
   pathwalk D-tier shows only ~$4–8 of edge — low priority).
5. Study a **risk-halving ratchet** (SL → −0.5R instead of entry) if BE keeps
   killing trend TPs that wicked entry — trigger level can't fix that (MFE
   overlaps), only post-arm placement can.

## 7. How to verify code changes (always)

python3 tools/smoke_test.py # must print "SMOKE TEST PASSED" (scenarios A–J)
python3 -m py_compile engine.py trade_filter.py
python3 tools/check_data.py # expect "0 fail" (gaps warnings are normal)



## 8. Data gotchas (hard-won — read before analyzing)

- `trades.csv` has 3 batches (`Trade_Num` resets on 09-04 due to balance
  resets) — dedupe by timestamp. Schema is 16-field with `Trade_Type`;
  `engine.migrate_trades_csv()` self-heals drift (the 09-10 SELL-row incident).
- **BE rows log the ratcheted stop** (`Stop_Loss` == `Entry_Price`, profit
  ~0). Any R-multiple math must reconstruct the original 2×/3×ATR geometry
  from `ATR_At_Entry` (1R$ ≈ 2×ATR) — all tools in `tools/` already do this.
- **Clock skew**: `forward_test_log.csv` bar timestamps lag `trades.csv` by up
  to ~1 min (different feeds). Any per-trade replay MUST use ±2 min windows,
  or MFE/MAE invert (winners appear to never reach TP).
- Same-minute multi-rows exist (18 min, 19 extra rows — restart
  re-evaluations); `check_data.py` reports them as INFO. Harmless: no trade
  entry/exit falls inside any.
- `phantom_trades.py` reconstruction notes (pre/post gate-change engines,
  reconstruction tolerance) are documented in its docstring.
- Gold price series here is the broker demo feed (~4.4k), not spot.

## 9. File map (short)

`engine.py` signals/execution · `trade_filter.py` risk gates ·
`trades.csv` ledger · `forward_test_log.csv` 1-min bars ·
`skipped_trades.csv` blocked signals (+reason) · `status.json` live state ·
`tools/` analysis+tests · `docs/REVIEW-*.md` data reviews ·
`archive/PROJECT_LOG.md` full history (this file is the executive summary).
