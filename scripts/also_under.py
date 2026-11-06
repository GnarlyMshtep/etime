"""Make a task count under a further category, or stop it doing so.

``also_under`` is the second-owner list on a task (see ``Task.also_under``): a
meeting filed under "meetings" that is also metagrad work. The dashboard counts
its time under both, in full and split.

Works on a completed task in history.jsonl (safe while etime runs -- the app
only ever appends there) or an open one in active.json (etime must be quit,
since it holds that list in memory). The categories named must be open tasks.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import ACTIVE_FILE, HISTORY_FILE  # noqa: E402
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


def matching(names: list[str], *, needle: str) -> list[int]:
    """Indices of exact (case-insensitive) matches, else of substring matches."""
    n = needle.strip().lower()
    exact = [i for i, x in enumerate(names) if x.strip().lower() == n]
    return exact or [i for i, x in enumerate(names) if n in x.lower()]


def find_category(tasks: list[Task], *, name: str) -> Task:
    hits = matching([t.name for t in tasks], needle=name)
    if not hits:
        roots = ", ".join(t.name for t in tasks if t.parent_task_id is None)
        sys.exit(f"no open task matching {name!r}. Top-level tasks: {roots}")
    if len(hits) > 1:
        sys.exit(f"{len(hits)} tasks match {name!r}: " + ", ".join(tasks[i].name for i in hits))
    return tasks[hits[0]]


def backup(path: Path) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = BACKUP_DIR / f"{path.name}.{stamp}.bak"
    shutil.copy2(path, dest)
    return dest


def updated_ids(current: list[str], *, add: list[Task], remove: list[Task],
                parent_id: Optional[str]) -> list[str]:
    out = [i for i in current if i not in {t.id for t in remove}]
    for t in add:
        if t.id == parent_id:
            sys.exit(f"{t.name!r} is already its parent")
        if t.id not in out:
            out.append(t.id)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task", required=True, help="name or unique substring")
    ap.add_argument("--add", action="append", default=[], help="category to add; repeatable")
    ap.add_argument("--remove", action="append", default=[], help="category to drop; repeatable")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not args.add and not args.remove:
        sys.exit("nothing to do: pass --add and/or --remove")

    tasks = load_active_tasks()
    names = {t.id: t.name for t in tasks}
    add = [find_category(tasks, name=n) for n in args.add]
    remove = [find_category(tasks, name=n) for n in args.remove]

    lines = HISTORY_FILE.read_text().splitlines()
    rows: dict[int, dict] = {i: json.loads(l) for i, l in enumerate(lines) if l.strip()}
    open_hits = matching([t.name for t in tasks], needle=args.task)
    hist_idx = list(rows)
    hist_hits = [hist_idx[i] for i in matching([rows[i].get("name", "") for i in hist_idx],
                                               needle=args.task)]
    found = [("active", tasks[i].name) for i in open_hits] + \
            [("history", rows[i].get("name", "")) for i in hist_hits]
    if len(found) != 1:
        listing = "\n  ".join(f"[{where}] {n}" for where, n in found)
        sys.exit(f"{len(found)} tasks match {args.task!r}" + (f":\n  {listing}" if found else ""))

    if open_hits:
        task = tasks[open_hits[0]]
        before = list(task.also_under)
        after = updated_ids(before, add=add, remove=remove, parent_id=task.parent_task_id)
        where, name = "active.json", task.name
    else:
        row = rows[hist_hits[0]]
        before = list(row.get("also_under") or [])
        after = updated_ids(before, add=add, remove=remove, parent_id=row.get("parent_task_id"))
        where, name = "history.jsonl", row.get("name", "")

    show = lambda ids: ", ".join(names.get(i, i) for i in ids) or "nothing"  # noqa: E731
    print(f"{name!r} ({where})\n  also under: {show(before)}  ->  {show(after)}")
    if after == before:
        print("  (no change)")
        return
    if not args.apply:
        print("\n(dry run -- pass --apply to write)")
        return

    if open_hits:
        assert_etime_not_running()
        dest = backup(ACTIVE_FILE)
        task.also_under = after
        save_active_tasks(tasks)
    else:
        dest = backup(HISTORY_FILE)
        row["also_under"] = after
        lines[hist_hits[0]] = json.dumps(row)
        tmp = HISTORY_FILE.with_suffix(".jsonl.tmp")
        tmp.write_text("\n".join(lines) + "\n")
        os.replace(tmp, HISTORY_FILE)
    print(f"\nBacked up to {dest}\nUpdated.")


if __name__ == "__main__":
    main()
