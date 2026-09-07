#!/usr/bin/env python3
"""Sunday-afternoon nudge: did I write this week's summary?

Run by the ``com.matan.etime-weekly-summary`` LaunchAgent (Sun 15:00 / Sun 20:00 /
Mon 10:00). Exits silently if the summary for the target week already has text,
so the extra firings are harmless catch-ups for a machine that was asleep.

Otherwise it puts up a dialog; choosing "Write it now" starts the dashboard if it
isn't already up and deep-links to the week view with the editor focused.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent
ETIME_DIR = Path.home() / ".etime"
SUMMARY_FILE = ETIME_DIR / "weekly_summaries.json"
PORT = 5173


def target_week_monday(today: date) -> date:
    """Monday of the week this nudge is about.

    Sunday-and-earlier nudges mean the current week; a Monday nudge is a
    catch-up for the week that just ended.
    """
    anchor = today - timedelta(days=1) if today.weekday() == 0 else today
    return anchor - timedelta(days=anchor.weekday())


def summary_written(monday: date) -> bool:
    if not SUMMARY_FILE.exists():
        return False
    try:
        data = json.loads(SUMMARY_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    entry = data.get(f"week-{monday.isoformat()}") or {}
    return bool(str(entry.get("text", "")).strip())


def dashboard_up() -> bool:
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def start_dashboard() -> None:
    python = REPO / ".venv" / "bin" / "python"
    subprocess.Popen(
        [str(python) if python.exists() else sys.executable, "-m", "dashboard.server",
         "--port", str(PORT)],
        cwd=str(REPO),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(20):
        if dashboard_up():
            return
        time.sleep(0.25)


def ask(monday: date) -> bool:
    """Show the nudge. True if the answer was "write it now"."""
    sunday = monday + timedelta(days=6)
    span = f"{monday:%b %-d} – {sunday:%b %-d}"
    script = (
        'display dialog "You haven\'t written your weekly summary for '
        f'{span} yet." with title "etime — weekly summary" '
        'buttons {"Later", "Write it now"} default button "Write it now" '
        'with icon note giving up after 600'
    )
    proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    # A dismissed / timed-out dialog exits non-zero or reports "gave up:true".
    if proc.returncode != 0:
        return False
    return "Write it now" in proc.stdout and "gave up:true" not in proc.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="nudge even if the summary is already written")
    parser.add_argument("--date", type=str, default=None,
                        help="pretend today is this ISO date (for testing)")
    args = parser.parse_args()

    today = date.fromisoformat(args.date) if args.date else date.today()
    monday = target_week_monday(today)

    if summary_written(monday) and not args.force:
        print(f"summary for week of {monday} already written — nothing to do")
        return

    if not ask(monday):
        print("dismissed")
        return

    if not dashboard_up():
        start_dashboard()
    url = f"http://127.0.0.1:{PORT}/?date={monday.isoformat()}&period=week#summary"
    # ``open`` rather than webbrowser: launchd gives this process a minimal
    # environment where webbrowser's browser detection is unreliable.
    subprocess.run(["open", url], check=False)


if __name__ == "__main__":
    main()
