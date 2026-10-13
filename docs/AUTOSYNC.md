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
| No **uncommitted hand-edits** in `engine.py` / `trade_filter.py` / `dashboard.py` / `tools/` | the script refuses to deploy over them | `cd /opt/gold && git status --short` |

`/opt/gold/.env` is read for the Telegram token / chat id but is never committed or required —
without it the script still runs, it just stays silent.

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
💰 equity 197.46 | 110W/248L | daily SLs 5/10 | open trade: yes | updated 2026-10-13 12:00:09 UTC
```

(`committed 0 new trade rows` = only the bar log / status changed, no trade closed in this window.)

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
`handoff=[…]`). Per-run detail: `/tmp/autosync_smoke.log`, `/tmp/autosync_check.log`,
`/tmp/autosync_handoff.log`.

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
| `LOCK_FILE` | `/var/lock/gold_autosync.lock` | `flock` guard; overlapping runs exit 0 |

At eight messages a day the digest is chatty but not the flood BTC had (its 15-minute cron sent ~96 a
day, which is why BTC's autosync grew `NOTIFY=alerts`: deploys and *changes* of incident state
immediately, one `(daily)` summary per UTC day, identical repeats suppressed). That policy is **not**
ported here — it changes what reaches the owner's phone, so it is the owner's call
(`docs/ANALYSIS-2026-10-13-btc-port-assessment.md` §3, item 4).
