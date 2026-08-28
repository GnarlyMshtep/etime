"""Small centered dialog to rename a task in place (⌃⌥⌘E)."""

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QKeyEvent

from config import (
    FONT_FAMILY_SERIF, COLOR_WINDOW_BG, COLOR_WINDOW_BORDER,
)


class RenameDialog(QDialog):
    """A minimal popup with a single text field to rename the focused task."""

    # Emitted with the new (non-empty, stripped) name.
    name_submitted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_window()
        self._setup_ui()

    def _setup_window(self):
        self.setWindowTitle("Rename Task")
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
            QLabel {{
                color: #2E2A24;
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
        """)
        self.setFixedWidth(440)

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("Rename task")
        title_font = QFont(FONT_FAMILY_SERIF)
        title_font.setPointSize(15)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        self.name_input = QLineEdit()
        self.name_input.setFont(QFont(FONT_FAMILY_SERIF, 15))
        layout.addWidget(self.name_input)

        hint = QLabel("Enter to save  ·  Esc to cancel")
        hint.setStyleSheet("color: #8A8175; font-size: 11px;")
        layout.addWidget(hint)

        self.setLayout(layout)

    def open_for(self, current_name: str) -> None:
        """Show the dialog pre-filled with ``current_name`` and select it all."""
        self.name_input.setText(current_name)
        self.show()
        self.raise_()
        self.activateWindow()
        self.name_input.setFocus()
        self.name_input.selectAll()

    def _submit(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            # Empty name is a no-op cancel (don't wipe the task's name).
            self.reject()
            return
        self.name_submitted.emit(name)
        self.accept()

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._submit()
        elif key == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        screen = self.screen().availableGeometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 3
        self.move(x, y)
