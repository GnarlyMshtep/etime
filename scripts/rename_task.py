"""Rename an open task -- typically a category tag.

Everything that belongs to a task points at it by id, not by name: its subtasks
in active.json and every completed task in history.jsonl. So a rename carries the
whole tree and its history along, and only active.json needs touching.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import ACTIVE_FILE  # noqa: E402
from models import Task  # noqa: E402
from storage import load_active_tasks, save_active_tasks  # noqa: E402

BACKUP_DIR = Path.home() / "Dev" / "etime" / "claude_data"


def assert_etime_not_running() -> None:
    pids = subprocess.run(
        ["pgrep", "-f", "[Pp]ython.*main[.]py"], capture_output=True, text=True
    ).stdout.split()
    if pids:
        sys.exit(f"etime is running (pid {', '.join(pids)}). Quit it first -- it holds the "
                 f"task list in memory and would write this straight back out.")


def find_task(tasks: list[Task], *, name: str) -> Task:
    exact = [t for t in tasks if t.name.strip().lower() == name.strip().lower()]
    partial = [t for t in tasks if name.strip().lower() in t.name.lower()]
    matches = exact or partial
    if not matches:
        sys.exit(f"no active task matching {name!r}")
    if len(matches) > 1:
        sys.exit(f"{len(matches)} tasks match {name!r}: " + ", ".join(t.name for t in matches))
    return matches[0]


def backup(path: Path) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = BACKUP_DIR / f"{path.name}.{stamp}.bak"
    shutil.copy2(path, dest)
    return dest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task", required=True, help="current name of the task")
    ap.add_argument("--to", required=True, help="new name")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    new_name = args.to.strip()
    if not new_name:
        sys.exit("--to can't be empty")

    tasks = load_active_tasks()
    task = find_task(tasks, name=args.task)
    taken = [t for t in tasks if t.id != task.id and t.name.strip().lower() == new_name.lower()]
    if taken:
        sys.exit(f"another open task is already named {new_name!r}")

    children = sum(1 for t in tasks if t.parent_task_id == task.id)
    kind = "top-level" if task.parent_task_id is None else "subtask"
    print(f"{task.name!r} -> {new_name!r}  ({kind}, {children} direct subtask(s))")

    if not args.apply:
        print("\n(dry run -- pass --apply to write)")
        return

    assert_etime_not_running()
    dest = backup(ACTIVE_FILE)
    task.name = new_name
    save_active_tasks(tasks)
    print(f"\nBacked up to {dest}")
    print(f"Renamed (id {task.id})")


if __name__ == "__main__":
    main()
