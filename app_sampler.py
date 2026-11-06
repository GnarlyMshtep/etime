"""Record which app was in front, so the dashboard can show where the day went.

etime knows what you *said* you were doing. This records what the machine was
actually showing: it reads the frontmost application every few seconds and
appends a run per stretch to ``~/.etime/app_usage.jsonl``. Cross-referenced
against your Raycast Focus block list (app_usage_types.load_block_list), that
gives the time on apps you yourself called distracting, as a band under the
timeline.

Deliberately narrow:

- **Documented APIs only.** ``NSWorkspace`` for the frontmost app, the HID event
  source for idle time, the window-server session dictionary for the lock
  screen. No scraping of other apps' windows, no reading their files.
- **App, never content.** The bundle id and name, nothing about documents, tab
  titles or URLs. Which is why a blocked *website* can't be seen here; only the
  browser it was in.
- **Append-only**, like history.jsonl: a run is written once it's over and never
  revised, so a crash costs at most APP_SEGMENT_MAX_SECONDS of the open run.

Time while you're away is not recorded: no input for APP_IDLE_SECONDS, or a
locked screen, closes the run. Sleep is handled by the same rule, plus a check
for a gap between samples far longer than the interval.

**Off unless you ask for it.** etime starts the sampler only when
``~/.etime/blocked_apps.json`` exists -- writing that file is the opt-in, and
without it nothing is sampled, nothing is written, and the dashboard shows no
band. Seed it from Raycast Focus with ``scripts/import_raycast_blocklist.py``,
or write it by hand if you don't use Raycast:

    {"apps": {"com.tinyspeck.slackmacgap": "Slack"}, "websites": ["youtube.com"]}

Needs no dependency etime doesn't already have, and nothing here is specific to
Raycast -- it only ever reads etime's own list.

Run it directly (``python app_sampler.py``), or let etime start it the way it
starts the dashboard (``launch_if_enabled()``).
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import Quartz
from AppKit import NSWorkspace

from app_usage_types import AppRun
from config import (
    APP_IDLE_SECONDS,
    BLOCKED_APPS_FILE,
    APP_SAMPLE_SECONDS,
    APP_SAMPLER_PID_FILE,
    APP_SEGMENT_MAX_SECONDS,
    APP_USAGE_FILE,
    ETIME_DIR,
)


@dataclass
class Sample:
    """One reading of the machine's state."""

    at: datetime
    bundle_id: str
    app_name: str
    idle_seconds: float
    locked: bool

    @property
    def away(self) -> bool:
        return self.locked or self.idle_seconds >= APP_IDLE_SECONDS


def read_sample() -> Sample:
    front = NSWorkspace.sharedWorkspace().frontmostApplication()
    idle = Quartz.CGEventSourceSecondsSinceLastEventType(
        Quartz.kCGEventSourceStateHIDSystemState, Quartz.kCGAnyInputEventType
    )
    session = Quartz.CGSessionCopyCurrentDictionary()
    locked = bool(session.get("CGSSessionScreenIsLocked", 0)) if session else False
    return Sample(
        at=datetime.now(),
        # A frontmost app with no bundle id happens for a few helper processes;
        # name it rather than dropping the time on the floor.
        bundle_id=(front.bundleIdentifier() if front else None) or "?",
        app_name=(front.localizedName() if front else None) or "?",
        idle_seconds=float(idle),
        locked=locked,
    )


@dataclass
class OpenRun:
    """The run being accumulated, not yet on disk."""

    bundle_id: str
    app_name: str
    start: datetime
    end: datetime
    idle_seconds: float = 0.0

    def finish(self) -> AppRun:
        return AppRun(
            bundle_id=self.bundle_id,
            app_name=self.app_name,
            start=self.start.isoformat(),
            end=self.end.isoformat(),
            seconds=(self.end - self.start).total_seconds(),
            idle_seconds=self.idle_seconds,
        )


def append_run(*, run: AppRun, path: Path = APP_USAGE_FILE) -> None:
    ETIME_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        fh.write(run.to_json() + "\n")
        fh.flush()
        os.fsync(fh.fileno())


# Set by SIGTERM so the open run is written before exit, rather than lost.
_stopping = False


def _handle_sigterm(signum: int, frame: object) -> None:
    global _stopping
    _stopping = True


