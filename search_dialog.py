"""Centered fuzzy-search popup for jumping to a task (⌃⌥⌘/)."""

from typing import List, Tuple
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QKeyEvent

from models import Task


class SearchDialog(QDialog):
    """A mid-screen popup to search active tasks by name and jump to one."""

    # Emitted with the selected task's id.
    task_selected = pyqtSignal(str)

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
        self.setStyleSheet("""
            QDialog {
                background-color: white;
                border: 2px solid #2196F3;
                border-radius: 10px;
            }
            QLineEdit {
                border: 1px solid #CCCCCC;
                border-radius: 6px;
                padding: 8px;
                font-size: 16px;
            }
            QLineEdit:focus {
                border: 2px solid #2196F3;
            }
            QListWidget {
                border: none;
                font-size: 14px;
            }
            QListWidget::item {
                padding: 6px;
                border-radius: 4px;
            }
            QListWidget::item:selected {
                background-color: #E3F2FD;
                color: #000000;
            }
        """)
        self.setFixedWidth(480)

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search tasks…")
        self.search_input.textChanged.connect(self._refilter)
        layout.addWidget(self.search_input)

        self.results = QListWidget()
        self.results.setFont(QFont("Menlo", 13))
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
        query = self.search_input.text().strip().lower()
        self.results.clear()
        for name, task_id in self._tasks:
            if query and query not in name.lower():
                continue
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, task_id)
            self.results.addItem(item)
        if self.results.count() > 0:
            self.results.setCurrentRow(0)

    def _choose(self) -> None:
        """Emit the currently-highlighted task and close."""
        item = self.results.currentItem()
        if item is None:
            return
        task_id = item.data(Qt.ItemDataRole.UserRole)
        self.task_selected.emit(task_id)
        self.accept()

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._choose()
        elif key == Qt.Key.Key_Escape:
            self.reject()
        elif key == Qt.Key.Key_Down:
            row = min(self.results.currentRow() + 1, self.results.count() - 1)
            self.results.setCurrentRow(max(row, 0))
        elif key == Qt.Key.Key_Up:
            row = max(self.results.currentRow() - 1, 0)
            self.results.setCurrentRow(row)
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
