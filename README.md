# etime (Evolved Timer)

A macOS floating overlay timer app for productivity tracking. Track time spent on concurrent tasks with estimated vs actual time tracking.

## Features

- **Floating overlay window** - Always on top at top-right, shows all active tasks
- **Global hotkeys** - Control everything without switching windows
- **Auto-start tasks** - New tasks start immediately
- **Ambitious time targets** - Optional stretch goals with green visual state and confetti on completion
- **Overtime detection** - Visual warnings (red text) when tasks exceed estimates
- **Looping alarms** - Continuous alerts until dismissed at 1x, 2x, 3x overtime
- **Bold alarm indicators** - Tasks with active alarms appear bolded
- **Auto-quiet on completion** - Completing a task automatically dismisses its alarm
- **Pause silences alarms** - Pausing a task stops its alarm; resuming re-triggers it if still overtime
- **Satisfying completion** - Confetti for all completions; green flash + extra confetti for ambitious
- **Focus restoration** - Returns focus to your previous app after creating tasks
- **Minimize/show overlay** - Hide the window when you need focus
- **Persistent storage** - Tasks saved to ~/.etime/
- **Task history** - Completed tasks logged to history.jsonl
- **Custom sounds** - Use your own .aiff files for alarms, success, and ambitious completions
- **Subtasks** - Create subtasks nested under parent tasks (cosmetic grouping with independent timers)
- **Work intervals** - Precise time tracking records when work actually happens (pause/resume timestamps)
- **Sleep detection** - Auto-pauses all tasks when Mac sleeps, resumes on wake
- **Help menu** - Toggle hotkey reference with ⌃⌥⌘H
- **Web dashboard** - Daily review with date picker, interval-based timeline, and sortable task table

## Installation

### Requirements
- macOS (tested on Sonoma/Sequoia)
- Python 3.11+
- Accessibility permissions (for global hotkeys)

### Setup

1. Clone or download this repository
2. Install dependencies:
   ```bash
   cd ~/Dev/etime
   pip install -r requirements.txt
   ```

3. Run the app:
   ```bash
   python main.py
   ```

4. **Grant Accessibility permissions**:
   - Go to System Settings → Privacy & Security → Accessibility
   - Enable etime (or Terminal/Python if running from terminal)
   - Restart the app if needed

## Usage

### Global Hotkeys

All hotkeys use: **Control (⌃) + Option (⌥) + Command (⌘)**

| Hotkey | Action |
|--------|--------|
| ⌃⌥⌘N | **New** task - Opens dialog to create and auto-start a task |
| ⌃⌥⌘P | **Toggle** start/pause - Switch between running and paused |
| ⌃⌥⌘C | **Complete** focused task (moves to history) |
| ⌃⌥⌘↑ | Move focus **up** |
| ⌃⌥⌘↓ | Move focus **down** |
| ⌃⌥⌘Q | **Quiet** - Dismiss all active alarms |
| ⌃⌥⌘U | **Undo** - Restore last completed task (single-level) |
| ⌃⌥⌘S | **Shrink** - Hide/show the overlay window |
| ⌃⌥⌘H | **Help** - Toggle hotkey reference popup |
| ⌃⌥⌘T | **Toggle subtask** - Make focused task a subtask of the task above it |

### Subtasks

Subtasks provide a cosmetic parent-child grouping. Each subtask has its own independent timer.

**Creating a subtask via dialog:**
1. Focus the intended parent task (⌃⌥⌘↑/↓)
2. Press ⌃⌥⌘N to open the new task dialog
3. The "Parent:" field shows the focused task's name
4. Leave it filled to create a subtask, or clear it for a top-level task
5. Subtask appears indented right below its parent

**Toggling subtask status on existing tasks:**
- Focus a task and press ⌃⌥⌘T to make it a subtask of the task above
- Press ⌃⌥⌘T again to un-subtask it

**Behavior:**
- Subtasks show indented in the overlay when their parent is active
- Completing a parent does not affect subtasks — they remain active but lose their indent
- Double-nesting (subtask of a subtask) works at the data level but only shows single indent in the overlay

### Work Intervals

etime tracks precise work intervals — every start/resume and pause/complete records a timestamp pair. This means:

- **Elapsed time is computed from actual work intervals**, not from a running counter
- **Dashboard timeline** shows when work actually happened, not just when tasks were completed
- **Pause/resume** creates clean interval boundaries
- **Sleep/wake** automatically closes and opens intervals

Old tasks without interval data display correctly using their stored `elapsed_seconds`.

### Task States & Colors

