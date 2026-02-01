"""Data models for etime application."""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional
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

    @classmethod
    def from_dict(cls, d: dict) -> 'Task':
        """Create Task from dictionary (JSON deserialization)."""
        d['state'] = TaskState(d['state'])
        # Handle old data missing ambitious_seconds
        if 'ambitious_seconds' not in d:
            d['ambitious_seconds'] = None
        return cls(**d)
