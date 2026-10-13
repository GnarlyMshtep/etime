"""New task dialog for etime application."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QSpinBox, QWidget
)
from PyQt6.QtCore import Qt, pyqtSignal
from datetime import datetime
from PyQt6.QtGui import QFont, QKeyEvent

from time_range import parse_time_range

from config import (
    DEFAULT_TASK_MINUTES, MIN_TASK_MINUTES, MAX_TASK_MINUTES,
    FONT_SIZE, FONT_FAMILY_SERIF
)


class TaskDialog(QDialog):
    """Dialog for creating a new task."""

    # Signal emitted when task is submitted
    # (name, minutes, ambitious_minutes, parent_task_id, start_iso, end_iso)
    # ambitious_minutes = 0 means None (no ambitious target)
    # parent_task_id = "" means no parent (top-level task)
    # start_iso/end_iso = "" means a live task that starts now; otherwise the task
    # is created already paused with that stretch of work already on the clock.
    task_submitted = pyqtSignal(str, int, int, str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_window()
        self._setup_ui()

    def _setup_window(self):
        """Configure dialog properties."""
        self.setWindowTitle("New Task")
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Dialog
        )

        # Styling — warm cream palette matching the overlay
        self.setStyleSheet("""
            QDialog {
                background-color: #F4EFE6;
                border: 2px solid #B89B72;
                border-radius: 12px;
            }
            QLabel {
                color: #2E2A24;
            }
            QLineEdit, QSpinBox {
                background-color: #FCFAF5;
                border: 1px solid #D6CCB8;
                border-radius: 6px;
                padding: 6px;
                font-size: 14px;
                color: #2E2A24;
            }
            QLineEdit:focus, QSpinBox:focus {
                border: 2px solid #B89B72;
            }
        """)

        self.setFixedWidth(350)

    def _setup_ui(self):
        """Setup UI elements."""
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Title
        title = QLabel("New Task")
        title_font = QFont(FONT_FAMILY_SERIF)
        title_font.setPointSize(17)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Name field
        name_layout = QHBoxLayout()
        name_label = QLabel("Name:")
        name_label.setFixedWidth(80)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g., paper-exp")
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.name_input)
        layout.addLayout(name_layout)

        # When field — blank means "starting now", which is the usual case.
        # Filling it in backdates the task instead of starting a timer.
        when_layout = QHBoxLayout()
        when_label = QLabel("When:")
        when_label.setFixedWidth(80)
        self.when_input = QLineEdit()
        self.when_input.setPlaceholderText("now  —  or 2:30-4, 9/26 9-10:30")
        self.when_input.textChanged.connect(self._on_when_changed)
        when_layout.addWidget(when_label)
        when_layout.addWidget(self.when_input)
        layout.addLayout(when_layout)

        # Echoes back how the When text was actually read, because "2:30-4" involves
        # guessing which 2:30 you meant. Seeing it beats trusting it.
        self.when_preview = QLabel("")
        self.when_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.when_preview.setStyleSheet("color: #4F7A55; font-size: 11px;")
        self.when_preview.setVisible(False)
        layout.addWidget(self.when_preview)

        # Time field
        time_layout = QHBoxLayout()
        time_label = QLabel("Time:")
        time_label.setFixedWidth(80)
        self.time_input = QSpinBox()
        self.time_input.setMinimum(MIN_TASK_MINUTES)
        self.time_input.setMaximum(MAX_TASK_MINUTES)
        self.time_input.setValue(DEFAULT_TASK_MINUTES)
        self.time_input.setSuffix(" min")
        self.time_input.valueChanged.connect(lambda _: setattr(self, "_estimate_touched", True))
        time_layout.addWidget(time_label)
        time_layout.addWidget(self.time_input)
        layout.addLayout(time_layout)

        # Ambitious time field (QLineEdit so user can leave empty = no target)
        ambitious_layout = QHBoxLayout()
        ambitious_label = QLabel("Ambitious:")
        ambitious_label.setFixedWidth(80)
        self.ambitious_input = QLineEdit()
        self.ambitious_input.setPlaceholderText("optional mins")
        ambitious_layout.addWidget(ambitious_label)
        ambitious_layout.addWidget(self.ambitious_input)
        layout.addLayout(ambitious_layout)

        # Subtask parent field (hidden when no parent context)
        self.parent_layout = QHBoxLayout()
        self.parent_label = QLabel("Parent:")
        self.parent_label.setFixedWidth(80)
        self.parent_input = QLineEdit()
        self.parent_input.setPlaceholderText("none")
        self.parent_layout.addWidget(self.parent_label)
        self.parent_layout.addWidget(self.parent_input)
        self.parent_container = QWidget()
        self.parent_container.setLayout(self.parent_layout)
        self.parent_container.setVisible(False)
        self._parent_task_id = ""
        self._parent_name = ""  # Name pre-filled for the context parent
        self._when_range = None      # parsed When field, or None for "starting now"
        self._estimate_touched = False  # True once you've set the estimate by hand
        # (name, id) of every active task, so a manually-typed parent resolves.
        self._available_parents: list[tuple[str, str]] = []
        layout.addWidget(self.parent_container)

        # Error label (hidden by default)
        self.error_label = QLabel("")
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_label.setStyleSheet("color: #D32F2F; font-size: 12px;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        # Instruction label
        instruction = QLabel("Enter to start  |  When = backdate it, paused")
        instruction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        instruction.setStyleSheet("color: #666666; font-size: 11px;")
        layout.addWidget(instruction)

        self.setLayout(layout)

    def _on_when_changed(self, text: str) -> None:
        """Show how the When text parsed, and size the estimate to match."""
        if not text.strip():
            self.when_preview.setVisible(False)
            self._when_range = None
            return
        try:
            block = parse_time_range(text)
        except ValueError as exc:
            self.when_preview.setText(str(exc))
            self.when_preview.setStyleSheet("color: #B23A2E; font-size: 11px;")
            self.when_preview.setVisible(True)
            self._when_range = None
            return

        self._when_range = block
        note = "  — that's in the future" if block.end > datetime.now() else ""
        self.when_preview.setText(block.describe() + note)
        self.when_preview.setStyleSheet(
            f"color: {'#B89B72' if note else '#4F7A55'}; font-size: 11px;")
        self.when_preview.setVisible(True)

        # Size the estimate to the block unless you've already set one yourself.
        # A backfilled meeting isn't an estimate you missed, so the default
        # shouldn't make it look like one.
        if not self._estimate_touched:
            clamped = max(MIN_TASK_MINUTES, min(MAX_TASK_MINUTES, block.minutes))
            self.time_input.blockSignals(True)
            self.time_input.setValue(clamped)
            self.time_input.blockSignals(False)

    def keyPressEvent(self, event: QKeyEvent):
        """Handle keyboard events."""
        key = event.key()

        if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            # Submit the task
            self._submit()
        elif key == Qt.Key.Key_Escape:
            # Cancel
            self.reject()
        else:
            # Default handling
            super().keyPressEvent(event)

    def showEvent(self, event):
        """Called when dialog is shown."""
        super().showEvent(event)

        # Center on screen
        screen = self.screen().availableGeometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)

        # Focus on name input
        self.name_input.setFocus()
        self.name_input.selectAll()

    def _submit(self):
        """Submit the task."""
        name = self.name_input.text().strip()

        if not name:
            print("Empty task name, not submitting")
            return

        minutes = self.time_input.value()

        # Validate timer length
        if minutes <= 0:
            print("ERROR: Timer length must be > 0 minutes")
            return

        # Parse ambitious time (empty string = None/0)
        ambitious_text = self.ambitious_input.text().strip()
        if ambitious_text == "":
            ambitious_minutes = 0
        else:
            try:
                ambitious_minutes = int(ambitious_text)
            except ValueError:
                self.error_label.setText("Ambitious time must be a number")
                self.error_label.setVisible(True)
                print(f"ERROR: Invalid ambitious time: '{ambitious_text}'")
                return

            if ambitious_minutes < 0:
                self.error_label.setText("Ambitious time must be positive")
                self.error_label.setVisible(True)
                return

        # Validate ambitious <= estimated (when ambitious is set)
        if ambitious_minutes > 0 and ambitious_minutes > minutes:
            self.error_label.setText("Ambitious time must be <= estimated time")
            self.error_label.setVisible(True)
            print(f"ERROR: Ambitious ({ambitious_minutes}m) > estimated ({minutes}m)")
            return

        self.error_label.setVisible(False)

        # Determine parent task ID. An empty field = top-level task. If the text
        # is unchanged from the pre-filled context parent, use that id directly;
        # otherwise resolve the typed name against the active task list.
        parent_text = self.parent_input.text().strip()
        if not parent_text:
            parent_id = ""
        elif parent_text == self._parent_name and self._parent_task_id:
            parent_id = self._parent_task_id
        else:
            matches = [
                tid for (nm, tid) in self._available_parents
                if nm.strip().lower() == parent_text.lower()
            ]
            if len(matches) == 0:
                self.error_label.setText(f"No active task named '{parent_text}'")
                self.error_label.setVisible(True)
                print(f"ERROR: No parent task named '{parent_text}'")
                return
            if len(matches) > 1:
                self.error_label.setText(f"'{parent_text}' matches multiple tasks")
                self.error_label.setVisible(True)
                print(f"ERROR: Ambiguous parent name '{parent_text}'")
                return
            parent_id = matches[0]
        # Re-parse rather than trusting the cached value: the preview could be
        # stale if the text changed without the signal landing.
        try:
            block = parse_time_range(self.when_input.text())
        except ValueError as exc:
            self.error_label.setText(str(exc))
            self.error_label.setVisible(True)
            return
        start_iso = block.start.isoformat() if block else ""
        end_iso = block.end.isoformat() if block else ""

        when_str = f", when={block.describe()}" if block else ""
        print(f"TaskDialog submitting: name='{name}', minutes={minutes}, "
              f"ambitious={ambitious_minutes}, parent={parent_id or 'none'}{when_str}")

        # Emit signal (ambitious_minutes=0 means None, parent_id="" means top-level,
        # empty start/end means start it now)
        self.task_submitted.emit(name, minutes, ambitious_minutes, parent_id,
                                 start_iso, end_iso)

        # Close dialog
        self.accept()
        print("TaskDialog closed")

    def set_parent_context(self, parent_name: str, parent_task_id: str) -> None:
        """Set the parent task context for the subtask field."""
        self._parent_task_id = parent_task_id
        self._parent_name = parent_name or ""
        if parent_name and parent_task_id:
            self.parent_input.setText(parent_name)
            self.parent_container.setVisible(True)
        else:
            self.parent_container.setVisible(False)
            self._parent_task_id = ""
            self._parent_name = ""

    def set_available_parents(self, parents: list[tuple[str, str]]) -> None:
        """Provide (name, id) of active tasks so a typed parent name resolves."""
        self._available_parents = parents

    def prefill(self, name: str, minutes: int, ambitious_minutes: int, when: str = "") -> None:
        """Pre-fill the fields (e.g. to restore text after undoing a creation)."""
        self.name_input.setText(name)
        self.time_input.setValue(minutes)
        self.ambitious_input.setText(str(ambitious_minutes) if ambitious_minutes > 0 else "")
        self.when_input.setText(when)

    def reset(self):
        """Reset dialog to default state."""
        self.name_input.clear()
        self.time_input.setValue(DEFAULT_TASK_MINUTES)
        self.ambitious_input.clear()
        self.when_input.clear()
        self.when_preview.setVisible(False)
        self._when_range = None
        self._estimate_touched = False
        self.error_label.setVisible(False)
        self.parent_input.clear()
        self.parent_container.setVisible(False)
        self._parent_task_id = ""
        self._parent_name = ""
        self._available_parents = []