- **Focused task**: Light blue background with ► indicator
- **Ongoing (not focused)**: Dimmed gray text
- **Paused**: Gray text, shows elapsed time
- **Overtime**: Red text when elapsed ≥ estimated
- **Alarmed**: Bold text indicating active alarm

### Data Files

All data stored in `~/.etime/`:
- `active.json` - Current active tasks (auto-saved)
- `history.jsonl` - Completed tasks (append-only log)
- `alarm.aiff` - Custom alarm sound (optional, falls back to system "Ping")

### Understanding Alarms

When a task exceeds its estimated time, etime triggers escalating alarms:

- **Alarm triggers**: At 1x, 2x, 3x, 4x... estimated time
- **Looping behavior**: Alarm plays continuously in a loop until dismissed
- **Visual indicator**: Tasks with active alarms appear **bolded**
- **Multiple alarms**: If multiple tasks trigger alarms, they all appear bold
- **Dismissing**: Press ⌃⌥⌘Q to quiet all active alarms at once
- **Pausing**: Pausing a task silences its alarm; resuming re-triggers it if still overtime

**Example**: A 15-minute task will trigger alarms at:
- 15 minutes (1x) - alarm starts looping, task becomes bold
- 30 minutes (2x) - second alarm level
- 45 minutes (3x) - third alarm level
- Press ⌃⌥⌘Q anytime to stop the alarm sound

## Ambitious Time

Ambitious time is an optional **stretch goal** for each task. It represents a slightly unrealistic "push yourself" target, separate from your realistic estimate.

### How It Works

- When creating a task (⌃⌥⌘N), set the "Ambitious" field (leave empty to skip)
- Ambitious time must be ≤ estimated time
- Time display shows 3 values: `actual / ambitious / estimated`
- If no ambitious time is set: `actual / --:-- / estimated`

### Visual States

