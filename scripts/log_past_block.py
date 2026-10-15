"""Log a stretch of past work as a task, under an existing parent.

For work that happened away from the timer -- a meeting, a class, a run -- where
the point is that the hours land in the right bucket, not that a timer ran.

Defaults to ``paused``, matching what the New Task dialog's When field does: the
work is on the clock but filing it isn't the same decision as finishing it, so
you complete or resume it yourself. ``--state completed`` instead appends
straight to history for something already done and done with.

Times go through the same parser as the dialog, so "yesterday 4 to 5:30" reads
the same way in both places.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import ACTIVE_FILE, HISTORY_FILE  # noqa: E402
from models import Task, TaskState  # noqa: E402
from storage import append_to_history, load_active_tasks, save_active_tasks  # noqa: E402
from time_range import TimeRange, parse_time_range  # noqa: E402

BACKUP_DIR = Path.home() / "Dev" / "etime" / "claude_data"


@dataclass
class Clash:
    start: datetime
    end: datetime
    name: str


def assert_etime_not_running() -> None:
    pids = subprocess.run(
        ["pgrep", "-f", "[Pp]ython.*main[.]py"], capture_output=True, text=True
    ).stdout.split()
    if pids:
        sys.exit(f"etime is running (pid {', '.join(pids)}). Quit it first -- it holds the "
                 f"task list in memory and would write this straight back out.")


def find_parent(tasks: list[Task], *, name: str) -> Task:
    exact = [t for t in tasks if t.name.strip().lower() == name.strip().lower()]
    partial = [t for t in tasks if name.strip().lower() in t.name.lower()]
    matches = exact or partial
    if not matches:
        roots = ", ".join(t.name for t in tasks if t.parent_task_id is None)
        sys.exit(f"no active task matching {name!r}. Top-level tasks: {roots}")
    if len(matches) > 1:
        sys.exit(f"{len(matches)} tasks match {name!r}: " + ", ".join(t.name for t in matches))
    return matches[0]


def subtree_end(tasks: list[Task], *, root: Task) -> int:
    """Index just past the last row of ``root``'s subtree."""
    ids = {root.id}
    grew = True
    while grew:
        grew = False
        for t in tasks:
            if t.parent_task_id in ids and t.id not in ids:
                ids.add(t.id)
                grew = True
    return max(i for i, t in enumerate(tasks) if t.id in ids) + 1


def clashes_with(block: TimeRange, *, tasks: list[Task]) -> list[Clash]:
    """Work already tracked over the same stretch, from both files."""
    rows = [json.loads(l) for l in HISTORY_FILE.read_text().splitlines() if l.strip()]
    rows += [t.to_dict() for t in tasks]
    out: list[Clash] = []
    for row in rows:
        for iv in row.get("work_intervals") or []:
            try:
                start = datetime.fromisoformat(iv["start"])
                end = datetime.fromisoformat(iv["end"]) if iv.get("end") else datetime.now()
            except (KeyError, TypeError, ValueError):
                continue
            if start < block.end and end > block.start:
                out.append(Clash(start=start, end=end, name=row.get("name", "")))
    return out


def build_task(*, name: str, block: TimeRange, parent: Task, completed: bool,
               minutes: Optional[int]) -> Task:
    estimated = (minutes or block.minutes) * 60
    task = Task(
        id="",
        name=name,
        estimated_seconds=estimated,
        state=TaskState.COMPLETED if completed else TaskState.PAUSED,
        elapsed_seconds=block.seconds,
        created_at=block.start.isoformat(),
        started_at=block.start.isoformat(),
        completed_at=block.end.isoformat() if completed else None,
        work_intervals=[{"start": block.start.isoformat(), "end": block.end.isoformat()}],
        parent_task_id=parent.id,
    )
    # Without this, resuming a block that already exceeds its estimate fires the
    # overtime alarm immediately, for time spent before the task existed.
    task.last_alarm_level = 1 if task.elapsed_seconds >= estimated else 0
    return task


def backup(path: Path) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / f"{path.name}.{stamp}.bak"
    shutil.copy2(path, dest)
    return dest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", required=True, help="name for the new task")
    ap.add_argument("--under", "--category", dest="under", required=True,
                    help="existing task to file it under")
    ap.add_argument("--when", required=True,
                    help='e.g. "yesterday 4 to 5:30", "2:30-4", "9/26 9-10:30"')
    ap.add_argument("--state", choices=("paused", "completed"), default="paused")
    ap.add_argument("--minutes", type=int, default=None,
                    help="estimate in minutes (default: the length of the block)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    try:
        block = parse_time_range(args.when)
    except ValueError as exc:
        sys.exit(str(exc))
    if block is None:
        sys.exit("--when can't be empty")

    tasks = load_active_tasks()
    parent = find_parent(tasks, name=args.under)
    completed = args.state == "completed"
    task = build_task(name=args.name, block=block, parent=parent,
                      completed=completed, minutes=args.minutes)

    print(f"{task.name!r} under {parent.name!r}, as {task.state.value}")
    print(f"  {block.start:%a %Y-%m-%d %H:%M} - {block.end:%H:%M}  ({block.minutes} min)")
    print(f"  estimate {task.estimated_seconds // 60} min, "
          f"-> {'history.jsonl' if completed else 'active.json'}")
    found = clashes_with(block, tasks=tasks)
    for c in found:
        print(f"  OVERLAPS {c.start:%H:%M}-{c.end:%H:%M} {c.name[:48]!r}")
    if not found:
        print("  no overlap with work already tracked")

    if not args.apply:
        print("\n(dry run -- pass --apply to write)")
        return

    if completed:
        dest = backup(HISTORY_FILE)
        append_to_history(task)
    else:
        assert_etime_not_running()
        dest = backup(ACTIVE_FILE)
        tasks.insert(subtree_end(tasks, root=parent), task)
        save_active_tasks(tasks)

    print(f"\nBacked up to {dest}")
    print(f"Added {task.name!r} (id {task.id})")


if __name__ == "__main__":
    main()
