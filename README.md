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
- **Satisfying completion** - Green flash animation, confetti for ambitious completions
- **Focus restoration** - Returns focus to your previous app after creating tasks
- **Minimize/show overlay** - Hide the window when you need focus
- **Persistent storage** - Tasks saved to ~/.etime/
- **Task history** - Completed tasks logged to history.jsonl
- **Custom sounds** - Use your own .aiff files for alarms, success, and ambitious completions

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
| ⌃⌥⌘S | **Shrink** - Hide/show the overlay window |

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

**Example**: A 15-minute task will trigger alarms at:
- 15 minutes (1x) - alarm starts looping, task becomes bold
- 30 minutes (2x) - second alarm level
- 45 minutes (3x) - third alarm level
- Press ⌃⌥⌘Q anytime to stop the alarm sound

## Ambitious Time

Ambitious time is an optional **stretch goal** for each task. It represents a slightly unrealistic "push yourself" target, separate from your realistic estimate.

### How It Works

- When creating a task (⌃⌥⌘N), set the "Ambitious" field (leave at `--` to skip)
- Ambitious time must be ≤ estimated time
- Time display shows 3 values: `actual / ambitious / estimated`
- If no ambitious time is set: `actual / --:-- / estimated`

### Visual States

- **Green text**: Task is ongoing and elapsed < ambitious time (you're on track!)
- **Normal text**: Task passed ambitious time but still within estimate
- **Red text**: Task exceeded estimate (overtime)

### Completion Celebration

- **Within ambitious time**: Sound + green flash + confetti particles + fade out
- **Normal completion**: Sound + fade out
- Both use the same completion sound ("Purr" by default, customizable)
- Both auto-dismiss active alarms

### Customizing Animations

Completion animations are controlled by `_remove_task_animated()` in `overlay.py` with two flags: `green_flash` and `confetti`. To change which animations play for normal vs ambitious completions, edit the `remove_task_with_celebration()` and `remove_task_with_confetti()` methods in `overlay.py`.

## Task Lifecycle Diagram

### State Machine

```
┌─────────┐
│ BACKLOG │ (Rare - tasks auto-start by default)
└────┬────┘
     │ start
     ↓
┌─────────────────┐ ◄──── resume ──────┐
│ ONGOING         │                     │
│                 │                     │
│ [ambitious]     │                     │
│  elapsed < amb  │                     │
│  GREEN text     │                     │
│        │        │                     │
│        ↓        │                     │
│ [normal]        │                     │
│  amb ≤ elapsed  │                     │
│  < estimated    │                     │
│  BLACK text     │                     │
│        │        │                     │
│        ↓        │                     │
│ [overtime]      │                     │
│  elapsed ≥ est  │                     │
│  RED text       │                     │
└────┬────────────┘                     │
     │                                  │
     ├──→ pause ──────► ┌───────────────┤
     │                  │    PAUSED     │
     │                  │  GRAY text    │
     │                  └───────────────┘
     │
     └──→ complete ──► ┌────────────────┐
                       │   COMPLETED    │
                       │                │
                       │ if ambitious:  │
                       │  green flash + │
                       │  confetti +    │
                       │  fade out      │
                       │ else:          │
                       │  fade out      │
                       └────────────────┘
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
         ┌──────────┴───────────┐
         │                      │
   ⌃⌥⌘Q pressed          Task completed (⌃⌥⌘C)
         │                      │
         └──────────┬───────────┘
                    ↓
              Alarm dismissed
         (sound stops, bold removed)
```

**Key Points**:
- Tasks start in ONGOING state (auto-start on creation)
- If ambitious time is set, task shows green while within ambitious target
- Alarms trigger when elapsed ≥ estimated (1x, 2x, 3x multiples)
- Alarms loop continuously until dismissed or task completed
- Completing a task with active alarm auto-dismisses the alarm
- Completing within ambitious time triggers confetti + triumphant sound
- Normal completion triggers green flash + "Hero" sound
- Focus automatically returns to your previous app after creating a task

### Customizing the Alarm Sound

You can use your own alarm sound instead of the system "Ping":

1. **Prepare your sound file**:
   - Must be in `.aiff` format
   - Use an online converter (e.g., online-convert.com) or ffmpeg:
     ```bash
     ffmpeg -i input.mp3 ~/.etime/alarm.aiff
     ```

2. **Save to the correct location**:
   ```bash
   # Place your custom sound here:
   ~/.etime/alarm.aiff
   ```

3. **Restart etime** to use the new sound

**Finding alarm sounds**:
- Free sounds: [freesound.org](https://freesound.org)
- Convert any audio: [online-convert.com](https://www.online-convert.com)
- Use system sounds: Look in `/System/Library/Sounds/`

### Customizing the Success Sound

When you complete a task, etime plays a celebratory success sound (system "Hero" by default). You can customize this:

1. **Prepare your sound file**:
   - Must be in `.aiff` format (same as alarm sound)
   - Use an online converter or ffmpeg:
     ```bash
     ffmpeg -i input.mp3 ~/.etime/success.aiff
     ```

2. **Save to the correct location**:
   ```bash
   # Place your custom success sound here:
   ~/.etime/success.aiff
   ```

3. **Restart etime** to use the new sound

**Tip**: The default system "Hero" sound is brief. For a more prolonged celebration, use a custom sound file (1-3 seconds works well)!

### Customizing the Ambitious Sound

When completing a task within its ambitious time, a more triumphant sound plays (system "Purr" by default):

```bash
# Custom ambitious completion sound:
ffmpeg -i fanfare.mp3 ~/.etime/ambitious.aiff
```

## Dashboard

etime includes a web dashboard for daily review, auto-launched when etime starts.

### Access

- **URL**: http://localhost:5173
- **Auto-refresh**: Every 60 seconds

### Features

- **Summary stats**: Tasks completed, total time, accuracy, distractions, ambitious goals hit
- **Time breakdown chart**: Horizontal bar chart showing elapsed vs estimated vs ambitious per task
- **Daily timeline**: Work minutes per hour (bars) with distractions overlay (line)
- **Task table**: Sortable columns, shows elapsed, % of day, ambitious, estimated, accuracy, status
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
- Pause tasks when taking breaks (timer stops, can resume later)
- Complete tasks when done (saves to history, removes from overlay)
- When alarms trigger, they loop until you press ⌃⌥⌘Q
- Tasks are saved automatically on every change

## Architecture

```
main.py           # Entry point, AppController
models.py         # Task dataclass, TaskState enum
storage.py        # File I/O (active.json, history.jsonl)
config.py         # Constants and paths
timer_engine.py   # QTimer with alarm logic
sounds.py         # Alarm playback (NSSound)
overlay.py        # Main overlay window
task_dialog.py    # New task popup
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
