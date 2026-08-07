"""New task dialog for etime application."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QSpinBox, QWidget
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QKeyEvent

from config import (
    DEFAULT_TASK_MINUTES, MIN_TASK_MINUTES, MAX_TASK_MINUTES,
    FONT_SIZE
)


class TaskDialog(QDialog):
    """Dialog for creating a new task."""

    # Signal emitted when task is submitted (name, minutes, ambitious_minutes, parent_task_id)
    # ambitious_minutes = 0 means None (no ambitious target)
    # parent_task_id = "" means no parent (top-level task)
    task_submitted = pyqtSignal(str, int, int, str)

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

        # Styling
        self.setStyleSheet("""
            QDialog {
                background-color: white;
                border: 2px solid #2196F3;
                border-radius: 8px;
            }
            QLabel {
                color: #333333;
            }
            QLineEdit, QSpinBox {
                border: 1px solid #CCCCCC;
                border-radius: 4px;
                padding: 6px;
                font-size: 14px;
            }
            QLineEdit:focus, QSpinBox:focus {
                border: 2px solid #2196F3;
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
        title_font = QFont()
        title_font.setPointSize(16)
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

        # Time field
        time_layout = QHBoxLayout()
        time_label = QLabel("Time:")
        time_label.setFixedWidth(80)
        self.time_input = QSpinBox()
        self.time_input.setMinimum(MIN_TASK_MINUTES)
        self.time_input.setMaximum(MAX_TASK_MINUTES)
        self.time_input.setValue(DEFAULT_TASK_MINUTES)
        self.time_input.setSuffix(" min")
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
        instruction = QLabel("Enter to start  |  Ambitious = stretch goal")
        instruction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        instruction.setStyleSheet("color: #666666; font-size: 11px;")
        layout.addWidget(instruction)

        self.setLayout(layout)

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
        print(f"TaskDialog submitting: name='{name}', minutes={minutes}, ambitious={ambitious_minutes}, parent={parent_id or 'none'}")

        # Emit signal (ambitious_minutes=0 means None, parent_id="" means top-level)
        self.task_submitted.emit(name, minutes, ambitious_minutes, parent_id)

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

    def prefill(self, name: str, minutes: int, ambitious_minutes: int) -> None:
        """Pre-fill the fields (e.g. to restore text after undoing a creation)."""
        self.name_input.setText(name)
        self.time_input.setValue(minutes)
        self.ambitious_input.setText(str(ambitious_minutes) if ambitious_minutes > 0 else "")

    def reset(self):
        """Reset dialog to default state."""
        self.name_input.clear()
        self.time_input.setValue(DEFAULT_TASK_MINUTES)
        self.ambitious_input.clear()
        self.error_label.setVisible(False)
        self.parent_input.clear()
        self.parent_container.setVisible(False)
        self._parent_task_id = ""
        self._parent_name = ""
        self._available_parents = []
