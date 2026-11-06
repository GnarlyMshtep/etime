"""Re-file a task, and everything under it, beneath a different parent.

Two things have to happen together. The task's ``parent_task_id`` changes, and
its rows move in ``active.json`` -- the overlay renders the list in file order
and computes indentation from parent links, so a re-parented task left where it
was would draw indented under a section it isn't next to.

Only the moved task's own parent changes. Its descendants keep pointing at it,
so the subtree arrives with its shape intact rather than flattened. The move
itself lives in ``task_tree.py``, shared with the app's edit dialog.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import ACTIVE_FILE  # noqa: E402
from models import Task  # noqa: E402
from storage import load_active_tasks, save_active_tasks  # noqa: E402
from task_tree import Move, apply_move, plan_move  # noqa: E402

BACKUP_DIR = Path.home() / "Dev" / "etime" / "claude_data"


def assert_etime_not_running() -> None:
    pids = subprocess.run(
        ["pgrep", "-f", "[Pp]ython.*main[.]py"], capture_output=True, text=True
    ).stdout.split()
    if pids:
        sys.exit(f"etime is running (pid {', '.join(pids)}). Quit it first -- it holds the "
                 f"task list in memory and would write the old order straight back out.")


def find_one(tasks: list[Task], *, needle: str, label: str) -> Task:
    exact = [t for t in tasks if t.name.strip().lower() == needle.strip().lower()]
    partial = [t for t in tasks if needle.strip().lower() in t.name.lower()]
    matches = exact or partial
    if not matches:
        sys.exit(f"no active task matching {needle!r} for --{label}")
    if len(matches) > 1:
        names = "\n  ".join(t.name for t in matches)
        sys.exit(f"{len(matches)} tasks match {needle!r} for --{label}:\n  {names}")
    return matches[0]


def plan_move_by_name(tasks: list[Task], *, task_name: str, parent_name: Optional[str]) -> Move:
    task = find_one(tasks, needle=task_name, label="task")
    new_parent = find_one(tasks, needle=parent_name, label="under") if parent_name else None
    try:
        return plan_move(tasks, task=task, new_parent=new_parent)
    except ValueError as exc:
        sys.exit(str(exc))


def backup() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = BACKUP_DIR / f"active.json.{stamp}.bak"
    shutil.copy2(ACTIVE_FILE, dest)
    return dest


def depth_of(tasks: list[Task], *, task: Task) -> int:
    by_id = {t.id: t for t in tasks}
    depth, cur, seen = 0, task, set()
    while cur.parent_task_id in by_id and cur.id not in seen:
        seen.add(cur.id)
        cur = by_id[cur.parent_task_id]
        depth += 1
    return depth


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task", required=True, help="the task to move (name or unique substring)")
    ap.add_argument("--under", default=None, help="new parent; omit for --to-top")
    ap.add_argument("--to-top", action="store_true", help="make it a top-level task")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if bool(args.under) == bool(args.to_top):
        sys.exit("pass exactly one of --under NAME or --to-top")

    tasks = load_active_tasks()
    move = plan_move_by_name(tasks, task_name=args.task, parent_name=args.under)
    target = move.new_parent.name if move.new_parent else "top level"

    print(f"Move {move.task.name!r} under {target}")
    print(f"  from index {move.from_index} -> {move.to_index}, "
          f"carrying {len(move.subtree)} row(s):")
    moved = apply_move(list(tasks), move=move)
    for t in move.subtree:
        print(f"    [{moved.index(t):2d}] depth {depth_of(moved, task=t)}  {t.name[:52]!r}")

    if not args.apply:
        print("\n(dry run -- pass --apply to write)")
        return

    assert_etime_not_running()
    dest = backup()
    save_active_tasks(moved)
    print(f"\nBacked up to {dest}")
    print(f"Moved {move.task.name!r} under {target}.")


if __name__ == "__main__":
    main()