def sample_loop(*, once: bool = False, verbose: bool = False,
                out_path: Optional[Path] = None) -> None:
    open_run: Optional[OpenRun] = None
    previous: Optional[Sample] = None
    # A gap this long means the machine slept or the sampler was stopped; the run
    # ends at the last sample we actually took, not at the far side of the gap.
    max_gap = timedelta(seconds=APP_SAMPLE_SECONDS * 3)

    def flush(reason: str) -> None:
        nonlocal open_run
        if open_run is None:
            return
        if open_run.end > open_run.start:
            run = open_run.finish()
            append_run(run=run, path=out_path or APP_USAGE_FILE)
            if verbose:
                print(f"{run.start[11:19]}-{run.end[11:19]} {run.seconds:6.1f}s "
                      f"{run.app_name}  ({reason})", flush=True)
        open_run = None

    while True:
        if _stopping:
            flush("terminated")
            return
        # Re-read each time round: deleting the list is how you turn this off,
        # and it has to take effect without waiting for an etime restart.
        if not is_enabled():
            flush("disabled")
            if verbose:
                print(f"{BLOCKED_APPS_FILE} is gone -- sampling off", flush=True)
            return
        now = read_sample()
        gap = (now.at - previous.at) if previous else timedelta(0)
        if previous is not None and gap > max_gap:
            flush("gap")
        elif now.away:
            flush("away")
        elif open_run is not None and now.bundle_id != open_run.bundle_id:
            flush("switch")
        elif open_run is not None and \
                (now.at - open_run.start).total_seconds() >= APP_SEGMENT_MAX_SECONDS:
            flush("segment")

        if not now.away:
            if open_run is None:
                open_run = OpenRun(bundle_id=now.bundle_id, app_name=now.app_name,
                                   start=now.at, end=now.at)
            else:
                open_run.end = now.at
                # The whole interval since the last sample was idle only if the
                # idle clock had already passed that interval's length.
                if now.idle_seconds >= gap.total_seconds():
                    open_run.idle_seconds += gap.total_seconds()
        previous = now

        if once:
            flush("once")
            return
        time.sleep(APP_SAMPLE_SECONDS)


# --------------------------------------------------------------------------- #
# Process management, mirroring dashboard/__init__.py
# --------------------------------------------------------------------------- #

def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _read_pid() -> Optional[int]:
    if not APP_SAMPLER_PID_FILE.exists():
        return None
    try:
        pid = int(APP_SAMPLER_PID_FILE.read_text().strip())
    except (ValueError, OSError):
        APP_SAMPLER_PID_FILE.unlink(missing_ok=True)
        return None
    if _is_alive(pid):
        return pid
    APP_SAMPLER_PID_FILE.unlink(missing_ok=True)
    return None


def is_enabled() -> bool:
    """Whether the user has opted in, by writing the blocked-app list."""
    return BLOCKED_APPS_FILE.exists()


def launch_if_enabled() -> None:
    """Start the sampler if opted in. Silent when not -- it's off by default."""
    if not is_enabled():
        return
    launch()


def launch() -> None:
    """Start the sampler as a background subprocess, unless one is running."""
    existing = _read_pid()
    if existing is not None:
        print(f"App sampler already running (PID {existing})")
        return

    repo_root = Path(__file__).parent
    venv_python = repo_root / ".venv" / "bin" / "python"
    python_exe = str(venv_python) if venv_python.exists() else sys.executable
    proc = subprocess.Popen(
        [python_exe, str(repo_root / "app_sampler.py")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    APP_SAMPLER_PID_FILE.write_text(str(proc.pid))
    print(f"App sampler started (PID {proc.pid})")


def stop() -> None:
    pid = _read_pid()
    if pid is None:
        print("App sampler not running")
        return
    os.kill(pid, signal.SIGTERM)
    APP_SAMPLER_PID_FILE.unlink(missing_ok=True)
    print(f"App sampler stopped (PID {pid})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--once", action="store_true",
                    help="take a single sample and exit -- for checking it reads the machine")
    ap.add_argument("--verbose", action="store_true", help="print each run as it's written")
    ap.add_argument("--stop", action="store_true", help="stop a running sampler")
    ap.add_argument("--status", action="store_true",
                    help="say whether it's opted in and running")
    args = ap.parse_args()

    if args.status:
        pid = _read_pid()
        print(f"blocked-app list: {BLOCKED_APPS_FILE} "
              f"{'exists -- sampling enabled' if is_enabled() else 'missing -- sampling off'}")
        print(f"sampler: {'running, PID ' + str(pid) if pid else 'not running'}")
        print(f"log: {APP_USAGE_FILE}"
              f"{'' if APP_USAGE_FILE.exists() else ' (not written yet)'}")
        return
    if args.stop:
        stop()
        return
    if args.once:
        s = read_sample()
        print(f"{s.at:%H:%M:%S}  {s.app_name} ({s.bundle_id})  "
              f"idle {s.idle_seconds:.1f}s  locked={s.locked}")
        return
    APP_SAMPLER_PID_FILE.write_text(str(os.getpid()))
    signal.signal(signal.SIGTERM, _handle_sigterm)
    try:
        sample_loop(verbose=args.verbose)
    except KeyboardInterrupt:
        print("stopped")
    finally:
        if _read_pid() == os.getpid():
            APP_SAMPLER_PID_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
