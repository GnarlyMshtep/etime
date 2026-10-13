"""Flask dashboard server for etime."""

import argparse
import calendar
import json
import os
import shutil
import tempfile
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, render_template, request

from .review import build_review, review_to_dict, union_seconds

# Resolve paths without importing config (avoids PyQt6 dependency chain)
ETIME_DIR = Path.home() / ".etime"
HISTORY_FILE = ETIME_DIR / "history.jsonl"
ACTIVE_FILE = ETIME_DIR / "active.json"
SUMMARY_FILE = ETIME_DIR / "weekly_summaries.json"
DISTRACTION_FILE = Path.home() / "Dev" / "DistractionCount" / "distraction_count.txt"
DETERRED_FILE = Path.home() / "Dev" / "DistractionCount" / "deterred_count.txt"
BACKUP_DIR = Path.home() / "Dev" / "etime" / "claude_data"

# history.jsonl is the user's whole time log. Every edit leaves a timestamped
# copy behind; only the newest few are kept so the directory doesn't grow without
# bound.
HISTORY_BACKUPS_KEPT = 20

# Guards on an edited interval. A day is already absurd for one work interval;
# anything past it is a dropped timezone or a bad drag, not a real session.
MAX_INTERVAL_SECONDS = 24 * 60 * 60


def _page_version() -> str:
    """Identifies the page a tab is running, so writes from a stale one are caught.

    A tab left open across a server restart keeps its old JavaScript and goes on
    speaking the old payload shape. Without this the mismatch surfaces as an
    unexplained rejection; with it the page can say "reload".
    """
    try:
        stat = (Path(__file__).parent / "templates" / "index.html").stat()
        return f"{int(stat.st_mtime)}-{stat.st_size}"
    except OSError:
        return "unknown"

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
    return render_template("index.html", date_str=target.isoformat(),
                           page_version=_page_version())


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
        # A month is reviewed by reading back the weeks inside it, so the month
        # view carries them along. Other periods don't need it: a week view is
        # already showing its own entry in the editor.
        "week_summaries": _week_summaries(dates) if period == "month" else [],
    })


def _week_summaries(dates: list[date]) -> list[dict]:
    """Written summaries for every Monday-start week the range touches.

    Weeks with nothing written are included too — a gap in the record is worth
    seeing, and it's also the affordance for going and filling it in.
    """
    summaries = _load_summaries()
    mondays = sorted({d - timedelta(days=d.weekday()) for d in dates})
    out = []
    for monday in mondays:
        entry = summaries.get(_summary_key("week", monday), {})
        out.append({
            "key": _summary_key("week", monday),
            "start": monday.isoformat(),
            "end": (monday + timedelta(days=6)).isoformat(),
            "text": entry.get("text", ""),
            "updated_at": entry.get("updated_at", ""),
        })
    return out


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


