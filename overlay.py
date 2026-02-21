"""Main overlay window for etime application."""

from typing import List, Optional, Dict
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
    FONT_FAMILY_MONO, FONT_SIZE,
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
        self.is_subtask = False  # Track indentation

        # Create layout
        layout = QHBoxLayout()
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        # Focus indicator
        self.focus_label = QLabel(FOCUS_INDICATOR if is_focused else NO_FOCUS_INDICATOR)
        self.focus_label.setFixedWidth(20)
        layout.addWidget(self.focus_label)

        # Task name (allow wrapping to 2 lines)
        self.name_label = QLabel(task.name)
        self.name_label.setMinimumWidth(150)
        self.name_label.setMaximumWidth(350)
        self.name_label.setWordWrap(True)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.name_label, stretch=1)

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

        # Check if task is in ambitious state (ongoing, has ambitious target, within it)
        in_ambitious = (
            self.task.state == TaskState.ONGOING
            and self.task.ambitious_seconds is not None
            and self.task.elapsed_seconds < self.task.ambitious_seconds
        )

        # Determine text color
        if self.task.state == TaskState.PAUSED:
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

        # Apply styling
        bg_color = COLOR_FOCUSED if self.is_focused else "#FFFFFF"  # White for non-focused (makes corners visible)
        self.setStyleSheet(f"""
            TaskWidget {{
                background-color: {bg_color};
                border-radius: 6px;
                border: 1px solid #DDDDDD;
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

    def set_indent(self, indent: bool):
        """Set subtask indentation and refresh display."""
        if self.is_subtask != indent:
            self.is_subtask = indent
            layout = self.layout()
            left = 28 if indent else 8  # Extra indent for subtasks
            layout.setContentsMargins(left, 4, 8, 4)
            self.update_display()

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

        # Window styling
        self.setStyleSheet(f"""
            OverlayWindow {{
                background-color: #FFE0B2;  /* Light orange */
                border: 2px solid #FF9800;  /* Darker orange border */
                border-radius: 8px;
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

    def _populate_tasks(self):
        """Populate window with existing tasks."""
        for i, task in enumerate(self.tasks):
            self._add_task_widget(task, i == self.focused_index, animate=False)

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
        """
        is_focused = index == self.focused_index

        widget = TaskWidget(task, is_focused)
        self.task_widgets[task.id] = widget
        self.layout.insertWidget(index, widget)

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

    def update_display(self):
        """Update all task widgets."""
        active_task_ids = {t.id for t in self.tasks}
        for i, task in enumerate(self.tasks):
            if task.id in self.task_widgets:
                widget = self.task_widgets[task.id]
                widget.task = task
                widget.set_focused(i == self.focused_index)
                # Pass alarm status if app_controller is available
                if self.app_controller:
                    is_alarmed = self.app_controller.is_task_alarmed(task.id)
                    widget.set_alarmed(is_alarmed)
                # Indent if this is an active subtask (parent still in active list)
                is_subtask = bool(
                    task.parent_task_id and task.parent_task_id in active_task_ids
                )
                widget.set_indent(is_subtask)
                widget.update_display()

    def move_focus(self, direction: int):
        """
        Move focus up (-1) or down (+1).

        Args:
            direction: -1 for up, +1 for down
        """
        if not self.tasks:
            return

        # Update focused index with wrap-around
        old_index = self.focused_index
        self.focused_index = (self.focused_index + direction) % len(self.tasks)

        # Update widget displays
        if old_index >= 0 and old_index < len(self.tasks):
            task_id = self.tasks[old_index].id
            if task_id in self.task_widgets:
                self.task_widgets[task_id].set_focused(False)

        if self.focused_index >= 0 and self.focused_index < len(self.tasks):
            task_id = self.tasks[self.focused_index].id
            if task_id in self.task_widgets:
                self.task_widgets[task_id].set_focused(True)

    def get_focused_task(self) -> Optional[Task]:
        """Get currently focused task."""
        if self.focused_index < 0 or self.focused_index >= len(self.tasks):
            return None
        return self.tasks[self.focused_index]

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
