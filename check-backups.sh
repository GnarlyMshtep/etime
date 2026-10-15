#!/bin/bash
# Report whether the etime backups are actually working.
#
# Written because the obvious check used to lie: a root-owned reflog in
# ~/.etime/.git left the remote-tracking ref frozen, so `git status` reported
# hundreds of unpushed commits while every push was in fact landing. This
# compares HEAD against what the remote actually has, which can't drift.
#
# Read-only. Exits non-zero if anything needs attention, so it can gate an alert.

set -uo pipefail

CODE_DIR="$HOME/Dev/etime"
DATA_DIR="$HOME/.etime"
BACKUP_LOG="$DATA_DIR/backup.log"
AGENT="com.matan.etime-backup"
STALE_HOURS=26   # the agent runs hourly but only while awake; a day's grace

problems=0
note() { printf '  %s\n' "$1"; }
fail() { printf '  !! %s\n' "$1"; problems=$((problems + 1)); }

check_repo() {
    local label="$1" dir="$2" auto="$3"
    printf '%s (%s)\n' "$label" "$dir"

    if [ ! -d "$dir/.git" ]; then
        fail "not a git repo"
        return
    fi

    local head remote dirty
    head=$(git -C "$dir" rev-parse HEAD 2>/dev/null)
    remote=$(git -C "$dir" ls-remote origin main 2>/dev/null | cut -f1)
    dirty=$(git -C "$dir" status --porcelain 2>/dev/null | grep -c . | tr -d ' ')

    if [ -z "$remote" ]; then
        fail "can't reach the remote (offline, or auth expired)"
    elif [ "$head" = "$remote" ]; then
        note "in sync with remote at ${head:0:8}"
    else
        fail "local ${head:0:8} != remote ${remote:0:8} — not backed up"
    fi

    if [ "$dirty" -gt 0 ]; then
        if [ "$auto" = "auto" ]; then
            note "$dirty file(s) changed since the last commit (the hourly run picks them up)"
        else
            note "$dirty file(s) changed since the last commit (commit + push by hand)"
        fi
    fi

    # A root-owned ref or reflog silently breaks tracking refs, which is what
    # made this script necessary in the first place.
    local foreign
    foreign=$(find "$dir/.git/refs" "$dir/.git/logs" ! -user "$(id -un)" 2>/dev/null | wc -l | tr -d ' ')
    [ "$foreign" -gt 0 ] && fail "$foreign path(s) under .git aren't owned by $(id -un) — tracking refs can't update"
}

check_repo "DATA  (task log + summaries)" "$DATA_DIR" auto
echo
check_repo "CODE" "$CODE_DIR" manual

echo
echo "Hourly backup agent ($AGENT)"
agent_line=$(launchctl list 2>/dev/null | grep -F "$AGENT")
if [ -z "$agent_line" ]; then
    fail "not loaded — run: launchctl load ~/Library/LaunchAgents/$AGENT.plist"
else
    exit_status=$(printf '%s' "$agent_line" | awk '{print $2}')
    if [ "$exit_status" = "0" ]; then
        note "loaded, last run exited cleanly"
    else
        fail "loaded, but last run exited $exit_status"
    fi
fi

if [ -f "$BACKUP_LOG" ]; then
    last=$(grep -E 'backed up|no changes' "$BACKUP_LOG" | tail -1)
    if [ -z "$last" ]; then
        fail "no successful run recorded in backup.log"
    else
        note "last: $last"
        stamp=$(printf '%s' "$last" | awk '{print $1" "$2}')
        last_epoch=$(date -j -f '%Y-%m-%d %H:%M:%S' "$stamp" +%s 2>/dev/null)
        if [ -n "$last_epoch" ]; then
            hours=$(( ( $(date +%s) - last_epoch ) / 3600 ))
            if [ "$hours" -gt "$STALE_HOURS" ]; then
                fail "that was ${hours}h ago (over ${STALE_HOURS}h) — has the agent stopped firing?"
            else
                note "${hours}h ago"
            fi
        fi
    fi
    errors=$(grep -c 'error:' "$BACKUP_LOG" 2>/dev/null | tr -d ' ')
    [ "${errors:-0}" -gt 0 ] && note "$errors historical 'error:' line(s) in backup.log (pre-Oct-2026 reflog issue)"
fi

echo
if [ "$problems" -eq 0 ]; then
    echo "All good."
else
    echo "$problems problem(s) above."
fi
exit "$problems"
