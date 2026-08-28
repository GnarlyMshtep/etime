"""Small centered dialog to add or remove elapsed minutes on a task (⌃⌥⌘+ / ⌃⌥⌘−).

Adding backdates the minutes to the [now - N, now] window; removing trims that
much off the most recent end of the timeline (capped at time actually spent).
See Task.add_manual_minutes / Task.subtract_manual_minutes.
"""

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QKeyEvent, QIntValidator

from config import (
    FONT_FAMILY_SERIF, COLOR_WINDOW_BG, COLOR_WINDOW_BORDER,
    MIN_TASK_MINUTES, MAX_TASK_MINUTES,
)


class TimeAdjustDialog(QDialog):
    """A minimal popup with a single numeric field to adjust a task's time."""

    # Emitted with (minutes, adding): adding True = add time, False = remove time.
    minutes_submitted = pyqtSignal(int, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._adding = True
        self._setup_window()
        self._setup_ui()

    def _setup_window(self):
        self.setWindowTitle("Adjust Time")
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

        self.title = QLabel("Adjust time")
        title_font = QFont(FONT_FAMILY_SERIF)
        title_font.setPointSize(15)
        title_font.setBold(True)
        self.title.setFont(title_font)
        layout.addWidget(self.title)

        self.minutes_input = QLineEdit()
        self.minutes_input.setFont(QFont(FONT_FAMILY_SERIF, 15))
        self.minutes_input.setValidator(
            QIntValidator(MIN_TASK_MINUTES, MAX_TASK_MINUTES)
        )
        self.minutes_input.setPlaceholderText("minutes")
        layout.addWidget(self.minutes_input)

        self.hint = QLabel("")
        self.hint.setStyleSheet("color: #8A8175; font-size: 11px;")
        layout.addWidget(self.hint)

        self.setLayout(layout)

    def open_for(self, task_name: str, adding: bool) -> None:
        """Show the dialog for ``task_name`` in add (``adding``) or remove mode."""
        self._adding = adding
        if adding:
            self.title.setText(f"Add time to “{task_name}”")
            self.hint.setText("Counts toward the last N minutes  ·  Enter to add  ·  Esc to cancel")
        else:
            self.title.setText(f"Remove time from “{task_name}”")
            self.hint.setText("Trims the most recent time (capped at time spent)  ·  Enter to remove  ·  Esc to cancel")
        self.minutes_input.clear()
        self.show()
        self.raise_()
        self.activateWindow()
        self.minutes_input.setFocus()

    def _submit(self) -> None:
        text = self.minutes_input.text().strip()
        if not text:
            # Empty is a no-op cancel (don't adjust by 0 / raise an error).
            self.reject()
            return
        try:
            minutes = int(text)
        except ValueError:
            self.reject()
            return
        if minutes <= 0:
            self.reject()
            return
        self.minutes_submitted.emit(minutes, self._adding)
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
