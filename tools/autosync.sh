#!/usr/bin/env bash
# ==============================================================================
# tools/autosync.sh — unattended data sync + safe auto-deploy for /opt/gold
# Runs from cron (root). Full documentation: docs/AUTOSYNC.md
#
# Every run:
#   1. Commits the live data files and pushes them to origin/main
#   2. If origin/main advanced (e.g. a merged PR):
#        stops the engine -> merges (conflicts: data files = server wins,
#        everything else = remote wins) -> runs the smoke test -> rolls back
#        on failure -> restarts the engine -> verifies status.json is fresh
#   3. Runs tools/check_data.py (integrity gate), tools/handoff_check.py (is docs/HANDOFF.md
#      still telling the truth?), tools/xm_quote_report.py --quiet (is the quote logger
#      writing?) and tools/box_alert.py --quiet (is the optional box notifier configured
#      and running?). The last three are ADVISORY: shown in the digest, never block a deploy
#   4. Sends a one-message digest to the Telegram chat configured in .env
#
# Safety model:
#   - flock: never two runs at once
#   - data is committed BEFORE any merge, so a rollback never loses data
#   - refuses to deploy if someone hand-edited code files on the server
#   - smoke-test gate with automatic rollback to pre-merge code
#   - .env (secrets) is read but never committed
# ==============================================================================
set -uo pipefail

GOLD_DIR="${GOLD_DIR:-/opt/gold}"
LOCK_FILE="${LOCK_FILE:-/var/lock/gold_autosync.lock}"
REMOTE="${REMOTE:-origin}"
BRANCH="${BRANCH:-main}"
AUTO_DEPLOY="${AUTO_DEPLOY:-1}"       # 0 = data-only mode (never pull/restart)
SMOKE_GATE="${SMOKE_GATE:-1}"         # 0 = deploy without the smoke test
ENGINE_SERVICE="${ENGINE_SERVICE:-}" # empty = auto-detect the unit running engine.py
DASHBOARD_SERVICE="${DASHBOARD_SERVICE:-}" # empty = auto-detect the unit running dashboard.py
BOXALERT_SERVICE="${BOXALERT_SERVICE:-}" # empty = auto-detect the optional box_alert.py unit
NOTIFY="${NOTIFY:-always}"            # always | quiet (quiet = only on events)
# 2026-10-23 owner ask: the digest is now a twice-daily trade report, not an 8x/day
# heartbeat. GOLD_DIGEST_EVERY_HOURS=12 sends at most one scheduled digest per 12 h;
# 0 restores a digest on every run (the old behaviour). An INCIDENT ($EXTRA - feed
# starvation, a failed integrity check, a rollback, a failed push) always sends at once
# and is never silenced, so slowing the routine digest cannot hide a real problem.
DIGEST_EVERY_HOURS="${GOLD_DIGEST_EVERY_HOURS:-12}"
DIGEST_STATE="${GOLD_DIGEST_STATE:-/var/lib/gold/autosync_digest.state}"
# xm_data/ = the read-only quote + contract-spec logger (docs/XM-LOGGER.md); `git add` of a directory that
# does not exist yet fails quietly (|| true below), so this is safe before the logger is installed.
DATA_FILES=(trades.csv forward_test_log.csv skipped_trades.csv status.json xm_data)

log() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S')] $*"; }

TG_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TG_CHAT="${TELEGRAM_CHAT_ID:-}"
if [ -z "$TG_TOKEN" ] && [ -f "$GOLD_DIR/.env" ]; then
    TG_TOKEN=$(sed -n 's/^TELEGRAM_BOT_TOKEN=//p' "$GOLD_DIR/.env" | head -n1 | tr -d "\"'")
    TG_CHAT=$(sed -n 's/^TELEGRAM_CHAT_ID=//p' "$GOLD_DIR/.env" | head -n1 | tr -d "\"'")
fi

