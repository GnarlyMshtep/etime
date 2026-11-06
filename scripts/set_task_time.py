"""Give an open task a stretch of work it did away from the timer, and optionally close it.

Different from logging a new block: the task already exists in ``active.json``,
usually with a second or two on it from a mis-start. ``--when`` replaces that
with the real stretch; ``--close`` then files it to history the way the app
would, so the hours land under the right tag.

``--resume-after`` is the other shape of the same mistake: the time on the task
is right as far as it goes, but the work carried on after you forgot to hit
resume. It appends one interval, from that many minutes past the last recorded
end up to now, and leaves the earlier intervals alone.

Refuses to close a task that has children. Completing a parent promotes its
children up a level, which is how a category header once lost its whole group --
not something to do as a side effect of setting a time.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import ACTIVE_FILE, HISTORY_FILE  # noqa: E402
from models import Task, TaskState  # noqa: E402
from storage import append_to_history, load_active_tasks, save_active_tasks  # noqa: E402
from time_range import TimeRange, parse_time_range  # noqa: E402

BACKUP_DIR = Path.home() / "Dev" / "etime" / "claude_data"


@dataclass
class Plan:
    task: Task
    block: Optional[TimeRange]   # None = leave the recorded time alone
    added: Optional[TimeRange]   # an interval appended to what's already there
    dropped: list[dict]          # intervals the new one replaces
    close: bool


def assert_etime_not_running() -> None:
    pids = subprocess.run(
        ["pgrep", "-f", "[Pp]ython.*main[.]py"], capture_output=True, text=True
    ).stdout.split()
    if pids:
        sys.exit(f"etime is running (pid {', '.join(pids)}). Quit it first -- it holds the "
                 f"task list in memory and would write this straight back out.")


def find_one(tasks: list[Task], *, needle: str) -> Task:
    exact = [t for t in tasks if t.name.strip().lower() == needle.strip().lower()]
    partial = [t for t in tasks if needle.strip().lower() in t.name.lower()]
    matches = exact or partial
    if not matches:
        sys.exit(f"no active task matching {needle!r}")
    if len(matches) > 1:
        names = "\n  ".join(t.name for t in matches)
        sys.exit(f"{len(matches)} active tasks match {needle!r}:\n  {names}")
    return matches[0]


def last_recorded_end(task: Task) -> datetime:
    ends = [iv["end"] for iv in task.work_intervals if iv.get("end")]
    if not ends:
        sys.exit(f"{task.name!r} has no finished interval to carry on from")
    # Keyed on the parsed value, not the string: offset-aware and naive stamps
    # don't sort lexicographically.
    return max((datetime.fromisoformat(e) for e in ends))


def plan(tasks: list[Task], *, needle: str, when: Optional[str],
         resume_after: Optional[float], close: bool) -> Plan:
    task = find_one(tasks, needle=needle)
    block = parse_time_range(when) if when else None
    added: Optional[TimeRange] = None
    if resume_after is not None:
        if any(not iv.get("end") for iv in task.work_intervals):
            sys.exit(f"{task.name!r} is still running -- pause it in etime first, "
                     f"otherwise there's no end to carry on from")
        start = last_recorded_end(task) + timedelta(minutes=resume_after)
        now = datetime.now()
        if start >= now:
            sys.exit(f"that puts the start at {start:%H:%M:%S}, which is not before "
                     f"now ({now:%H:%M:%S})")
        added = TimeRange(start=start, end=now)
    if close:
        children = [t for t in tasks if t.parent_task_id == task.id]
        if children:
            sys.exit(f"{task.name!r} has {len(children)} subtask(s) -- closing it would "
                     f"promote them to its own level. Deal with them first:\n  "
                     + "\n  ".join(c.name for c in children))
    return Plan(task=task, block=block, added=added,
                dropped=list(task.work_intervals), close=close)


def apply_plan(*, p: Plan) -> None:
    if p.block is not None:
        p.task.elapsed_seconds = p.block.seconds
        p.task.started_at = p.block.start.isoformat()
        p.task.work_intervals = [{"start": p.block.start.isoformat(),
                                  "end": p.block.end.isoformat()}]
        # Otherwise resuming a task already past its estimate fires the overtime
        # alarm for time spent before the block was recorded.
        p.task.last_alarm_level = (
            1 if p.task.elapsed_seconds >= p.task.estimated_seconds else 0
        )
    if p.added is not None:
        p.task.work_intervals.append({"start": p.added.start.isoformat(),
                                      "end": p.added.end.isoformat()})
        # Rounded because float seconds accumulate noise that shows up as a
        # changed elapsed on a task nothing else touched.
        p.task.elapsed_seconds = round(p.task.elapsed_seconds + p.added.seconds, 6)
        p.task.last_alarm_level = (
            1 if p.task.elapsed_seconds >= p.task.estimated_seconds else 0
        )
    p.task.waiting_since = None
    if p.close:
        p.task.state = TaskState.COMPLETED
        # With no block given there's nothing to date it to but now.
        end = p.added.end if p.added else (p.block.end if p.block else datetime.now())
        p.task.completed_at = end.isoformat()
    else:
        p.task.state = TaskState.PAUSED


def backup(path: Path) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = BACKUP_DIR / f"{path.name}.{stamp}.bak"
    shutil.copy2(path, dest)
    return dest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task", required=True, help="name or unique substring")
    ap.add_argument("--when", default=None,
                    help='e.g. "yesterday 9 to 10pm"; omit to leave its time as-is')
    ap.add_argument("--resume-after", dest="resume_after", type=float, default=None,
                    metavar="MIN",
                    help="append an interval running from MIN minutes after the last "
                         "recorded end up to now -- for work that carried on past a pause")
    ap.add_argument("--close", action="store_true", help="complete it and file it to history")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not args.when and args.resume_after is None and not args.close:
        sys.exit("nothing to do -- pass --when, --resume-after, --close, or a combination")
    if args.when and args.resume_after is not None:
        sys.exit("--when replaces the recorded time and --resume-after adds to it; "
                 "pick one")

    tasks = load_active_tasks()
    p = plan(tasks, needle=args.task, when=args.when,
             resume_after=args.resume_after, close=args.close)
    by_id = {t.id: t for t in tasks}
    parent = by_id.get(p.task.parent_task_id)

    print(f"{p.task.name!r}")
    print(f"  under      {parent.name if parent else '(top level)'!r}")
    if p.block is None:
        print(f"  time       left as recorded "
              f"({p.task.elapsed_seconds:.1f}s, est {p.task.estimated_seconds // 60} min)")
    else:
        print(f"  set time   {p.block.start:%a %Y-%m-%d %H:%M} - {p.block.end:%H:%M} "
              f"({p.block.minutes} min, est {p.task.estimated_seconds // 60} min)")
    for iv in (p.dropped if p.block is not None else []):
        span = (datetime.fromisoformat(iv["end"]) - datetime.fromisoformat(iv["start"])
                ).total_seconds() if iv.get("end") else None
        print(f"  replacing  {iv.get('start', '?')[:19]} -> {iv.get('end') or 'OPEN'}"
              + (f"  ({span:.1f}s)" if span is not None else ""))
    if p.added is not None:
        total = (p.task.elapsed_seconds + p.added.seconds) / 60
        print(f"  carry on   {p.added.start:%a %Y-%m-%d %H:%M:%S} - {p.added.end:%H:%M:%S} "
              f"(+{p.added.minutes} min, {len(p.dropped)} interval(s) kept)")
        print(f"  total      {total:.1f} min against a "
              f"{p.task.estimated_seconds // 60} min estimate")
    print(f"  then       {'complete it -> history.jsonl' if p.close else 'leave it paused'}")

    if not args.apply:
        print("\n(dry run -- pass --apply to write)")
        return

    assert_etime_not_running()
    backups = [backup(ACTIVE_FILE)] + ([backup(HISTORY_FILE)] if p.close else [])
    apply_plan(p=p)
    if p.close:
        append_to_history(p.task)
        save_active_tasks([t for t in tasks if t.id != p.task.id])
    else:
        save_active_tasks(tasks)

    print("\nBacked up to:\n  " + "\n  ".join(str(b) for b in backups))
    print(f"{'Closed' if p.close else 'Updated'} {p.task.name!r} "
          f"({p.task.elapsed_seconds / 60:.0f} min)")


if __name__ == "__main__":
    main()
