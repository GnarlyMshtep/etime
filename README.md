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
- **Task stash** - Hide paused tasks from the overlay without completing them; reveal with "show all" toggle
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
| ⌃⌥⌘E | **Edit** focused task - name, estimate, ambitious, parent (blank = top level), also under. Never its time on the clock |
| ⌃⌥⌘↑ | Move focus **up** |
| ⌃⌥⌘↓ | Move focus **down** |
| ⌃⌥⌘Q | **Quiet** - Dismiss all active alarms |
| ⌃⌥⌘U | **Undo** - Restore last completed task (single-level) |
| ⌃⌥⌘S | **Shrink** - Hide/show the overlay window |
| ⌃⌥⌘H | **Help** - Toggle hotkey reference popup |
| ⌃⌥⌘T | **Toggle subtask** - Make focused task a subtask of the task above it |
| ⌃⌥⌘A | **All** - Toggle show all (reveals stashed tasks) |
| ⇧⌃⌥⌘→ | **Stash** - Hide focused task (must be paused) |
| ⇧⌃⌥⌘← | **Unstash** - Restore focused task (in show-all mode) |

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

### Task Stash

Stashing hides paused tasks from the overlay without completing or deleting them. Useful when the overlay gets cluttered with many tasks.

- **Stash** (⇧⌃⌥⌘→): Hides the focused task. Only paused tasks can be stashed — pause first with ⌃⌥⌘P.
- **Show all** (⌃⌥⌘A): Toggles visibility of stashed tasks. An "All" label appears at the top-left when active. Stashed tasks appear dimmed with a ⏸ prefix.
- **Unstash** (⇧⌃⌥⌘←): Restores a stashed task to the normal view. Only works in show-all mode.
- Stashed state persists across restarts.
- Focus navigation skips stashed tasks in the normal view.
- In show-all mode, stashing/unstashing updates the marker in-place (no animation).

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
- `blocked_apps.json` - Apps/sites you call distracting. Optional; its presence turns on app sampling
- `app_usage.jsonl` - Foreground-app runs (append-only), only while sampling is on

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
     │                              └──────┬───────┘
     │                                     │
     │                              stash (⇧⌃⌥⌘→)
     │                                     ↓
     │                              ┌──────────────┐
     │                              │   STASHED    │
     │                              │  hidden from │
     │                              │  default view│
     │                              └──────┬───────┘
     │                                     │
     │                              unstash (⇧⌃⌥⌘←)
     │                              (in show-all mode)
     │                                     ↓
     │                              ┌──────────────┐
     │                              │  → PAUSED    │
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
| **Stashed (show-all)** | Dimmed gray bg, ⏸ prefix, gray text | is_stashed=True, show-all mode on |

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

### App Usage & Distraction Band (optional)

**Off unless you turn it on.** etime can record which app was in the foreground
and draw the time you spent on apps *you* call distracting as a red strip along
the bottom of each day on the timeline. Nothing is sampled, written or shown
until the opt-in file exists.

**Turning it on.** Write the list of apps and sites you consider distracting to
`~/.etime/blocked_apps.json`:

```json
{
  "apps": { "com.tinyspeck.slackmacgap": "Slack", "com.apple.mail": "Mail" },
  "websites": ["youtube.com"]
}
```

Bundle ids come from `osascript -e 'id of app "Slack"'`. That file's existence is
the switch: etime starts the sampler alongside the dashboard, and the band
appears. Delete it and everything stops. `python app_sampler.py --status` says
where things stand; `--stop` stops a running sampler.

**What it records.** Every few seconds: the frontmost application's bundle id and
name, and how long since your last keystroke or click. Consecutive seconds in
one app become one run appended to `~/.etime/app_usage.jsonl`, append-only like
the task log. Time while you're away isn't recorded -- a locked screen or two
minutes without input ends the run, which also covers sleep.

**What it does not record.** No document names, window titles, tab titles or
URLs. Only documented macOS APIs (`NSWorkspace`, the HID event source, the
window-server session dictionary); it never reads another application's files or
windows. Needs no dependency etime doesn't already have. The consequence is that
a distracting *website* can't be seen -- only the browser it was in -- which is
why the `websites` list above is recorded for later and not yet drawn.

On the timeline, a faded strip means the app was in front but untouched: a window
left open, not time spent. Hover a strip for the app and duration; a day's label
gains, say, `· 24m off · 7×`. The count is separate sittings, and includes the
six-second checks that are too short to draw -- how often you went looking is a
different number from how long you stayed, and usually the more interesting one.

### Raycast Focus (optional, one-time import)

If you already keep a block list in [Raycast Focus](https://manual.raycast.com/focus),
`scripts/import_raycast_blocklist.py` copies it into `blocked_apps.json` so you
don't maintain the same list twice. It reads only the categories you created
yourself -- Raycast's built-in ones (travel, streaming, ...) say nothing about
what distracts *you*.

Run by hand, never by etime. The categories file sits in a macOS Group
Container, so the first read may raise a permission prompt; after the import
nothing in etime touches Raycast again, and the band works the same with Raycast
uninstalled.

Raycast **focus sessions themselves cannot be read**, which is worth writing down
so it isn't re-investigated: session starts, pauses, breaks, snoozes and
overrides live in `raycast-activities-enc.sqlite`, which is encrypted, and no
documented API or export reports session state. Raycast's App Intents and
deeplinks (`raycast://focus/start`, `toggle`, `complete`) only *control* sessions.
So "was focus on at 3pm" isn't available from structured data, and this feature
doesn't claim it: the band measures what you actually had in front of you, which
is the thing worth plotting anyway.

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
task_dialog.py    # New task popup (with subtask parent field); also the ⌃⌥⌘E edit dialog
task_tree.py      # Moving a task + its subtree under a new parent (edit dialog, scripts)
app_sampler.py    # Optional foreground-app sampler (opt-in; see Distraction Band)
app_usage.py      # Reads app_usage.jsonl into the spans the timeline draws
app_usage_types.py # AppRun, BlockList
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
- **Hotkeys stop working after a while**: macOS can silently kill the Quartz event tap even though it reports as enabled. etime proactively recreates the tap every ~60 seconds to recover from this. If hotkeys still don't respond, restart the app. If the problem persists, try toggling the Accessibility permission off and back on.

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
