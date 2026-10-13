"""Data models for etime application."""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
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
    is_stashed: bool = False  # Hidden from default view but not completed
    is_collapsed: bool = False  # When True, this task's subtree is folded (hidden) in the overlay
    # ISO timestamp of when this task started waiting on something external (a
    # reply, a sweep, a build). Deliberately a field on a paused task rather than
    # a new TaskState: waiting is about *why* it's parked, and everything that
    # reasons about state — the dashboard, the review, the alarms — should go on
    # treating it as plain paused.
    waiting_since: Optional[str] = None

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

    @staticmethod
    def _interval_end(iv: dict, now: datetime) -> datetime:
        """End of an interval, treating an open (running) interval as ending now."""
        return datetime.fromisoformat(iv["end"]) if iv["end"] else now

    def add_manual_minutes(self, minutes: int) -> dict:
        """Backfill ``minutes`` of work ending now, attributed to [now - minutes, now].

        Adds a closed work interval covering the last ``minutes`` minutes (this
        feeds the dashboard's time-of-day view, so the time lands in the window
        just before now) and bumps ``elapsed_seconds`` by exactly ``minutes``.

        We add to the *prior* elapsed rather than re-derive purely from intervals:
        a legacy task with no ``work_intervals`` carries its time in
        ``elapsed_seconds`` (compute_elapsed's fallback), which adding an interval
        would otherwise shadow away.

        The interval is inserted *before* any trailing open interval, never after,
        so the "open interval is always last" invariant that start_interval /
        end_interval rely on is preserved. Returns the added interval dict.
        """
        now = datetime.now()
        start = now - timedelta(minutes=minutes)
        interval = {"start": start.isoformat(), "end": now.isoformat()}
        prior = self.compute_elapsed()
        if self.work_intervals and self.work_intervals[-1]["end"] is None:
            # Keep the running (open) interval last.
            self.work_intervals.insert(len(self.work_intervals) - 1, interval)
        else:
            self.work_intervals.append(interval)
        self.elapsed_seconds = prior + minutes * 60
        return interval

    def subtract_manual_minutes(self, minutes: int) -> float:
        """Remove up to ``minutes`` from the newest end of the timeline.

        Trims work intervals from the most recent end backwards (so it undoes the
        "latest" time, mirroring add), capped at the time actually spent — elapsed
        never goes below zero. A running (open) interval is clamped forward, never
        deleted, so the task keeps ticking. Returns the seconds actually removed,
        which is less than requested when capped.
        """
        now = datetime.now()
        req = minutes * 60

        if not self.work_intervals:
            # Legacy task: time lives only in elapsed_seconds, nothing to trim.
            removed = min(req, self.elapsed_seconds)
            self.elapsed_seconds = max(0.0, self.elapsed_seconds - removed)
            return removed

        def _dur(iv: dict) -> float:
            start = datetime.fromisoformat(iv["start"])
            return (self._interval_end(iv, now) - start).total_seconds()

        interval_total = sum(_dur(iv) for iv in self.work_intervals)
        budget = min(req, interval_total)
        remaining = budget

        # Process newest-end first. List order isn't chronological (backfills are
        # inserted, not time-ordered), so sort by end descending rather than trust
        # positional order.
        order = sorted(
            range(len(self.work_intervals)),
            key=lambda i: self._interval_end(self.work_intervals[i], now),
            reverse=True,
        )
        to_delete: set[int] = set()
        for i in order:
            if remaining <= 1e-9:
                break
            iv = self.work_intervals[i]
            start = datetime.fromisoformat(iv["start"])
            end = self._interval_end(iv, now)
            dur = (end - start).total_seconds()
            if iv["end"] is None:
                # Open interval — clamp its start forward (never delete) so it
                # stays open and keeps ticking.
                trim = min(remaining, dur)
                iv["start"] = min(now, start + timedelta(seconds=trim)).isoformat()
                remaining -= trim
            elif dur <= remaining + 1e-9:
                to_delete.add(i)
                remaining -= dur
            else:
                # Partial trim from this closed interval's end.
                iv["end"] = (end - timedelta(seconds=remaining)).isoformat()
                remaining = 0.0

        if to_delete:
            self.work_intervals = [
                iv for j, iv in enumerate(self.work_intervals) if j not in to_delete
            ]

        removed = budget - remaining
        self.elapsed_seconds = max(0.0, self.elapsed_seconds - removed)
        return removed

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
        if 'is_stashed' not in d:
            d['is_stashed'] = False
        if 'is_collapsed' not in d:
            d['is_collapsed'] = False
        if 'waiting_since' not in d:
            d['waiting_since'] = None
        return cls(**d)
