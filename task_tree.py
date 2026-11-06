"""Re-filing a task, and everything under it, beneath a different parent.

Two things have to happen together. The task's ``parent_task_id`` changes, and
its rows move in the task list -- the overlay renders the list in order and
computes indentation from parent links, so a re-parented task left where it was
would draw indented under a section it isn't next to.

Only the moved task's own parent changes. Its descendants keep pointing at it,
so the subtree arrives with its shape intact rather than flattened.

Shared by the edit dialog in the app and ``scripts/move_subtree.py``. Problems
raise ``ValueError`` rather than exiting, so the running app can show them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from models import Task


@dataclass
class Move:
    task: Task
    subtree: list[Task]          # the task first, then its descendants, in list order
    new_parent: Optional[Task]   # None means "make it top level"
    from_index: int
    to_index: int


def subtree_ids(tasks: list[Task], *, root: Task) -> set[str]:
    """Ids of the root and all its descendants, wherever they sit in the list."""
    ids = {root.id}
    grew = True
    while grew:
        grew = False
        for t in tasks:
            if t.parent_task_id in ids and t.id not in ids:
                ids.add(t.id)
                grew = True
    return ids


def collect_subtree(tasks: list[Task], *, root: Task) -> list[Task]:
    """The root and all its descendants, in the order they appear in the list."""
    ids = subtree_ids(tasks, root=root)
    block = [t for t in tasks if t.id in ids]

    indices = [i for i, t in enumerate(tasks) if t.id in ids]
    if indices != list(range(indices[0], indices[0] + len(indices))):
        raise ValueError(f"the subtree under {root.name!r} isn't a contiguous run "
                         f"(indices {indices}) -- refusing to reorder around it")
    return block


def subtree_end(tasks: list[Task], *, root: Task) -> int:
    """Index just past the last row of ``root``'s subtree."""
    block_ids = {t.id for t in collect_subtree(tasks, root=root)}
    last = max(i for i, t in enumerate(tasks) if t.id in block_ids)
    return last + 1


def plan_move(tasks: list[Task], *, task: Task, new_parent: Optional[Task]) -> Move:
    block = collect_subtree(tasks, root=task)
    from_index = tasks.index(task)

    if new_parent is not None:
        if new_parent.id in {t.id for t in block}:
            raise ValueError(f"{new_parent.name!r} is inside {task.name!r}'s own subtree -- "
                             f"that would make a cycle")
        if new_parent.id == task.parent_task_id:
            raise ValueError(f"{task.name!r} is already under {new_parent.name!r}")

    # Where it lands is computed on the list with the block already removed, so
    # this works whether the task currently sits above or below its new parent.
    remaining = [t for t in tasks if t.id not in {b.id for b in block}]
    to_index = subtree_end(remaining, root=new_parent) if new_parent else len(remaining)
    return Move(task=task, subtree=block, new_parent=new_parent,
                from_index=from_index, to_index=to_index)


def apply_move(tasks: list[Task], *, move: Move) -> list[Task]:
    block_ids = {t.id for t in move.subtree}
    remaining = [t for t in tasks if t.id not in block_ids]
    move.task.parent_task_id = move.new_parent.id if move.new_parent else None
    return remaining[:move.to_index] + move.subtree + remaining[move.to_index:]
