# AUTOSYNC — unattended data sync + safe auto-deploy

`tools/autosync.sh` is the only thing that touches `/opt/gold` unattended. It is the reference
for the questions "do I need to do anything else?", "when did my merge actually go live?" and
"what does the Telegram digest mean?". Referenced from the script header and
`docs/HANDOFF.md` §10. (The script header has pointed at this file since the script was written;
the file itself was missing until 2026-10-13. Ported in shape from `bitcoin-trading-bot`'s
`docs/AUTOSYNC.md`, then rewritten against this script's actual behaviour.)

---

## 1. What the cron line assumes

The crontab lives on the host and is **not in the repo** (not inspected for this doc). The schedule
below is read off the data commits instead: `data collection N` lands at **HH:00:01 UTC every 3 hours**
(00, 03, 06 … 21), which is what

```cron
0 */3 * * * /opt/gold/tools/autosync.sh >> /var/log/gold_autosync.log 2>&1
```

produces. Everything else in this file holds if these are true:

| Requirement | Why | Check |
|---|---|---|
| `/opt/gold` is a git clone of this repo | the script `cd`s there and runs git | `cd /opt/gold && git remote -v` |
| The clone is **on `main`** | `BRANCH=main`: it merges `origin/main` to deploy | `cd /opt/gold && git rev-parse --abbrev-ref HEAD` |
| `tools/autosync.sh` is executable | cron needs the +x bit | `ls -l /opt/gold/tools/autosync.sh` |
| git can **push** to `origin/main` unattended | data commits are pushed every run | `cd /opt/gold && git push --dry-run origin main` |
| cron user is **root** | `systemctl stop/start` the engine | `crontab -l` (root's crontab) |
| `python3` works from that cwd | smoke gate + `check_data.py` + `handoff_check.py` | `cd /opt/gold && python3 tools/check_data.py` |
| `docs/HANDOFF.md` has its snapshot block | the advisory freshness check reads it | `cd /opt/gold && python3 tools/handoff_check.py --quiet` |
| *(optional)* the quote logger `mt5quotes-gold` is running | autosync commits its `xm_data/` and reports its liveness; without it the digest just says `not collecting yet` | `systemctl status mt5quotes-gold` (install: `docs/XM-LOGGER.md` §3) |
| *(optional)* the box notifier `boxalert-gold` is running | the `🔔` line reports it from the sidecar's heartbeat; without it the line says `notifier not running (optional …)` | `cd /opt/gold && python3 tools/box_alert.py --quiet` (install: `deploy/boxalert.service`) |
| No **uncommitted hand-edits** in `engine.py` / `trade_filter.py` / `dashboard.py` / `tools/` | the script refuses to deploy over them | `cd /opt/gold && git status --short` |

`/opt/gold/.env` is read for the Telegram token / chat id but is never committed or required —
without it the script still runs, it just stays silent. The script keeps the pair in its own unexported
variables, so a child process does not inherit it. `tools/box_alert.py` reads the same file itself (§3, `🔔`).

---

## 2. The branch rule (the one that bites) — and what "deployed" means

**Data flows up `main`; code only comes down `main`.** Every run:

1. commits `trades.csv forward_test_log.csv skipped_trades.csv status.json` locally and pushes them
   to `origin/main` (`data collection N`);
2. `git fetch origin main`; **if `origin/main` advanced**, it stops the engine (only when
   `engine.py` / `trade_filter.py` changed), merges (data-file conflicts = server wins, everything
   else = remote wins), runs the smoke gate, rolls back on failure, restarts the engine and checks
   `status.json` is fresh;
3. runs `tools/check_data.py`, the candle-freshness backstop, and `tools/handoff_check.py --quiet`
   (advisory: does `docs/HANDOFF.md`'s snapshot block still match the data it just committed? it never
   blocks a deploy and never touches the incident lines);
4. sends one digest to Telegram (§3).

So a commit on any other branch (an `arena/*` work branch, an open PR) **never reaches the bot**.
**Merging to `main` is the deploy trigger, and the next cron slot is the deploy time.**

### The deploy time is the era boundary — read it from the host, not from the plan

Every experiment in this repo is judged on "entries ≥ the cutover", so the cutover must be the moment
the engine **actually started running the new code**. It is **not** the planned time and **not** the
PR merge time. The structural stop is the worked example (2026-10-06):

| Event | UTC | Source |
|---|---|---|
| Cutover promised in the docs ("next autosync") | 2026-10-05 21:00 | `ANALYSIS-2026-10-05` (wrong) |
| PR #28 merged | 2026-10-06 00:31:53 | `gh pr view 28` |
| **Deployed** (`autosync: merge upstream`, `2f4f4c6`) | **2026-10-06 03:00:04** | `git log --grep 'autosync: merge upstream'` |
| First trade on the new geometry (#499) | 2026-10-06 03:33:05 | `tools/check_structural_stop.py` |

Four trades (#495–#498) entered in the 6-hour gap and ran the **old** rule; counting them as the new
era made the pre-registered "stop inside the level must be 0" check fail on a change that was working.
Rule for the next deploy: take the cutover from `git log --grep 'autosync: merge upstream' --format='%H %cI'`
on the host (or `gh api repos/shashidaren/gold-trading-bot/commits?sha=main`), then confirm it from the
ledger (`check_structural_stop.py` prints the evidence bracket for the structural stop; build an
equivalent invariant for any new runtime change — HANDOFF §7).

### What the dates in the ledger mean

Commits named `data collection N` are the script's own data commits. Don't rebase or squash them
away — `tools/check_data.py` and the analysis tools read the ledger as-is, and a force-push can drop
a trading day's log (which `handoff_check.py` reports as "snapshot AHEAD of the data").

---

## 3. Reading the Telegram digest

```
🤖 gold autosync — 10-13 14:19 UTC
📦 data: committed 0 new trade rows -> 'data collection 227' (push: ok)
🚀 deploy: none
🩺 integrity: 0 fail, 8 warn ==
📈 candles: ok (12 open min since last candle)
📝 handoff: fresh, 2 advisory drift (data moved since the snapshot)
📡 xm logger: OK | 6/14 complete days, 0/2 weekends | rows 17210, outage 0.1 h | spread median $0.25 p95 $0.41 /oz ($0.25/trade median)
💰 equity 197.46 | 110W/248L | daily SLs 5/10 | open trade: yes | updated 2026-10-13 12:00:09 UTC
```

(`committed 0 new trade rows` = only the bar log / status / `xm_data/` changed, no trade closed in this window. Since
the quote logger exists, `xm_data/` is part of every data commit.)

- **📦 data** — `no new data` is the normal weekend / daily-break case; during market hours the 1-minute
  log changes every run, so a data line is expected.
- **🚀 deploy** — `none` means `origin/main` did not move; otherwise one of the states below.
- **🩺 integrity** — the `check_data.py` verdict. `0 fail` is required; warnings are known and informational.
- **📈 candles** — open-market minutes since the last logged candle (weekend / daily break excluded,
  mirroring `engine.is_market_quiet`). `STALE N open min` (> 90) also raises a 🛑 line: the
  engine/feed is starving (2026-09-29 outage; `docs/REVIEW-2026-09-29-feed-outage.md`).
- **📝 handoff** — `tools/handoff_check.py --quiet`: does the machine-checked snapshot block in
  `docs/HANDOFF.md` still describe the data on the box?

  | Text | Meaning | Action |
  |---|---|---|
  | `fresh (snapshot matches the live data)` | the doc and the CSVs agree | none |
  | `fresh, N advisory drift (data moved since the snapshot)` | counts moved inside tolerance (30 closed trades / 48 h) | none, or refresh at the next session |
  | `STALE (N problem(s)): <first problem>` | the doc is behind the data (> 30 closed trades or > 48 h of log), outcomes/money changed with no new trade (ledger edited), the snapshot is *ahead of* the data (lost rows / stale checkout), the cost or cutover config disagrees with the tools, or the doc contradicts itself (a `--cost` command, a reference to a file that does not exist) | next session starts with `python3 tools/handoff_check.py --update`, then rewrites the prose (HANDOFF §11 ritual) |
  | `not run (...)` | `tools/handoff_check.py` or `docs/HANDOFF.md` missing on the box, or no snapshot block | `git pull` the branch that added them |

  **Advisory by design:** it never blocks a deploy, never rolls anything back and never adds a
  🚨/⚠️/🛑 line — a doc that is a dozen trades behind is not an incident, and nagging eight times a
  day would get the digest muted. (Gold's §1 was 8 days and 82 trades behind when this was added.)
- **📡 xm logger** — `tools/xm_quote_report.py --quiet`: is the read-only quote/spec logger
  (`docs/XM-LOGGER.md`) writing, and what is gold costing?

  | Text | Meaning | Action |
  |---|---|---|
  | `xm logger: OK \| N/14 complete days, M/2 weekends \| rows …, outage … h \| spread median $… p95 $… /oz ($…/trade median)` | rows are arriving (newest ≤ 15 min old); the counts are progress towards a decision-grade sample | none |
  | `… \| market closed or feed frozen` appended | the newest row's tick is stale: gold is shut (weekend / daily break) or the feed froze. The **logger is alive** (it keeps writing `STALE` rows) | none, unless it persists through a weekday — then the feed, not the logger, is down (the 🛑 candles line says so too) |
  | `STALE (newest row 3.1 h old - is mt5quotes-gold running?)` + a ⚠️ line | the **logger** stopped: no row for 15+ min. The only case that adds a ⚠️ line (its text carries no changing numbers) | `systemctl status mt5quotes-gold`, `journalctl -u mt5quotes-gold -n 50`; trading is unaffected |
  | `not collecting yet (no quote rows in xm_data)` | not installed, or just started | install per `docs/XM-LOGGER.md` §3 |
  | `report failed to run (<last line>)` | `xm_quote_report.py` crashed (an import error, say) | run it by hand; advisory, the sync is unaffected |

  Advisory by design, like the handoff line: it never blocks a deploy, and the phase runs *after* the deploy
  decision and assigns no deploy variable.
- **🔔 box alerts** — `tools/box_alert.py --quiet`: is the **optional** box-watch Telegram notifier
  (`deploy/boxalert.service`, `docs/ANALYSIS-2026-10-21-box-chop-retest-alerts.md`) switched on, does it have
  the Telegram pair, and is it actually running? The tool reads the pair and its `GOLD_BOX_ALERT*` knobs from
  the environment, then from `$GOLD_DATA_DIR/.env` (autosync passes `GOLD_DATA_DIR=$GOLD_DIR`). That is the
  same `/opt/gold/.env` the engine loads and the unit's `EnvironmentFile=` reads. "Running" comes from the
  heartbeat the sidecar's `--loop` stamps into its own `box_alert_state.json` every tick, not from systemd
  (the 2026-09-29 lesson: a sidecar's own fresh output is the only reliable sign it is alive).

  | Text | Meaning | Action |
  |---|---|---|
  | `Telegram pair found · notifier not running (optional: install deploy/boxalert.service)` | the pair is there but no `--loop` has ever run against this state file, i.e. the unit is not installed. **The default**: installing it is the owner's choice | none, or install it (`deploy/boxalert.service` header: `--once --dry-run`, `--test`, then `systemctl enable --now boxalert-gold`) |
  | `running · N sent today · last MM-DD HH:MM UTC BUY` (`· a candidate is live now`) | the loop's heartbeat is fresh (≤ max(5 min, 3 ticks)); counts come from its state file | none |
  | `notifier STOPPED (last heartbeat MM-DD HH:MM UTC) · …` | it **was** running and its heartbeat went stale: the unit died or was stopped | `systemctl status boxalert-gold`, `journalctl -u boxalert-gold -n 50`; trading is unaffected |
  | `disabled (GOLD_BOX_ALERTS=0)` | switched off on purpose (environment or `.env`) | none |
  | `not configured (no TELEGRAM_BOT_TOKEN/CHAT_ID in the environment or /opt/gold/.env)` | no pair anywhere. The digest itself needs the same pair, so you will usually see this only in `/var/log/gold_autosync.log` | add the pair to `/opt/gold/.env` |
  | `report failed to run (<last line>)` | `box_alert.py` crashed (an import error, say) | run it by hand; advisory, the sync is unaffected |

  **Before 2026-10-21's fix, the 18:00 UTC digest said `not configured (no TELEGRAM_BOT_TOKEN/CHAT_ID)` in the
  very message the pair had just delivered.** This script keeps the pair in its own *unexported* `TG_TOKEN` /
  `TG_CHAT` for `curl`, so a child process never inherits it, and the tool then read only its environment. The
  line also could not tell "pair found" from "notifier running". Both are fixed, as above. Advisory by design:
  it never blocks a deploy and never adds a ⚠️/🛑 line, even for `STOPPED`, because the notifier is opt-in and
  not part of the trading path.
- **💰 stats** — straight from `status.json`.

### Deploy states and what they mean

| Digest text | Meaning | Action |
|---|---|---|
| `deployed <sha> (code files: N, smoke: ok)` | merged, smoke test passed, engine restarted if core files changed | none — **and note the time: that is the cutover** (§2) |
| `none` | nothing to deploy | none |
| `SKIPPED (AUTO_DEPLOY=0)` | data-only mode | expected if you set it |
| `SKIPPED - local code edits detected on server` | someone hand-edited code on the box | `cd /opt/gold && git status` → commit or `git checkout -- <file>` |
| `ROLLED BACK (smoke=FAIL)` + 🚨 | the smoke gate failed after merging; code was reset to the pre-merge SHA | read `/tmp/autosync_smoke.log`, fix, re-merge |
| `push FAILED` + ⚠️ | data is safe in a **local commit**, retried next run | fix git credentials on the box |
| `engine service NOT FOUND - restart engine manually` + ⚠️ | `detect_service` found no systemd unit that references `/opt/gold` **and** `engine.py` | restart manually, or set `ENGINE_SERVICE=` in the crontab |
| `engine active but status.json looks STALE` | the unit is up but has not written state for 3+ minutes | check `journalctl -u goldbot` |

Machine-readable history: `/var/log/gold_autosync.log` (each run's `done.` line ends with
`handoff=[…] xm=[…] boxalert=[…]`). Per-run detail: `/tmp/autosync_smoke.log`, `/tmp/autosync_check.log`,
`/tmp/autosync_handoff.log`, `/tmp/autosync_xm.log`, `/tmp/autosync_boxalert.log`.

**Deploying a change to `autosync.sh` itself is safe.** The running bash holds the old file open and `git merge`
replaces files by unlinking and re-creating them, so the in-flight run keeps reading the *old* copy to the end and
the *next* cron run uses the new one. Checked in a sandbox on 2026-10-13 (a bare origin plus a server clone, stubbed
`curl`/`systemctl`): the old script merged a new `autosync.sh` mid-run, ran the smoke gate and finished cleanly. The
consequence for reading logs: the run that deploys a new phase does **not** run it; the next one does.

---

## 4. What a deploy does to a running trade

Safe: the engine restores an open trade from `status.json` and re-seeds its stats and slope history
from `trades.csv` / `forward_test_log.csv` on start, so a restart mid-trade resumes the same trade
(including its structural stop; smoke Scenario N). The engine is only stopped and restarted when
`engine.py` or `trade_filter.py` changed (`CORE_CHANGED`); a `dashboard.py` change only restarts the
dashboard; a tools-only or docs-only change restarts nothing.

The smoke gate runs before the restart, so a broken commit is rolled back *before* the engine ever
loads it. That makes `tools/smoke_test.py` **the deploy gate, not just a dev tool**: `autosync.sh` reads
only its exit code (`SMOKE TEST PASSED` / `sys.exit(1)`), and it runs on **any** `*.py` change. Two
consequences for anyone adding a scenario:

- it must be **hermetic** — synthetic data in a temp dir, never the live CSVs (they change every 3 h);
- it must not depend on the **wall clock** or on a constant that is legitimately changed later
  (Scenario O pins `LIVE_CUTOVER` for this reason). A scenario that goes red only in some hours, or
  after a routine data drop, will roll back a good deploy.

---

## 5. Tuning (environment variables, set in the crontab line)

```cron
0 */3 * * * AUTO_DEPLOY=1 SMOKE_GATE=1 NOTIFY=always /opt/gold/tools/autosync.sh >> /var/log/gold_autosync.log 2>&1
```

| Var | Default | Effect |
|---|---|---|
| `GOLD_DIR` | `/opt/gold` | repo location |
| `REMOTE` / `BRANCH` | `origin` / `main` | what to sync against |
| `AUTO_DEPLOY` | `1` | `0` = commit/push data only, never pull or restart |
| `SMOKE_GATE` | `1` | `0` = deploy without the smoke test (**not recommended**) |
| `NOTIFY` | `always` | `always` = a digest every run (8 a day at the 3-hour cadence); `quiet` = skip a run only when nothing changed (`no new data`, no deploy, push ok, no 🚨/⚠️/🛑) — which on gold is mostly weekends, because the minute log changes every run during market hours |
| `ENGINE_SERVICE` / `DASHBOARD_SERVICE` | auto-detect | pin the systemd unit names if detection fails |
| `BOXALERT_SERVICE` | auto-detect | pin the optional box-alert unit, restarted when `tools/box_alert.py` or `pressure.py` changes; absent = nothing to restart |
| `LOCK_FILE` | `/var/lock/gold_autosync.lock` | `flock` guard; overlapping runs exit 0 |

At eight messages a day the digest is chatty but not the flood BTC had (its 15-minute cron sent ~96 a
day, which is why BTC's autosync grew `NOTIFY=alerts`: deploys and *changes* of incident state
immediately, one `(daily)` summary per UTC day, identical repeats suppressed). That policy is **not**
ported here: the owner decided on 2026-10-13 to leave notifications as they are
(`docs/ANALYSIS-2026-10-13-btc-port-assessment.md` §3, item 4). If it is ever wanted, port BTC's `alert_once` +
daily stamp and keep `always` as the one-line revert.

One thing to know before ever setting `NOTIFY=quiet`: with the quote logger installed `xm_data/` changes on every
run, so `no new data` is never true and quiet mode stops going quiet. `always` is unaffected.
