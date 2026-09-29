# Review — 2026-09-29 feed outage (silent 6-h starvation after a host reboot)

**Type:** ops / detection fix. **No strategy, gate or parameter change** — the
max-hold isolation window (deploy 09-21, re-review ~10-05) is undisturbed.

## 1. What the user saw

The dashboard showed **STALE** next to `Last update: 2026-09-29 08:29:19`.
That badge is correct: `status.json` was never rewritten after 08:29:19 UTC, so
`_stale_info()` (5-min threshold) had been firing for ~6 h when it was checked.

## 2. Evidence chain (all UTC)

| Time | Evidence |
|------|----------|
| 08:29:15 | `goldbot.service` stopped; journal shows `-- Boot c22469d0… --` → **the host rebooted** |
| 08:29:18 | `goldbot.service`, `mt5feed.service` and `mt5.service` all started by systemd |
| 08:29:19 | engine restart: `Loaded trade stats -> next_trade=#404`, `MT5 feed file found`, `Loaded 200 candles`, forward test starting |
| — | `mt5.service` (MetaTrader terminal) never came back: `systemctl \| grep mt5` showed it stuck in **`deactivating stop-sigterm`** (6 h later, still stuck) |
| 08:29 | `/opt/gold/mt5_last_candle.json` **mtime frozen**; payload `ts = 1790681280` = 11:28 MT5-server time = **08:28 UTC** candle — the last bar the terminal ever produced |
| 08:29:19 | `/opt/gold/status.json` mtime frozen at this second (last `save_status()` call) |
| 09:00 / 12:00 / 15:00 | autosync runs: `data: no new data`, push ok, `check_data.py` **0 fail** — all green |
| repo | `origin/main` tip `data collection 141` @ 08:34:01; no commit since → no live data for 6 h+ |

The engine (`goldbot.service`) was **`active (running)` the whole time** — it
was not the thing that died.

## 3. Why nothing alerted (the actual bug)

`run_mt5_test()` looped as follows (pre-fix):

```python
rates = self.read_mt5_feed()
if rates is not None and len(rates) > 0:
    candle = self.mt5_next_candle(rates, last_ts)
    if candle is None:
        time.sleep(5)
        continue          # <-- same closed candle forever: skips the guard below
    ...
else:
    print("MT5: no feed ...")   # file *missing* case only
    time.sleep(5); continue
# stale-feed guard lived HERE
stale = self.feed_stale_seconds()
if stale > STALE_FEED_SECONDS: ...
```

The sidecar kept the frozen file in place (it never deletes it), so the engine
took the `candle is None` path: sleep 5 s, `continue` — **past the stale-feed
guard**, `save_status()`, and every print. Two consequences:

1. **No journal line and no Telegram alert**, ever. `journalctl -u goldbot -n 80`
   ends at the 08:29:19 startup block — zero output for 6 h.
2. **The guard could not have fired anyway.** `feed_stale_seconds()` reads
   `_last_price_mono`, which is only set when a *new* candle is accepted. After
   a restart `last_ts` is restored from `status.json`, the frozen candle is
   deduped, so `_last_price_mono` stays `None` → the function returns `0.0`
   forever ("fresh"). This is why a heartbeat-based check was needed, not just
   moving the guard.

`status.json` is only written from `__init__`, `evaluate_candle()` and trade
events, so a starving engine freezes it too — which is why the dashboard's
STALE badge was the *only* working detector of the whole failure.

## 4. Precursor: it had already happened once, undocumented

The price log hides a second stall in the same 24 h:

| Gap | Length | Open-market minutes |
|-----|--------|---------------------|
| 2026-09-28 17:50:05 → 2026-09-29 03:33:37 | 583.5 min (9.7 h) | ~283 |
| 2026-09-29 08:29:19 → (recovery) | 6 h+ | 6 h+ |

The first one is not mentioned in any doc, and it produced trade **#398**'s
entry at 03:33:37 — i.e. the engine picked up the moment the feed resumed, with
no trace that 283 market minutes were missing. Same signature as the reboot
outage: a dead terminal publishing nothing, an engine looping silently. The
"09-27/09-28 slide" discussion in the handoff never noticed the hole.

## 5. Impact

- ~6 h of London/NY session missing (08:29 → recovery) plus ~283 open minutes on
  09-28. The engine logs one row per closed minute and does **not** backfill, so
  those signals are simply not in the forward test.