def _backup_history() -> Path:
    """Timestamped copy of history.jsonl, pruned to the newest few."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = BACKUP_DIR / f"history.jsonl.{stamp}.bak"
    shutil.copy2(HISTORY_FILE, dest)

    old = sorted(BACKUP_DIR.glob("history.jsonl.*.bak"))[:-HISTORY_BACKUPS_KEPT]
    for stale in old:
        stale.unlink(missing_ok=True)
    return dest


def _rewrite_history_line(index: int, task: dict) -> None:
    """Replace one line of history.jsonl, leaving every other byte untouched."""
    lines = HISTORY_FILE.read_text().splitlines(keepends=True)
    trailing_newline = lines[index].endswith("\n")
    lines[index] = json.dumps(task) + ("\n" if trailing_newline else "")

    fd, tmp = tempfile.mkstemp(dir=str(ETIME_DIR), prefix=".history_", suffix=".jsonl.tmp")
    with os.fdopen(fd, "w") as f:
        f.writelines(lines)
    os.replace(tmp, HISTORY_FILE)


def _find_history_line(task_id: str) -> tuple[int, dict]:
    """Locate a task in history.jsonl by id. Raises if it isn't uniquely there."""
    matches: list[tuple[int, dict]] = []
    for i, line in enumerate(HISTORY_FILE.read_text().splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            task = json.loads(line)
        except json.JSONDecodeError:
            continue
        if task.get("id") == task_id:
            matches.append((i, task))

    if not matches:
        raise LookupError(f"task {task_id} is not in history.jsonl")
    if len(matches) > 1:
        raise LookupError(
            f"task {task_id} appears {len(matches)} times in history.jsonl — "
            f"refusing to guess which one to edit"
        )
    return matches[0]


@app.route("/api/interval", methods=["POST"])
def api_interval():
    """Move or stretch the run of work intervals behind one timeline block.

    Deliberately narrow. Only completed tasks are touched (etime rewrites
    active.json from memory and would clobber anything written here), only the
    exact intervals the client last saw are touched, and the whole edit is
    rejected rather than approximated if anything doesn't line up.

    A move slides every interval in the run by the same amount, so durations and
    the gaps between them survive untouched. A stretch moves one edge, and only
    the interval that owns that edge changes.
    """
    payload = request.get_json(silent=True) or {}
    task_id = str(payload.get("task_id", "")).strip()
    if not task_id:
        return jsonify({"error": "missing task_id"}), 400

    # A tab open across a dashboard restart still speaks the old payload shape.
    # Say so plainly instead of letting it surface as a parse failure.
    if str(payload.get("page_version", "")) != _page_version():
        return jsonify({
            "error": "this page was loaded before the dashboard was updated — "
                     "reload it (⌘R) and try again"
        }), 409

    mode = str(payload.get("mode", ""))
    if mode not in ("move", "resize_start", "resize_end"):
        return jsonify({"error": f"unknown mode {mode!r}"}), 400

    try:
        indices = [int(i) for i in payload["interval_indices"]]
        expected = list(payload["expected"])
        # The client sends only the edge it dragged. Everything else is carried
        # over from storage, so sub-millisecond precision that a browser Date
        # can't represent survives the round trip.
        edge = datetime.fromisoformat(payload["edge"])
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"error": f"bad payload: {exc}"}), 400

    if not indices or len(indices) != len(expected):
        return jsonify({"error": "interval_indices and expected must line up"}), 400

    if any(t.get("id") == task_id for t in _load_active()):
        return jsonify({
            "error": "that task is still open in etime, which owns active.json — "
                     "finish it there first"
        }), 409

    try:
        line_no, task = _find_history_line(task_id)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404

    intervals = task.get("work_intervals") or []
    for index in indices:
        if not 0 <= index < len(intervals):
            return jsonify({"error": f"interval {index} does not exist"}), 404

    # Compare as datetimes, not strings: isoformat() drops zero microseconds, so
    # a stored "...T15:01:23.000000" and the "...T15:01:23" the client was handed
    # are the same instant spelled two ways.
    def _same_instant(stored: Optional[str], claimed: str) -> bool:
        if not stored:
            return False
        try:
            return datetime.fromisoformat(stored) == datetime.fromisoformat(claimed)
        except (TypeError, ValueError):
            return False

    stale = any(
        not (_same_instant(intervals[i].get("start"), exp.get("start", ""))
             and _same_instant(intervals[i].get("end"), exp.get("end", "")))
        for i, exp in zip(indices, expected)
    )
    if stale:
        return jsonify({
            "error": "this block changed since the page loaded — reload and retry"
        }), 409

    run = [(i, datetime.fromisoformat(intervals[i]["start"]),
            datetime.fromisoformat(intervals[i]["end"])) for i in indices]
    before = union_seconds([(s, e) for _, s, e in run])

    if mode == "move":
        shift = edge - min(s for _, s, _ in run)
        updated = {i: (s + shift, e + shift) for i, s, e in run}
    elif mode == "resize_start":
        owner = min(run, key=lambda p: p[1])[0]
        updated = {i: (edge if i == owner else s, e) for i, s, e in run}
    else:
        owner = max(run, key=lambda p: p[2])[0]
        updated = {i: (s, edge if i == owner else e) for i, s, e in run}

    for i, (s, e) in updated.items():
        if e <= s:
            return jsonify({"error": "that would make an interval end before it starts"}), 400
        if (e - s).total_seconds() > MAX_INTERVAL_SECONDS:
            return jsonify({"error": "that would make an interval longer than a day"}), 400
        if s.date() != e.date():
            return jsonify({"error": "that would push an interval across midnight"}), 400

    after = union_seconds(list(updated.values()))

    backup = _backup_history()
    for i, (s, e) in updated.items():
        intervals[i]["start"] = s.isoformat()
        intervals[i]["end"] = e.isoformat()
    # elapsed_seconds is the app's own timer accumulator, not a sum of intervals
    # (older tasks predate interval tracking). Shift it by the change rather than
    # recomputing, so any pre-existing gap between the two survives the edit. A
    # move doesn't change the total at all, so it doesn't touch the field —
    # adding and subtracting the same delta would leave float noise behind.
    if after != before:
        task["elapsed_seconds"] = max(
            0.0, round(task.get("elapsed_seconds", 0.0) + after - before, 6)
        )
    _rewrite_history_line(index=line_no, task=task)

    return jsonify({
        "ok": True,
        "task_id": task_id,
        "intervals": [{"index": i, "start": intervals[i]["start"], "end": intervals[i]["end"]}
                      for i in sorted(updated)],
        "elapsed_seconds": task.get("elapsed_seconds"),
        "backup": str(backup),
    })


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