# tg <text> [silent]  - silent=1 sends with disable_notification (routine digests buzz
# nobody; incidents always buzz). Telegram is never allowed to fail this script.
tg() {
    local text="$1" silent="${2:-0}"
    if [ -z "$TG_TOKEN" ] || [ -z "$TG_CHAT" ]; then return 0; fi
    local quiet_arg=()
    if [ "$silent" = "1" ]; then quiet_arg=(--data-urlencode "disable_notification=true"); fi
    curl -s -m 10 -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${TG_CHAT}" \
        --data-urlencode "text=${text}" \
        ${quiet_arg[@]+"${quiet_arg[@]}"} >/dev/null 2>&1 || true
}

detect_service() {
    # $1 = marker to look for in the unit definition (e.g. 'engine\.py')
    # $2 = optional explicit unit name override (skips detection)
    # Detection is scoped to units that ALSO reference $GOLD_DIR, so services
    # belonging to other repos on the same box (e.g. a bitcoin bot with its
    # own engine.py) are never picked up by mistake.
    if [ -n "${2:-}" ]; then echo "$2"; return 0; fi
    local unit def
    while IFS= read -r unit; do
        [ -z "$unit" ] && continue
        def=$(systemctl cat "$unit" 2>/dev/null) || continue
        if printf '%s' "$def" | grep -q "$1" && printf '%s' "$def" | grep -qF "$GOLD_DIR"; then
            echo "$unit"; return 0
        fi
    done < <(systemctl list-units --type=service --no-legend --plain 2>/dev/null | awk '{print $1}')
    return 1
}

# --- lock ---------------------------------------------------------------------
exec 9>"$LOCK_FILE" || { log "FATAL: cannot open lock file"; exit 1; }
if ! flock -n 9; then log "another autosync run is active - skipping"; exit 0; fi

cd "$GOLD_DIR" || { log "FATAL: cannot cd to $GOLD_DIR"; tg "gold autosync: FATAL - cannot cd to $GOLD_DIR"; exit 1; }

if [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ] || [ -f .git/MERGE_HEAD ]; then
    log "repo is mid rebase/merge - manual attention required"
    tg "gold autosync: /opt/gold is mid rebase/merge. Fix manually; autosync paused."
    exit 1
fi

git config user.email >/dev/null 2>&1 || git config user.email "autosync@$(hostname)"
git config user.name  >/dev/null 2>&1 || git config user.name  "gold-autosync"
export GIT_TERMINAL_PROMPT=0

DATA_MSG="no new data"
DEPLOY_MSG="none"
EXTRA=""

# --- phase 1: commit live data -------------------------------------------------
for f in "${DATA_FILES[@]}"; do git add -- "$f" 2>/dev/null || true; done
if ! git diff --cached --quiet 2>/dev/null; then
    NEW_TRADES=$(git diff --cached -- trades.csv | grep -c '^+[^+]' || true)
    LAST_N=$(git log --format=%s | sed -n 's/^data collection \([0-9][0-9]*\)$/\1/p' | sort -n | tail -n1)
    N=$(( ${LAST_N:-0} + 1 ))
    if git commit -q -m "data collection $N"; then
        DATA_MSG="committed ${NEW_TRADES} new trade rows -> 'data collection $N'"
        log "data: $DATA_MSG"
    else
        DATA_MSG="COMMIT FAILED (will retry next run)"
        log "data commit failed"
    fi
else
    log "no data changes"
fi

# --- phase 2: fetch & (maybe) deploy ------------------------------------------
git fetch "$REMOTE" "$BRANCH" >/dev/null 2>&1 || log "WARN: git fetch failed (offline/credentials?)"

LOCAL_SHA=$(git rev-parse HEAD 2>/dev/null || echo "")
REMOTE_SHA=$(git rev-parse "$REMOTE/$BRANCH" 2>/dev/null || echo "")

NEED_MERGE=0
if [ -n "$REMOTE_SHA" ] && [ "$LOCAL_SHA" != "$REMOTE_SHA" ]; then
    if git merge-base --is-ancestor "$REMOTE_SHA" HEAD 2>/dev/null; then
        : # local ahead (data commit) - phase 3 will push
    else
        NEED_MERGE=1
    fi
