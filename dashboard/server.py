"""Flask dashboard server for etime."""

import argparse
import json
import os
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, render_template

# Resolve paths without importing config (avoids PyQt6 dependency chain)
ETIME_DIR = Path.home() / ".etime"
HISTORY_FILE = ETIME_DIR / "history.jsonl"
ACTIVE_FILE = ETIME_DIR / "active.json"
DISTRACTION_FILE = Path.home() / "Dev" / "DistractionCount" / "distraction_count.txt"

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


def _compute_stats(tasks: list[dict], distractions: dict) -> dict:
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
    }


@app.route("/")
def index():
    """Serve the dashboard HTML."""
    target = _date_filter or date.today()
    return render_template("index.html", date_str=target.isoformat())


@app.route("/api/data")
def api_data():
    """Return all dashboard data as JSON."""
    target = _date_filter or date.today()

    history = _load_history()
    day_tasks = _filter_by_date(history, target)
    active = _load_active()
    distractions = _load_distractions(target)
    stats = _compute_stats(day_tasks, distractions)

    return jsonify({
        "date": target.isoformat(),
        "stats": stats,
        "tasks": [_format_task_for_api(t) for t in day_tasks],
        "active_tasks": [_format_task_for_api(t) for t in active],
        "distractions": distractions,
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
