# PROPOSAL 2026-10-23 — Telegram routing: alerts only, trade news in a twice-daily digest

**Status:** implemented on the session branch, awaiting owner sign-off and a dashboard/sidecar
deploy. **No strategy, gate, parameter, exit, sizing or ledger change** — nothing in this
document moves a threshold in `docs/HANDOFF.md` §4, `engine.py`'s trade logic, `trade_filter.py`
or the open structural-stop window. What changes is *which messages are sent* and *when*.

Owner ask (2026-10-23, verbatim intent): *"staring at the screen until we get a go ahead to
trade seems like a long wait… I have many telegram messages, I may miss out on this… maybe we
limit the telegram messages for the indicators only, the rest on the auto trade I possibly
don't need for now."*

---

## 1. The measured problem (why this is not just a preference)

Counted from the checked-in ledger and the skip log, 10 trading days to 2026-10-23:

| source | where | messages/day | what it is |
|---|---|---|---|
| `BUY/SELL SETUP SKIPPED` | `engine.py` | **36.8** | one per *blocked bar*: cooldown minute-ticks, blackout repeats |
| entry alerts (`BUY/SELL #n`) | `engine.py` | 14.0 | the trade being taken |
| exit alerts (TP / SL / BE / TIME) | `engine.py` | 14.0 | how it ended |
| `BE STOP ARMED` | `engine.py` | 4.1 | the ratchet moving the stop (a second message per scratch) |
| autosync digest | `tools/autosync.sh` | 8.0 | every 3 h, healthy or not |
| **box-watch notice** | `tools/box_alert.py` | **≈5.1** (cap 6) | the one message the owner actually reads |
| **total** | | **≈82/day**, worst day in the sample **101** | |

So the wanted message is ~6% of the traffic, and **skips alone are 45%** of it — they carry no
information a reader can act on (the minute countdown is in `skipped_trades.csv`, 1 607 rows,
and in the dashboard). Two failures follow from that: the notice gets buried, and the owner
ends up watching a screen because a message arriving is not the same as a message *worth*
looking at.

## 2. What was built

### 2.1 Engine: messages carry a KIND, and the kinds are selectable

`engine.py` gains `TELEGRAM_KINDS = ("trade", "exit", "skip", "risk", "feed")`,
`notify_kinds(env)` / `notify_enabled(kind, env)` (both pure) and
`send_telegram(text, kind="trade")`:

| kind | messages |
|---|---|
| `trade` | entry alert, LIVE order executed |
| `exit` | TP / SL / BE exit, TIME stop, `BE STOP ARMED` |
| `skip` | `BUY/SELL SETUP SKIPPED` (cooldown / blackout / breaker / ATR) |
| `risk` | sizer refusals, `account_info()` unavailable, `ORDER FAILED` |
| `feed` | stale-feed alert, feed recovered |

Selection is `GOLD_TELEGRAM_KINDS` in `/opt/gold/.env`:

| value | effect | messages/day |
|---|---|---|
| *(unset / blank)* | **send everything — today's behaviour, byte for byte** | ≈82 |
| `feed,risk` | **proposed default**: ops events only | ≈0.2 |
| `none` / `off` / `0` | engine silent | 0 |
| a typo (`trades,exits`) | falls back to **everything** (never silently mutes the bot) | ≈82 |

Filtering is silent by design — a suppressed skip must not become a print flood — the engine
still prints the skip line and still writes every event to `trades.csv`, `skipped_trades.csv`,
`status.json` and `forward_test_log.csv`. **The trading path is untouched:** the same entries,
exits, skips and cooldowns happen whether or not a message is sent. `send_telegram` has a
default of `trade`, so a call site that forgets a kind still sends.

Owner choice recorded this session: **trade messages off** ("silence them entirely"), trade news
moves to the digest (§2.2).

### 2.2 Digest: twice a day, and it becomes the trade report

`tools/autosync.sh`:

* new `GOLD_DIGEST_EVERY_HOURS` (default **12**; `0` restores a digest on every run) and a
  last-sent epoch in `GOLD_DIGEST_STATE` (default `/var/lib/gold/autosync_digest.state`). The
  cron stays at 3 h — a routine digest is simply not *due* on most runs.
* **an incident always sends immediately and is never silenced**, regardless of the clock:
  anything in `$EXTRA` (feed starvation, `check_data` failure, deploy rollback, failed push), a
  deploy that `ROLLED BACK`, `FAILED`, or was skipped for hand-edits on the server, and any
  non-`ok` push. Slowing the routine digest therefore cannot hide a real problem.
* routine digests are sent with `disable_notification=true` (Telegram delivers silently); an
  incident buzzes. A quiet phone now means a healthy box.
* new first line, computed read-only from `trades.csv` since the last digest:
  `🧾 trades: 7 closed (2W/3L/2BE) | net $+4.28 gross`. **Gross of costs**, matching the ledger
  convention in HANDOFF §1 — it is a report, not a costed P&L claim.

### 2.3 The session watch plan — the actual answer to "long wait"

The wait was the complaint, so the fix is not only fewer messages. `pressure.box_plan_next()`
(pure, windowed) + `pressure.box_plan_text()` + `tools/box_alert.py --plan` send **one message
shortly after 07:00 and 13:00 UTC** (London / NY open, 15-minute window, nothing stale after
45 min):

