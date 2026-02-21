"""File storage layer for etime application."""

import json
import tempfile
import os
from pathlib import Path
from typing import List

from models import Task
from config import ETIME_DIR, ACTIVE_FILE, HISTORY_FILE


def ensure_etime_dir() -> None:
    """Create ~/.etime directory if it doesn't exist."""
    ETIME_DIR.mkdir(parents=True, exist_ok=True)


def load_active_tasks() -> List[Task]:
    """
    Load active tasks from active.json.

    Returns:
        List of Task objects. Empty list if file doesn't exist or is corrupt.
    """
    if not ACTIVE_FILE.exists():
        return []

    try:
        with open(ACTIVE_FILE, 'r') as f:
            data = json.load(f)

        if not isinstance(data, list):
            print(f"Warning: {ACTIVE_FILE} is not a list, starting fresh")
            return []

        tasks = []
        for task_dict in data:
            try:
                task = Task.from_dict(task_dict)
                tasks.append(task)
            except Exception as e:
                print(f"Warning: Failed to load task {task_dict.get('id', 'unknown')}: {e}")
                continue

        return tasks

    except Exception as e:
        print(f"Warning: Failed to load {ACTIVE_FILE}: {e}")
        return []


def save_active_tasks(tasks: List[Task]) -> None:
    """
    Save active tasks to active.json using atomic write.

    Args:
        tasks: List of Task objects to save.
    """
    ensure_etime_dir()

    # Convert tasks to dictionaries
    data = [task.to_dict() for task in tasks]

    # Atomic write: write to temp file, then rename
    try:
        # Create temp file in same directory as target
        fd, temp_path = tempfile.mkstemp(
            dir=ETIME_DIR,
            prefix='.active_',
            suffix='.json.tmp'
        )

        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)

        # Atomic rename
        os.rename(temp_path, ACTIVE_FILE)

    except Exception as e:
        print(f"Error: Failed to save {ACTIVE_FILE}: {e}")
        # Clean up temp file if it exists
        try:
            if 'temp_path' in locals():
                os.unlink(temp_path)
        except:
            pass


def append_to_history(task: Task) -> None:
    """
    Append completed task to history.jsonl.

    Args:
        task: Task object to append to history.
    """
    ensure_etime_dir()

    try:
        with open(HISTORY_FILE, 'a') as f:
            json_line = json.dumps(task.to_dict())
            f.write(json_line + '\n')

    except Exception as e:
        print(f"Error: Failed to append to {HISTORY_FILE}: {e}")


def remove_last_from_history(expected_task_id: str) -> bool:
    """
    Remove the last entry from history.jsonl if it matches expected task ID.

    Args:
        expected_task_id: The task ID we expect to find in the last line.

    Returns:
        True if successfully removed, False otherwise.
    """
    if not HISTORY_FILE.exists():
        print("Warning: history file does not exist")
        return False

    try:
        with open(HISTORY_FILE, 'r') as f:
            lines = f.readlines()

        if not lines:
            print("Warning: history file is empty")
            return False

        # Parse last line and validate
        last_line = lines[-1].strip()
        if not last_line:
            # Empty last line, try second to last
            if len(lines) >= 2:
                last_line = lines[-2].strip()
                lines = lines[:-1]  # Remove empty line
            else:
                print("Warning: no valid entries in history")
                return False

        try:
            last_task = json.loads(last_line)
            if last_task.get('id') != expected_task_id:
                print(f"Warning: last history entry ({last_task.get('id')}) doesn't match expected ({expected_task_id})")
                return False
        except json.JSONDecodeError:
            print("Warning: last history line is not valid JSON")
            return False

        # Rewrite file without last line
        with open(HISTORY_FILE, 'w') as f:
            f.writelines(lines[:-1])

        print(f"Removed task {expected_task_id} from history")
        return True

    except Exception as e:
        print(f"Error: Failed to remove from history: {e}")
        return False
