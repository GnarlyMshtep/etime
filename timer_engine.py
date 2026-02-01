"""Timer engine with alarm checking for etime application."""

from typing import Optional, List
from PyQt6.QtCore import QTimer, QObject, pyqtSignal

from models import Task, TaskState
from config import TIMER_INTERVAL_MS, TIMER_INCREMENT_S


def check_alarm(task: Task) -> Optional[int]:
    """
    Check if task should trigger an alarm.

    Args:
        task: Task to check.

    Returns:
        Alarm level (1 for overtime, 2 for 2x, 3 for 3x, etc.) or None.
    """
    if task.state != TaskState.ONGOING:
        return None

    if task.estimated_seconds <= 0:
        return None

    ratio = task.elapsed_seconds / task.estimated_seconds

    # Determine current level: 1 = overtime, 2 = 2x, 3 = 3x, etc.
    if ratio >= 1.0:
        current_level = max(1, int(ratio))
        if current_level > task.last_alarm_level:
            return current_level

    return None


class TimerEngine(QObject):
    """Timer engine that updates task elapsed times and checks for alarms."""

    # Signals
    tick = pyqtSignal()  # Emitted on every timer tick
    alarm = pyqtSignal(str, int)  # Emitted when alarm triggers (task_id, level)

    def __init__(self, tasks: List[Task]):
        """
        Initialize timer engine.

        Args:
            tasks: List of tasks to manage (reference, not copy).
        """
        super().__init__()
        self.tasks = tasks
        self.timer = QTimer()
        self.timer.timeout.connect(self._on_tick)
        self.timer.setInterval(TIMER_INTERVAL_MS)

    def start(self) -> None:
        """Start the timer."""
        self.timer.start()

    def stop(self) -> None:
        """Stop the timer."""
        self.timer.stop()

    def _on_tick(self) -> None:
        """Handle timer tick: update elapsed times and check alarms."""
        # Update elapsed time for all ONGOING tasks
        for task in self.tasks:
            if task.state == TaskState.ONGOING:
                task.elapsed_seconds += TIMER_INCREMENT_S

                # Check if alarm should trigger
                alarm_level = check_alarm(task)
                if alarm_level is not None:
                    # Update last alarm level
                    task.last_alarm_level = alarm_level
                    # Emit alarm signal
                    self.alarm.emit(task.id, alarm_level)

        # Emit tick signal for UI updates
        self.tick.emit()
