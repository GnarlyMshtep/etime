"""Centered fuzzy-search popup for jumping to a task (⌃⌥⌘/)."""

from typing import List, Tuple
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem
)
from PyQt6.QtCore import Qt, QEvent, pyqtSignal
from PyQt6.QtGui import QFont, QKeyEvent

from models import Task
from config import (
    FONT_FAMILY_SERIF, COLOR_WINDOW_BG, COLOR_WINDOW_BORDER, COLOR_FOCUSED,
)


class SearchDialog(QDialog):
    """A mid-screen popup to search active tasks by name and jump to one."""

    # Emitted with the selected task's id.
    task_selected = pyqtSignal(str)
    # Emitted with the typed text when the user asks to create a new task
    # (Enter with no matching result).
    create_task_requested = pyqtSignal(str)

    # Sentinel stored on the synthetic "create new task" row.
    _CREATE_SENTINEL = "__create__"

    def __init__(self, parent=None):
        super().__init__(parent)
        # (name, id) of every searchable task, set via set_tasks().
        self._tasks: List[Tuple[str, str]] = []
        self._setup_window()
        self._setup_ui()

    def _setup_window(self):
        self.setWindowTitle("Search Tasks")
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Dialog
        )
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {COLOR_WINDOW_BG};
                border: 2px solid {COLOR_WINDOW_BORDER};
                border-radius: 14px;
            }}
            QLineEdit {{
                background-color: #FCFAF5;
                border: 1px solid #D6CCB8;
                border-radius: 8px;
                padding: 9px;
                font-size: 16px;
                color: #2E2A24;
            }}
            QLineEdit:focus {{
                border: 2px solid {COLOR_WINDOW_BORDER};
            }}
            QListWidget {{
                background-color: transparent;
                border: none;
                font-size: 15px;
                color: #2E2A24;
            }}
            QListWidget::item {{
                padding: 7px;
                border-radius: 6px;
            }}
            QListWidget::item:selected {{
                background-color: {COLOR_FOCUSED};
                color: #2E2A24;
            }}
        """)
        self.setFixedWidth(480)

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search tasks…")
        self.search_input.setFont(QFont(FONT_FAMILY_SERIF, 15))
        self.search_input.textChanged.connect(self._refilter)
        # Keep focus in the text box but route arrows/Enter to the list.
        self.search_input.installEventFilter(self)
        layout.addWidget(self.search_input)

        self.results = QListWidget()
        self.results.setFont(QFont(FONT_FAMILY_SERIF, 14))
        self.results.itemActivated.connect(lambda _: self._choose())
        self.results.itemClicked.connect(lambda _: self._choose())
        layout.addWidget(self.results)

        self.setLayout(layout)

    def set_tasks(self, tasks: List[Task]) -> None:
        """Load the searchable task list and reset the filter."""
        self._tasks = [(t.name, t.id) for t in tasks]
        self.search_input.clear()
        self._refilter("")

    def _refilter(self, text: str = "") -> None:
        """Repopulate the result list, filtering by substring match."""
        raw = self.search_input.text().strip()
        query = raw.lower()
        self.results.clear()
        for name, task_id in self._tasks:
            if query and query not in name.lower():
                continue
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, task_id)
            self.results.addItem(item)
        # No match but something typed → offer to create a new task with that name.
        if self.results.count() == 0 and raw:
            item = QListWidgetItem(f"＋  Create new task “{raw}”")
            item.setData(Qt.ItemDataRole.UserRole, self._CREATE_SENTINEL)
            self.results.addItem(item)
        if self.results.count() > 0:
            self.results.setCurrentRow(0)

    def _choose(self) -> None:
        """Emit the currently-highlighted task (or a create request) and close."""
        item = self.results.currentItem()
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if data == self._CREATE_SENTINEL:
            self.create_task_requested.emit(self.search_input.text().strip())
        else:
            self.task_selected.emit(data)
        self.accept()

    def _move_selection(self, delta: int) -> None:
        """Move the highlighted row by ``delta``, clamped to the list bounds."""
        count = self.results.count()
        if count == 0:
            return
        row = self.results.currentRow()
        if row < 0:
            row = 0
        row = max(0, min(row + delta, count - 1))
        self.results.setCurrentRow(row)

    def eventFilter(self, obj, event):
        """Route Up/Down/Enter from the search box to the results list.

        The text box keeps focus (so typing works), but arrow keys navigate the
        list instead of moving the text cursor.
        """
        if obj is self.search_input and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Down:
                self._move_selection(1)
                return True
            if key == Qt.Key.Key_Up:
                self._move_selection(-1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._choose()
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._choose()
        elif key == Qt.Key.Key_Escape:
            self.reject()
        elif key == Qt.Key.Key_Down:
            self._move_selection(1)
        elif key == Qt.Key.Key_Up:
            self._move_selection(-1)
        else:
            super().keyPressEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        # Center on screen.
        screen = self.screen().availableGeometry()
        self.setFixedHeight(360)
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 3
        self.move(x, y)
        self.search_input.setFocus()