fi

if [ "$NEED_MERGE" = "1" ]; then
    if ! git diff --quiet -- engine.py trade_filter.py dashboard.py pressure.py chart.py manual_scalp.py scalp_template.py tools/ 2>/dev/null; then
        DEPLOY_MSG="SKIPPED - local code edits detected on server (hand-edits are not supported); manual pull needed"
        log "$DEPLOY_MSG"
    elif [ "$AUTO_DEPLOY" != "1" ]; then
        DEPLOY_MSG="SKIPPED (AUTO_DEPLOY=0) - origin/main is ahead; manual pull needed"
        log "$DEPLOY_MSG"
    else
        CODE_CHANGED=$(git diff --name-only HEAD "$REMOTE_SHA" -- '*.py' | grep -c . || true)
        CORE_CHANGED=$(git diff --name-only HEAD "$REMOTE_SHA" -- engine.py trade_filter.py | grep -c . || true)
        DASH_CHANGED=$(git diff --name-only HEAD "$REMOTE_SHA" -- dashboard.py pressure.py chart.py manual_scalp.py scalp_template.py | grep -c . || true)
        # the box-alert sidecar runs pressure.py's read layer, so either file changing
        # needs its own restart (it is display-only: like the dashboard, never the engine)
        BOXALERT_CHANGED=$(git diff --name-only HEAD "$REMOTE_SHA" -- tools/box_alert.py pressure.py | grep -c . || true)
        SVC=$(detect_service 'engine\.py' "$ENGINE_SERVICE" || true)
        PRE_MERGE=$(git rev-parse HEAD)

        if [ -n "$SVC" ] && [ "$CORE_CHANGED" -gt 0 ]; then
            log "stopping engine ($SVC)"
            systemctl stop "$SVC" >/dev/null 2>&1 || log "WARN: stop $SVC failed"
        fi

        MERGE_RC=0
        if ! git merge "$REMOTE/$BRANCH" -m "autosync: merge upstream (live data kept local)" >/dev/null 2>&1; then
            log "merge conflict - resolving: data files=ours, everything else=theirs"
            for f in $(git diff --name-only --diff-filter=U); do
                case "$f" in
                    trades.csv|forward_test_log.csv|skipped_trades.csv|status.json|xm_data/*)
                        git checkout --ours -- "$f" ;;
                    *) git checkout --theirs -- "$f" ;;
                esac
                git add -- "$f" >/dev/null 2>&1 || true
            done
            git commit -q -m "autosync: merge upstream (live data kept local)" >/dev/null 2>&1 || MERGE_RC=1
        fi

        SMOKE="not run (no code change)"
        if [ "$MERGE_RC" = "0" ] && [ "$SMOKE_GATE" = "1" ] && [ "$CODE_CHANGED" -gt 0 ]; then
            if python3 tools/smoke_test.py >/tmp/autosync_smoke.log 2>&1; then
                SMOKE="ok"
            else
                SMOKE="FAIL"
            fi
        fi

        if [ "$MERGE_RC" != "0" ] || [ "$SMOKE" = "FAIL" ]; then
            log "deploy failed (merge_rc=$MERGE_RC smoke=$SMOKE) - rolling back to $PRE_MERGE"
            [ -f .git/MERGE_HEAD ] && git merge --abort >/dev/null 2>&1
            git reset --hard "$PRE_MERGE" >/dev/null 2>&1
            DEPLOY_MSG="ROLLED BACK (smoke=$SMOKE) - needs a manual look"
            EXTRA="$EXTRA
🚨 deploy rolled back - start a review session"
        else
            DEPLOY_MSG="deployed $(git rev-parse --short HEAD) (code files: $CODE_CHANGED, smoke: $SMOKE)"
        fi

        if [ "$CORE_CHANGED" -gt 0 ]; then
            if [ -n "$SVC" ]; then
                log "starting engine ($SVC)"
                systemctl start "$SVC" >/dev/null 2>&1 || DEPLOY_MSG="$DEPLOY_MSG; FAILED to start $SVC"
                sleep 20
                if systemctl is-active --quiet "$SVC" 2>/dev/null; then
                    if [ -z "$(find status.json -mmin -3 2>/dev/null)" ]; then
                        DEPLOY_MSG="$DEPLOY_MSG; engine active but status.json looks STALE"
                    fi
                else
                    DEPLOY_MSG="$DEPLOY_MSG; ENGINE SERVICE NOT ACTIVE"
                fi
            else
                DEPLOY_MSG="$DEPLOY_MSG; engine service NOT FOUND - restart engine manually"
                EXTRA="$EXTRA
⚠️ engine service not detected - manual restart needed"
            fi
        fi
        if [ "$DASH_CHANGED" -gt 0 ]; then
            DSVC=$(detect_service 'dashboard\.py' "$DASHBOARD_SERVICE" || true)
            if [ -n "$DSVC" ]; then
                log "restarting dashboard ($DSVC)"
                systemctl restart "$DSVC" >/dev/null 2>&1 \
                    || DEPLOY_MSG="$DEPLOY_MSG; FAILED to restart $DSVC"
            else
                DEPLOY_MSG="$DEPLOY_MSG; dashboard service NOT FOUND - restart dashboard manually"
            fi
        fi
        # OPTIONAL sidecar: absent on a box that never installed it, and that is fine -
        # it is a notification, not part of the trading path. Never touch the engine here.
        if [ "$BOXALERT_CHANGED" -gt 0 ]; then
            BSVC=$(detect_service 'box_alert\.py' "$BOXALERT_SERVICE" || true)
            if [ -n "$BSVC" ]; then
                log "restarting box-alert sidecar ($BSVC)"
                systemctl restart "$BSVC" >/dev/null 2>&1 \
                    || DEPLOY_MSG="$DEPLOY_MSG; FAILED to restart $BSVC"
            fi
        fi
    fi
fi

# --- phase 3: push -------------------------------------------------------------
PUSH_MSG="ok"
if ! git push "$REMOTE" "$BRANCH" >/dev/null 2>&1; then
    PUSH_MSG="FAILED (data is safe in a local commit; retries next run)"
    EXTRA="$EXTRA
⚠️ push to $REMOTE failed"
fi
log "push: $PUSH_MSG"

# --- phase 4: integrity + stats --------------------------------------------------
CHECK_MSG="not run"
python3 tools/check_data.py >/tmp/autosync_check.log 2>&1
CHECK_RC=$?
CHECK_MSG=$(grep -E '^== result' /tmp/autosync_check.log | tail -n1 | sed 's/^== result: //')
if [ -z "$CHECK_MSG" ]; then
    CHECK_MSG="check_data FAILED to run (rc=$CHECK_RC)"
fi
if [ "$CHECK_RC" != "0" ]; then
    EXTRA="$EXTRA
🚨 check_data: $CHECK_MSG - start a review session"
fi

STATS=$(python3 - <<'PYEOF' 2>/dev/null
import json
try:
    s = json.load(open("status.json"))
    print("equity {eq} | {w}W/{l}L | daily SLs {d}/{m} | open trade: {a} | updated {u} UTC".format(
        eq=s.get("equity"), w=s.get("wins"), l=s.get("losses"),
        d=s.get("daily_losses"), m=s.get("max_daily_losses"),
        a="yes" if s.get("trade_active") else "no", u=s.get("last_update")))
except Exception as e:
    print("status.json unreadable: %s" % e)
PYEOF
)

# --- phase 4b: data-freshness backstop -----------------------------------------
# 2026-09-29: a host reboot left the MT5 terminal stuck, the feed file froze at
# 08:29 UTC and the engine starved *silently* for 6 h - the 09:00 and 12:00
# autosync runs reported "no new data" and looked green. This backstop counts
# the minutes the market was OPEN since the last logged candle (weekend/daily
# break excluded, mirroring engine.is_market_quiet) and shouts in the digest
# when that exceeds STALE_OPEN_MIN.
FRESH_MSG=$(python3 - <<'PYEOF' 2>/dev/null
import csv
from datetime import datetime, timedelta, timezone

STALE_OPEN_MIN = 90  # open-market minutes with no new candle


def _quiet(t):
    # Mirrors engine.is_market_quiet(): weekend, or the broker daily break.
    return t.weekday() >= 5 or t.hour >= 21 or t.hour < 2


def open_minutes(ts, now):
    total, step, t = 0, timedelta(minutes=5), ts
    while t < now:
        if not _quiet(t):
            total += 5
        t += step
    return total


try:
    last = None
    with open("forward_test_log.csv") as f:
        for row in csv.reader(f):
            if row and row[0] and row[0] != "Timestamp":
                last = row
    ts = datetime.strptime(last[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
except Exception as e:  # never break the sync over a health check
    print("unreadable (%s)" % e)
    raise SystemExit

now = datetime.now(timezone.utc)
mins = open_minutes(ts, now)
if mins > STALE_OPEN_MIN:
    print("STALE %d open min (last candle %s UTC)" % (mins, last[0]))
else:
    print("ok (%d open min since last candle)" % mins)
PYEOF
)
log "freshness: $FRESH_MSG"
case "$FRESH_MSG" in
    STALE*)
        EXTRA="$EXTRA
🛑 engine/feed starving: no new candles for $FRESH_MSG - check systemctl status goldbot mt5 mt5feed"
        ;;
esac

# --- phase 4c: handoff freshness (ADVISORY - never blocks a deploy) -------------
# docs/HANDOFF.md carries a machine-checked snapshot block; tools/handoff_check.py recomputes it
# from the data files this script just committed. A stale handoff is how a new session ends up
# retuning on a week-old picture (2026-10-13: §1 said 493 closed, the box had 575). The verdict
# rides along in the digest. It deliberately does NOT touch $EXTRA: a doc that is a dozen trades
# behind is not an incident, and shouting about it every 3 hours would get the digest muted.
# The exit code is ignored on purpose; only the one-line verdict is used.
# Fix it with: python3 tools/handoff_check.py --update   (then rewrite the prose, HANDOFF §11)
HANDOFF_MSG="not run"
if [ -f tools/handoff_check.py ] && [ -f docs/HANDOFF.md ]; then
    python3 tools/handoff_check.py --quiet >/tmp/autosync_handoff.log 2>&1
    HANDOFF_MSG=$(tail -n1 /tmp/autosync_handoff.log)
    [ -z "$HANDOFF_MSG" ] && HANDOFF_MSG="handoff_check failed to run"
    log "handoff: $HANDOFF_MSG"
fi

# --- phase 4d: quote-logger liveness (ADVISORY - never blocks a deploy) ------------
# mt5quotes-gold (docs/XM-LOGGER.md) writes a row every 30 s even while gold is shut (weekend, daily
# break: the tick is frozen and the row is flagged STALE), so "the newest row is older than 15 min"
# means the LOGGER is down, not that the market is closed. A dead logger would otherwise fail silently:
# the engine does not depend on it and nothing else notices. Only that one case raises a line in $EXTRA;
# the routine summary rides in the digest. The STALE text carries no changing numbers on purpose.
# The exit code is ignored; only the one-line verdict is used (xm_quote_report --quiet never fails).
XM_MSG="xm logger: report not installed"
if [ -f tools/xm_quote_report.py ]; then
    python3 tools/xm_quote_report.py --quiet >/tmp/autosync_xm.log 2>&1
    XM_MSG=$(tail -n1 /tmp/autosync_xm.log)
    # --quiet never fails and always prints "xm logger: ..."; anything else means the script itself
    # crashed (an import error prints a traceback), so say so instead of pasting a traceback line
    case "$XM_MSG" in
        "xm logger:"*) ;;
        *) XM_MSG="xm logger: report failed to run (${XM_MSG:-no output})" ;;
    esac
    log "$XM_MSG"
    case "$XM_MSG" in
        "xm logger: STALE"*)
            EXTRA="$EXTRA
⚠️ XM quote logger has stopped writing rows - check: systemctl status mt5quotes-gold (advisory: trading is unaffected)"
            ;;
    esac
fi

# --- phase 4e: box-alert sidecar (ADVISORY - never blocks a deploy) -----------------
# tools/box_alert.py is an OPTIONAL display-only notifier (docs/ANALYSIS-2026-10-21-
# box-chop-retest-alerts.md). --quiet always prints one "box alerts: ..." line and
# exits 0, including when it is not configured or not installed - so this can never
# block a deploy or shout about a box the owner never opted into.
# The Telegram pair: this script keeps it in its OWN unexported TG_TOKEN/TG_CHAT, so
# a child never inherits it. From 2026-10-21 box_alert.py reads $GOLD_DATA_DIR/.env
# itself, the same file engine.py and the unit's EnvironmentFile= use. Before that,
# the 18:00 digest said "not configured" in the message the pair had just delivered.
# GOLD_DATA_DIR points it at this run's root, the .env and box_alert_state.json the
# sidecar uses (the unit sets GOLD_DATA_DIR=/opt/gold). No secret passes on argv/env.
# The line also reports whether the notifier is RUNNING, from the --loop heartbeat in
# that state file, so "pair found" is never mistaken for "installed and working".
BOXALERT_MSG=""
if [ -f tools/box_alert.py ]; then
    GOLD_DATA_DIR="${GOLD_DATA_DIR:-$GOLD_DIR}" \
        python3 tools/box_alert.py --quiet >/tmp/autosync_boxalert.log 2>&1
    BOXALERT_MSG=$(tail -n1 /tmp/autosync_boxalert.log)
    case "$BOXALERT_MSG" in
        "box alerts:"*) ;;
        *) BOXALERT_MSG="box alerts: report failed to run (${BOXALERT_MSG:-no output})" ;;
    esac
    log "$BOXALERT_MSG"
fi

log "done. data=[$DATA_MSG] deploy=[$DEPLOY_MSG] check=[$CHECK_MSG] handoff=[$HANDOFF_MSG] xm=[$XM_MSG] boxalert=[$BOXALERT_MSG]"

# --- phase 4f: trade summary since the last digest (2026-10-23) --------------------
# The engine no longer sends per-trade messages (GOLD_TELEGRAM_KINDS; see engine.py and
# docs/PROPOSAL-2026-10-23-telegram-routing.md), so trade news lands HERE: what closed
# since the previous digest, straight from trades.csv. Read-only - the ledger is never
# written by this script. $ figures are gross of costs, matching the engine ledger.
LAST_DIGEST=$(tr -dc '0-9' < "$DIGEST_STATE" 2>/dev/null | head -c 20)
if [ -z "$LAST_DIGEST" ]; then
    _hours="$DIGEST_EVERY_HOURS"
    case "$_hours" in ''|*[!0-9]*) _hours=12 ;; esac
    [ "$_hours" -gt 0 ] || _hours=3
    LAST_DIGEST=$(( $(date -u +%s) - _hours * 3600 ))
fi
TNG_MSG=$(TNG_SINCE="$LAST_DIGEST" python3 - <<'PYEOF' 2>/dev/null
import csv, os
from datetime import datetime, timezone

try:
    since = datetime.fromtimestamp(int(os.environ["TNG_SINCE"]), tz=timezone.utc).replace(tzinfo=None)
except (KeyError, ValueError):
    since = None
rows = []
with open("trades.csv", newline="") as f:
    for r in csv.DictReader(f):
        try:
            t = datetime.strptime(r["Exit_Time"], "%Y-%m-%d %H:%M:%S")
        except (KeyError, TypeError, ValueError):
            continue
        if since is None or t > since:
            rows.append(r)
if not rows:
    print("no trades closed since the last digest")
else:
    def n(reason):
        return sum(1 for r in rows if (r.get("Exit_Reason") or "").upper() == reason)
    try:
        net = sum(float(r.get("Profit") or 0) for r in rows)
    except (TypeError, ValueError):
        net = 0.0
    parts = [f"{n('TP')}W", f"{n('SL')}L"]
    if n("BE"):
        parts.append(f"{n('BE')}BE")
    if n("TIME"):
        parts.append(f"{n('TIME')}TIME")
    print(f"{len(rows)} closed ({'/'.join(parts)}) | net ${net:+.2f} gross")
PYEOF
)
[ -z "$TNG_MSG" ] && TNG_MSG="trades.csv unreadable"
log "trades: $TNG_MSG"

# --- phase 5: the digest (twice a day by default; incidents always) -----------------
# Owner ask 2026-10-23: "limit the telegram messages for the indicators only". Engine
# chatter is filtered at source; the ops digest drops from 8/day to 2/day and becomes
# the trade report. An incident is never delayed or silenced:
#   * anything in $EXTRA (feed starvation, integrity failure, rollback, failed push)
#   * a deploy that failed, rolled back, or was skipped for server hand-edits
#   * a push that did not go through
# A quiet chat now means a healthy box, and a message that does arrive matters.
INCIDENT=0
[ -n "$EXTRA" ] && INCIDENT=1
case "$DEPLOY_MSG" in
    *"ROLLED BACK"*|*FAILED*|*"local code edits"*) INCIDENT=1 ;;
esac
[ "$PUSH_MSG" = "ok" ] || INCIDENT=1

NOW_EPOCH=$(date -u +%s)
DUE=1
case "$DIGEST_EVERY_HOURS" in
    ''|*[!0-9]*) DIGEST_EVERY_HOURS=12 ;;
esac
if [ "$DIGEST_EVERY_HOURS" -gt 0 ] && [ "$INCIDENT" = "0" ] \
   && [ $(( NOW_EPOCH - LAST_DIGEST )) -lt $(( DIGEST_EVERY_HOURS * 3600 )) ]; then
    DUE=0
fi

QUIET_SKIP=0
if [ "$NOTIFY" = "quiet" ] && [ "$DATA_MSG" = "no new data" ] && [ "$DEPLOY_MSG" = "none" ] \
   && [ "$PUSH_MSG" = "ok" ] && [ -z "$EXTRA" ]; then
    QUIET_SKIP=1
fi

if [ "$QUIET_SKIP" = "1" ]; then
    log "digest: skipped (NOTIFY=quiet, nothing changed)"
elif [ "$DUE" = "0" ] && [ "$INCIDENT" = "0" ]; then
    log "digest: not due (routine digest is every ${DIGEST_EVERY_HOURS}h; incidents send at once)"
else
    # routine digests are silent (no phone buzz), incidents are not
    if [ "$INCIDENT" = "1" ]; then _silent=0; else _silent=1; fi
    tg "🤖 gold autosync — $(date -u '+%m-%d %H:%M') UTC
🧾 trades: $TNG_MSG
📦 data: $DATA_MSG (push: $PUSH_MSG)
🚀 deploy: $DEPLOY_MSG
🩺 integrity: $CHECK_MSG
📈 candles: $FRESH_MSG
📝 handoff: $HANDOFF_MSG
📡 $XM_MSG
${BOXALERT_MSG:+🔔 $BOXALERT_MSG
}💰 $STATS$EXTRA" "$_silent"
    mkdir -p "$(dirname "$DIGEST_STATE")" 2>/dev/null || true
    printf '%s\n' "$NOW_EPOCH" > "$DIGEST_STATE" 2>/dev/null \
        || log "WARN: could not record the digest time in $DIGEST_STATE"
    log "digest: sent (incident=$INCIDENT, silent=$_silent)"
fi