```
🗺 gold watch plan — London open (07:00 UTC bar)
Price $4030.64 · ATR $2.64 · nearest edge: last 4h (240 bars) high $4030.73 (0.03 ATR away)
BUY: notice fires on a close above $4030.28 → entry … / stop … / target … (0.67:1 after $0.55 spread)
SELL: notice fires on a close below $4023.01 → entry … / stop … / target … (0.70:1 after $0.55 spread)
Blocked right now — …
Context (measured, not a gate): ATR 92nd percentile of the last 100 bars; tick volume 0.90× …
Trigger now: closed beyond the 20-bar level (engine's own) high (0.23 ATR)
No edge measured: 0 of 8 box geometries cleared the driftless reference; 74% of breaks close back
inside within 15 min. This is a heads-up, not a signal.
```

* Deduped per (date, session) in the sidecar's own state file, so a 60-second loop sends
  exactly one message per anchor; a missed window sends **nothing** rather than a stale plan
  from an hour earlier. `mock` verified in smoke Scenario X.
* Weekend / daily-break anchors send nothing (`market_quiet`).
* The context lines are the two hints from `docs/INDICATOR-AUDIT-2026-10-23.md`
  (ATR percentile p=0.014, tick-volume ratio p=0.031). **Neither cleared the adoption bar**,
  so the message labels them context, and the no-edge footer rides along. Tick volume is not
  traded volume — VWAP stays out.
* `--loop` sends the plan too; `--no-plan` runs break notices only. `--plan --dry-run` previews.

## 3. Traffic after this change (the point of the exercise)

| | before | after |
|---|---|---|
| engine chatter | ≈69/day | **0** (`GOLD_TELEGRAM_KINDS=none`) or ≈0.2 (`feed,risk`) |
| ops digest | 8/day, all buzzing | **2/day, silent**; incidents still immediate and loud |
| session watch plan | — | **2/day** |
| instant box notice | ≈5.1/day | ≈5.1/day, unchanged |
| **total** | **≈82/day (101 worst)** | **≈7–9/day, at most 4 of them unsolicited** |

## 4. What this explicitly does NOT do

* No change to entries, exits, the BE ratchet, `MAX_HOLD_MINUTES`, ATR bounds, blackouts,
  session windows, `SL_CLEAR_ATR`, `RR_TARGET`, the sizer, or the ledger. `smoke_test.py`
  passes unchanged (Scenario X added; Scenario L's `send_telegram` stub updated for the new
  `kind` argument).
* It does **not** loosen the box-alert rule, and it claims no edge for the alert or the plan.
  Measured: 0 of 8 box geometries cleared the driftless reference; waiting for the held retest
  measured the same −$0.31/trade as entering the break
  (`docs/ANALYSIS-2026-10-20-box-theory-manual-trading.md`,
  `docs/ANALYSIS-2026-10-21-box-chop-retest-alerts.md`).
* It does **not** touch the fired §7 closure-gap trigger, the blocked gap guard, or the
  struct-stop window. Those blockers are unchanged (HANDOFF §1/§6).

## 5. Deploy notes (owner action)

1. `engine.py` changed → **`goldbot` restarts** on deploy (autosync detects `CORE_CHANGED`).
   `status.json` persists, so an open paper trade survives the restart; the restart happens in
   the same 3-hourly window as any other engine deploy.
2. `pressure.py` + `tools/box_alert.py` changed → the dashboard restarts and, **if installed**,
   `boxalert-gold` restarts. The notifier remains optional: per HANDOFF §6/§10 it is not
   installed unless the owner installs `deploy/boxalert.service` — and it now has two jobs
   (instant notice + session plan), so without it neither is sent. Check with
   `python3 tools/box_alert.py --quiet` (reads `Telegram pair found · notifier not running`).
3. Settings to add to `/opt/gold/.env` **after** signing off on traffic:

   ```env
   GOLD_TELEGRAM_KINDS=none        # or feed,risk to keep ops alerts in the chat
   GOLD_DIGEST_EVERY_HOURS=12      # 0 = a digest every 3 h again
   ```
   Nothing needs to be added for the change to be *safe*: with both unset the box behaves
   exactly as it does today.
4. Proof before installing anything: `python3 tools/box_alert.py --once --dry-run`,
   `python3 tools/box_alert.py --plan --dry-run`, `python3 tools/box_alert.py --test`.

**Revert:** unset `GOLD_TELEGRAM_KINDS` (engine back to every message) and set
`GOLD_DIGEST_EVERY_HOURS=0` (digest every run). No code rollback required; `--no-plan` drops the
session message.

## 6. Evidence / reproduction

```bash
python3 tools/smoke_test.py                 # Scenario X: routing + plan (hermetic)
python3 tools/test_box_alert.py             # 34 tests, unchanged
GOLD_DATA_DIR=. python3 tools/box_alert.py --plan --dry-run     # the live message, not sent
python3 - <<'EOF'                           # the volume table in §1
import csv, collections
sk = collections.Counter(r["Timestamp"][:10] for r in csv.DictReader(open("skipped_trades.csv")))
tr = collections.Counter(r["Entry_Time"][:10] for r in csv.DictReader(open("trades.csv")))
print(sum(sk.values()) / len(sk), "skips/day over", len(sk), "days")
EOF
```