- **Green text**: Task is ongoing and elapsed < ambitious time (you're on track!)
- **Normal text**: Task passed ambitious time but still within estimate
- **Red text**: Task exceeded estimate (overtime)

### Completion Celebration

- **Within ambitious time**: "Glass" sound + green flash + lots of confetti + fade out
- **Normal completion**: "Purr" sound + mini confetti + fade out
- Both auto-dismiss active alarms

### Customizing Sounds

**Alarm sound** (loops when overtime):
```bash
ffmpeg -i input.mp3 ~/.etime/alarm.aiff
```
Falls back to system "Ping" if no custom file.

**Success sound** (normal completion):
```bash
ffmpeg -i input.mp3 ~/.etime/success.aiff
```
Falls back to system "Purr" → "Hero".

**Ambitious sound** (completed within ambitious time):
```bash
ffmpeg -i fanfare.mp3 ~/.etime/ambitious.aiff
```
Falls back to system "Glass" → "Purr" → "Hero".

## Task Lifecycle Diagram

### State Machine

```
┌─────────┐
│ BACKLOG │ (Rare - tasks auto-start by default)
└────┬────┘
     │ start (opens work interval)
     ↓
┌─────────────────┐ ◄── resume (opens interval) ──┐
│ ONGOING         │                                │
│                 │                                │
│ [ambitious]     │                                │
│  elapsed < amb  │                                │
│  GREEN text     │                                │
│        │        │                                │
│        ↓        │                                │
│ [normal]        │                                │
│  amb ≤ elapsed  │                                │
│  < estimated    │                                │
│  BLACK text     │                                │
│        │        │                                │
│        ↓        │                                │
│ [overtime]      │                                │
│  elapsed ≥ est  │                                │
│  RED text       │                                │
└────┬────────────┘                                │
     │                                             │
     ├──→ pause (closes interval) ► ┌──────────────┤
     │    alarm silenced if active  │    PAUSED    │
     │                              │  GRAY text   │
     │                              └──────────────┘
     │
     └──→ complete (closes interval) ► ┌───────────────┐
                                       │   COMPLETED   │
                                       │               │
                                       │ if ambitious:  │
                                       │  Glass sound + │
                                       │  green flash + │
                                       │  confetti      │
                                       │ else:          │
                                       │  Purr sound +  │
                                       │  mini confetti │
                                       └───────┬───────┘
                                               │
                                               │ undo (⌃⌥⌘U)
                                               │ (opens new interval)
                                               ↓
                                       ┌───────────────┐
                                       │  → ONGOING    │
                                       │  removed from │
                                       │  history      │
                                       └───────────────┘

Sleep → auto-pauses all ONGOING tasks (closes intervals)
Wake  → auto-resumes those tasks (opens new intervals)
```

### Visual States & Colors

| State | Appearance | Trigger |
|-------|-----------|---------|
| **Ambitious (ongoing)** | Green text (#2E7D32) | elapsed < ambitious_seconds |
| **Focused + Ongoing** | Light blue bg, black text, ► indicator | Focus navigation, past ambitious |
| **Unfocused + Ongoing** | White bg, gray text (#666), space indicator | Not focused |
| **Paused** | Gray text (#999), shows elapsed time | ⌃⌥⌘P on ongoing task |
| **Overtime** | **Red text** (#D32F2F) | elapsed ≥ estimated |
| **Alarmed** | **Bold text** | Alarm triggers at 1x, 2x, 3x... |
| **Subtask** | Indented left margin | parent_task_id set, parent active |

### Alarm Lifecycle

```
Task running → Elapsed ≥ Estimated
                    ↓
              Alarm triggers at 1x, 2x, 3x...
                    ↓
         ┌──────────┴───────────┐
         │                      │
    Task bolded            Sound loops
         │                      │
         └──────────┬───────────┘
                    ↓
         ┌──────────┼───────────────┐
         │          │               │
   ⌃⌥⌘Q pressed  Task completed  Task paused
         │          │               │
         └──────────┴───────────────┘
                    ↓
              Alarm dismissed
         (sound stops, bold removed)
         Pause: alarm re-fires on resume
```

## Dashboard

etime includes a web dashboard for daily review, auto-launched when etime starts.

### Access

- **URL**: http://localhost:5173
- **Date picker**: Click the date in the header to view any day
- **URL param**: http://localhost:5173/?date=2026-01-15
- **Auto-refresh**: Every 60 seconds

### Features

- **Summary stats**: Tasks completed, total time, accuracy, distractions, ambitious goals hit
- **Time breakdown chart**: Horizontal bar chart showing elapsed vs estimated vs ambitious per task
- **Daily timeline**: Work minutes per hour based on actual work intervals (falls back to completion-hour for old tasks)
- **Task table**: Sortable columns, shows elapsed, % of day, ambitious, estimated, accuracy, status. Subtasks shown with ↳ prefix
- **Insights**: Calibration feedback, ambitious goal tracking, distraction timestamps
- **Active tasks**: Shows currently running tasks (live section)

### Historical Data

Use `etime-dash-day` to view a dashboard for a specific date:

```bash
./etime-dash-day 01/15/2026
```

Opens a dashboard on port 5174 filtered to that date.

### Distraction Tracking

The dashboard integrates distraction data from `~/Dev/DistractionCount/distraction_count.txt` (one timestamp per line in `YYYY-MM-DD HH:MM:SS` format).

## Building Standalone App

To create a standalone macOS application:

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "etime" main.py
```

The app will be at `dist/etime.app` - you can drag it to Applications.

## Tips

- Create a new task with ⌃⌥⌘N, enter name and time, press Enter
- Use ⌃⌥⌘↑/↓ to navigate between tasks
- Use ⌃⌥⌘P to toggle between running and paused
- Use ⌃⌥⌘S to hide the overlay when you need screen space
- Use ⌃⌥⌘H to see all hotkeys at a glance
- Pause tasks when taking breaks (timer stops, can resume later)
- Complete tasks when done (saves to history, removes from overlay)
- When alarms trigger, they loop until you press ⌃⌥⌘Q or pause the task
- Tasks are saved automatically on every change
- Closing your Mac lid auto-pauses all tasks; opening resumes them

## Architecture

```
main.py           # Entry point, AppController, SleepObserver, HelpDialog
models.py         # Task dataclass, TaskState enum, work intervals
storage.py        # File I/O (active.json, history.jsonl)
config.py         # Constants and paths
timer_engine.py   # QTimer with alarm logic
sounds.py         # Alarm playback (NSSound)
overlay.py        # Main overlay window
task_dialog.py    # New task popup (with subtask parent field)
hotkeys.py        # Quartz event tap for global hotkeys
dashboard/        # Flask web dashboard
  __init__.py     # Launcher (auto-start, PID management)
  server.py       # Flask app, API endpoints
  templates/      # HTML templates
etime-dash-day    # CLI tool for historical date dashboards
```

## Troubleshooting

### Hotkeys don't work
- Ensure Accessibility permissions are granted
- Check System Settings → Privacy & Security → Accessibility
- Restart the app after granting permissions

### Alarm doesn't play
- Default alarm uses system "Ping" sound
- To use custom alarm, place `.aiff` file at `~/.etime/alarm.aiff`

### Window doesn't stay on top
- This should not happen - report as bug if it does
- Window has Qt.WindowStaysOnTopHint flag

## License

MIT

## Author

Built with Claude Code for productive PhD work.
