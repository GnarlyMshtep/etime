#!/usr/bin/env python3
"""etime - Evolved Timer for productivity tracking."""

import sys
from datetime import datetime
from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog, QVBoxLayout, QLabel
from PyQt6.QtCore import QObject, QTimer, Qt
from PyQt6.QtGui import QFont
from AppKit import NSWorkspace
from Foundation import NSObject
import objc

from models import Task, TaskState
from typing import Optional
from storage import ensure_etime_dir, load_active_tasks, save_active_tasks, append_to_history, remove_last_from_history
from timer_engine import TimerEngine
from overlay import OverlayWindow
from task_dialog import TaskDialog
from hotkeys import HotkeyManager
from config import KEY_N, KEY_P, KEY_C, KEY_Q, KEY_S, KEY_U, KEY_H, KEY_T, KEY_UP, KEY_DOWN
from sounds import play_alarm_loop, stop_alarm, play_success_sound, play_ambitious_success_sound
import dashboard


class SleepObserver(NSObject):
    """Observes macOS sleep/wake notifications via NSWorkspace."""

    def init(self):
        self = objc.super(SleepObserver, self).init()
        if self is None:
            return None
        self.on_sleep = None
        self.on_wake = None
        return self

    def handleSleep_(self, notification):
        if self.on_sleep:
            self.on_sleep()

    def handleWake_(self, notification):
        if self.on_wake:
            self.on_wake()


