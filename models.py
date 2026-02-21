"""Data models for etime application."""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional, List
import uuid


class TaskState(str, Enum):
    """Task lifecycle states."""
    BACKLOG = "backlog"    # Created but not started (rare, since we auto-start)
    ONGOING = "ongoing"    # Timer running
    PAUSED = "paused"      # Timer stopped, can resume
    COMPLETED = "completed"


@dataclass
class Task:
    """Represents a single time-tracked task."""

    id: str                              # uuid4 string
    name: str                            # e.g., "implement baseline"
    estimated_seconds: int               # e.g., 1800 for 30 min
    state: TaskState = TaskState.ONGOING
    elapsed_seconds: float = 0.0         # Accumulated time
    created_at: str = ""                 # ISO format timestamp
    started_at: Optional[str] = None     # When first started
    completed_at: Optional[str] = None   # When completed
    ambitious_seconds: Optional[int] = None  # Stretch goal time (must be <= estimated)
    linear_issue: Optional[str] = None   # e.g., "MSH-28" (for future use)
    last_alarm_level: int = 0            # 0=none, 1=overtime, 2=2x, 3=3x...
    work_intervals: List[dict] = field(default_factory=list)  # [{"start": ISO, "end": ISO|None}]
    parent_task_id: Optional[str] = None  # ID of parent task (for subtasks)

    def __post_init__(self):
        """Auto-generate ID and timestamp if not provided."""
        if not self.id:
            self.id = str(uuid.uuid4())
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    def to_dict(self) -> dict:
        """Convert Task to dictionary for JSON serialization."""
        d = asdict(self)
        d['state'] = self.state.value
        return d

    def start_interval(self) -> None:
        """Record the start of a new work interval (task started/resumed)."""
        self.work_intervals.append({"start": datetime.now().isoformat(), "end": None})

    def end_interval(self) -> None:
        """Close the current open work interval (task paused/completed)."""
        if self.work_intervals and self.work_intervals[-1]["end"] is None:
            self.work_intervals[-1]["end"] = datetime.now().isoformat()

    def compute_elapsed(self) -> float:
        """Compute elapsed seconds from work intervals (single source of truth).

        Falls back to self.elapsed_seconds for old tasks without intervals,
        ensuring full backwards compatibility.
        """
        if not self.work_intervals:
            return self.elapsed_seconds
        total = 0.0
        now = datetime.now()
        for iv in self.work_intervals:
            start = datetime.fromisoformat(iv["start"])
            end = datetime.fromisoformat(iv["end"]) if iv["end"] else now
            total += (end - start).total_seconds()
        return total

    @classmethod
    def from_dict(cls, d: dict) -> 'Task':
        """Create Task from dictionary (JSON deserialization)."""
        d['state'] = TaskState(d['state'])
        # Handle old data missing fields
        if 'ambitious_seconds' not in d:
            d['ambitious_seconds'] = None
        if 'work_intervals' not in d:
            d['work_intervals'] = []
        if 'parent_task_id' not in d:
            d['parent_task_id'] = None
        return cls(**d)
