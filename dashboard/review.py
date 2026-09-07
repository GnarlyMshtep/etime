"""Weekly-review aggregation: what did I work on, for the weekly summary.

Everything here is derived from ``work_intervals`` clipped to the requested
range, not from ``elapsed_seconds`` / ``completed_at``. A task that spans
Mon->Fri therefore contributes to each of those days rather than dumping its
whole elapsed time on its completion day.

Intervals are *unioned*, never summed: a parent task is often running while one
of its own subtasks runs, so summing durations double-counts wall-clock time
(~7% over the last month of real data).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, date, time, timedelta
from typing import Optional

Interval = tuple[datetime, datetime]

# Intervals shorter than this are noise (a mis-start, a nav-through) and are
# dropped from the timeline ribbon only — they still count toward totals.
MIN_BLOCK_SECONDS = 90


# --------------------------------------------------------------------------- #
# Types
# --------------------------------------------------------------------------- #

@dataclass
class TagRow:
    """One high-level tag (= the root of a task tree) over the range."""
    id: str
    name: str
    seconds: float
    task_count: int
    has_children: bool
    top_tasks: list[dict] = field(default_factory=list)


@dataclass
class TaskRow:
    """One task with any tracked time inside the range."""
    id: str
    name: str
    tag: str
    tag_id: str
    seconds: float                  # clipped to the range, overlaps merged
    total_elapsed_seconds: float    # lifetime elapsed, for context
    estimated_seconds: int
    ambitious_seconds: Optional[int]
    accuracy: float                 # clipped seconds / estimate, 0 if no estimate
    overtime: bool
    within_ambitious: bool
    state: str
    is_root: bool
    parent_task_id: Optional[str]
    subtree_seconds: float          # own time + all descendants', overlaps merged
    first_start: str                # ISO, first work in range
    last_end: str                   # ISO, last work in range
    days: list[str]                 # ISO dates touched inside the range
    created_at: str
    completed_at: str


@dataclass
class Block:
    """A drawable chunk of work on one calendar day."""
    task_id: str
    name: str
    tag: str
    tag_id: str
    start_minute: int               # minutes since local midnight
    end_minute: int
    minutes: float
    start: str


@dataclass
class DayRow:
    date: str
    seconds: float
    distractions: int
    distraction_times: list[str]    # "HH:MM", for ticks on the timeline
    by_tag: dict[str, float]
    blocks: list[Block]


@dataclass
class Review:
    start: str
    end: str
    tracked_seconds: float          # union across everything (wall-clock)
    tag_seconds_total: float        # sum of per-tag unions (the % denominator)
    active_days: int
    tasks_completed: int
    longest_focus: Optional[dict]
    tags: list[TagRow]
    tasks: list[TaskRow]
    days: list[DayRow]
    overruns: list[dict]
    wins: list[dict]
    loose_threads: list[dict]
    no_interval_tasks: int          # tasks with time but no interval data
    day_min_minute: int             # timeline x-axis bounds
    day_max_minute: int
    summary_text: str


# --------------------------------------------------------------------------- #
# Interval helpers
# --------------------------------------------------------------------------- #

def _clip(task: dict, lo: datetime, hi: datetime, now: datetime) -> list[Interval]:
    """Work intervals of ``task`` intersected with [lo, hi). Open ones end now."""
    out: list[Interval] = []
    for iv in task.get("work_intervals", []):
        try:
            start = datetime.fromisoformat(iv["start"])
        except (KeyError, TypeError, ValueError):
            continue
        raw_end = iv.get("end")
        if raw_end:
            try:
                end = datetime.fromisoformat(raw_end)
            except (TypeError, ValueError):
                continue
        else:
            end = now
        if end <= start:
            continue
        start, end = max(start, lo), min(end, hi)
        if end > start:
            out.append((start, end))
    return out


def merge(intervals: list[Interval]) -> list[Interval]:
    """Merge overlapping/touching intervals into a disjoint, sorted list."""
    if not intervals:
        return []
    merged: list[Interval] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def union_seconds(intervals: list[Interval]) -> float:
    return sum((e - s).total_seconds() for s, e in merge(intervals))


def _split_by_day(intervals: list[Interval]) -> dict[date, list[Interval]]:
    """Split intervals at midnight so each piece belongs to one calendar day."""
    by_day: dict[date, list[Interval]] = {}
    for start, end in intervals:
        cur = start
        while cur < end:
            midnight = datetime.combine(cur.date() + timedelta(days=1), time.min)
            piece_end = min(end, midnight)
            by_day.setdefault(cur.date(), []).append((cur, piece_end))
            cur = piece_end
    return by_day


def _minute(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


# --------------------------------------------------------------------------- #
# Tag (root-of-tree) resolution
# --------------------------------------------------------------------------- #

def _root_of(task: dict, by_id: dict[str, dict]) -> dict:
    """Walk parent links to the root task, which acts as the high-level tag."""
    seen: set[str] = set()
    cur = task
    while True:
        parent_id = cur.get("parent_task_id")
        if not parent_id or parent_id not in by_id or cur.get("id") in seen:
            return cur
        seen.add(cur.get("id", ""))
        cur = by_id[parent_id]


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #

def _hm(seconds: float) -> str:
    total = int(round(seconds / 60))
    h, m = divmod(total, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #

def build_review(
    *,
    history: list[dict],
    active: list[dict],
    dates: list[date],
    distractions_by_day: dict[str, int],
    distraction_times_by_day: Optional[dict[str, list[str]]] = None,
    now: Optional[datetime] = None,
) -> Review:
    """Aggregate everything the weekly-review UI needs for ``dates``."""
    now = now or datetime.now()
    lo = datetime.combine(dates[0], time.min)
    hi = datetime.combine(dates[-1] + timedelta(days=1), time.min)

    all_tasks = list(history) + list(active)
    by_id = {t["id"]: t for t in all_tasks if t.get("id")}
    has_children: set[str] = {
        t["parent_task_id"] for t in all_tasks
        if t.get("parent_task_id") in by_id
    }

    # Tasks with tracked time in the range, plus their clipped intervals.
    clipped: dict[str, list[Interval]] = {}
    in_range: list[dict] = []
    for t in all_tasks:
        ivs = _clip(t, lo, hi, now)
        if ivs:
            clipped[t["id"]] = ivs
            in_range.append(t)

    # Loud about the gap: tasks that completed in the range with no interval
    # data at all (pre-Feb-2026 tracking) are invisible to everything below.
    no_interval_tasks = sum(
        1 for t in history
        if not t.get("work_intervals")
        and (t.get("completed_at") or t.get("created_at", ""))[:10]
        in {d.isoformat() for d in dates}
    )

    # ---- tags ------------------------------------------------------------- #
    tag_intervals: dict[str, list[Interval]] = {}
    tag_names: dict[str, str] = {}
    tag_tasks: dict[str, list[tuple[str, float]]] = {}
    task_tag: dict[str, tuple[str, str]] = {}

    for t in in_range:
        root = _root_of(t, by_id)
        tid, tname = root.get("id", ""), root.get("name", "(untitled)")
        task_tag[t["id"]] = (tid, tname)
        tag_names[tid] = tname
        tag_intervals.setdefault(tid, []).extend(clipped[t["id"]])
        tag_tasks.setdefault(tid, []).append(
            (t.get("name", ""), union_seconds(clipped[t["id"]]))
        )

    tags: list[TagRow] = []
    for tid, ivs in tag_intervals.items():
        top = sorted(tag_tasks[tid], key=lambda x: x[1], reverse=True)[:5]
        tags.append(TagRow(
            id=tid,
            name=tag_names[tid],
            seconds=round(union_seconds(ivs), 1),
            task_count=len(tag_tasks[tid]),
            has_children=tid in has_children,
            top_tasks=[{"name": n, "seconds": round(s, 1)} for n, s in top if s > 0],
        ))
    tags.sort(key=lambda r: r.seconds, reverse=True)

    tracked_seconds = union_seconds([iv for ivs in clipped.values() for iv in ivs])
    tag_seconds_total = sum(t.seconds for t in tags)

    # ---- per-task rows ---------------------------------------------------- #
    day_isos = {d.isoformat() for d in dates}
    children_of: dict[str, list[str]] = {}
    for t in in_range:
        parent = t.get("parent_task_id")
        if parent:
            children_of.setdefault(parent, []).append(t["id"])

    def subtree_intervals(task_id: str, seen: Optional[set[str]] = None) -> list[Interval]:
        seen = seen if seen is not None else set()
        if task_id in seen:
            return []
        seen.add(task_id)
        out = list(clipped.get(task_id, []))
        for child in children_of.get(task_id, []):
            out.extend(subtree_intervals(child, seen))
        return out

    tasks: list[TaskRow] = []
    for t in in_range:
        ivs = merge(clipped[t["id"]])
        secs = sum((e - s).total_seconds() for s, e in ivs)
        est = int(t.get("estimated_seconds", 0) or 0)
        amb = t.get("ambitious_seconds")
        lifetime = float(t.get("elapsed_seconds", 0) or 0)
        tid, tname = task_tag[t["id"]]
        tasks.append(TaskRow(
            id=t["id"],
            name=t.get("name", ""),
            tag=tname,
            tag_id=tid,
            seconds=round(secs, 1),
            total_elapsed_seconds=round(lifetime, 1),
            estimated_seconds=est,
            ambitious_seconds=amb,
            accuracy=round(lifetime / est, 3) if est > 0 else 0.0,
            overtime=est > 0 and lifetime > est,
            within_ambitious=amb is not None and lifetime <= amb,
            state=t.get("state", ""),
            is_root=t["id"] == tid,
            parent_task_id=t.get("parent_task_id"),
            subtree_seconds=round(union_seconds(subtree_intervals(t["id"])), 1),
            first_start=ivs[0][0].isoformat(),
            last_end=ivs[-1][1].isoformat(),
            days=sorted({s.date().isoformat() for s, _ in ivs} & day_isos)
                 or sorted({s.date().isoformat() for s, _ in ivs}),
            created_at=t.get("created_at", ""),
            completed_at=t.get("completed_at") or "",
        ))
    tasks.sort(key=lambda r: r.seconds, reverse=True)

    # ---- days + timeline blocks ------------------------------------------- #
    day_rows: list[DayRow] = []
    day_min, day_max = 24 * 60, 0
    for d in dates:
        blocks: list[Block] = []
        by_tag: dict[str, float] = {}
        day_ivs: list[Interval] = []
        for t in in_range:
            pieces = _split_by_day(merge(clipped[t["id"]])).get(d, [])
            if not pieces:
                continue
            tid, tname = task_tag[t["id"]]
            for start, end in pieces:
                dur = (end - start).total_seconds()
                day_ivs.append((start, end))
                by_tag[tid] = by_tag.get(tid, 0.0) + dur
                if dur >= MIN_BLOCK_SECONDS:
                    blocks.append(Block(
                        task_id=t["id"],
                        name=t.get("name", ""),
                        tag=tname,
                        tag_id=tid,
                        start_minute=_minute(start),
                        end_minute=max(_minute(start) + 1, _minute(end) or 24 * 60),
                        minutes=round(dur / 60, 1),
                        start=start.isoformat(),
                    ))
        blocks.sort(key=lambda b: b.start_minute)
        for b in blocks:
            day_min = min(day_min, b.start_minute)
            day_max = max(day_max, b.end_minute)
        day_rows.append(DayRow(
            date=d.isoformat(),
            seconds=round(union_seconds(day_ivs), 1),
            distractions=distractions_by_day.get(d.isoformat(), 0),
            distraction_times=(distraction_times_by_day or {}).get(d.isoformat(), []),
            by_tag={k: round(v, 1) for k, v in by_tag.items()},
            blocks=blocks,
        ))
    if day_max <= day_min:
        day_min, day_max = 8 * 60, 22 * 60
    day_min = max(0, (day_min // 60) * 60)
    day_max = min(24 * 60, -(-day_max // 60) * 60)

    # ---- overruns / wins -------------------------------------------------- #
    # Only tasks that actually finished in the range have a meaningful
    # estimate-vs-actual, and sub-15-min estimates make the ratio pure noise.
    finished = [
        t for t in tasks
        if t.completed_at[:10] in day_isos and t.estimated_seconds >= 900
    ]
    overruns = [
        {
            "name": t.name, "tag": t.tag,
            "elapsed_seconds": t.total_elapsed_seconds,
            "estimated_seconds": t.estimated_seconds,
            "over_seconds": round(t.total_elapsed_seconds - t.estimated_seconds, 1),
            "accuracy": t.accuracy,
        }
        for t in finished if t.total_elapsed_seconds > t.estimated_seconds
    ]
    overruns.sort(key=lambda r: r["over_seconds"], reverse=True)

    wins = [
        {
            "name": t.name, "tag": t.tag,
            "elapsed_seconds": t.total_elapsed_seconds,
            "estimated_seconds": t.estimated_seconds,
            "ambitious_seconds": t.ambitious_seconds,
            "accuracy": t.accuracy,
            "beat_ambitious": t.within_ambitious,
        }
        for t in finished
        if t.total_elapsed_seconds >= 300
        and (t.within_ambitious or t.total_elapsed_seconds < 0.75 * t.estimated_seconds)
    ]
    wins.sort(key=lambda r: r["accuracy"])

    # ---- loose threads ---------------------------------------------------- #
    loose_threads = [
        {
            "name": t.name, "tag": t.tag, "seconds": t.seconds,
            "state": t.state, "last_end": t.last_end,
            "estimated_seconds": t.estimated_seconds,
            "total_elapsed_seconds": t.total_elapsed_seconds,
        }
        for t in tasks if t.state != "completed" and t.seconds >= 300
    ]

    # Count every completion in the range, including tasks whose work all
    # happened earlier — otherwise this disagrees with the "Tasks completed"
    # stat card sitting directly above it.
    tasks_completed = sum(
        1 for t in history
        if (t.get("completed_at") or t.get("created_at", ""))[:10] in day_isos
    )
    active_days = sum(1 for d in day_rows if d.seconds > 0)

    longest_focus = None
    for t in in_range:
        for start, end in merge(clipped[t["id"]]):
            dur = (end - start).total_seconds()
            if longest_focus is None or dur > longest_focus["seconds"]:
                longest_focus = {
                    "seconds": round(dur, 1),
                    "name": t.get("name", ""),
                    "start": start.isoformat(),
                }

    review = Review(
        start=dates[0].isoformat(),
        end=dates[-1].isoformat(),
        tracked_seconds=round(tracked_seconds, 1),
        tag_seconds_total=round(tag_seconds_total, 1),
        active_days=active_days,
        tasks_completed=tasks_completed,
        longest_focus=longest_focus,
        tags=tags,
        tasks=tasks,
        days=day_rows,
        overruns=overruns[:8],
        wins=wins[:6],
        loose_threads=loose_threads[:12],
        no_interval_tasks=no_interval_tasks,
        day_min_minute=day_min,
        day_max_minute=day_max,
        summary_text="",
    )
    review.summary_text = _draft_summary(review)
    return review


def _draft_summary(r: Review) -> str:
    """A copy-pasteable skeleton to write the weekly summary on top of."""
    lines: list[str] = [
        f"# {r.start} → {r.end}",
        f"{_hm(r.tracked_seconds)} tracked over {r.active_days} active day(s), "
        f"{r.tasks_completed} task(s) completed.",
        "",
    ]
    for tag in r.tags:
        if r.tag_seconds_total > 0:
            share = f" ({tag.seconds / r.tag_seconds_total * 100:.0f}%)"
        else:
            share = ""
        if tag.seconds < 600 and not tag.has_children:
            continue
        lines.append(f"## {tag.name} — {_hm(tag.seconds)}{share}")
        for sub in tag.top_tasks:
            if sub["name"] != tag.name and sub["seconds"] >= 300:
                lines.append(f"- {sub['name']} ({_hm(sub['seconds'])})")
        lines.append("")

    small = [t for t in r.tags if t.seconds < 600 and not t.has_children]
    if small:
        lines.append(
            f"## Odds and ends — {_hm(sum(t.seconds for t in small))} across "
            f"{len(small)} small item(s): " + ", ".join(t.name for t in small[:12])
        )
        lines.append("")

    if r.overruns:
        lines.append("## Ran long")
        for o in r.overruns[:5]:
            lines.append(
                f"- {o['name']} — {_hm(o['elapsed_seconds'])} vs "
                f"{_hm(o['estimated_seconds'])} estimated (+{_hm(o['over_seconds'])})"
            )
        lines.append("")
    if r.wins:
        lines.append("## Came in under")
        for w in r.wins[:5]:
            lines.append(
                f"- {w['name']} — {_hm(w['elapsed_seconds'])} vs "
                f"{_hm(w['estimated_seconds'])} estimated"
            )
        lines.append("")
    if r.loose_threads:
        lines.append("## Carrying over")
        for t in r.loose_threads[:8]:
            lines.append(f"- {t['name']} ({_hm(t['seconds'])} this period, {t['state']})")
        lines.append("")
    if r.no_interval_tasks:
        lines.append(
            f"_Note: {r.no_interval_tasks} task(s) in this range have no work-interval "
            f"data and are excluded from every number above._"
        )
    return "\n".join(lines).rstrip() + "\n"


def review_to_dict(r: Review) -> dict:
    return asdict(r)