- **No position was open across either gap**: #397 exited 09-28 17:40:02 (SL),
  #403 exited 09-29 07:51:03 (SL), `trade_active: false`. No phantom P&L, no
  unreliable exit price.
- Ledger frozen at **402 closed trades, 64W/166L/172BE/0TIME, 27.8% decisive,
  true P&L −$254.99 → $245.01, engine ledger $261.98** (drift +$16.97).
- Nothing about the strategy conclusions changed; the eras merely stopped
  collecting for 6 h.

## 6. Fix shipped with this review (detection only)

`engine.py`:
- `feed_publisher_age_seconds()` — mtime age of `MT5_FEED_FILE`. The sidecar
  rewrites the file every poll (5 s) **even when the market is closed**, so a
  stale mtime means the *publisher* died, not that the market is quiet.
- `mt5_feed_problem()` — returns a reason for (1) missing/unreadable file,
  (2) stale heartbeat (`MT5_FEED_PUBLISHER_STALE_SECONDS = 180`), (3) corrupt
  payload, (4) no accepted candle > `STALE_FEED_SECONDS` **during market hours**
  (`is_market_quiet()` suppresses the weekend/daily-break case, so a closed
  market with a live heartbeat stays silent).
- `report_mt5_feed_problem()` / `report_mt5_feed_recovered()` — journal print
  every 5 min (so `journalctl -u goldbot` shows the outage), Telegram alert on
  the existing 30-min cooldown (now with MT5 wording via a new `detail=` arg),
  quiet-hours suppression kept, and one recovery line when a new candle lands.
- The health check now runs **before** the dedup `continue`, which is the only
  place it can see a frozen file.
- `read_mt5_feed()` records its failure reason for the message.

`tools/smoke_test.py`: **Scenario L** covers missing file, frozen file with no
price event (the post-restart case: `feed_stale_seconds() == 0.0`), corrupt
payload, quiet-market silence, alert rate-limit + wording, single recovery, and
that recovery only happens on a newly accepted candle.

`tools/autosync.sh`: new phase-4b digest backstop — counts **open-market**
minutes since the last logged candle (weekend/daily break excluded, mirroring
`is_market_quiet`) and adds `📈 candles: STALE N open min …` + a 🛑 line to the
3-hourly digest when it exceeds 90. Verified against real data: today's outage
flags at the 12:00 run (215 open min), Saturday/Sunday runs and the post-weekend
resume stay quiet.

## 7. Ops follow-ups (server-side, not in this repo)

1. **`mt5.service` hardening** — it hung in `deactivating` for 6 h, which is why
   nothing restarted it:
   ```bash
   sudo systemctl edit mt5.service     # drop-in:
   # [Service]
   # Restart=always
   # RestartSec=10
   # TimeoutStopSec=30
   # KillMode=control-group
   sudo systemctl daemon-reload && sudo systemctl enable mt5.service
   ```
2. **Recovery runbook** after a terminal/feed loss:
   ```bash
   sudo systemctl status mt5 mt5feed goldbot
   sudo systemctl stop mt5.service          # it is stuck; stop, then (if needed)
   sudo systemctl kill -s SIGKILL mt5.service
   sudo systemctl start mt5.service         # terminal up + logged in
   sudo systemctl restart mt5feed           # re-init the MT5 IPC handle
   cat /opt/gold/mt5_last_candle.json       # updated_at advancing?
   # goldbot resumes by itself on the next 5-s poll; verify:
   tail -1 /opt/gold/forward_test_log.csv
   ```
3. Optional: make `tools/mt5_feed.py` exit after N consecutive empty polls so
   systemd (`Restart=always`) surfaces a failed unit instead of a wedged one.
   Not shipped — the engine-side alert + autosync backstop cover detection.
4. Watch item: two stalls in 24 h on the same box → treat the Wine MT5 terminal
   as the least reliable component in the stack. `uptime`/`journalctl -b -1`
   for the 08:29 reboot cause is still unexplained.

## 8. Verification on this snapshot

- `python3 tools/smoke_test.py` → **SMOKE TEST PASSED** (A–L, 0 fail)
- `python3 -m py_compile engine.py trade_filter.py tools/*.py` → clean
- `python3 tools/check_data.py` → **0 fail / 8 warn** (known warnings only)
- `python3 tools/win_rate_report.py` → runs end-to-end (402 trades)
- `bash -n tools/autosync.sh` → clean; freshness logic dry-run on the real log:
  `STALE 215 open min (last candle 2026-09-29 08:29:19 UTC)` at a simulated
  12:00 run