class HelpDialog(QDialog):
    """Simple popup showing all hotkeys."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("etime — Hotkeys")
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )

        layout = QVBoxLayout()
        layout.setSpacing(6)
        layout.setContentsMargins(20, 16, 20, 16)

        hotkeys = [
            ("⌃⌥⌘N", "New task"),
            ("⌃⌥⌘P", "Toggle start / pause"),
            ("⌃⌥⌘C", "Complete focused task"),
            ("⌃⌥⌘U", "Undo last completion"),
            ("⌃⌥⌘Q", "Dismiss alarm"),
            ("⌃⌥⌘S", "Toggle overlay visibility"),
            ("⌃⌥⌘H", "Show this help"),
            ("⌃⌥⌘T", "Toggle subtask (of task above)"),
            ("⌃⌥⌘↑", "Focus previous task"),
            ("⌃⌥⌘↓", "Focus next task"),
        ]

        mono = QFont("Menlo", 13)
        for key, desc in hotkeys:
            label = QLabel(f"{key}    {desc}")
            label.setFont(mono)
            layout.addWidget(label)

        self.setLayout(layout)
        self.adjustSize()


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
        self.last_completed_task: Optional[Task] = None  # For undo
        self.last_completed_index: int = -1  # Original position for undo
        self._auto_paused_tasks: set = set()  # Task IDs paused due to sleep

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
        self.hotkey_manager.register(KEY_U, self.undo_complete)
        self.hotkey_manager.register(KEY_H, self.show_help)
        self.hotkey_manager.register(KEY_T, self.toggle_subtask)

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

        # Setup help dialog (kept as instance to prevent GC)
        self.help_dialog = HelpDialog()

        # Setup sleep/wake observer
        self._sleep_observer = SleepObserver.alloc().init()
        self._sleep_observer.on_sleep = self._on_sleep
        self._sleep_observer.on_wake = self._on_wake
        nc = NSWorkspace.sharedWorkspace().notificationCenter()
        nc.addObserver_selector_name_object_(
            self._sleep_observer, 'handleSleep:',
            'NSWorkspaceWillSleepNotification', None)
        nc.addObserver_selector_name_object_(
            self._sleep_observer, 'handleWake:',
            'NSWorkspaceDidWakeNotification', None)
        print("Sleep/wake observer registered")

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

        # Pass focused task as potential parent for subtask checkbox
        focused = self.overlay.get_focused_task()
        if focused:
            self.task_dialog.set_parent_context(
                parent_name=focused.name, parent_task_id=focused.id
            )

        self.task_dialog.show()
        self.task_dialog.raise_()  # Bring to front
        self.task_dialog.activateWindow()  # Activate and focus
        self.task_dialog.name_input.setFocus()  # Ensure name field has focus

    def _on_task_submitted(self, name: str, minutes: int, ambitious_minutes: int, parent_task_id: str):
        """Handle task submission from dialog."""
        ambitious_str = f", ambitious={ambitious_minutes}" if ambitious_minutes > 0 else ""
        parent_str = f", subtask of {parent_task_id[:8]}" if parent_task_id else ""
        print(f"Creating new task: {name}, {minutes} min{ambitious_str}{parent_str}")
        print(f"Before task creation: {len(self.tasks)} tasks")

        # Create task
        task = Task(
            id="",  # Will be auto-generated
            name=name,
            estimated_seconds=minutes * 60,
            ambitious_seconds=ambitious_minutes * 60 if ambitious_minutes > 0 else None,
            state=TaskState.ONGOING,  # Auto-start
            started_at=datetime.now().isoformat(),
            parent_task_id=parent_task_id or None,
        )
        task.start_interval()

        # Determine insertion position: right after parent if subtask, else end
        if parent_task_id:
            parent_idx = next(
                (i for i, t in enumerate(self.tasks) if t.id == parent_task_id), None
            )
            if parent_idx is not None:
                # Insert right after parent (and after any existing subtasks of that parent)
                insert_idx = parent_idx + 1
                while (insert_idx < len(self.tasks)
                       and self.tasks[insert_idx].parent_task_id == parent_task_id):
                    insert_idx += 1
                self.tasks.insert(insert_idx, task)
                self.overlay.insert_task(task, insert_idx)
                new_index = insert_idx
            else:
                # Parent not found, append at end
                self.tasks.append(task)
                self.overlay.add_task(task)
                new_index = len(self.tasks) - 1
        else:
            self.tasks.append(task)
            self.overlay.add_task(task)
            new_index = len(self.tasks) - 1

        print(f"After task creation: {len(self.tasks)} tasks (inserted at {new_index})")

        # Always focus the new task
        self.overlay.focused_index = new_index
        self.overlay.update_display()
        print(f"Set focused index to {new_index}")

        # Ensure overlay is visible
        if not self.overlay_visible:
            self.overlay.show()
            self.overlay.position_at_top_right()
            self.overlay_visible = True
            print("Overlay shown for new task")

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

        task.start_interval()

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

        # If this task has an active alarm, silence it and reset alarm level
        # so the alarm re-fires when the task is resumed
        if task.id in self.active_alarms:
            self.active_alarms.discard(task.id)
            task.last_alarm_level = 0
            if len(self.active_alarms) == 0:
                stop_alarm()
                print("Alarm silenced due to pause")

        task.end_interval()

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

        # Get task_id and index early (for undo)
        task_id = task.id
        task_index = self.overlay.focused_index

        # Check if this task has an active alarm - auto-quiet it
        had_alarm = task_id in self.active_alarms
        if had_alarm:
            print(f"Task had active alarm - auto-quieting")
            self.active_alarms.discard(task_id)

            # If this was the last active alarm, stop the sound
            if len(self.active_alarms) == 0:
                stop_alarm()
                print("All alarms cleared - sound stopped")

        # Save state for undo (before modifying)
        self.last_completed_task = task
        self.last_completed_index = task_index

        task.end_interval()

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

    def undo_complete(self):
        """Undo the last task completion."""
        if self.last_completed_task is None:
            print("Nothing to undo")
            return

        task = self.last_completed_task
        print(f"Undoing completion of: {task.name}")

        # Remove from history
        if not remove_last_from_history(task.id):
            print("Failed to remove from history - undo aborted")
            return

        # Restore task state
        task.state = TaskState.ONGOING
        task.completed_at = None
        task.start_interval()

        # Re-insert at original position (or end if index is now invalid)
        insert_index = min(self.last_completed_index, len(self.tasks))
        self.tasks.insert(insert_index, task)

        # Re-add to overlay
        self.overlay.insert_task(task, insert_index)

        # Set focus to restored task
        self.overlay.focused_index = insert_index
        self.overlay.update_display()

        # Save active tasks
        save_active_tasks(self.tasks)

        # Clear undo state
        self.last_completed_task = None
        self.last_completed_index = -1

        print(f"Task '{task.name}' restored")

    def toggle_subtask(self):
        """Toggle focused task as subtask of the task directly above it."""
        task = self.overlay.get_focused_task()
        if not task:
            print("No task focused")
            return

        idx = self.overlay.focused_index
        if task.parent_task_id:
            # Already a subtask — remove the link
            task.parent_task_id = None
            print(f"Removed subtask link from '{task.name}'")
        else:
            # Become a subtask of the task above
            if idx <= 0:
                print("No task above to use as parent")
                return
            parent = self.tasks[idx - 1]
            task.parent_task_id = parent.id
            print(f"'{task.name}' is now a subtask of '{parent.name}'")

        save_active_tasks(self.tasks)
        self.overlay.update_display()

    def _on_sleep(self):
        """Pause all ongoing tasks when Mac goes to sleep."""
        print("System going to sleep — auto-pausing tasks")

        # Stop any active alarms
        if self.active_alarms:
            self.active_alarms.clear()
            stop_alarm()

        # Pause all ongoing tasks and remember which ones we paused
        self._auto_paused_tasks = set()
        for task in self.tasks:
            if task.state == TaskState.ONGOING:
                task.end_interval()
                task.state = TaskState.PAUSED
                task.last_alarm_level = 0  # Reset so alarm re-fires on resume
                self._auto_paused_tasks.add(task.id)

        if self._auto_paused_tasks:
            save_active_tasks(self.tasks)
            self.overlay.update_display()
            print(f"Auto-paused {len(self._auto_paused_tasks)} task(s)")

    def _on_wake(self):
        """Resume auto-paused tasks when Mac wakes."""
        print("System woke — resuming auto-paused tasks")

        resumed = 0
        for task in self.tasks:
            if task.id in self._auto_paused_tasks and task.state == TaskState.PAUSED:
                task.state = TaskState.ONGOING
                task.start_interval()
                resumed += 1

        self._auto_paused_tasks = set()

        if resumed > 0:
            save_active_tasks(self.tasks)
            self.overlay.update_display()
            print(f"Resumed {resumed} auto-paused task(s)")

    def show_help(self):
        """Toggle the hotkey help dialog."""
        if self.help_dialog.isVisible():
            self.help_dialog.hide()
        else:
            self.help_dialog.show()
            self.help_dialog.raise_()
            self.help_dialog.activateWindow()


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
