"""Dashboard launcher for etime."""

import os
import signal
import subprocess
import sys
from pathlib import Path

from config import DASHBOARD_PORT, DASHBOARD_PID_FILE


def _is_process_alive(pid: int) -> bool:
    """Check if a process with given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _read_pid() -> int | None:
    """Read PID from pid file, return None if missing or stale."""
    if not DASHBOARD_PID_FILE.exists():
        return None
    try:
        pid = int(DASHBOARD_PID_FILE.read_text().strip())
        if _is_process_alive(pid):
            return pid
        # Stale pid file
        DASHBOARD_PID_FILE.unlink(missing_ok=True)
        return None
    except (ValueError, OSError):
        DASHBOARD_PID_FILE.unlink(missing_ok=True)
        return None


def launch(port: int = DASHBOARD_PORT, date_filter: str | None = None) -> None:
    """Launch the dashboard server as a background subprocess.

    Skips if already running (checked via PID file).

    Args:
        port: Port to serve on.
        date_filter: Optional date string (MM/DD/YYYY) to filter history.
    """
    existing_pid = _read_pid()
    if existing_pid is not None:
        print(f"Dashboard already running (PID {existing_pid}) on port {port}")
        return

    server_path = Path(__file__).parent / "server.py"
    cmd = [sys.executable, str(server_path), "--port", str(port)]
    if date_filter:
        cmd.extend(["--date", date_filter])

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    DASHBOARD_PID_FILE.write_text(str(proc.pid))
    print(f"Dashboard launched (PID {proc.pid}) on http://localhost:{port}")


def stop() -> None:
    """Stop the running dashboard server."""
    pid = _read_pid()
    if pid is None:
        print("Dashboard not running")
        return
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Dashboard stopped (PID {pid})")
    except OSError as e:
        print(f"Failed to stop dashboard: {e}")
    finally:
        DASHBOARD_PID_FILE.unlink(missing_ok=True)
