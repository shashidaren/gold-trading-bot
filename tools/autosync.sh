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
#   3. Runs tools/check_data.py (integrity gate)
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
NOTIFY="${NOTIFY:-always}"            # always | quiet (quiet = only on events)
DATA_FILES=(trades.csv forward_test_log.csv skipped_trades.csv status.json)

log() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S')] $*"; }

TG_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TG_CHAT="${TELEGRAM_CHAT_ID:-}"
if [ -z "$TG_TOKEN" ] && [ -f "$GOLD_DIR/.env" ]; then
    TG_TOKEN=$(sed -n 's/^TELEGRAM_BOT_TOKEN=//p' "$GOLD_DIR/.env" | head -n1 | tr -d "\"'")
    TG_CHAT=$(sed -n 's/^TELEGRAM_CHAT_ID=//p' "$GOLD_DIR/.env" | head -n1 | tr -d "\"'")
fi

tg() {
    if [ -z "$TG_TOKEN" ] || [ -z "$TG_CHAT" ]; then return 0; fi
    curl -s -m 10 -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${TG_CHAT}" \
        --data-urlencode "text=${1}" >/dev/null 2>&1 || true
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
    if ! git diff --quiet -- engine.py trade_filter.py dashboard.py tools/ 2>/dev/null; then
        DEPLOY_MSG="SKIPPED - local code edits detected on server (hand-edits are not supported); manual pull needed"
        log "$DEPLOY_MSG"
    elif [ "$AUTO_DEPLOY" != "1" ]; then
        DEPLOY_MSG="SKIPPED (AUTO_DEPLOY=0) - origin/main is ahead; manual pull needed"
        log "$DEPLOY_MSG"
    else
        CODE_CHANGED=$(git diff --name-only HEAD "$REMOTE_SHA" -- '*.py' | grep -c . || true)
        CORE_CHANGED=$(git diff --name-only HEAD "$REMOTE_SHA" -- engine.py trade_filter.py | grep -c . || true)
        DASH_CHANGED=$(git diff --name-only HEAD "$REMOTE_SHA" -- dashboard.py | grep -c . || true)
        SVC=$(detect_service 'engine\.py' "$ENGINE_SERVICE" || true)
        PRE_MERGE=$(git rev-parse HEAD)

        if [ -n "$SVC" ] && [ "$CORE_CHANGED" -gt 0 ]; then
            log "stopping engine ($SVC)"
            systemctl stop "$SVC" >/dev/null 2>&1 || log "WARN: stop $SVC failed"
        fi

        MERGE_RC=0
        if ! git merge "$REMOTE/$BRANCH" -m "autosync: merge upstream (live data kept local)" >/dev/null 2>&1; then
            log "merge conflict - resolving: data 
