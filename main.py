#!/usr/bin/env python3
"""etime - Evolved Timer for productivity tracking."""

import sys
from collections import deque
from dataclasses import dataclass, field
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


# Maximum number of undoable actions retained.
UNDO_BUFFER_SIZE = 5


@dataclass
class UndoAction:
    """A single undoable action, stored on the undo stack (most recent last).

    kind:
        "create"      — task was created; undo removes it.
        "complete"    — task was completed; undo restores it to its original spot.
        "adjust_time" — minutes were added to / removed from a task's time; undo
                        restores the snapshotted intervals, elapsed, and alarm.
    anchor_before_id:
        ID of the task that was immediately before this one in ``self.tasks`` at
        action time (None if it was first). Used to restore the *exact original
        list position* on undo, robust to other tasks shifting around.
    fallback_index:
        Absolute index in ``self.tasks`` at action time, used only if the anchor
        task is no longer present.
    reparented_children:
        For a "complete" action: (child_id, previous_parent_id) pairs for each
        direct child that was promoted up one level when this task was completed.
        Undo restores each child to its recorded previous parent. Storing the
        previous parent (not just the id) keeps undo correct under interleaved
        completions/undos.
    prev_work_intervals:
        For an "adjust_time" action: a deep copy of the task's work_intervals
        before the adjustment, restored on undo. A snapshot is robust to add
        (one interval inserted) and remove (several intervals trimmed/dropped)
        alike.
    prev_last_alarm_level:
        For an "adjust_time" action: the task's alarm level before the change,
        restored on undo (add may raise it to suppress an immediate alarm; remove
        may lower it to re-arm one).
    prev_elapsed_seconds:
        For an "adjust_time" action: the task's elapsed_seconds before the change,
        restored verbatim on undo (a plain recompute can't recover it when the
        backfill was the task's only interval).
    """
    kind: str
    task: Task
    anchor_before_id: Optional[str] = None
    fallback_index: int = -1
    reparented_children: list[tuple[str, Optional[str]]] = field(default_factory=list)
    prev_work_intervals: Optional[list] = None
    prev_last_alarm_level: int = 0
    prev_elapsed_seconds: float = 0.0
