"""Main overlay window for etime application."""

from typing import List, Optional, Dict
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QGraphicsOpacityEffect, QSizePolicy
)
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QFont, QScreen

from models import Task, TaskState
from config import (
    WINDOW_MARGIN_X, WINDOW_MARGIN_Y,
    COLOR_FOCUSED, COLOR_OVERTIME, COLOR_PAUSED, COLOR_NORMAL, COLOR_UNFOCUSED, COLOR_AMBITIOUS,
    COLOR_WINDOW_BG, COLOR_WINDOW_BORDER, COLOR_CARD_BG, COLOR_CARD_BORDER,
    COLOR_FOCUSED_BORDER, COLOR_RECENT, COLOR_LAST_RUN_BG, LAST_RUN_MIN_SECONDS,
    COLOR_WAITING, COLOR_WAITING_BG,
    FONT_FAMILY_MONO, FONT_FAMILY_SERIF, FONT_SIZE,
    FOCUS_INDICATOR, NO_FOCUS_INDICATOR,
    FADE_IN_DURATION_MS, FADE_OUT_DURATION_MS
)


class TaskWidget(QWidget):
    """Widget displaying a single task."""

    def __init__(self, task: Task, is_focused: bool = False):
        super().__init__()
        self.task = task
        self.is_focused = is_focused
        self.is_alarmed = False  # Track if task has active alarm
        self.depth = 0  # Nesting depth (0 = top-level, 1 = subtask, 2 = sub-subtask, ...)
        self.has_children = False  # Whether this task has subtasks (shows a fold triangle)
        self.is_collapsed = False  # Whether this task's subtree is currently folded
        self.has_active_hidden = False  # A folded-away descendant is currently running
        self.has_overtime_hidden = False  # A folded-away running descendant is overtime
        self.hidden_count = 0  # Number of folded-away non-stashed descendants (shown when collapsed)
        self.parked_count = 0  # Number of folded-away stashed descendants (the "p" in "n/p")
        self.is_stashed = False  # Track stashed display state
        self.is_recent = False  # One of the most-recently-active tasks (gets a highlight)
        self.is_last_run = False  # The single last-run task (gets a "return here" fill)

        # Create layout
        layout = QHBoxLayout()
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        # Focus indicator
        self.focus_label = QLabel(FOCUS_INDICATOR if is_focused else NO_FOCUS_INDICATOR)
        self.focus_label.setFixedWidth(20)
        layout.addWidget(self.focus_label)

        # Task name (allow wrapping to 2 lines), in a fresh serif face
        self.name_label = QLabel(task.name)
        name_font = QFont(FONT_FAMILY_SERIF, FONT_SIZE)
        name_font.setStyleHint(QFont.StyleHint.Serif)
        self.name_label.setFont(name_font)
        self.name_label.setMinimumWidth(150)
        self.name_label.setMaximumWidth(350)
        self.name_label.setWordWrap(True)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.name_label, stretch=1)

        # How long this task has been blocked on something external. Hidden
        # unless it is — a wait only means something once you can see its age.
        self.wait_label = QLabel()
        wait_font = QFont(FONT_FAMILY_MONO, FONT_SIZE - 1)
        wait_font.setStyleHint(QFont.StyleHint.Monospace)
        self.wait_label.setFont(wait_font)
        self.wait_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.wait_label.hide()
        layout.addWidget(self.wait_label)

        # Time display (monospace font)
        self.time_label = QLabel()
        time_font = QFont(FONT_FAMILY_MONO, FONT_SIZE)
        time_font.setStyleHint(QFont.StyleHint.Monospace)
        self.time_label.setFont(time_font)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.time_label)

        self.setLayout(layout)

        # Prevent shrinking when new tasks are added to the overlay
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        self.update_display()

    def update_display(self):
        """Update widget appearance based on task state."""
        # Format times
        elapsed_str = self._format_time(self.task.elapsed_seconds)
        estimated_str = self._format_time(self.task.estimated_seconds)

        # Format ambitious time (-- when None)
        if self.task.ambitious_seconds is not None:
            ambitious_str = self._format_time(self.task.ambitious_seconds)
        else:
            ambitious_str = "--:--"

        # Always show 3-value display: actual / ambitious / estimated
        self.time_label.setText(f"{elapsed_str} / {ambitious_str} / {estimated_str}")

        waiting_for = self._waiting_seconds()
        if waiting_for is None:
            self.wait_label.hide()
        else:
            self.wait_label.setText(f"⏳ {self._format_wait(waiting_for)}")
            self.wait_label.show()

        # Check if task is in ambitious state (ongoing, has ambitious target, within it)
        in_ambitious = (
            self.task.state == TaskState.ONGOING
            and self.task.ambitious_seconds is not None
            and self.task.elapsed_seconds < self.task.ambitious_seconds
        )

        # Determine text color
        if waiting_for is not None:
            # Blocked on someone else — distinct from "I put this down".
            color = COLOR_WAITING
        elif self.task.state == TaskState.PAUSED:
            color = COLOR_PAUSED
        elif self.task.elapsed_seconds >= self.task.estimated_seconds:
            # Overtime tasks are always red (focused or not)
            color = COLOR_OVERTIME
        elif in_ambitious:
            # Within ambitious time target - green
            color = COLOR_AMBITIOUS
        elif self.is_focused:
            # Focused ongoing task is black
            color = COLOR_NORMAL
        else:
            # Non-focused ongoing task is dimmed gray
            color = COLOR_UNFOCUSED

        # Stashed tasks get dimmed appearance with marker
        self.is_stashed = self.property("stashed") or False
        if self.is_stashed:
            color = "#A79E8E"
            bg_color = "#EFEAE0" if self.is_focused else "#E7E1D5"
            border_color = "#D6CCB8"
        else:
            bg_color = COLOR_FOCUSED if self.is_focused else COLOR_CARD_BG
            border_color = COLOR_FOCUSED_BORDER if self.is_focused else COLOR_CARD_BORDER

        # A folded category with a running subtask inside gets an accent so you
        # can tell work is still happening even though it's collapsed: red when
        # that hidden task is overtime, otherwise sage green.
        if self.is_collapsed and self.has_active_hidden:
            if self.has_overtime_hidden:
                color = COLOR_OVERTIME
                bg_color = "#F0D6D1" if self.is_focused else "#F7E7E4"
                border_color = "#B23A2E"
            else:
                color = COLOR_AMBITIOUS
                bg_color = "#D4E3D2" if self.is_focused else "#E6EFE4"
                border_color = "#4F7A55"

        # The single most-recently-run task (that ran long enough to be real)
        # gets a soft blue fill so you can jump back to it after stepping away.
        if (self.is_last_run and not self.is_stashed
                and not (self.is_collapsed and self.has_active_hidden)):
            bg_color = COLOR_LAST_RUN_BG

        # Waiting outranks the return-here cue: if the last thing you touched is
        # now blocked, that's the more useful thing to know about it.
        if waiting_for is not None and not self.is_stashed:
            bg_color = COLOR_WAITING_BG

        # Recently-active tasks (or the visible section header of a folded-away
        # active task) get a gold border so you can spot where work is happening.
        border_width = 1
        if self.is_recent:
            border_color = COLOR_RECENT
            border_width = 2

        # Apply styling
        self.setStyleSheet(f"""
            TaskWidget {{
                background-color: {bg_color};
                border-radius: 8px;
                border: {border_width}px solid {border_color};
                padding: 2px;
            }}
            QLabel {{
                color: {color};
                background-color: transparent;
                border: none;
            }}
        """)

        # Update focus indicator
        self.focus_label.setText(FOCUS_INDICATOR if self.is_focused else NO_FOCUS_INDICATOR)

        # Compose name prefix: a fold triangle for parents, a bullet for leaf
        # subtasks, plus the stash marker. At most one hierarchy glyph per row.
        prefix_parts = []
        if self.has_children:
            prefix_parts.append("▸" if self.is_collapsed else "▾")  # disclosure triangle
        elif self.depth >= 1:
            prefix_parts.append("•")  # bullet marking a (sub)subtask leaf
        if self.is_stashed:
            prefix_parts.append("⏸")
        name_text = " ".join(prefix_parts + [self.task.name]) if prefix_parts else self.task.name
        # When folded, show how many subtasks are hidden away: (n) or (n/p) where
        # n = non-stashed descendants, p = parked (stashed) descendants.
        if self.is_collapsed and (self.hidden_count > 0 or self.parked_count > 0):
            if self.parked_count > 0:
                name_text = f"{name_text}  ({self.hidden_count}/{self.parked_count})"
            else:
                name_text = f"{name_text}  ({self.hidden_count})"
        self.name_label.setText(name_text)

        # Make text bold if alarmed
        if self.is_alarmed:
            self.name_label.setStyleSheet("font-weight: bold; background-color: transparent; border: none;")
            time_font = self.time_label.font()
            time_font.setBold(True)
            self.time_label.setFont(time_font)
        else:
            self.name_label.setStyleSheet("font-weight: normal; background-color: transparent; border: none;")
            time_font = self.time_label.font()
            time_font.setBold(False)
            self.time_label.setFont(time_font)

    def set_focused(self, focused: bool):
        """Update focus state and refresh display."""
        self.is_focused = focused
        self.update_display()

    def set_alarmed(self, alarmed: bool):
        """Set alarm status and refresh display."""
        self.is_alarmed = alarmed
        self.update_display()

    def set_depth(self, depth: int):
        """Set subtask nesting depth and refresh indentation.

        Indentation grows with depth so a level-2 sub-subtask is visibly deeper
        than a level-1 subtask (8px base + 22px per level).
        """
        if self.depth != depth:
            self.depth = depth
            layout = self.layout()
            left = 8 + depth * 22
            layout.setContentsMargins(left, 4, 8, 4)
            self.update_display()

    def set_fold_state(self, has_children: bool, is_collapsed: bool,
                       has_active_hidden: bool = False, hidden_count: int = 0,
                       parked_count: int = 0, has_overtime_hidden: bool = False):
        """Set fold-related display state (triangle, collapse tint, hidden count)."""
        if (self.has_children != has_children
                or self.is_collapsed != is_collapsed
                or self.has_active_hidden != has_active_hidden
                or self.hidden_count != hidden_count
                or self.parked_count != parked_count
                or self.has_overtime_hidden != has_overtime_hidden):
            self.has_children = has_children
            self.is_collapsed = is_collapsed
            self.has_active_hidden = has_active_hidden
            self.hidden_count = hidden_count
            self.parked_count = parked_count
            self.has_overtime_hidden = has_overtime_hidden
            self.update_display()

    def set_recent(self, is_recent: bool):
        """Mark/unmark this row as a recently-active task and refresh display."""
        if self.is_recent != is_recent:
            self.is_recent = is_recent
            self.update_display()

    def set_last_run(self, is_last_run: bool):
        """Mark/unmark this row as the last-run "return here" task."""
        if self.is_last_run != is_last_run:
            self.is_last_run = is_last_run
            self.update_display()

    def _waiting_seconds(self) -> Optional[float]:
        """Seconds this task has been waiting, or None if it isn't.

        A completed or running task is never waiting, whatever the field says —
        that guards against a marker that outlived whatever set it.
        """
        stamp = getattr(self.task, "waiting_since", None)
        if not stamp or self.task.state in (TaskState.ONGOING, TaskState.COMPLETED):
            return None
        try:
            return max(0.0, (datetime.now() - datetime.fromisoformat(stamp)).total_seconds())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _format_wait(seconds: float) -> str:
        """Coarse duration for a wait: minutes, then hours, then days."""
        minutes = int(seconds // 60)
        if minutes < 60:
            return f"{minutes}m"
        hours, minutes = divmod(minutes, 60)
        if hours < 24:
            return f"{hours}h {minutes:02d}m"
        days, hours = divmod(hours, 24)
        return f"{days}d {hours}h"

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format seconds as MM:SS."""
        total_secs = int(seconds)
        mins = total_secs // 60
        secs = total_secs % 60
        return f"{mins:02d}:{secs:02d}"


class OverlayWindow(QWidget):
    """Main overlay window displaying all active tasks."""

    def __init__(self, tasks: List[Task], app_controller=None):
        super().__init__()
        self.tasks = tasks
        self.app_controller = app_controller  # Reference to AppController for alarm status
        self.task_widgets: Dict[str, TaskWidget] = {}  # task_id -> TaskWidget
        self.show_all: bool = False  # When True, stashed tasks are visible
        self.focused_index = 0 if tasks else -1

        self._setup_window()
        self._setup_ui()
        self._populate_tasks()

    def _setup_window(self):
        """Configure window properties."""
        # Window flags: always on top, frameless, tool (no Cmd+Tab)
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool
        )

        # Window styling — warm cream backdrop, soft brown border, rounder corners
        self.setStyleSheet(f"""
            OverlayWindow {{
                background-color: {COLOR_WINDOW_BG};
                border: 2px solid {COLOR_WINDOW_BORDER};
                border-radius: 14px;
            }}
        """)

        # macOS-specific: ensure window stays visible
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)

        # Position at top-right (will be adjusted after window is shown with correct size)
        self.position_at_top_right()

    def position_at_top_right(self):
        """Position window at top-right corner of screen."""
        screen = QScreen.availableGeometry(self.screen())
        # Calculate position: screen_width - window_width - margin
        x = screen.width() - self.width() - WINDOW_MARGIN_X
        y = WINDOW_MARGIN_Y
        self.move(x, y)

    def _setup_ui(self):
        """Setup UI layout."""
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(8, 8, 8, 8)  # Increased padding
        self.layout.setSpacing(4)  # Increased spacing between tasks
        self.setLayout(self.layout)

        # "All" mode indicator (hidden by default)
        self.show_all_label = QLabel("All")
        self.show_all_label.setStyleSheet(
            "color: #666666; font-size: 11px; font-weight: bold; "
            "background: transparent; border: none; padding: 0px 2px;"
        )
        self.show_all_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.show_all_label.hide()
        self.layout.insertWidget(0, self.show_all_label)

    def _populate_tasks(self):
        """Populate window with existing tasks."""
        visible = self._visible_tasks()
        # Set initial focus to first visible task
        if visible:
            self.focused_index = 0
        else:
            self.focused_index = -1
        for i, task in enumerate(visible):
            widget = TaskWidget(task, i == self.focused_index)
            if task.is_stashed:
                widget.setProperty("stashed", True)
            self.task_widgets[task.id] = widget
            self.layout.addWidget(widget)

    def _add_task_widget(self, task: Task, is_focused: bool, animate: bool = True):
        """Add a task widget to the layout."""
        widget = TaskWidget(task, is_focused)
        self.task_widgets[task.id] = widget
        self.layout.addWidget(widget)

        if animate:
            self._fade_in_widget(widget)

    def add_task(self, task: Task):
        """Add a new task with fade-in animation."""
        # Add to bottom of list
        is_focused = len(self.tasks) == 0  # Focus if first task
        if is_focused:
            self.focused_index = 0

        self._add_task_widget(task, is_focused, animate=True)

        # Adjust window size
        self.adjustSize()

    def insert_task(self, task: Task, index: int):
        """Insert a task at a specific position with fade-in animation.

        Used for undo functionality to restore task at original position.
        The index is into self.tasks; we convert to visible layout index.
        """
        # Skip adding widget if task is stashed and not in show-all mode
        if task.is_stashed and not self.show_all:
            return

        # Find the correct layout position among visible tasks
        visible = self._visible_tasks()
        layout_index = next(
            (i for i, t in enumerate(visible) if t.id == task.id),
            len(visible) - 1
        )
        is_focused = layout_index == self.focused_index

        widget = TaskWidget(task, is_focused)
        self.task_widgets[task.id] = widget
        # +1 to account for show_all_label at layout position 0
        self.layout.insertWidget(layout_index + 1, widget)

        self._fade_in_widget(widget)
        self.adjustSize()

    def sync_visible_widgets(self):
        """Add/remove widgets so they match ``_visible_tasks()``.

        Existing widgets are kept in place; only rows that should newly appear
        are faded in and rows that should disappear are removed. Used when the
        visible set changes without a full rebuild (e.g. auto-unfolding a parent
        when a subtask is added to a folded section).
        """
        visible = self._visible_tasks()
        visible_ids = {t.id for t in visible}

        # Remove widgets for tasks that are no longer visible.
        for task_id in list(self.task_widgets.keys()):
            if task_id not in visible_ids:
                widget = self.task_widgets.pop(task_id)
                self.layout.removeWidget(widget)
                widget.deleteLater()

        # Add widgets for newly-visible tasks, in display order. Because we go in
        # order and every earlier visible task already has a widget at its slot,
        # inserting at layout_index + 1 (+1 for the show_all_label) is correct.
        for layout_index, task in enumerate(visible):
            if task.id not in self.task_widgets:
                is_focused = (layout_index == self.focused_index)
                widget = TaskWidget(task, is_focused)
                if task.is_stashed:
                    widget.setProperty("stashed", True)
                self.task_widgets[task.id] = widget
                self.layout.insertWidget(layout_index + 1, widget)
                self._fade_in_widget(widget)

        self.adjustSize()

    def _remove_task_animated(self, task_id: str, green_flash: bool = False,
                              confetti: bool = False, confetti_count: int = 12, callback=None):
        """Remove a task with optional green flash and confetti animations.

        Args:
            task_id: ID of task to remove.
            green_flash: Show bright green flash before fade-out.
            confetti: Spawn confetti particles (implies green_flash delay).
            callback: Called after widget is fully removed.
        """
        if task_id not in self.task_widgets:
            return

        widget = self.task_widgets[task_id]

        def finish_removal():
            def on_fade_finished():
                self.layout.removeWidget(widget)
                widget.deleteLater()
                del self.task_widgets[task_id]
                self.adjustSize()
                if callback:
                    callback()
            self._fade_out_widget(widget, on_fade_finished)

        if green_flash:
            widget.setStyleSheet("""
                TaskWidget {
                    background-color: #A5D6A7;
                    border-radius: 6px;
                    border: 2px solid #4CAF50;
                    padding: 2px;
                }
                QLabel {
                    color: #1B5E20;
                    background-color: transparent;
                    border: none;
                    font-weight: bold;
                }
            """)
            if confetti:
                self._spawn_confetti(widget, count=confetti_count)
            from PyQt6.QtCore import QTimer
            delay = 600 if confetti else 400
            QTimer.singleShot(delay, finish_removal)
        elif confetti:
            # Mini confetti without green flash (normal completion)
            self._spawn_confetti(widget, count=confetti_count)
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(100, finish_removal)
        else:
            finish_removal()

    def remove_task(self, task_id: str, callback=None):
        """Remove a task with fade-out animation."""
        self._remove_task_animated(task_id, callback=callback)

    def remove_task_with_celebration(self, task_id: str, callback=None):
        """Remove a completed task with mini confetti (normal completion)."""
        self._remove_task_animated(task_id, confetti=True, confetti_count=4, callback=callback)

    def remove_task_with_confetti(self, task_id: str, callback=None):
        """Remove a task with green flash + confetti (ambitious completion)."""
        self._remove_task_animated(task_id, green_flash=True, confetti=True,
                                   callback=callback)

    def _spawn_confetti(self, source_widget, count: int = 12):
        """Spawn confetti particle labels that scatter from the widget."""
        import random
        from PyQt6.QtCore import QTimer

        confetti_colors = ["#4CAF50", "#FF9800", "#2196F3", "#E91E63", "#9C27B0", "#FFEB3B"]
        confetti_chars = ["●", "■", "▲", "★", "◆"]

        center_x = source_widget.x() + source_widget.width() // 2
        center_y = source_widget.y() + source_widget.height() // 2

        particles = []
        for _ in range(count):
            color = random.choice(confetti_colors)
            char = random.choice(confetti_chars)

            particle = QLabel(char, self)
            particle.setStyleSheet(f"color: {color}; font-size: 14px; background: transparent; border: none;")
            particle.setFixedSize(20, 20)
            particle.move(center_x, center_y)
            particle.show()

            # Animate particle outward
            dx = random.randint(-80, 80)
            dy = random.randint(-60, 60)

            anim = QPropertyAnimation(particle, b"pos")
            anim.setDuration(500)
            anim.setStartValue(particle.pos())
            from PyQt6.QtCore import QPoint
            anim.setEndValue(QPoint(center_x + dx, center_y + dy))
            anim.setEasingCurve(QEasingCurve.Type.OutQuad)

            # Fade out particle
            opacity = QGraphicsOpacityEffect(particle)
            particle.setGraphicsEffect(opacity)
            fade = QPropertyAnimation(opacity, b"opacity")
            fade.setDuration(500)
            fade.setStartValue(1.0)
            fade.setEndValue(0.0)
            fade.setEasingCurve(QEasingCurve.Type.InQuad)

            anim.start()
            fade.start()

            particles.append((particle, anim, fade))

        # Clean up particles after animation
        def cleanup():
            for p, a, f in particles:
                p.deleteLater()

        QTimer.singleShot(600, cleanup)

    def _task_depth(self, task: Task, by_id: Dict[str, Task]) -> int:
        """Nesting depth of a task (0 = top-level), walking the parent chain.

        Stops at any parent not in the active list (e.g. a completed parent),
        treating such a task as top-level. Cycle-guarded.
        """
        depth = 0
        seen = set()
        cur = task
        while cur.parent_task_id and cur.parent_task_id in by_id:
            if cur.parent_task_id in seen:
                break
            seen.add(cur.parent_task_id)
            cur = by_id[cur.parent_task_id]
            depth += 1
        return depth

    def _hidden_by_collapse(self, task: Task, by_id: Dict[str, Task]) -> bool:
        """True if any ancestor of this task is collapsed (so it should be folded away)."""
        seen = set()
        cur = task
        while cur.parent_task_id and cur.parent_task_id in by_id:
            if cur.parent_task_id in seen:
                break
            seen.add(cur.parent_task_id)
            parent = by_id[cur.parent_task_id]
            if parent.is_collapsed:
                return True
            cur = parent
        return False

    def _has_children(self, task: Task) -> bool:
        """True if any active task is a direct subtask of this one."""
        return any(t.parent_task_id == task.id for t in self.tasks)

    def _subtree_info(self, task: Task, by_id: Dict[str, Task]) -> tuple[int, int, bool, bool]:
        """Return (active_count, parked_count, has_ongoing, has_overtime) for a subtree.

        ``active_count`` counts non-stashed descendants (the rows you'd see when
        unfolded); ``parked_count`` counts stashed descendants (only visible with
        "show all"). ``has_overtime`` is True if any ongoing descendant is past
        its estimate (so a folded header can show red instead of green). Walks
        each task's ancestor chain to see if ``task`` is an ancestor; cycle-guarded
        and robust to non-contiguous subtrees.
        """
        count = 0
        parked = 0
        has_active = False
        has_overtime = False
        for t in self.tasks:
            if t.id == task.id:
                continue
            cur = t
            seen = set()
            is_descendant = False
            while cur.parent_task_id and cur.parent_task_id in by_id:
                if cur.parent_task_id in seen:
                    break
                seen.add(cur.parent_task_id)
                if cur.parent_task_id == task.id:
                    is_descendant = True
                    break
                cur = by_id[cur.parent_task_id]
            if is_descendant:
                if t.is_stashed:
                    parked += 1
                else:
                    count += 1
                if t.state == TaskState.ONGOING:
                    has_active = True
                    if t.elapsed_seconds >= t.estimated_seconds:
                        has_overtime = True
        return count, parked, has_active, has_overtime

    def _visible_tasks(self) -> List[Task]:
        """Return tasks that should be visible (respecting stash + collapse state)."""
        by_id = {t.id: t for t in self.tasks}
        result = []
        for t in self.tasks:
            if not self.show_all and t.is_stashed:
                continue
            if self._hidden_by_collapse(t, by_id):
                continue
            result.append(t)
        return result

    def _fade_out_and_remove(self, task_id: str):
        """Fade a single task widget out, then remove it from the layout."""
        if task_id not in self.task_widgets:
            return
        widget = self.task_widgets[task_id]

        def on_fade_finished():
            self.layout.removeWidget(widget)
            widget.deleteLater()
            # Guard against the widget having already been replaced/removed.
            if self.task_widgets.get(task_id) is widget:
                del self.task_widgets[task_id]
            self.adjustSize()

        self._fade_out_widget(widget, callback=on_fade_finished)

    def stash_task_widget(self, task_id: str):
        """Animate out and remove widget for a stashed task."""
        self._fade_out_and_remove(task_id)

    def toggle_collapse(self, task: Task) -> None:
        """Fold/unfold a task's subtree, animating only the affected rows.

        Only the descendant rows that appear/disappear are faded in/out — the
        rest of the overlay stays in place (no full rebuild/flash).
        """
        before = {t.id for t in self._visible_tasks()}
        task.is_collapsed = not task.is_collapsed
        visible = self._visible_tasks()
        after = {t.id for t in visible}

        if task.is_collapsed:
            # Fold: fade out the rows that just became hidden.
            for task_id in before - after:
                self._fade_out_and_remove(task_id)
        else:
            # Unfold: fade in the rows that just became visible, in display order
            # (insert_task derives each row's layout slot from the visible list).
            newly_visible = after - before
            for t in visible:
                if t.id in newly_visible and t.id not in self.task_widgets:
                    self.insert_task(t, 0)

        # Refresh remaining rows (parent triangle, focus, indentation).
        self.update_display()

    def rebuild_widgets(self):
        """Rebuild all widgets based on current show_all state."""
        # Remove all existing task widgets (keep show_all_label)
        for task_id, widget in list(self.task_widgets.items()):
            self.layout.removeWidget(widget)
            widget.deleteLater()
        self.task_widgets.clear()

        # Show/hide "All" indicator
        if self.show_all:
            self.show_all_label.show()
        else:
            self.show_all_label.hide()

        # Re-add widgets for visible tasks
        visible = self._visible_tasks()
        for i, task in enumerate(visible):
            is_focused = (i == self.focused_index)
            widget = TaskWidget(task, is_focused)
            if task.is_stashed:
                widget.setProperty("stashed", True)
            self.task_widgets[task.id] = widget
            self.layout.addWidget(widget)
            self._fade_in_widget(widget)

        # Clamp focus
        if visible:
            self.focused_index = max(0, min(self.focused_index, len(visible) - 1))
        else:
            self.focused_index = -1

        self.adjustSize()
        self.update_display()

    def _recently_active_ids(self, limit: int = 3) -> List[str]:
        """IDs of the most-recently-active tasks, ranked most-recent first.

        "Activity" is the latest work-interval start (falling back to started_at).
        Tasks never worked on are excluded.
        """
        scored: List[tuple[str, str]] = []  # (timestamp_iso, task_id)
        for t in self.tasks:
            ts: Optional[str] = None
            if t.work_intervals:
                starts = [iv["start"] for iv in t.work_intervals if iv.get("start")]
                if starts:
                    ts = max(starts)
            if ts is None:
                ts = t.started_at
            if ts:
                scored.append((ts, t.id))
        scored.sort(reverse=True)
        return [tid for _, tid in scored[:limit]]

    def _last_run_task_id(self) -> Optional[str]:
        """ID of the still-active task whose most recent run was the latest.

        Only considers work intervals that ran at least ``LAST_RUN_MIN_SECONDS``
        (a shorter run usually means "started then immediately paused"). Returns
        None if no task qualifies.
        """
        best_id: Optional[str] = None
        best_start: Optional[str] = None
        for t in self.tasks:
            for iv in t.work_intervals:
                start = iv.get("start")
                if not start:
                    continue
                try:
                    start_dt = datetime.fromisoformat(start)
                    end = iv.get("end")
                    end_dt = datetime.fromisoformat(end) if end else datetime.now()
                except (ValueError, TypeError):
                    continue
                if (end_dt - start_dt).total_seconds() < LAST_RUN_MIN_SECONDS:
                    continue
                if best_start is None or start > best_start:
                    best_start = start
                    best_id = t.id
        return best_id

    def _nearest_visible_ancestor(self, task: Task, by_id: Dict[str, Task],
                                  visible_ids: set) -> Optional[str]:
        """ID of the closest ancestor that is currently visible, or None."""
        seen = set()
        cur = task
        while cur.parent_task_id and cur.parent_task_id in by_id:
            if cur.parent_task_id in seen:
                break
            seen.add(cur.parent_task_id)
            parent = by_id[cur.parent_task_id]
            if parent.id in visible_ids:
                return parent.id
            cur = parent
        return None

    def _highlight_ids(self, by_id: Dict[str, Task], visible_ids: set) -> set:
        """Visible task IDs to highlight for recent activity.

        A recently-active task that is itself hidden inside a folded section
        maps to its nearest visible ancestor (the section header) instead.
        """
        highlight: set = set()
        for tid in self._recently_active_ids(limit=3):
            task = by_id.get(tid)
            if task is None:
                continue
            if tid in visible_ids:
                highlight.add(tid)
            else:
                anc = self._nearest_visible_ancestor(task, by_id, visible_ids)
                if anc:
                    highlight.add(anc)
        return highlight

    def update_display(self):
        """Update all task widgets."""
        by_id = {t.id: t for t in self.tasks}
        visible = self._visible_tasks()
        visible_ids = {t.id for t in visible}
        highlight_ids = self._highlight_ids(by_id, visible_ids)

        # Map the last-run task to a visible target (itself, or — if folded away —
        # its nearest visible section header), so the blue cue is always visible.
        last_run_id = self._last_run_task_id()
        last_run_target: Optional[str] = None
        if last_run_id is not None:
            if last_run_id in visible_ids:
                last_run_target = last_run_id
            elif last_run_id in by_id:
                last_run_target = self._nearest_visible_ancestor(
                    by_id[last_run_id], by_id, visible_ids
                )

        for i, task in enumerate(visible):
            if task.id in self.task_widgets:
                widget = self.task_widgets[task.id]
                widget.task = task
                widget.set_focused(i == self.focused_index)
                # Pass alarm status if app_controller is available
                if self.app_controller:
                    is_alarmed = self.app_controller.is_task_alarmed(task.id)
                    widget.set_alarmed(is_alarmed)
                # Indent proportional to nesting depth (level 2 deeper than level 1)
                widget.set_depth(self._task_depth(task, by_id))
                # Fold triangle + (when collapsed) subtask count and active-inside tint
                has_children = self._has_children(task)
                if has_children:
                    active_count, parked_count, has_active, has_overtime = self._subtree_info(task, by_id)
                else:
                    active_count, parked_count, has_active, has_overtime = 0, 0, False, False
                widget.set_fold_state(
                    has_children, task.is_collapsed,
                    has_active_hidden=has_active, hidden_count=active_count,
                    parked_count=parked_count, has_overtime_hidden=has_overtime,
                )
                # Recent-activity highlight (see _recently_active_ids)
                widget.set_recent(task.id in highlight_ids)
                # "Return here" cue on the single last-run task
                widget.set_last_run(task.id == last_run_target)
                # Apply stashed styling in show-all mode
                widget.setProperty("stashed", task.is_stashed)
                widget.update_display()

    def move_focus(self, direction: int):
        """
        Move focus up (-1) or down (+1).

        Args:
            direction: -1 for up, +1 for down
        """
        visible = self._visible_tasks()
        if not visible:
            return

        # Update focused index with wrap-around
        old_index = self.focused_index
        self.focused_index = (self.focused_index + direction) % len(visible)

        # Update widget displays
        if 0 <= old_index < len(visible):
            task_id = visible[old_index].id
            if task_id in self.task_widgets:
                self.task_widgets[task_id].set_focused(False)

        if 0 <= self.focused_index < len(visible):
            task_id = visible[self.focused_index].id
            if task_id in self.task_widgets:
                self.task_widgets[task_id].set_focused(True)

    def get_focused_task(self) -> Optional[Task]:
        """Get currently focused task."""
        visible = self._visible_tasks()
        if self.focused_index < 0 or self.focused_index >= len(visible):
            return None
        return visible[self.focused_index]

    def closeEvent(self, event):
        """Handle window close event - prevent accidental closes."""
        print("WARNING: Overlay window close event triggered!")
        event.ignore()  # Don't allow closing the main overlay

    def _fade_in_widget(self, widget: QWidget):
        """Fade in a widget."""
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)

        animation = QPropertyAnimation(effect, b"opacity")
        animation.setDuration(FADE_IN_DURATION_MS)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        animation.start()

        # Keep reference to prevent garbage collection
        widget._fade_animation = animation

    def _fade_out_widget(self, widget: QWidget, callback=None):
        """Fade out a widget."""
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)

        animation = QPropertyAnimation(effect, b"opacity")
        animation.setDuration(FADE_OUT_DURATION_MS)
        animation.setStartValue(1.0)
        animation.setEndValue(0.0)
        animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

        if callback:
            animation.finished.connect(callback)

        animation.start()

        # Keep reference to prevent garbage collection
        widget._fade_animation = animation
