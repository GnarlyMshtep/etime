"""Configuration constants for etime application."""

from pathlib import Path

# Directories and files
ETIME_DIR = Path.home() / ".etime"
ACTIVE_FILE = ETIME_DIR / "active.json"
HISTORY_FILE = ETIME_DIR / "history.jsonl"
ALARM_FILE = ETIME_DIR / "alarm.aiff"
SUCCESS_SOUND_FILE = ETIME_DIR / "success.aiff"

# Timer constants
TIMER_INTERVAL_MS = 100  # 100ms tick for smooth updates
TIMER_INCREMENT_S = 0.1  # 0.1 second increment per tick

# Window positioning
WINDOW_MARGIN_X = 10  # Small margin from edge
WINDOW_MARGIN_Y = 10  # Small margin from top

# Colors (hex codes)
COLOR_FOCUSED = "#E3F2FD"  # Light blue background for focused task
COLOR_OVERTIME = "#D32F2F"  # Red text for overtime tasks
COLOR_PAUSED = "#999999"  # Gray text for paused tasks
COLOR_NORMAL = "#000000"  # Black text for normal tasks
COLOR_UNFOCUSED = "#666666"  # Gray text for non-focused ongoing tasks
COLOR_AMBITIOUS = "#2E7D32"  # Green text for tasks within ambitious time
COLOR_BACKGROUND = "#FFFFFF"  # White background

# Sounds
AMBITIOUS_SOUND_FILE = ETIME_DIR / "ambitious.aiff"

# Fonts
FONT_FAMILY_MONO = "Menlo"  # Monospace font for time display (fixes SF Mono warning)
FONT_SIZE = 14

# Focus indicator
FOCUS_INDICATOR = "►"  # U+25BA
NO_FOCUS_INDICATOR = " "

# Animation durations
FADE_IN_DURATION_MS = 300
FADE_OUT_DURATION_MS = 300

# Task defaults
DEFAULT_TASK_MINUTES = 15
MIN_TASK_MINUTES = 1
MAX_TASK_MINUTES = 999

# Dashboard
DASHBOARD_PORT = 5173
DASHBOARD_PID_FILE = ETIME_DIR / "dashboard.pid"
DISTRACTION_FILE = Path.home() / "Dev" / "DistractionCount" / "distraction_count.txt"

# Hotkey definitions (macOS virtual key codes)
KEY_N = 45    # N key - New task
KEY_P = 35    # P key - Toggle start/pause
KEY_C = 8     # C key - Complete task
KEY_Q = 12    # Q key - Dismiss alarm
KEY_S = 1     # S key - Minimize/show overlay
KEY_UP = 126  # Up arrow - Focus up
KEY_DOWN = 125  # Down arrow - Focus down