from timer_engine import TimerEngine
from overlay import OverlayWindow
from task_dialog import TaskDialog
from search_dialog import SearchDialog
from rename_dialog import RenameDialog
from time_adjust_dialog import TimeAdjustDialog
from hotkeys import HotkeyManager
from config import KEY_N, KEY_P, KEY_C, KEY_Q, KEY_S, KEY_U, KEY_H, KEY_T, KEY_F, KEY_UP, KEY_DOWN, KEY_A, KEY_LEFT, KEY_RIGHT, KEY_G, KEY_SLASH, KEY_E, KEY_EQUAL, KEY_MINUS, DEFAULT_TASK_MINUTES, DETERRED_FILE
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
            ("⌃⌥⌘E", "Rename focused task"),
            ("⌃⌥⌘+", "Add time to focused task"),
            ("⌃⌥⌘−", "Remove time from focused task"),
            ("⌃⌥⌘U", "Undo (last 5 actions)"),
            ("⌃⌥⌘Q", "Dismiss alarm"),
            ("⌃⌥⌘S", "Toggle overlay visibility"),
            ("⌃⌥⌘H", "Toggle this help"),
            ("⌃⌥⌘/", "Search, jump, or create task"),
            ("⌃⌥⌘T", "Toggle subtask (of task above)"),
            ("⌃⌥⌘F", "Fold / unfold subtasks"),
            ("⌃⌥⌘A", "Toggle show all (stashed tasks)"),
            ("⇧⌃⌥⌘→", "Stash focused task"),
            ("⇧⌃⌥⌘←", "Unstash focused task"),
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
        # Undo stack of recent actions (most recent last), capped at UNDO_BUFFER_SIZE.
        self.undo_stack: deque[UndoAction] = deque(maxlen=UNDO_BUFFER_SIZE)
        self._auto_paused_tasks: set = set()  # Task IDs paused due to sleep
        self.show_all_mode: bool = False  # Toggle visibility of stashed tasks
        # Text captured when a creation is undone, restored into the next dialog.
        self._pending_prefill: Optional[dict] = None

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
        self.hotkey_manager.register(KEY_U, self.undo)
        self.hotkey_manager.register(KEY_H, self.show_help)
        self.hotkey_manager.register(KEY_T, self.toggle_subtask)
        self.hotkey_manager.register(KEY_F, self.toggle_collapse)
        self.hotkey_manager.register(KEY_RIGHT, self.stash_task, shift=True)
        self.hotkey_manager.register(KEY_LEFT, self.unstash_task, shift=True)
        self.hotkey_manager.register(KEY_A, self.toggle_show_all)
        self.hotkey_manager.register(KEY_G, self.log_deterred)
        self.hotkey_manager.register(KEY_SLASH, self.open_search)
        self.hotkey_manager.register(KEY_E, self.edit_task_name)
        # ⌃⌥⌘+ adds time, ⌃⌥⌘− removes it; register both the shifted and bare
        # variants of each key so a fumbled Shift still works.
        self.hotkey_manager.register(KEY_EQUAL, self.add_time)
        self.hotkey_manager.register(KEY_EQUAL, self.add_time, shift=True)
        self.hotkey_manager.register(KEY_MINUS, self.subtract_time)
        self.hotkey_manager.register(KEY_MINUS, self.subtract_time, shift=True)

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

        # Setup search dialog (kept as instance to prevent GC)
        self.search_dialog = SearchDialog()
        self.search_dialog.task_selected.connect(self._on_search_selected)
        self.search_dialog.create_task_requested.connect(self._on_search_create)

        # Setup rename dialog (kept as instance to prevent GC)
        self.rename_dialog = RenameDialog()
        self.rename_dialog.name_submitted.connect(self._on_rename_submitted)
        # Id of the task currently being renamed (set when the dialog opens).
        self._renaming_task_id: Optional[str] = None

        # Setup time-adjust dialog (kept as instance to prevent GC)
        self.time_adjust_dialog = TimeAdjustDialog()
        self.time_adjust_dialog.minutes_submitted.connect(self._on_time_adjust_submitted)
        # Id of the task currently being time-adjusted (set when the dialog opens).
        self._time_adjust_task_id: Optional[str] = None

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

    def new_task(self, suppress_parent: bool = False):
        """Handle new task hotkey.

        suppress_parent: when True, do not pre-fill the focused task as parent
        context (used by the search "create new task" path, which should make a
        top-level task rather than silently nesting under whatever is focused).
        """
        print("New task hotkey pressed")

        # Store previously focused app for focus restoration
        self.previous_app = NSWorkspace.sharedWorkspace().frontmostApplication()

        self.task_dialog.reset()

        # Provide all active tasks so a manually-typed parent name can resolve.
        self.task_dialog.set_available_parents(
            [(t.name, t.id) for t in self.tasks]
        )

        # Pass focused task as potential parent for subtask checkbox
        focused = self.overlay.get_focused_task()
        if focused and not suppress_parent:
            self.task_dialog.set_parent_context(
                parent_name=focused.name, parent_task_id=focused.id
            )

        # Restore any text stashed by undoing a creation (see _undo_creation).
        if self._pending_prefill is not None:
            self.task_dialog.prefill(**self._pending_prefill)
            self._pending_prefill = None

        self.task_dialog.show()
        self.task_dialog.raise_()  # Bring to front
        self.task_dialog.activateWindow()  # Activate and focus
        self.task_dialog.name_input.setFocus()  # Ensure name field has focus

    def _unfold_ancestors(self, task: Task) -> None:
        """Un-collapse every ancestor of ``task`` so the task is not folded away."""
        by_id = {t.id: t for t in self.tasks}
        seen: set = set()
        cur = task
        while cur.parent_task_id and cur.parent_task_id in by_id:
            if cur.parent_task_id in seen:
                break
            seen.add(cur.parent_task_id)
            parent = by_id[cur.parent_task_id]
            parent.is_collapsed = False
            cur = parent

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
                # If the parent (or any ancestor) is folded, unfold the chain so
                # the new subtask appears inside its section in the right spot
                # instead of getting stranded at the bottom.
                self._unfold_ancestors(task)
                self.overlay.sync_visible_widgets()
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

        # Always focus the new task (convert to visible index)
        visible = self.overlay._visible_tasks()
        visible_index = next(
            (i for i, t in enumerate(visible) if t.id == task.id),
            len(visible) - 1
        )
        self.overlay.focused_index = visible_index
        self.overlay.update_display()
        print(f"Set focused index to {visible_index}")

        # Ensure overlay is visible
        if not self.overlay_visible:
            self.overlay.show()
            self.overlay.position_at_top_right()
            self.overlay_visible = True
            print("Overlay shown for new task")

        # Track for undo
        self.undo_stack.append(UndoAction(kind="create", task=task))

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

        # Get task_id and full-list position early (for undo). We anchor to the
        # task immediately before this one so undo restores the exact original
        # position even if other tasks have shifted.
        task_id = task.id
        full_index = self.tasks.index(task)
        anchor_before_id = self.tasks[full_index - 1].id if full_index > 0 else None

        # Check if this task has an active alarm - auto-quiet it
        had_alarm = task_id in self.active_alarms
        if had_alarm:
            print(f"Task had active alarm - auto-quieting")
            self.active_alarms.discard(task_id)

            # If this was the last active alarm, stop the sound
            if len(self.active_alarms) == 0:
                stop_alarm()
                print("All alarms cleared - sound stopped")

        # Promote direct children up exactly one level: re-parent them to this
        # task's own parent. Without this, a completed task's children become
        # orphans that render as top-level — so a grandchild would jump up two
        # levels when its immediate parent is completed. Record each child's
        # previous parent so undo can restore the links.
        reparented_children: list[tuple[str, Optional[str]]] = []
        for child in self.tasks:
            if child.parent_task_id == task_id:
                reparented_children.append((child.id, child.parent_task_id))
                child.parent_task_id = task.parent_task_id

        # Save state for undo (before modifying)
        self.undo_stack.append(UndoAction(
            kind="complete",
            task=task,
            anchor_before_id=anchor_before_id,
            fallback_index=full_index,
            reparented_children=reparented_children,
        ))

        task.end_interval()

        # Set state to COMPLETED
        task.state = TaskState.COMPLETED
        task.completed_at = datetime.now().isoformat()

        # Append to history
        append_to_history(task)

        # Remove from active tasks
        self.tasks.remove(task)

        # Persist immediately. The removal animation's callback also saves, but it
        # is skipped when the widget can't be found (e.g. a folded-away task), so
        # save here to guarantee the re-parenting reaches disk.
        save_active_tasks(self.tasks)

        # Update focus index if needed (use visible task count)
        visible_count = len(self.overlay._visible_tasks())
        if self.overlay.focused_index >= visible_count and visible_count > 0:
            self.overlay.focused_index = visible_count - 1
        elif visible_count == 0:
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

    def undo(self):
        """Undo the most recent action (creation or completion), LIFO.

        Up to UNDO_BUFFER_SIZE actions can be undone in reverse order.
        """
        if not self.undo_stack:
            print("Nothing to undo")
            return

        action = self.undo_stack.pop()
        if action.kind == "create":
            self._undo_creation(action)
        elif action.kind == "complete":
            self._undo_completion(action)
        elif action.kind == "adjust_time":
            self._undo_adjust_time(action)
        else:
            print(f"Unknown undo action kind: {action.kind}")

    def _reinsertion_index(self, action: UndoAction) -> int:
        """Compute the index in self.tasks to restore a task to its original spot.

        Prefers inserting right after the anchor task (the task it originally
        followed); falls back to the stored absolute index if the anchor is gone.
        """
        if action.anchor_before_id is not None:
            anchor_idx = next(
                (i for i, t in enumerate(self.tasks) if t.id == action.anchor_before_id),
                None,
            )
            if anchor_idx is not None:
                return anchor_idx + 1
        # No anchor stored (was first task) or anchor no longer present:
        # fall back to the absolute index, clamped to the current list.
        return min(max(action.fallback_index, 0), len(self.tasks))

    def _undo_creation(self, action: UndoAction):
        """Undo a task creation — removes the task and restores its text.

        The name/time/ambitious the user typed are stashed so the next New Task
        dialog (which we reopen immediately) comes back pre-filled for editing.
        """
        task = action.task
        print(f"Undoing creation of: {task.name}")

        # Stash the typed values to restore into the reopened dialog.
        self._pending_prefill = {
            "name": task.name,
            "minutes": max(1, task.estimated_seconds // 60),
            "ambitious_minutes": (task.ambitious_seconds // 60) if task.ambitious_seconds else 0,
        }

        # End any open interval
        if task.work_intervals and task.work_intervals[-1]["end"] is None:
            task.end_interval()

        # Remove from task list and overlay
        if task in self.tasks:
            self.tasks.remove(task)
        self.overlay.remove_task(task.id)

        # Adjust focus
        visible = self.overlay._visible_tasks()
        if visible:
            self.overlay.focused_index = min(self.overlay.focused_index, len(visible) - 1)
        else:
            self.overlay.focused_index = -1
        self.overlay.update_display()

        save_active_tasks(self.tasks)
        print(f"Task '{task.name}' removed")

        # Reopen the dialog so the restored text is right there to re-edit.
        self.new_task()

    def _undo_adjust_time(self, action: UndoAction):
        """Undo an add/remove-time — restores the snapshotted intervals and state."""
        task = action.task
        print(f"Undoing time adjustment on: {task.name}")

        # Restore a fresh copy of the pre-adjustment intervals (fresh so a later
        # redo/undo can't alias the stored snapshot).
        if action.prev_work_intervals is not None:
            task.work_intervals = [dict(iv) for iv in action.prev_work_intervals]

        task.last_alarm_level = action.prev_last_alarm_level
        # Restore the exact prior elapsed. A recompute would be wrong when the
        # only interval was the one added (compute_elapsed would then fall back to
        # the now-stale elapsed_seconds).
        task.elapsed_seconds = action.prev_elapsed_seconds

        save_active_tasks(self.tasks)
        self.overlay.update_display()
        print(f"Restored time on '{task.name}'")

    def _undo_completion(self, action: UndoAction):
        """Undo a task completion — restores the task to its original position."""
        task = action.task
        print(f"Undoing completion of: {task.name}")

        # Remove from history. Completions append to history.jsonl in order and
        # the undo stack pops LIFO, so the matching entry is always the last line.
        if not remove_last_from_history(task.id):
            print("Failed to remove from history - undo aborted")
            # Put the action back so the user can retry / undo something else.
            self.undo_stack.append(action)
            return

        # Restore task state
        task.state = TaskState.ONGOING
        task.completed_at = None
        task.start_interval()

        # Restore any children that were promoted up a level on completion, back
        # to their recorded previous parent (this task, in the normal case).
        if action.reparented_children:
            prev_parent = dict(action.reparented_children)
            for child in self.tasks:
                if child.id in prev_parent:
                    child.parent_task_id = prev_parent[child.id]

        # Re-insert at original position (anchored to the task it followed).
        insert_index = self._reinsertion_index(action)
        self.tasks.insert(insert_index, task)

        # Re-add to overlay (insert_task derives the visible layout slot by id).
        self.overlay.insert_task(task, insert_index)

        # Set focus to restored task (convert to visible index)
        visible = self.overlay._visible_tasks()
        visible_index = next(
            (i for i, t in enumerate(visible) if t.id == task.id),
            len(visible) - 1
        )
        self.overlay.focused_index = visible_index
        self.overlay.update_display()

        # Save active tasks
        save_active_tasks(self.tasks)

        print(f"Task '{task.name}' restored")

    def toggle_subtask(self):
        """Toggle focused task as subtask of the task directly above it."""
        task = self.overlay.get_focused_task()
        if not task:
            print("No task focused")
            return

        visible = self.overlay._visible_tasks()
        idx = self.overlay.focused_index
        if task.parent_task_id:
            # Already a subtask — remove the link
            task.parent_task_id = None
            print(f"Removed subtask link from '{task.name}'")
        else:
            # Become a subtask of the task above (in visible list)
            if idx <= 0:
                print("No task above to use as parent")
                return
            parent = visible[idx - 1]
            task.parent_task_id = parent.id
            print(f"'{task.name}' is now a subtask of '{parent.name}'")

        save_active_tasks(self.tasks)
        self.overlay.update_display()

    def toggle_collapse(self):
        """Fold/unfold the focused task's subtree (⌃⌥⌘F).

        Only meaningful for a task that has subtasks; folding hides its whole
        descendant subtree from the overlay. Focus stays on the parent task.
        """
        task = self.overlay.get_focused_task()
        if not task:
            print("No task focused")
            return

        if not self.overlay._has_children(task):
            print("No subtasks to fold")
            return

        # Overlay flips is_collapsed and animates only the affected subtree.
        self.overlay.toggle_collapse(task)
        print(f"{'Folded' if task.is_collapsed else 'Unfolded'} subtasks of '{task.name}'")

        save_active_tasks(self.tasks)

    def stash_task(self):
        """Stash the focused task — hide from default view. Only paused tasks can be stashed."""
        task = self.overlay.get_focused_task()
        if not task or task.is_stashed:
            return

        if task.state == TaskState.ONGOING:
            print("Cannot stash an ongoing task — pause it first")
            return

        print(f"Stashing task: {task.name}")
        task.is_stashed = True

        if self.show_all_mode:
            # In show-all mode, just update appearance (no swipe away)
            self.overlay.update_display()
        else:
            # In normal mode, animate out and adjust focus
            visible = self.overlay._visible_tasks()
            if len(visible) > 0:
                self.overlay.focused_index = min(self.overlay.focused_index, len(visible) - 1)
            else:
                self.overlay.focused_index = -1
            self.overlay.stash_task_widget(task.id)
            self.overlay.update_display()

        save_active_tasks(self.tasks)

    def unstash_task(self):
        """Unstash the focused task (only in show-all mode)."""
        if not self.show_all_mode:
            print("Can only unstash in show-all mode")
            return

        task = self.overlay.get_focused_task()
        if not task or not task.is_stashed:
            return

        print(f"Unstashing task: {task.name}")
        task.is_stashed = False
        self.overlay.update_display()
        save_active_tasks(self.tasks)

    def toggle_show_all(self):
        """Toggle visibility of stashed tasks."""
        self.show_all_mode = not self.show_all_mode
        self.overlay.show_all = self.show_all_mode
        self.overlay.rebuild_widgets()
        print(f"Show all: {self.show_all_mode}")

    def log_deterred(self):
        """Log a deterred distraction (⌃⌥⌘G)."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        DETERRED_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(DETERRED_FILE, "a") as f:
            f.write(timestamp + "\n")
        print(f"Deterred distraction logged: {timestamp}")

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

        # Force-recreate the event tap — macOS often silently kills it across sleep
        self.hotkey_manager.force_recreate()

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

    def open_search(self):
        """Open the centered task-search popup (⌃⌥⌘/).

        Opens even with no tasks: typing a name and pressing Enter with no match
        offers to create a new task with that name.
        """
        self.previous_app = NSWorkspace.sharedWorkspace().frontmostApplication()
        self.search_dialog.set_tasks(self.tasks)
        self.search_dialog.show()
        self.search_dialog.raise_()
        self.search_dialog.activateWindow()
        self.search_dialog.search_input.setFocus()

    def _on_search_selected(self, task_id: str):
        """Jump to a task chosen in the search popup.

        Unfolds any collapsed ancestor sections (and reveals the task if it was
        stashed) so the selected task becomes visible and focused.
        """
        task = next((t for t in self.tasks if t.id == task_id), None)
        if task is None:
            print(f"Search selected unknown task {task_id}")
            return

        # Unfold collapsed ancestors so the task isn't folded away.
        self._unfold_ancestors(task)

        # If the task itself is stashed and hidden, switch to show-all so it shows.
        if task.is_stashed and not self.show_all_mode:
            self.show_all_mode = True
            self.overlay.show_all = True

        # Rebuild so section-header state, stash visibility, and widgets are all
        # consistent, then focus the (now-visible) task.
        self.overlay.rebuild_widgets()
        visible = self.overlay._visible_tasks()
        idx = next((i for i, t in enumerate(visible) if t.id == task_id), None)
        if idx is not None:
            self.overlay.focused_index = idx
        self.overlay.update_display()
        save_active_tasks(self.tasks)

        # Restore focus to the app the user was in before searching.
        if self.previous_app:
            self.previous_app.activateWithOptions_(1)
            self.previous_app = None

    def _on_search_create(self, name: str):
        """Create a new task from the search box when nothing matched.

        Opens the New Task dialog pre-filled with the typed name, as a top-level
        task (parent context suppressed).
        """
        name = name.strip()
        if not name:
            return
        print(f"Search: creating new task '{name}'")
        # Pre-fill the dialog with the typed name (default time/ambitious).
        self._pending_prefill = {
            "name": name,
            "minutes": DEFAULT_TASK_MINUTES,
            "ambitious_minutes": 0,
        }
        self.new_task(suppress_parent=True)

    def edit_task_name(self):
        """Rename the focused task in place (⌃⌥⌘E).

        Edits whichever task is focused (which is normally the running one). If
        the rename dialog is already open, do nothing so re-pressing the hotkey
        (which the local monitor also delivers) doesn't reset the field.
        """
        if self.rename_dialog.isVisible():
            return
        task = self.overlay.get_focused_task()
        if not task:
            print("No task focused to rename")
            return
        self.previous_app = NSWorkspace.sharedWorkspace().frontmostApplication()
        self._renaming_task_id = task.id
        print(f"Renaming task: {task.name}")
        self.rename_dialog.open_for(task.name)

    def _on_rename_submitted(self, new_name: str):
        """Apply a submitted rename to the task that was being edited."""
        task_id = self._renaming_task_id
        self._renaming_task_id = None
        task = next((t for t in self.tasks if t.id == task_id), None)
        if task is None:
            print(f"Rename target {task_id} no longer exists")
            return
        old = task.name
        task.name = new_name
        print(f"Renamed '{old}' -> '{new_name}'")
        save_active_tasks(self.tasks)
        self.overlay.update_display()

        # Restore focus to the app the user was in before renaming.
        if self.previous_app:
            self.previous_app.activateWithOptions_(1)
            self.previous_app = None

    def add_time(self):
        """Add elapsed minutes to the focused task, backdated to now (⌃⌥⌘+).

        Opens the time-adjust dialog on the focused task (normally the running
        one). The entered minutes are attributed to the [now - N, now] window so
        they show up in the dashboard's time-of-day view just before now.
        """
        self._open_time_adjust(adding=True)

    def subtract_time(self):
        """Remove elapsed minutes from the focused task (⌃⌥⌘−).

        Trims the entered minutes off the most recent end of the task's timeline,
        capped at the time actually spent (elapsed never goes negative).
        """
        self._open_time_adjust(adding=False)

    def _open_time_adjust(self, adding: bool):
        """Shared opener for the add/remove-time dialog."""
        if self.time_adjust_dialog.isVisible():
            return
        task = self.overlay.get_focused_task()
        if not task:
            print(f"No task focused to {'add time to' if adding else 'remove time from'}")
            return
        self.previous_app = NSWorkspace.sharedWorkspace().frontmostApplication()
        self._time_adjust_task_id = task.id
        print(f"{'Adding time to' if adding else 'Removing time from'} task: {task.name}")
        self.time_adjust_dialog.open_for(task.name, adding)

    def _on_time_adjust_submitted(self, minutes: int, adding: bool):
        """Apply an add/remove-time submission to the task that was being edited."""
        task_id = self._time_adjust_task_id
        self._time_adjust_task_id = None
        task = next((t for t in self.tasks if t.id == task_id), None)
        if task is None:
            print(f"Time-adjust target {task_id} no longer exists")
            return

        # Snapshot for undo: a full intervals copy plus the scalars we touch.
        prev_intervals = [dict(iv) for iv in task.work_intervals]
        prev_elapsed = task.elapsed_seconds
        prev_alarm = task.last_alarm_level

        if adding:
            task.add_manual_minutes(minutes)
            print(f"Added {minutes} min to '{task.name}' (now {task.elapsed_seconds / 60:.1f} min)")
        else:
            removed = task.subtract_manual_minutes(minutes)
            removed_min = removed / 60
            if removed < minutes * 60 - 1:
                # Capped at the time actually spent — say so (never silently do less).
                print(f"Removed {removed_min:.1f} min from '{task.name}' "
                      f"(capped at time spent; now {task.elapsed_seconds / 60:.1f} min)")
            else:
                print(f"Removed {minutes} min from '{task.name}' (now {task.elapsed_seconds / 60:.1f} min)")

        # Re-derive the alarm level from the new elapsed. Adding past work should
        # not nag immediately; removing should re-arm a crossed alarm. check_alarm
        # fires on int(ratio) > last_alarm_level, so:
        if task.estimated_seconds > 0:
            ratio = task.elapsed_seconds / task.estimated_seconds
            new_level = int(ratio) if ratio >= 1.0 else 0
            if adding:
                task.last_alarm_level = max(prev_alarm, new_level)   # suppress an immediate re-alarm
            else:
                task.last_alarm_level = min(prev_alarm, new_level)   # allow a future re-crossing to alarm
        else:
            task.last_alarm_level = 0

        self.undo_stack.append(UndoAction(
            kind="adjust_time",
            task=task,
            prev_work_intervals=prev_intervals,
            prev_last_alarm_level=prev_alarm,
            prev_elapsed_seconds=prev_elapsed,
        ))

        save_active_tasks(self.tasks)
        self.overlay.update_display()

        # Restore focus to the app the user was in before adjusting time.
        if self.previous_app:
            self.previous_app.activateWithOptions_(1)
            self.previous_app = None

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
