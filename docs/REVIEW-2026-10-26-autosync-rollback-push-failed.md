# REVIEW — 2026-10-26 autosync digest: "deploy ROLLED BACK" + "push to origin FAILED" (PR #61 deploy)

**Date:** 2026-10-26 ~16:00–16:25 UTC
**Type:** ops incident review. **No strategy, gate, parameter or ledger change. No code change in this PR**
(docs only → `autosync` restarts nothing when it merges it).
**Trigger:** the 15:38 UTC digest — `🚨 deploy rolled back - start a review session` and
`⚠️ push to origin failed`.

## 0. Verdict

**All good (as of ~16:00 UTC): no data was lost, nothing is stuck, and the PR #61 deploy is live.** The digest described the
*first* of two autosync runs ~80 s apart. Run #1 could not merge PR #61, rolled back, and its push was
(necessarily) rejected. Run #2 merged, passed the smoke gate, deployed and pushed everything — including run
#1's data commit. `origin/main` = `d4686f8` holds every data row. **The two alerts are one event, not two: the
push failure is a symptom of the rollback, not a credentials problem.**

Three things remain open, none of them urgent:

1. **Why run #1's merge failed.** GitHub cannot say and the script threw the evidence away (§5). Ruled out: a
   merge conflict, the smoke gate, credentials, data-file overlap.
2. **The running engine after the 15:39 restart** cannot be seen from the repo until the 18:00 data commit, and
   **silence is not evidence of health** — a dead engine after a *successful* merge sends no message (§6).
3. **Seven defects in `tools/autosync.sh`** that made this digest misleading and hard to diagnose (§7).
   Proposed, **not applied**: it is the unattended deploy path and each fix needs an owner decision.

## 1. What the owner saw (15:38 UTC digest, abridged)

```
🧾 trades: 6 closed (0W/5L/1BE) | net $-20.04 gross
📦 data: committed 1 new trade rows -> 'data collection 351' (push: FAILED (data is safe in a local commit; retries next run))
🚀 deploy: ROLLED BACK (smoke=not run (no code change)) - needs a manual look
🩺 integrity: 0 fail, 8 warn      📈 candles: ok (5 open min)
📝 handoff: STALE (2 problem(s)): log_last_bar_utc +66.7 h of log since the snapshot
💰 equity 124.34 | 142W/308L | daily SLs 7/10 | open trade: no | updated 2026-10-26 15:38:04 UTC
🚨 deploy rolled back - start a review session      ⚠️ push to origin failed
```

## 2. Timeline (UTC; every commit read from the GitHub API)

