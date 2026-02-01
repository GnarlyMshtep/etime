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
