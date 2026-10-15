"""Undo an accidentally-completed parent task without discarding anything since.

``complete_task`` promotes a completed task's children up one level. That's
right for a real task -- otherwise a grandchild would jump two levels -- and
wrong for a category header, where it dumps the whole group at top level and
takes the header away.

The app's own undo would fix it, but undo is LIFO, so anything done afterwards
would have to be thrown away first. This reaches for the one task instead.

Which children belonged to it can't be read off the live file -- the completion
overwrote exactly that. It's read from a snapshot in the ``~/.etime`` backup
repo taken before the mishap, which is why this takes a git revision.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ETIME_DIR = Path.home() / ".etime"
ACTIVE_FILE = ETIME_DIR / "active.json"
HISTORY_FILE = ETIME_DIR / "history.jsonl"
BACKUP_DIR = Path.home() / "Dev" / "etime" / "claude_data"


@dataclass
class Restore:
    parent: dict            # the row as it looked before completion
    child_ids: list[str]
    history_line: int
    insert_at: int


def assert_etime_not_running() -> None:
    pids = subprocess.run(["pgrep", "-f", "[Pp]ython.*main[.]py"],
                          capture_output=True, text=True).stdout.split()
    if pids:
        sys.exit(f"etime is running (pid {', '.join(pids)}). Quit it first -- it holds the "
                 f"task list in memory and would write this straight back out.")


def snapshot(revision: str) -> list[dict]:
    out = subprocess.run(["git", "-C", str(ETIME_DIR), "show", f"{revision}:active.json"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"can't read active.json at {revision}: {out.stderr.strip()}")
    return json.loads(out.stdout)


def plan(*, name: str, revision: str) -> Restore:
    before = snapshot(revision)
    matches = [t for t in before if t["name"] == name]
    if len(matches) != 1:
        sys.exit(f"{len(matches)} tasks named {name!r} in {revision} -- need exactly one")
    parent = matches[0]
    child_ids = [t["id"] for t in before if t.get("parent_task_id") == parent["id"]]

    active = json.loads(ACTIVE_FILE.read_text())
    live = {t["id"] for t in active}
    if parent["id"] in live:
        sys.exit(f"{name!r} is already in active.json -- nothing to restore")
    missing = [c for c in child_ids if c not in live]
    if missing:
        sys.exit(f"{len(missing)} of its children are no longer active -- "
                 f"restoring would only half-rebuild the group")

    # Slot it immediately before its children so the subtree stays one
    # contiguous run, which the insertion and folding code both assume.
    insert_at = min(i for i, t in enumerate(active) if t["id"] in set(child_ids))

    lines = HISTORY_FILE.read_text().splitlines()
    rows = [(i, json.loads(l)) for i, l in enumerate(lines) if l.strip()]
    hits = [(i, r) for i, r in rows if r.get("id") == parent["id"]]
    if len(hits) != 1:
        sys.exit(f"{len(hits)} history rows with id {parent['id']} -- expected exactly one")

    return Restore(parent=parent, child_ids=child_ids,
                   history_line=hits[0][0], insert_at=insert_at)


def backup(path: Path) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / f"{path.name}.{stamp}.bak"
    shutil.copy2(path, dest)
    return dest


def write_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.stem}_", suffix=".tmp")
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    os.replace(tmp, path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", required=True)
    ap.add_argument("--from-revision", required=True,
                    help="git rev in ~/.etime from before the completion, e.g. 39a1542")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    r = plan(name=args.name, revision=args.from_revision)
    active = json.loads(ACTIVE_FILE.read_text())
    by_id = {t["id"]: t for t in active}

    print(f"Restore {r.parent['name']!r} at index {r.insert_at}, "
          f"as {r.parent['state']} (est {r.parent['estimated_seconds']}s, "
          f"elapsed {r.parent['elapsed_seconds']:.1f}s, collapsed={r.parent['is_collapsed']})")
    print(f"Re-parent {len(r.child_ids)} task(s) currently at top level:")
    for cid in r.child_ids:
        print(f"    {by_id[cid]['name'][:58]!r}")
    print(f"Drop history.jsonl line {r.history_line + 1} (the completion)")

    if not args.apply:
        print("\n(dry run -- pass --apply to write)")
        return

    assert_etime_not_running()
    backups = [backup(ACTIVE_FILE), backup(HISTORY_FILE)]

    restored = dict(r.parent)
    restored["state"] = "paused"          # it was never really finished
    restored["completed_at"] = None
    for cid in r.child_ids:
        by_id[cid]["parent_task_id"] = restored["id"]
    active.insert(r.insert_at, restored)
    write_atomic(ACTIVE_FILE, json.dumps(active, indent=2))

    lines = HISTORY_FILE.read_text().splitlines()
    del lines[r.history_line]
    write_atomic(HISTORY_FILE, "\n".join(lines) + "\n")

    print("\nBacked up to:\n  " + "\n  ".join(str(b) for b in backups))
    print(f"Restored {restored['name']!r} with {len(r.child_ids)} children.")


if __name__ == "__main__":
    main()