| Time | Commit | Event |
|---|---|---|
| 15:00:01 | `dc330a5` | `data collection 350` — the normal cron slot; pushed fine |
| 15:33:21 | `0f7f71e` | **PR #61 merged** on GitHub (17 files: engine LIVE-path hardening, Readiness tab, docs; **0 data files**) |
| 15:37:50 | `fde881a` | `data collection 351` — **run #1** (off the 3-hourly grid, so a forced run). Carries trade **#711** |
| ~15:38 | — | run #1: `git merge` fails → rollback to `fde881a` → `git push` rejected (origin has `0f7f71e`) → digest above |
| 15:39:09 | `fd2746e` | `data collection 352` — **run #2**, parent is `fde881a` (the local commit survived the rollback) |
| **15:39:13** | `d4686f8` | `autosync: merge upstream` — parents `fd2746e` + `0f7f71e`. **This is the deploy.** Smoke gate passed (a failed gate would have reset it away and it would not be on GitHub) |
| ≈15:39:24 | — | engine + dashboard restart (derived from the script's order and the measured 10.6 s smoke run; exact line is in the box log) |

Per `docs/AUTOSYNC.md` §2 the **cutover is the host's merge commit: `d4686f8`, 2026-10-26 15:39:13 UTC** — not the
PR merge (15:33:21) and not the failed attempt (15:37:50).

## 3. The two alerts, explained

### 3.1 ⚠️ "push to origin failed" — a symptom

`autosync.sh` order is: commit data → merge/rollback → **push**. After run #1's rollback the local branch was
`…350 → 351` while `origin/main` was `…350 → PR#61`. Neither contains the other, so `git push origin main` is a
non-fast-forward rejection by construction. The script discards push stderr (`>/dev/null 2>&1`), so the literal
message cannot be shown — but run #2 pushed 351, 352 and the merge from the same box with the same credentials
(all three are on GitHub, authored `gold-autosync <autosync@metatrade>`), and the 15:00 push worked too.
**Credentials are fine.** The same "push failed" appears whenever the merge does not happen while origin is
ahead (reproduced for a hand-edited code file too, §5 S2).

### 3.2 🚨 "ROLLED BACK (smoke=not run (no code change))" — the merge failed; the label is wrong

The rollback condition is `MERGE_RC != 0 || SMOKE == FAIL`. The smoke gate only runs when the merge succeeded, so
`smoke=not run` means **`git merge` itself failed**. The words "(no code change)" are just the variable's default
string and were printed although the incoming change had **8 `.py` files, including `engine.py`** (replayed
below: `CODE_CHANGED=8 CORE_CHANGED=1 DASH_CHANGED=3`). Anyone reading the digest would look at the smoke gate,
which never ran.

## 4. Verification

Everything below was run on the merged tree (`d4686f8`) unless stated. "Replay" = a scratch worktree of the
box's exact HEAD.

| # | Check | Result |
|---|---|---|
| 1 | Data commits are on `origin/main` | `d4686f8` → `fd2746e`(352) → `fde881a`(351) → `dc330a5`(350): both run-#1/#2 data commits are ancestors |
| 2 | Is the deploy commit a *pure* merge? | Re-merged `fd2746e` + `0f7f71e` in a scratch worktree: tree `9b7e32f…` **identical** to `d4686f8`'s. Nothing stray, nothing dropped |
| 3 | Replay of run #1's exact merge (clean tree, at `fde881a`) | **exit 0, zero unmerged files**, 17 files `+2054/−138` — same stats as the real merge. A textual conflict cannot have caused the failure |
| 4 | Digest numbers vs ledger | 351 added exactly one row, **#711** (BUY 15:20:03→15:28:04, SL, −3.42, balance 124.34). Trades closed after ~06:00 = **6 (0W/5L/1BE), net −20.04** — the digest reproduced to the cent. `status.json`: equity 124.34, 142W/308L, `daily_losses 7/10`, `next_trade_num 712`, no open trade |
| 5 | Ledger integrity | #704→#711 contiguous, balance chain exact. The only anomalies are the old known ones (duplicate numbers #1–3, #171, #697; balance-chain breaks at #1, #12–13, #331) |
| 6 | Bar log across both engine restarts | 51 435 bars to 15:39:04: **0 gaps > 90 s since 12:00, 0 non-increasing timestamps**. Quote logger (30 s cadence): 0 gaps > 75 s since 14:00; reopens its file on every append, so a git file-replace cannot orphan a handle |
| 7 | Restart safety | No trade was open at either restart (#711 closed 15:28:04). Daily-loss count is recomputed from the ledger every save, so a restart cannot forget it |
| 8 | Deploy gate `tools/smoke_test.py` | **PASSED — 484 checks, 0 failures**, 10.6 s |
| 9 | Unit suites | `test_live_readiness` 18, `test_readiness_tab` 16, `test_dashboard_context` 17, `test_box_alert` 35, `test_box_report` 14, `test_box_watch` 6, `test_manual_chart` 32, `test_signal_outlook` 9, `test_repair_phantom_ledger` 7, `goldbot` 64 — **all OK (218)** |
| 10 | `check_data.py` | `0 fail, 8 warn` — identical to the digest; every warning is documented history; `status.json agrees with trades.csv` |
| 11 | `handoff_check.py` | **FRESH (2 advisory drift)** on the merged tree. On the *pre-merge* tree (`fde881a`) it prints **exactly the digest's line**, `STALE (2 problem(s)): log_last_bar_utc +66.7 h` (snapshot as_of 2026-10-23 20:57). The stale-handoff alert was a **consequence of the rollback** (old `HANDOFF.md`), not a separate problem. No `--update` needed |
| 12 | Era guards | `check_structural_stop.py` **PASS** (n=214, 0 stops inside level, bracket #498/#499 intact); `check_gap_rides.py` unchanged at **3/2**; `pressure_report` SCREEN MET, n=214 |
| 13 | LIVE gate | `live_readiness.py` **9 PASS / 8 TODO / 3 MANUAL — CLOSED**; `--strict` exits 1. `TRADING_MODE` still `FORWARD_TEST`, no order path opened |
| 14 | **Is the paper path really unchanged?** (`engine.py`, before = `dc330a5`) | AST comparison of all 112 top-level definitions: **103 identical** (incl. `evaluate_candle`, entry gates, SL/TP, BE ratchet, guards, ledger writers), 5 added (`live_armed`, `resolve_order_filling`, `restore_live_bar_ts_from_status`, 2 constants), 0 removed, **4 changed**: `run_live` and `execute_live_trade` (LIVE only, never called in paper), `__init__` (one extra fail-open read of `status.json`) and `save_status` (one extra key). |
| 15 | Startup of the *real* engine class on the *real* committed data, old vs new | Identical state: FORWARD_TEST, 200 bars seeded, same EMAs, equity 124.34, 142W/308L, `daily_losses 7`, `next_trade_num 712`, same candle watermark. **Only difference: `status.json` gains `"live_last_candle_ts": null`** |
| 16 | Consumers of that new key | `check_data`, `handoff_check`, `box_alert`, autosync's `STATS` snippet and the dashboard (HTTP 200 on all tabs, Readiness tab renders gate CLOSED / 9·8·3 and all 20 check ids) all accept it |
| 17 | The *next* cron run uses the new `autosync.sh` | Sandboxed a normal data-only cycle with the post-merge script (S5): data commit, push ok, `deploy none`, `0 fail`, handoff fresh. `bash -n` clean |

Note on check 14: smoke Scenario AA is titled "the paper strategy is byte-for-byte unchanged by LIVE hardening"
but asserts only four constants (`TRADING_MODE`, `SL_CLEAR_ATR`, `GUARD_CUTOFF_MIN`, `BE_TRIGGER_R`). The claim is
**true** (check 14) but the test does not prove it; worth renaming or backing with a golden-trade comparison.

## 5. Why did run #1's merge fail?

**Ruled out:** a textual conflict (check 3); the smoke gate (never ran); credentials (§3.1); overlap with data
files (PR #61 touches none); an `autosync.sh` self-update (run #2 did the same merge fine; PR #61's script diff is a
path-list widening); a concurrent `git` from a service (only `handoff_check.py` runs a read-only `git log`, inside
autosync itself; the units shipped in `deploy/` run as root).

**Not knowable from GitHub:** `git merge`'s own output and the working-tree state at 15:37:5x — the script sends
merge output to `/dev/null`, logs the same "merge conflict - resolving" line for *any* non-zero exit, and the
rollback's `git reset --hard` erases uncommitted state.

**Reproduction.** The situation was rebuilt with the *real* pre-merge `autosync.sh` against a bare origin + server
clone (real PR #61 tree, real `data collection 351` diff left uncommitted in the working tree; `systemctl`,
`curl`, `sleep` stubbed — Appendix A):

| Scenario | Server state | Observed |
|---|---|---|
| **S0** control | clean, only live data | `deployed … (code files: 8, smoke: ok)`, push ok — matches the real run #2 |
| **S1** | a tracked **doc** edited and uncommitted (`handoff_check.py --update`, which the digest/doc tell operators to run when STALE) | **the digest, line for line**: `ROLLED BACK (smoke=not run (no code change))`, `push: FAILED (data is safe in a local commit…)`, `handoff: STALE … +66.7 h`, both alert lines. Edit wiped by the rollback. **Retry merges and pushes** — the real timeline, including the same graph shape |
| **S2** | a tracked **code** file edited | `SKIPPED - local code edits detected on server`, edit preserved — the guard working as designed (push "fails" here too) |
| **S3** | an *untracked* `readiness.py` already on disk | rollback, **and the retry fails identically** (untracked files survive `reset --hard`) — fits the evidence badly |

**Best-fitting class (reproduced, not proven): an uncommitted change to a tracked file that PR #61 also changed
and that the hand-edit guard does not cover.** The guard checks `engine.py trade_filter.py dashboard.py
pressure.py chart.py goldbot/ tools/` only, so a dirty *code* file gives a clean `SKIPPED`, but a dirty *doc* makes
`git merge` refuse. PR #61 changed exactly six unguarded files, so if this was the cause it was one of:
`README.md`, `archive/PROJECT_LOG.md`, `docs/AUTOSYNC.md`, `docs/EXECUTION-PLAN.md`, `docs/HANDOFF-HISTORY.md`,
`docs/HANDOFF.md`. The rollback then wiped the edit, which is why the identical retry succeeded. There is **no
evidence anyone edited the box**; other transient causes (a one-off `index.lock` from an operator's own
`git status`, a hook, disk) fit equally and cannot be excluded. The box log shows `merge conflict - resolving`
followed by `deploy failed (merge_rc=1 …)` for all of them — it cannot discriminate.

## 6. What I could not verify — and why silence is not proof

* **The engine running since ≈15:39:24.** The repo's last data is commit 352 (15:39:09); no bar from the new code
  is on GitHub yet. Offline evidence is strong (checks 8–17) but not runtime evidence.
* **After a successful merge, a dead engine is silent.** Reproduced (S4): merge ok + engine fails to come back +
  a digest sent <12 h ago → log says `deployed … ; ENGINE SERVICE NOT ACTIVE`, **0 Telegram messages**.
  `ENGINE SERVICE NOT ACTIVE` and `engine active but status.json looks STALE` do not set the incident flag. The
  only automatic backstop is `📈 candles: STALE` after 90 open-market minutes — the 18:00 UTC run at the earliest.
  So the lack of a second digest after 15:39 means nothing either way.

## 7. `tools/autosync.sh` defects found (proposed, none applied)

| # | Defect | Evidence | Proposed fix | Risk |
|---|---|---|---|---|
| D1 | `smoke=not run (no code change)` is printed when the merge failed | §3.2; S1 | `SMOKE="not run (merge failed)"` when `MERGE_RC≠0`; say "no code change" only when `CODE_CHANGED=0` | none (text) |
| D2 | `git merge` / `git push` output discarded; "merge conflict - resolving" logged for any failure | §5 | tee both to `/tmp/autosync_merge.log` / `_push.log`; log first lines + `git status --short`; one-line reason in `DEPLOY_MSG` / `PUSH_MSG` (keep the `ROLLED BACK` / `FAILED` tokens that trigger the incident path) | none (logging) |
| D3 | Rollback is destructive: `git reset --hard "$PRE_MERGE"` also deletes uncommitted edits **and live rows written since the phase-1 commit** | S1: the row the "engine" wrote after the commit was gone; never committed → unrecoverable | `git merge --abort` for a conflicted merge; no reset if nothing merged; otherwise re-commit data first (or `git reset --keep`) | medium — changes rollback semantics |
| D4 | Hand-edit guard ignores docs | S1 vs S2 | widen to every tracked path except `DATA_FILES` | medium — could turn deploys into `SKIPPED` if something on the box is routinely dirty |
| D5 | Post-deploy `ENGINE SERVICE NOT ACTIVE` / `status.json STALE` are not incidents | S4 | add them to the incident `case` and `EXTRA` (⚠️ line) | low (more alerts) |
| D6 | Rollback still stops/starts the engine although no new code loaded | S1 `systemctl` log | skip restart when rolled back | low |
| D7 | `tr … < "$DIGEST_STATE" 2>/dev/null` prints "No such file or directory" when the state file is absent | S0, S5 | redirect inside a group / test `-f` first | none (cosmetic) |

Recommendation: ship **D1 + D2 + D5** together (observability only, ~25 lines, verifiable with the Appendix
harness) and decide **D3/D4** separately. In this incident D3 cost nothing — the engine was stopped for the window
and the bar log has no hole — but a docs/dashboard-only deploy (`CORE_CHANGED=0`) leaves the engine writing
through the whole merge-and-smoke window.

## 8. Record for the deploy ledger

| Item | Value |
|---|---|
| Deployed | PR #61 (`0f7f71e`) via `autosync` merge **`d4686f8`, 2026-10-26 15:39:13 UTC** |
| Engine | no open trade at the restart. **Inferred from the script's order — confirm with §9:** restarted ≈15:39:24, ≈15–20 s down, no bar missed (bars land at :04), first bar from the new code ≈15:40. **Paper behaviour unchanged** (check 14); `status.json` gains `live_last_candle_ts: null` |
| Dashboard | restarted (`DASH_CHANGED=3`) — Readiness tab live |
| Era boundaries | **none moved.** Struct-stop era still entries ≥ 2026-10-06 03:00 UTC (n=214); no runtime variable changed |
| Failed attempt | 15:37:50 — rolled back, no new code ever ran |
| Live gate | CLOSED (9 PASS / 8 TODO / 3 MANUAL) |

## 9. Box-side checks (all read-only)

```bash
cd /opt/gold
git fetch origin main -q && git status -sb | head -3     # expect ## main...origin/main — never "behind"
git log --oneline -5                                      # expect d4686f8 / fd2746e / fde881a …
git push --dry-run origin main                            # expect Everything up-to-date (or a plain fast-forward)
grep -n "15:3[789]" /var/log/gold_autosync.log            # run #1: merge_rc=1 + push FAILED; run #2: deployed d4686f8
systemctl is-active goldbot                               # + the dashboard unit (systemctl list-units | grep -i dash)
journalctl -u goldbot --since "15:39" --no-pager | head -30   # start-up block, no Traceback
tail -n 3 forward_test_log.csv                            # newest bar within ~2 min of `date -u`, later than 15:39:24
python3 -c "import json;s=json.load(open('status.json'));print(s['last_update'],'live_last_candle_ts' in s)"
#   -> fresh timestamp + True = the NEW engine is the one running (the old one never writes that key)
history | grep -n "handoff_check\|nano\|vi " ; git -C /opt/gold reflog -8   # was anything edited on the box?
```

**Before merging this PR:** `git -C /opt/gold status --short` should list only data files. This PR touches three
docs, i.e. the very class of file that (§5) can make a merge refuse and trigger another rollback.

## Appendix A — sandbox harness (throw-away, lives in `/tmp/sim`)

`systemctl` stub: `list-units` → `goldbot.service`, `golddash.service`; `cat` → an `ExecStart=… /tmp/sim/gold/engine.py`
/ `dashboard.py`; `is-active` → 0 unless `/tmp/sim/engine_down` exists; `stop` runs `/tmp/sim/on_stop.sh` (S1 uses it
to append a bar "after the data commit"); `start` touches `status.json`. `curl` stub appends the `text=` argument to
`/tmp/sim/telegram.log`. `sleep` stub exits 0.

```bash
REPO=/path/to/checkout; S=/tmp/sim                      # needs objects dc330a5, 0f7f71e, fde881a (git fetch --depth=4 origin <sha>)
git init -q --bare -b main $S/origin.git; git init -q -b main $S/seed; cd $S/seed
(cd $REPO && git archive dc330a5) | tar -x -C .;  git add -A; git commit -qm "data collection 350"
git remote add origin $S/origin.git; git push -q origin main
git rm -rq .; (cd $REPO && git archive 0f7f71e) | tar -x -C .;  git add -A; git commit -qm "PR #61 tree"; git push -q origin main
git clone -q $S/origin.git $S/gold; cd $S/gold; git reset -q --hard origin/main~1      # server = 350, origin = PR
(cd $REPO && git diff dc330a5 fde881a) | git apply; touch status.json                  # real 351 data, uncommitted
# S1: python3 tools/handoff_check.py --update           # dirty a doc          S2: echo '#' >> tools/check_gap_rides.py
# S3: echo '#' > readiness.py                           # untracked collision  S4: touch $S/engine_down + SIM_DIGEST_HOURS=12
PATH=$S/bin:$PATH GOLD_DIR=$S/gold LOCK_FILE=$S/lock GOLD_DIGEST_STATE=$S/digest.state GOLD_DIGEST_EVERY_HOURS=0 \
  TELEGRAM_BOT_TOKEN=x TELEGRAM_CHAT_ID=y bash $S/gold/tools/autosync.sh      # the SERVER's own copy, as on the box
```

S4 additionally needs a fresh last row in `xm_data/quotes-*.csv` (else the unrelated XM warning makes the run an incident) and
`digest.state` holding the current epoch. **S5** (next cron run, post-merge script): build origin **and** server from
`git archive d4686f8`, append one bar to `forward_test_log.csv` on the server, run the same command.
(The sandbox's `xm logger: STALE` ⚠️ in S0–S3 is just the sandbox clock being 30 min past the last quote row.)
