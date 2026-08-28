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

# Colors (hex codes) — "warm paper / study" palette to match the brown-on-grey
# clock favicon. Text colors keep their original semantic names.
COLOR_FOCUSED = "#EFE3C8"  # Warm parchment highlight behind the focused task
COLOR_OVERTIME = "#B23A2E"  # Brick red text for overtime tasks
COLOR_PAUSED = "#A79E8E"  # Muted taupe text for paused tasks
COLOR_NORMAL = "#2E2A24"  # Near-black espresso text for normal tasks
COLOR_UNFOCUSED = "#8A8175"  # Soft stone text for non-focused ongoing tasks
COLOR_AMBITIOUS = "#4F7A55"  # Sage green text for tasks within ambitious time
COLOR_BACKGROUND = "#FFFFFF"  # White background

# Surfaces (window + task cards)
COLOR_WINDOW_BG = "#F4EFE6"      # Warm cream window backdrop
COLOR_WINDOW_BORDER = "#B89B72"  # Muted brown window border
COLOR_CARD_BG = "#FCFAF5"        # Off-white card
COLOR_CARD_BORDER = "#E4DBCA"    # Faint sand card border
COLOR_FOCUSED_BORDER = "#B89B72" # Brown border for the focused card
COLOR_RECENT = "#D9A441"         # Warm gold accent for recently-active tasks
COLOR_LAST_RUN_BG = "#CFE1F2"    # Light blue fill for the last-run "return here" task

# The last-run task must have run at least this long to be highlighted (a shorter
# run usually means you started it and immediately paused).
LAST_RUN_MIN_SECONDS = 3.0

# Sounds
AMBITIOUS_SOUND_FILE = ETIME_DIR / "ambitious.aiff"

# Fonts
FONT_FAMILY_MONO = "Menlo"  # Monospace font for time display (fixes SF Mono warning)
FONT_FAMILY_SERIF = "Georgia"  # Fresh serif for task names / headers
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
DETERRED_FILE = Path.home() / "Dev" / "DistractionCount" / "deterred_count.txt"

# Hotkey definitions (macOS virtual key codes)
KEY_N = 45    # N key - New task
KEY_P = 35    # P key - Toggle start/pause
KEY_C = 8     # C key - Complete task
KEY_Q = 12    # Q key - Dismiss alarm
KEY_S = 1     # S key - Minimize/show overlay
KEY_U = 32    # U key - Undo complete
KEY_H = 4     # H key - Help menu
KEY_T = 17    # T key - Toggle subtask
KEY_F = 3     # F key - Fold/unfold subtasks of focused task
KEY_UP = 126  # Up arrow - Focus up
KEY_DOWN = 125  # Down arrow - Focus down
KEY_A = 0       # A key - Toggle show all (stashed tasks)
KEY_LEFT = 123  # Left arrow - Unstash (with Shift)
KEY_RIGHT = 124 # Right arrow - Stash (with Shift)
KEY_G = 5       # G key - Log deterred distraction
KEY_SLASH = 44  # / key - Search tasks
KEY_E = 14      # E key - Edit focused task's name
KEY_EQUAL = 24  # = / + key - Add elapsed minutes to focused task
KEY_MINUS = 27  # - / _ key - Remove elapsed minutes from focused task
