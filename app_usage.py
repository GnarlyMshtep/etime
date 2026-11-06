"""Read the app-usage log and turn it into spans the timeline can draw.

The sampler (app_sampler.py) writes one short run per stretch of foreground
time. This coalesces those back into human-sized spans, keeps the ones on apps
your blocked-app list names, and reports them per day.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable, Optional

from app_usage_types import AppRun, BlockList, load_block_list
from config import APP_USAGE_FILE

# Two runs of the same app this close together are the same sitting -- the gap is
# a sample boundary or a glance at another window, not a return to work.
COALESCE_GAP_SECONDS = 60.0
# Shorter than this is a pass through the app (cmd-tab overshoot, a glance at a
# notification) and only adds noise to the band.
MIN_SPAN_SECONDS = 20.0


@dataclass
class UsageSpan:
    """One sitting in one app, as the timeline wants it."""

    bundle_id: str
    app_name: str
    start: str
    end: str
    seconds: float
    idle_seconds: float
    start_minute: int       # minutes past midnight, matching Block
    end_minute: int

    @property
    def minutes(self) -> float:
        return self.seconds / 60.0

    @property
    def active_seconds(self) -> float:
        """Time with input in it. A browser left open all afternoon isn't time spent."""
        return max(0.0, self.seconds - self.idle_seconds)


def load_runs(*, path: Path = APP_USAGE_FILE, lo: Optional[datetime] = None,
              hi: Optional[datetime] = None) -> list[AppRun]:
    """Read runs overlapping [lo, hi). Returns [] when the sampler has never run."""
    if not path.exists():
        return []
    runs: list[AppRun] = []
    with open(path, "r") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                run = AppRun(**raw)
                start, end = run.start_dt, run.end_dt
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{path}:{line_no} is not an app run: {exc}") from exc
            if lo is not None and end <= lo:
                continue
            if hi is not None and start >= hi:
                continue
            runs.append(run)
    runs.sort(key=lambda r: r.start_dt)
    return runs


def coalesce(*, runs: Iterable[AppRun],
             gap_seconds: float = COALESCE_GAP_SECONDS) -> list[UsageSpan]:
    """Merge consecutive runs of the same app into one span."""
    spans: list[UsageSpan] = []
    for run in runs:
        start, end = run.start_dt, run.end_dt
        if spans:
            last = spans[-1]
            same_app = last.bundle_id == run.bundle_id
            close = (start - datetime.fromisoformat(last.end)).total_seconds() <= gap_seconds
            if same_app and close:
                last.end = run.end
                last.seconds += run.seconds
                last.idle_seconds += run.idle_seconds
                last.end_minute = end.hour * 60 + end.minute
                continue
        spans.append(UsageSpan(
            bundle_id=run.bundle_id,
            app_name=run.app_name,
            start=run.start,
            end=run.end,
            seconds=run.seconds,
            idle_seconds=run.idle_seconds,
            start_minute=start.hour * 60 + start.minute,
            end_minute=end.hour * 60 + end.minute,
        ))
    return spans


@dataclass
class DayUsage:
    """What the sampler saw on one day, reduced to the blocked apps."""

    date: str
    spans: list[UsageSpan]
    blocked_seconds: float
    blocked_active_seconds: float
    by_app: dict[str, float]        # app name -> seconds, blocked apps only
    visits: int                     # separate sittings, however short
    sampled: bool                   # False when the sampler wasn't running
    note: str = ""                  # why the band is empty, when it is

    def as_dict(self) -> dict:
        return {
            "date": self.date,
            "sampled": self.sampled,
            "blocked_seconds": round(self.blocked_seconds, 1),
            "blocked_active_seconds": round(self.blocked_active_seconds, 1),
            "visits": self.visits,
            "by_app": {k: round(v, 1) for k, v in self.by_app.items()},
            "note": self.note,
            "spans": [
                {
                    "app": s.app_name,
                    "start_minute": s.start_minute,
                    "end_minute": s.end_minute,
                    "minutes": round(s.minutes, 2),
                    "active_minutes": round(s.active_seconds / 60.0, 2),
                    "start": s.start[11:16],
                    "end": s.end[11:16],
                }
                for s in self.spans
            ],
        }


def blocked_usage_by_day(*, dates: list[date], path: Path = APP_USAGE_FILE,
                         block_list: Optional[BlockList] = None) -> dict[str, DayUsage]:
    """Per-day blocked-app spans for ``dates``.

    ``sampled`` distinguishes "the sampler saw nothing distracting" from "the
    sampler wasn't running" -- without it an empty band reads as a clean day.
    """
    if block_list is None:
        block_list = load_block_list()
    lo = datetime.combine(dates[0], time.min)
    hi = datetime.combine(dates[-1] + timedelta(days=1), time.min)
    runs = load_runs(path=path, lo=lo, hi=hi)

    out: dict[str, DayUsage] = {}
    for d in dates:
        key = d.isoformat()
        day_runs = [r for r in runs if r.start_dt.date() == d]
        # Any sample at all that day, blocked or not, means we were watching.
        sampled = bool(day_runs)
        # Counted over *all* the day's runs, so a sitting broken into segments
        # counts once and leaving the app and coming back counts twice. Before
        # the length filter: a 6-second check of Slack is exactly the kind of
        # visit worth counting and the wrong thing to draw.
        visits = sum(1 for s in coalesce(runs=day_runs)
                     if block_list.blocks(bundle_id=s.bundle_id))
        spans = [s for s in coalesce(runs=[r for r in day_runs
                                           if block_list.blocks(bundle_id=r.bundle_id)])
                 if s.seconds >= MIN_SPAN_SECONDS]
        by_app: dict[str, float] = {}
        for s in spans:
            by_app[s.app_name] = by_app.get(s.app_name, 0.0) + s.seconds
        out[key] = DayUsage(
            date=key,
            spans=spans,
            blocked_seconds=sum(s.seconds for s in spans),
            blocked_active_seconds=sum(s.active_seconds for s in spans),
            by_app=dict(sorted(by_app.items(), key=lambda kv: -kv[1])),
            visits=visits,
            sampled=sampled,
            note=("" if block_list.missing else
                  block_list.error if block_list.error else
                  "" if sampled else "app sampler wasn't running"),
        )
    return out
