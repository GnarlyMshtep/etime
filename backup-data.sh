#!/bin/bash
# Auto-backup ~/.etime data to its GitHub remote.
# Commits + pushes ONLY when the data actually changed. Safe to run on a timer.
# Invoked by the com.matan.etime-backup LaunchAgent (hourly) and runnable by hand.

set -euo pipefail

DATA_DIR="$HOME/.etime"

if [ ! -d "$DATA_DIR/.git" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR: $DATA_DIR is not a git repo — skipping"
    exit 1
fi

cd "$DATA_DIR"

git add -A

if git diff --staged --quiet; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') no changes to back up"
    exit 0
fi

git commit -m "Auto-backup $(date '+%Y-%m-%d %H:%M')" >/dev/null
git push
echo "$(date '+%Y-%m-%d %H:%M:%S') etime data backed up"
