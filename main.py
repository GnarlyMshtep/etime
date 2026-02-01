#!/usr/bin/env python3
"""etime - Evolved Timer for productivity tracking."""

import sys
from datetime import datetime
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QObject, QTimer
from AppKit import NSWorkspace

from models import Task, TaskState
from storage import ensure_etime_dir, load_active_tasks, save_active_tasks, append_to_history
from timer_engine import TimerEngine
from overlay import OverlayWindow
from task_dialog import TaskDialog
from hotkeys import HotkeyManager
from config import KEY_N, KEY_P, KEY_C, KEY_Q, KEY_S, KEY_UP, KEY_DOWN
from sounds import play_alarm_loop, stop_alarm, play_success_sound, play_ambitious_success_sound
import dashboard


class AppController(QObject):
    """Main application controller."""

    def __init__(self):
        super().__init__()

        # State
        self.tasks = []
        self.overlay = None
        self.timer_engine = None
        self.hotkey_manager = None
        self.task_dialog = None
        self.overlay_visible = True  # Track overlay visibility
        self.active_alarms = set()  # Track which tasks have active alarms
        self.previous_app = None  # Track previously focused app for focus restoration

        # Initialize
        self._initialize()

    def _initialize(self):
        """Initialize application components."""
        # Ensure data directory exists
        ensure_etime_dir()

        # Load active tasks
        self.tasks = load_active_tasks()
        print(f"Loaded {len(self.tasks)} active tasks")

        # Create overlay window
        self.overlay = OverlayWindow(self.tasks, self)
        self.overlay.show()

        # Create timer engine
        self.timer_engine = TimerEngine(self.tasks)
        self.timer_engine.tick.connect(self._on_timer_tick)
        self.timer_engine.alarm.connect(self._on_alarm)
        self.timer_engine.start()

        # Create task dialog (reused for each new task)
        self.task_dialog = TaskDialog()
        self.task_dialog.task_submitted.connect(self._on_task_submitted)

        # Setup hotkey manager
        self.hotkey_manager = HotkeyManager()
        self.hotkey_manager.register(KEY_N, self.new_task)
        self.hotkey_manager.register(KEY_P, self.toggle_start_pause)  # Toggle start/pause
        self.hotkey_manager.register(KEY_C, self.complete_task)
        self.hotkey_manager.register(KEY_S, self.toggle_overlay)  # Minimize/show overlay
        self.hotkey_manager.register(KEY_UP, self.focus_up)
        self.hotkey_manager.register(KEY_DOWN, self.focus_down)
        self.hotkey_manager.register(KEY_Q, self.dismiss_alarm)

        if not self.hotkey_manager.start():
            # Show error dialog if hotkeys fail
            QMessageBox.critical(
                None,
                "Accessibility Permissions Required",
                "etime needs Accessibility permissions to work.\n\n"
                "Please enable etime in:\n"
                "System Settings → Privacy & Security → Accessibility\n\n"
                "Then restart the app."
            )
            sys.exit(1)

        # Periodic health check for event tap (recovers from Spotify-style conflicts)
        self.hotkey_health_timer = QTimer()
        self.hotkey_health_timer.timeout.connect(self.hotkey_manager.check_and_repair)
        self.hotkey_health_timer.start(3000)  # Check every 3 seconds

        # Launch dashboard server
        dashboard.launch()

        print("Application initialized successfully")

    def _on_timer_tick(self):
        """Handle timer tick: update overlay display."""
        self.overlay.update_display()

    def _on_alarm(self, task_id: str, level: int):
        """Handle alarm trigger."""
        # Find task
        task = next((t for t in self.tasks if t.id == task_id), None)
        if not task:
            return

        print(f"Alarm triggered for task '{task.name}' at level {level}x")

        # Track this alarm
        self.active_alarms.add(task_id)

        # Play looping alarm if not already playing
        if len(self.active_alarms) == 1:  # First alarm
            play_alarm_loop()

        # Update overlay to show bolded task
        self.overlay.update_display()

        # Save state (alarm level was updated in timer engine)
        save_active_tasks(self.tasks)

    def new_task(self):
        """Handle new task hotkey."""
        print("New task hotkey pressed")

        # Store previously focused app for focus restoration
        self.previous_app = NSWorkspace.sharedWorkspace().frontmostApplication()

        self.task_dialog.reset()
        self.task_dialog.show()
        self.task_dialog.raise_()  # Bring to front
        self.task_dialog.activateWindow()  # Activate and focus
        self.task_dialog.name_input.setFocus()  # Ensure name field has focus

    def _on_task_submitted(self, name: str, minutes: int, ambitious_minutes: int):
        """Handle task submission from dialog."""
        ambitious_str = f", ambitious={ambitious_minutes}" if ambitious_minutes > 0 else ""
        print(f"Creating new task: {name}, {minutes} min{ambitious_str}")
        print(f"Before task creation: {len(self.tasks)} tasks")

        # Create task
        task = Task(
            id="",  # Will be auto-generated
            name=name,
            estimated_seconds=minutes * 60,
            ambitious_seconds=ambitious_minutes * 60 if ambitious_minutes > 0 else None,
            state=TaskState.ONGOING,  # Auto-start
            started_at=datetime.now().isoformat()
        )

        # Add to list
        self.tasks.append(task)
        print(f"After task creation: {len(self.tasks)} tasks")

        # Update overlay
        self.overlay.add_task(task)
        print(f"Task added to overlay, overlay visible: {self.overlay.isVisible()}")

        # Update focus if this is the first task
        if len(self.tasks) == 1:
            self.overlay.focused_index = 0
            self.overlay.update_display()
            print("Set focused index to 0")

        # Save
        save_active_tasks(self.tasks)
        print("Task saved successfully")

        # Restore focus to previous app
        if self.previous_app:
            self.previous_app.activateWithOptions_(1)  # NSApplicationActivateIgnoringOtherApps
            self.previous_app = None
            print("Focus restored to previous app")

    def toggle_start_pause(self):
        """Toggle between start and pause for focused task."""
        task = self.overlay.get_focused_task()
        if not task:
            print("No task focused")
            return

        if task.state == TaskState.ONGOING:
            # Currently running, so pause it
            self.pause_task()
        else:
            # Currently paused or backlog, so start it
            self.start_task()

    def start_task(self):
        """Handle start/resume task hotkey."""
        task = self.overlay.get_focused_task()
        if not task:
            print("No task focused")
            return

        print(f"Starting task: {task.name}")

        # Set state to ONGOING
        task.state = TaskState.ONGOING

        # Set started_at if not already set
        if not task.started_at:
            task.started_at = datetime.now().isoformat()

        # Update display
        self.overlay.update_display()

        # Save
        save_active_tasks(self.tasks)

    def pause_task(self):
        """Handle pause task hotkey."""
        task = self.overlay.get_focused_task()
        if not task:
            print("No task focused")
            return

        print(f"Pausing task: {task.name}")

        # Set state to PAUSED
        task.state = TaskState.PAUSED

        # Update display
        self.overlay.update_display()

        # Save
        save_active_tasks(self.tasks)

    def complete_task(self):
        """Handle complete task hotkey."""
        task = self.overlay.get_focused_task()
        if not task:
            print("No task focused")
            return

        print(f"Completing task: {task.name}")

        # Get task_id early
        task_id = task.id

        # Check if this task has an active alarm - auto-quiet it
        had_alarm = task_id in self.active_alarms
        if had_alarm:
            print(f"Task had active alarm - auto-quieting")
            self.active_alarms.discard(task_id)

            # If this was the last active alarm, stop the sound
            if len(self.active_alarms) == 0:
                stop_alarm()
                print("All alarms cleared - sound stopped")

        # Set state to COMPLETED
        task.state = TaskState.COMPLETED
        task.completed_at = datetime.now().isoformat()

        # Append to history
        append_to_history(task)

        # Remove from active tasks
        self.tasks.remove(task)

        # Update focus index if needed
        if self.overlay.focused_index >= len(self.tasks) and len(self.tasks) > 0:
            self.overlay.focused_index = len(self.tasks) - 1
        elif len(self.tasks) == 0:
            self.overlay.focused_index = -1

        # Determine if task was completed within ambitious time
        completed_in_ambitious = (
            task.ambitious_seconds is not None
            and task.elapsed_seconds <= task.ambitious_seconds
        )

        # Play appropriate sound
        if completed_in_ambitious:
            print(f"Completed within ambitious time! ({task.elapsed_seconds:.0f}s <= {task.ambitious_seconds}s)")
            play_ambitious_success_sound()
        else:
            play_success_sound()

        # Remove from overlay with appropriate animation
        def on_removed():
            save_active_tasks(self.tasks)
            self.overlay.update_display()

        if completed_in_ambitious:
            self.overlay.remove_task_with_confetti(task_id, callback=on_removed)
        else:
            self.overlay.remove_task_with_celebration(task_id, callback=on_removed)

    def focus_up(self):
        """Handle focus up hotkey."""
        print("Focus up")
        self.overlay.move_focus(-1)

    def focus_down(self):
        """Handle focus down hotkey."""
        print("Focus down")
        self.overlay.move_focus(1)

    def dismiss_alarm(self):
        """Handle dismiss alarm hotkey - quiet all active alarms."""
        print(f"Dismissing {len(self.active_alarms)} alarm(s)")
        self.active_alarms.clear()
        stop_alarm()
        # Update overlay to remove bold from tasks
        self.overlay.update_display()

    def is_task_alarmed(self, task_id: str) -> bool:
        """Check if a task has an active alarm."""
        return task_id in self.active_alarms

    def toggle_overlay(self):
        """Toggle overlay visibility (minimize/show)."""
        if self.overlay_visible:
            self.overlay.hide()
            self.overlay_visible = False
            print("Overlay hidden")
        else:
            self.overlay.show()
            self.overlay.position_at_top_right()  # Reposition when showing
            self.overlay_visible = True
            print("Overlay shown")


def main():
    """Main entry point."""
    app = QApplication(sys.argv)
    app.setApplicationName("etime")

    # CRITICAL FIX: Prevent Qt from exiting when all windows close
    # Tool windows don't count as "windows" for Qt, so when dialog closes,
    # Qt thinks there are no windows left and exits automatically
    app.setQuitOnLastWindowClosed(False)

    # Add exit handler
    def on_exit():
        print("Application exiting normally")

    app.aboutToQuit.connect(on_exit)

    try:
        # Create and run controller
        controller = AppController()

        # Run event loop
        exit_code = app.exec()
        print(f"Application exited with code: {exit_code}")
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("Application interrupted by user (Ctrl+C)")
        sys.exit(0)
    except Exception as e:
        print(f"Application crashed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
