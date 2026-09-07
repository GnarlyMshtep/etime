"""Flask dashboard server for etime."""

import argparse
import calendar
import json
import os
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, render_template, request

from .review import build_review, review_to_dict

# Resolve paths without importing config (avoids PyQt6 dependency chain)
ETIME_DIR = Path.home() / ".etime"
HISTORY_FILE = ETIME_DIR / "history.jsonl"
ACTIVE_FILE = ETIME_DIR / "active.json"
SUMMARY_FILE = ETIME_DIR / "weekly_summaries.json"
DISTRACTION_FILE = Path.home() / "Dev" / "DistractionCount" / "distraction_count.txt"
DETERRED_FILE = Path.home() / "Dev" / "DistractionCount" / "deterred_count.txt"

app = Flask(__name__)

# Set via CLI arg or default to today
_date_filter: Optional[date] = None


def _load_history() -> list[dict]:
    """Load all tasks from history.jsonl."""
    if not HISTORY_FILE.exists():
        return []
    tasks = []
    with open(HISTORY_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                tasks.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return tasks


def _load_active() -> list[dict]:
    """Load active tasks from active.json."""
    if not ACTIVE_FILE.exists():
        return []
    try:
        with open(ACTIVE_FILE, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _filter_by_date(tasks: list[dict], target: date) -> list[dict]:
    """Filter tasks to those completed on the target date."""
    filtered = []
    for t in tasks:
        completed_at = t.get("completed_at") or t.get("created_at", "")
        try:
            dt = datetime.fromisoformat(completed_at)
            if dt.date() == target:
                filtered.append(t)
        except (ValueError, TypeError):
            continue
    return filtered


def _load_distractions(target: date) -> dict:
    """Load distraction timestamps for the target date."""
    if not DISTRACTION_FILE.exists():
        return {"count": 0, "timestamps": []}

    timestamps = []
    try:
        with open(DISTRACTION_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    dt = datetime.strptime(line, "%Y-%m-%d %H:%M:%S")
                    if dt.date() == target:
                        timestamps.append(dt.strftime("%H:%M:%S"))
                except ValueError:
                    continue
    except OSError:
        pass

    return {"count": len(timestamps), "timestamps": timestamps}


def _load_deterred(target: date) -> dict:
    """Load deterred distraction timestamps for the target date."""
    if not DETERRED_FILE.exists():
        return {"count": 0, "timestamps": []}

    timestamps = []
    try:
        with open(DETERRED_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    dt = datetime.strptime(line, "%Y-%m-%d %H:%M:%S")
                    if dt.date() == target:
                        timestamps.append(dt.strftime("%H:%M:%S"))
                except ValueError:
                    continue
    except OSError:
        pass

    return {"count": len(timestamps), "timestamps": timestamps}


def _compute_stats(tasks: list[dict], distractions: dict, deterred: dict | None = None) -> dict:
    """Compute summary statistics from a list of completed tasks."""
    total_tasks = len(tasks)
    total_elapsed = sum(t.get("elapsed_seconds", 0) for t in tasks)
    total_estimated = sum(t.get("estimated_seconds", 0) for t in tasks)

    # Calibration: how accurate are estimates?
    accuracies = []
    for t in tasks:
        est = t.get("estimated_seconds", 0)
        elap = t.get("elapsed_seconds", 0)
        if est > 0:
            accuracies.append(elap / est)
    avg_accuracy = sum(accuracies) / len(accuracies) if accuracies else 0

    # Ambitious stats
    ambitious_tasks = [t for t in tasks if t.get("ambitious_seconds") is not None]
    ambitious_within = [
        t for t in ambitious_tasks
        if t.get("elapsed_seconds", 0) <= (t.get("ambitious_seconds") or 0)
    ]

    return {
        "total_tasks": total_tasks,
        "total_elapsed_seconds": round(total_elapsed, 1),
        "total_estimated_seconds": round(total_estimated, 1),
        "avg_accuracy": round(avg_accuracy, 3),
        "ambitious_tasks": len(ambitious_tasks),
        "ambitious_within": len(ambitious_within),
        "ambitious_rate": round(
            len(ambitious_within) / len(ambitious_tasks), 3
        ) if ambitious_tasks else 0,
        "distractions": distractions["count"],
        "deterred": deterred["count"] if deterred else 0,
    }


def _format_task_for_api(t: dict) -> dict:
    """Format a task dict for the API response."""
    elapsed = t.get("elapsed_seconds", 0)
    estimated = t.get("estimated_seconds", 0)
    ambitious = t.get("ambitious_seconds")

    return {
        "name": t.get("name", ""),
        "elapsed_seconds": round(elapsed, 1),
        "estimated_seconds": estimated,
        "ambitious_seconds": ambitious,
        "accuracy": round(elapsed / estimated, 3) if estimated > 0 else 0,
        "overtime": elapsed > estimated,
        "within_ambitious": (
            ambitious is not None and elapsed <= ambitious
        ),
        "completed_at": t.get("completed_at", ""),
        "created_at": t.get("created_at", ""),
        "work_intervals": t.get("work_intervals", []),
        "parent_task_id": t.get("parent_task_id"),
        "id": t.get("id", ""),
    }


def _interval_bounds(iv: dict) -> Optional[tuple[datetime, datetime]]:
    """Parse a work interval into (start, end) datetimes.

    Open intervals (end is None, i.e. currently running) are closed at now.
    Returns None if the interval is malformed or end precedes start.
    """
    try:
        start = datetime.fromisoformat(iv["start"])
    except (ValueError, TypeError, KeyError):
        return None
    end_raw = iv.get("end")
    if end_raw:
        try:
            end = datetime.fromisoformat(end_raw)
        except (ValueError, TypeError):
            return None
    else:
        end = datetime.now()
    if end < start:
        return None
    return start, end


def _day_has_intervals(day_tasks: list[dict], active: list[dict], target: date) -> bool:
    """Whether any task has a work interval starting on ``target``.

    Used to distinguish a real 0 context switches from "no interval data".
    """
    for t in list(day_tasks) + list(active):
        for iv in t.get("work_intervals", []):
            bounds = _interval_bounds(iv)
            if bounds and bounds[0].date() == target:
                return True
    return False


def _compute_context_switching(
    day_tasks: list[dict],
    active: list[dict],
    target: date,
    min_seconds: int = 60,
) -> dict:
    """Compute context-switching metrics from work intervals.

    A "session" is a maximal run of consecutive intervals on the same task in the
    global time-ordered stream, so pausing and resuming the same task with nothing
    else in between is NOT a switch. Intervals shorter than ``min_seconds`` are
    dropped (sub-minute starts/resumes don't count). A "context switch" is a
    boundary between two adjacent sessions (which are always different tasks).
    """
    # Pool qualifying intervals across completed + active tasks for the target day.
    intervals: list[tuple[datetime, datetime, str, str]] = []
    for t in list(day_tasks) + list(active):
        name = t.get("name", "")
        tid = t.get("id", "") or name
        for iv in t.get("work_intervals", []):
            bounds = _interval_bounds(iv)
            if bounds is None:
                continue
            start, end = bounds
            if start.date() != target:
                continue
            if (end - start).total_seconds() < min_seconds:
                continue
            intervals.append((start, end, tid, name))

    intervals.sort(key=lambda x: x[0])

    # Merge consecutive same-task intervals into sessions.
    sessions: list[dict] = []
    for start, end, tid, name in intervals:
        if sessions and sessions[-1]["task_id"] == tid:
            # Extend the current session (max guards against nested/overlapping intervals).
            sessions[-1]["end"] = max(sessions[-1]["end"], end)
        else:
            sessions.append({"task_id": tid, "name": name, "start": start, "end": end})

    total_switches = max(0, len(sessions) - 1)

    # Per-task: each session is a "start" (starting or returning to the task).
    per_task: dict[str, dict] = {}
    for s in sessions:
        rec = per_task.setdefault(s["task_id"], {"name": s["name"], "sessions": 0})
        rec["sessions"] += 1
    per_task_list = [
        {"name": rec["name"], "starts": rec["sessions"]}
        for rec in per_task.values()
    ]
    per_task_list.sort(key=lambda r: r["starts"], reverse=True)

    # Switches by hour: attribute each switch to the hour of the session entered.
    by_hour = [0] * 24
    for i in range(1, len(sessions)):
        by_hour[sessions[i]["start"].hour] += 1

    # Timeline ribbon: each session as a labeled block.
    timeline = [
        {
            "name": s["name"],
            "task_id": s["task_id"],
            "start": s["start"].isoformat(),
            "end": s["end"].isoformat(),
            "minutes": round((s["end"] - s["start"]).total_seconds() / 60, 1),
        }
        for s in sessions
    ]

    return {
        "total_switches": total_switches,
        "total_sessions": len(sessions),
        "per_task": per_task_list,
        "by_hour": by_hour,
        "timeline": timeline,
    }


@app.route("/")
def index():
    """Serve the dashboard HTML."""
    date_param = request.args.get("date")
    if date_param:
        try:
            target = date.fromisoformat(date_param)
        except ValueError:
            target = _date_filter or date.today()
    else:
        target = _date_filter or date.today()
    return render_template("index.html", date_str=target.isoformat())


@app.route("/api/data")
def api_data():
    """Return all dashboard data as JSON."""
    date_param = request.args.get("date")
    if date_param:
        try:
            target = date.fromisoformat(date_param)
        except ValueError:
            target = _date_filter or date.today()
    else:
        target = _date_filter or date.today()

    history = _load_history()
    day_tasks = _filter_by_date(history, target)
    active = _load_active()
    distractions = _load_distractions(target)
    deterred = _load_deterred(target)
    stats = _compute_stats(day_tasks, distractions, deterred=deterred)
    context = _compute_context_switching(day_tasks, active, target)

    return jsonify({
        "date": target.isoformat(),
        "stats": stats,
        "tasks": [_format_task_for_api(t) for t in day_tasks],
        "active_tasks": [_format_task_for_api(t) for t in active],
        "distractions": distractions,
        "deterred": deterred,
        "context": context,
    })


def _range_dates(anchor: date, period: str) -> list[date]:
    """Return the list of dates in the period containing ``anchor``.

    day   -> just the anchor.
    week  -> Monday..Sunday containing anchor.
    month -> 1st..last day of anchor's calendar month.

    Days after today are dropped: rendering the 24 empty future days of the
    current month as "no activity" reads as broken data, not as the future.
    """
    if period == "day":
        return [anchor]
    if period == "month":
        start = anchor.replace(day=1)
        n = calendar.monthrange(anchor.year, anchor.month)[1]
        dates = [start + timedelta(days=i) for i in range(n)]
    else:
        start = anchor - timedelta(days=anchor.weekday())  # Monday
        dates = [start + timedelta(days=i) for i in range(7)]
    today = date.today()
    if dates[0] <= today <= dates[-1]:
        dates = [d for d in dates if d <= today]
    return dates


@app.route("/api/range")
def api_range():
    """Aggregate stats across a week or month for the global view."""
    period = request.args.get("period", "week")
    if period not in ("day", "week", "month"):
        period = "week"

    date_param = request.args.get("date")
    if date_param:
        try:
            anchor = date.fromisoformat(date_param)
        except ValueError:
            anchor = _date_filter or date.today()
    else:
        anchor = _date_filter or date.today()

    dates = _range_dates(anchor, period)
    history = _load_history()
    active = _load_active()

    daily: list[dict] = []
    all_tasks: list[dict] = []
    total_switches = 0
    for d in dates:
        day_tasks = _filter_by_date(history, d)
        # Context switches need recorded work intervals. If the day had task
        # activity but no interval data (e.g. before interval tracking existed),
        # report None ("not available") rather than a misleading 0.
        if _day_has_intervals(day_tasks, active, d):
            switches = _compute_context_switching(day_tasks, active, d)["total_switches"]
            total_switches += switches
        elif day_tasks:
            switches = None
        else:
            switches = 0
        elapsed = sum(t.get("elapsed_seconds", 0) for t in day_tasks)
        daily.append({
            "date": d.isoformat(),
            "hours": round(elapsed / 3600, 2),
            "switches": switches,
            "tasks": len(day_tasks),
        })
        all_tasks.extend(day_tasks)

    distraction_days = {d.isoformat(): _load_distractions(d) for d in dates}
    distractions_by_day = {k: v["count"] for k, v in distraction_days.items()}
    review = build_review(
        history=history,
        active=active,
        dates=dates,
        distractions_by_day=distractions_by_day,
        distraction_times_by_day={
            k: [t[:5] for t in v["timestamps"]] for k, v in distraction_days.items()
        },
    )
    # Interval-clipped hours: time is credited to the day it was actually worked,
    # not to the day the task happened to be completed on.
    tracked_by_day = {day.date: day.seconds for day in review.days}
    for row in daily:
        row["tracked_hours"] = round(tracked_by_day.get(row["date"], 0.0) / 3600, 2)

    distractions_total = sum(distractions_by_day.values())
    deterred_total = sum(_load_deterred(d)["count"] for d in dates)
    stats = _compute_stats(all_tasks, {"count": distractions_total}, {"count": deterred_total})
    stats["total_switches"] = total_switches
    stats["active_days"] = sum(1 for day in daily if day["tasks"] > 0)

    calibration = [
        {
            "name": t.get("name", ""),
            "estimated_seconds": t.get("estimated_seconds", 0),
            "elapsed_seconds": round(t.get("elapsed_seconds", 0), 1),
            "date": (t.get("completed_at") or t.get("created_at", ""))[:10],
            "overtime": t.get("elapsed_seconds", 0) > t.get("estimated_seconds", 0),
        }
        for t in all_tasks
        if t.get("estimated_seconds", 0) > 0
    ]

    return jsonify({
        "period": period,
        "start": dates[0].isoformat(),
        "end": dates[-1].isoformat(),
        "stats": stats,
        "daily": daily,
        "calibration": calibration,
        "review": review_to_dict(review),
        "summary": _load_summaries().get(
            _summary_key(period, dates[0]), {"text": "", "updated_at": ""}
        ),
    })


def _summary_key(period: str, start: date) -> str:
    """Storage key for one period's written summary, e.g. ``week-2026-08-31``."""
    return f"{period}-{start.isoformat()}"


def _load_summaries() -> dict:
    """All written summaries, keyed by ``_summary_key``."""
    if not SUMMARY_FILE.exists():
        return {}
    try:
        with open(SUMMARY_FILE, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_summary(key: str, text: str) -> dict:
    """Write one summary, preserving the rest of the file. Returns the entry."""
    summaries = _load_summaries()
    entry = {"text": text, "updated_at": datetime.now().isoformat(timespec="seconds")}
    summaries[key] = entry
    tmp = SUMMARY_FILE.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(summaries, f, indent=2, ensure_ascii=False)
    tmp.replace(SUMMARY_FILE)
    return entry


@app.route("/api/summary", methods=["GET", "POST"])
def api_summary():
    """Read or write the user's own written summary for one period."""
    if request.method == "GET":
        key = request.args.get("key", "")
        return jsonify(_load_summaries().get(key, {"text": "", "updated_at": ""}))

    payload = request.get_json(silent=True) or {}
    key = str(payload.get("key", "")).strip()
    if not key:
        return jsonify({"error": "missing key"}), 400
    return jsonify(_save_summary(key, str(payload.get("text", ""))))


def main():
    parser = argparse.ArgumentParser(description="etime dashboard server")
    parser.add_argument("--port", type=int, default=5173)
    parser.add_argument("--date", type=str, default=None,
                        help="Date filter in MM/DD/YYYY format")
    args = parser.parse_args()

    global _date_filter
    if args.date:
        _date_filter = datetime.strptime(args.date, "%m/%d/%Y").date()
        print(f"Dashboard filtering to date: {_date_filter}")

    # Write PID file
    pid_file = ETIME_DIR / "dashboard.pid"
    pid_file.write_text(str(os.getpid()))

    try:
        app.run(host="127.0.0.1", port=args.port, debug=False)
    finally:
        pid_file.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
