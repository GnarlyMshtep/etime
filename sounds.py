"""Sound playback for alarm notifications."""

import os
from AppKit import NSSound

from config import ALARM_FILE, SUCCESS_SOUND_FILE, AMBITIOUS_SOUND_FILE


_current_sound = None  # Keep reference to prevent garbage collection
_sound_loop_active = False


def play_alarm_loop() -> None:
    """
    Play alarm sound in a loop until stopped.

    Tries to play custom alarm file (~/.etime/alarm.aiff) first.
    Falls back to system "Ping" sound if custom file doesn't exist.
    The sound will loop continuously until stop_alarm() is called.
    """
    global _current_sound, _sound_loop_active

    # If already playing, don't restart
    if _sound_loop_active and _current_sound and _current_sound.isPlaying():
        return

    _sound_loop_active = True

    # Try custom alarm file first
    custom_path = os.path.expanduser(str(ALARM_FILE))
    if os.path.exists(custom_path):
        try:
            _current_sound = NSSound.alloc().initWithContentsOfFile_byReference_(
                custom_path, True
            )
            if _current_sound:
                _current_sound.setLoops_(True)  # Enable looping
                _current_sound.play()
                print("Playing custom alarm in loop")
                return
        except Exception as e:
            print(f"Warning: Failed to play custom alarm {custom_path}: {e}")

    # Fall back to system sound
    try:
        _current_sound = NSSound.soundNamed_("Ping")
        if _current_sound:
            _current_sound.setLoops_(True)  # Enable looping
            _current_sound.play()
            print("Playing system alarm in loop")
        else:
            print("Warning: Could not load system sound 'Ping'")
    except Exception as e:
        print(f"Warning: Failed to play system sound: {e}")


def stop_alarm() -> None:
    """Stop currently playing alarm sound and disable loop."""
    global _current_sound, _sound_loop_active

    _sound_loop_active = False

    if _current_sound:
        try:
            _current_sound.stop()
            print("Alarm stopped")
        except Exception as e:
            print(f"Warning: Failed to stop alarm: {e}")


def play_success_sound() -> None:
    """
    Play a short success sound when task is completed.

    Tries custom sound (~/.etime/success.aiff) first,
    falls back to system "Hero" sound.
    """
    # Try custom success sound
    custom_path = os.path.expanduser(str(SUCCESS_SOUND_FILE))
    if os.path.exists(custom_path):
        try:
            sound = NSSound.alloc().initWithContentsOfFile_byReference_(
                custom_path, True
            )
            if sound:
                sound.play()
                print("Playing custom success sound")
                return
        except Exception as e:
            print(f"Warning: Failed to play custom success sound: {e}")

    # Fall back to system sound - use Purr (same as ambitious)
    for sound_name in ("Purr", "Hero"):
        try:
            sound = NSSound.soundNamed_(sound_name)
            if sound:
                sound.play()
                print(f"Playing system success sound '{sound_name}'")
                return
        except Exception as e:
            print(f"Warning: Failed to play '{sound_name}': {e}")

    print("Warning: Could not play any success sound")


def play_ambitious_success_sound() -> None:
    """
    Play a triumphant sound when completing a task within ambitious time.

    Tries custom sound (~/.etime/ambitious.aiff) first,
    falls back to system "Purr" sound (more celebratory than "Hero").
    """
    # Try custom ambitious sound
    custom_path = os.path.expanduser(str(AMBITIOUS_SOUND_FILE))
    if os.path.exists(custom_path):
        try:
            sound = NSSound.alloc().initWithContentsOfFile_byReference_(
                custom_path, True
            )
            if sound:
                sound.play()
                print("Playing custom ambitious success sound")
                return
        except Exception as e:
            print(f"Warning: Failed to play custom ambitious sound: {e}")

    # Fall back to system sound - try Purr (more celebratory), then Hero
    for sound_name in ("Purr", "Hero"):
        try:
            sound = NSSound.soundNamed_(sound_name)
            if sound:
                sound.play()
                print(f"Playing system ambitious sound '{sound_name}'")
                return
        except Exception as e:
            print(f"Warning: Failed to play '{sound_name}': {e}")

    print("Warning: Could not play any ambitious success sound")
