"""Create a category tag: a top-level task estimated at one minute.

Categories are a convention, not a type -- a root with a one-minute estimate,
holding no real work, used as the tag the dashboard totals under. They're kept
clustered at the top of the overlay list, so a new one joins the cluster rather
than landing at the bottom among actual tasks (the same rule main.py applies to
a category created through the dialog).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import ACTIVE_FILE, CATEGORY_ESTIMATE_SECONDS  # noqa: E402
from models import Task, TaskState  # noqa: E402
from storage import load_active_tasks, save_active_tasks  # noqa: E402

BACKUP_DIR = Path.home() / "Dev" / "etime" / "claude_data"


def assert_etime_not_running() -> None:
    pids = subprocess.run(
        ["pgrep", "-f", "[Pp]ython.*main[.]py"], capture_output=True, text=True
    ).stdout.split()
    if pids:
        sys.exit(f"etime is running (pid {', '.join(pids)}). Quit it first -- it holds the "
                 f"task list in memory and would write the old list straight back out.")


def category_insert_index(tasks: list[Task]) -> int:
    """Just past the last category tag's subtree."""
    last = None
    for i, t in enumerate(tasks):
        if t.parent_task_id is None and t.estimated_seconds == CATEGORY_ESTIMATE_SECONDS:
            last = i
    if last is None:
        return len(tasks)
    idx = last + 1
    while idx < len(tasks) and tasks[idx].parent_task_id is not None:
        idx += 1
    return idx


def backup() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / f"active.json.{stamp}.bak"
    shutil.copy2(ACTIVE_FILE, dest)
    return dest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    tasks = load_active_tasks()
    clash = [t for t in tasks if t.name.strip().lower() == args.name.strip().lower()]
    if clash:
        sys.exit(f"there's already an active task named {args.name!r} -- "
                 f"refusing to create a second one you can't tell apart")

    category = Task(
        id="",
        name=args.name,
        estimated_seconds=CATEGORY_ESTIMATE_SECONDS,
        state=TaskState.PAUSED,
        created_at=datetime.now().isoformat(),
    )
    at = category_insert_index(tasks)
    after = tasks[at - 1].name if at else "(start of list)"

    print(f"Add category {category.name!r} at index {at}, after {after!r}")
    if not args.apply:
        print("(dry run -- pass --apply to write)")
        return

    assert_etime_not_running()
    dest = backup()
    tasks.insert(at, category)
    save_active_tasks(tasks)
    print(f"Backed up to {dest}")
    print(f"Created {category.name!r} (id {category.id})")


if __name__ == "__main__":
    main()
