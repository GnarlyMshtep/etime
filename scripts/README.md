# scripts/

Maintenance tools for the task log. They operate on `~/.etime/active.json` and
`~/.etime/history.jsonl` directly, for the things the overlay has no hotkey for:
backfilling work that happened away from the timer, re-filing tasks, and undoing
accidents.

Every one of them **dry-runs by default** and prints exactly what it would do.
Pass `--apply` to write.

## The rules they all follow

- **Back up first.** Each run copies the file it touches into `claude_data/`
  before writing, timestamped.
- **Refuse to run while etime is up**, for anything that writes `active.json`.
  The app holds the task list in memory and rewrites that file on every change,
  so it would overwrite the edit seconds later. Quit etime, run the script,
  restart it. Scripts that only *append* to `history.jsonl` — which is what the
  app itself does on completion — are safe to run with it open.
- **Fail loudly.** An ambiguous task name, a non-contiguous subtree, a missing
  parent: all exit with a message rather than guessing.
- **Keep subtrees contiguous.** The overlay renders `active.json` in file order
  but computes indentation from `parent_task_id`, so a re-parented task has to
  be moved in the file too or it draws indented under a section it isn't next to.

## The tools

| | |
|---|---|
| `log_past_block.py` | Add a task for a stretch of past work, under an existing parent. `--state paused` (default) leaves it for you to finish; `--state completed` files it straight to history. |
| `set_task_time.py` | Give a task that's *already open* the time it actually took, and optionally `--close` it. Refuses to close a task with subtasks. |
| `add_category.py` | Create a category tag — a root estimated at one minute — placed in the category cluster at the top of the list. |
| `move_subtree.py` | Re-file a task and everything under it beneath a different parent, or `--to-top`. |
| `restore_completed_parent.py` | Undo an accidentally-completed parent task, rebuilding it from a snapshot in the `~/.etime` backup repo. Needed because completing a task promotes its children up a level, which erases exactly the links you'd need to reverse it. |

Times are parsed by `time_range.py` in the repo root, the same module behind the
New Task dialog's **When** field, so they read identically in both places:

```
2:30-4            today, afternoon (a bare 1–6 reads as pm)
9-10:30           today, morning
9-10:06 pm        a trailing am/pm applies to both ends
04:00-05:00       a zero-padded hour is 24-hour time, left alone
yesterday 2-3     also: today, 9/26, 2026-09-26
```

## Examples

```bash
# a meeting you didn't time
python3 scripts/log_past_block.py --name "1:1 with wen" --under meetings --when "yesterday 2:30-4"

# a task you'd started but never timed, now finished
python3 scripts/set_task_time.py --task "general trends" --when "yesterday 9 to 10pm" --close

# new category, then file something under it
python3 scripts/add_category.py --name health --apply
python3 scripts/log_past_block.py --name run --under health --when "yesterday 4-5:30" --apply

# re-file a task and its subtree
python3 scripts/move_subtree.py --task ningning --under writing --apply
```
