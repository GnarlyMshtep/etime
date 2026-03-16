"""Global hotkey registration using Quartz event tap."""

import sys
import time
from typing import Dict, Callable
import Quartz
from Quartz import (
    CGEventTapCreate, kCGSessionEventTap, kCGHeadInsertEventTap,
    kCGEventTapOptionDefault, CGEventTapEnable, CGEventTapIsEnabled,
    CFMachPortCreateRunLoopSource, CFRunLoopGetCurrent,
    CFRunLoopAddSource, CFRunLoopRemoveSource, kCFRunLoopCommonModes,
    CGEventGetIntegerValueField, kCGKeyboardEventKeycode,
    CGEventGetFlags, CGEventMaskBit, kCGEventKeyDown,
    kCGEventFlagMaskControl, kCGEventFlagMaskAlternate, kCGEventFlagMaskCommand,
    kCGEventFlagMaskShift,
    kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput
)
from ApplicationServices import AXIsProcessTrusted

# Required modifiers: Control + Option + Command
HOTKEY_MODIFIERS = (
    kCGEventFlagMaskControl |
    kCGEventFlagMaskAlternate |
    kCGEventFlagMaskCommand
)


class HotkeyManager:
    """Manages global hotkey registration and handling."""

    def __init__(self):
        """Initialize hotkey manager."""
        self.callbacks: Dict[tuple[int, bool], Callable] = {}
        self.tap = None
        self.run_loop_source = None
        self._health_check_count: int = 0

    def register(self, keycode: int, callback: Callable, shift: bool = False) -> None:
        """
        Register a hotkey callback.

        Args:
            keycode: Virtual key code (e.g., KEY_N).
            callback: Function to call when hotkey is pressed.
            shift: If True, requires Shift as additional modifier.
        """
        self.callbacks[(keycode, shift)] = callback

    def start(self) -> bool:
        """
        Start listening for hotkeys.

        Returns:
            True if successful, False if accessibility permissions not granted.
        """
        # Check accessibility permissions
        if not AXIsProcessTrusted():
            print("Error: Accessibility permissions not granted.")
            print("Please enable etime in System Settings → Privacy & Security → Accessibility")
            return False

        if not self._create_tap():
            return False

        print("Hotkey manager started successfully")
        return True

    def _create_tap(self) -> bool:
        """Create and enable the event tap. Returns True on success."""
        # Create event tap
        self.tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionDefault,
            CGEventMaskBit(kCGEventKeyDown),
            self._event_callback,
            None
        )

        if not self.tap:
            print("Error: Failed to create event tap")
            return False

        # Create run loop source and add to run loop
        self.run_loop_source = CFMachPortCreateRunLoopSource(None, self.tap, 0)
        CFRunLoopAddSource(
            CFRunLoopGetCurrent(),
            self.run_loop_source,
            kCFRunLoopCommonModes
        )

        # Enable the tap
        CGEventTapEnable(self.tap, True)
        return True

    def check_and_repair(self) -> None:
        """
        Periodic health check for the event tap.
        Call this every few seconds to detect and recover from
        disabled taps (e.g. caused by Spotify or other apps).
        Also proactively recreates the tap every ~60s to recover
        from silent failures where the tap appears enabled but
        stops firing callbacks.
        """
        self._health_check_count += 1

        # Proactive full recreation every ~60s (20 checks * 3s interval)
        if self._health_check_count % 20 == 0:
            self.stop()
            if self._create_tap():
                print("Event tap proactively recreated")
            else:
                print("ERROR: Failed to proactively recreate event tap")
            return

        if not self.tap:
            print("WARNING: Event tap is None - attempting full recreation")
            if self._create_tap():
                print("Event tap recreated successfully")
            else:
                print("ERROR: Failed to recreate event tap")
            return

        if not CGEventTapIsEnabled(self.tap):
            print("WARNING: Event tap found disabled during health check - re-enabling")
            CGEventTapEnable(self.tap, True)

            # Verify it actually re-enabled
            if CGEventTapIsEnabled(self.tap):
                print("Event tap re-enabled successfully")
            else:
                # Re-enable failed, try full recreation
                print("WARNING: Re-enable failed - attempting full tap recreation")
                self.stop()
                if self._create_tap():
                    print("Event tap recreated successfully")
                else:
                    print("ERROR: Failed to recreate event tap")

    def _event_callback(self, proxy, event_type, event, refcon):
        """
        Event tap callback for processing key events.

        Args:
            proxy: Event tap proxy.
            event_type: Type of event.
            event: The event itself.
            refcon: User-defined data (unused).

        Returns:
            The event to pass through, or None to consume it.
        """
        # Handle system-disabled tap (e.g. Spotify or other apps causing conflict)
        if event_type in (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput):
            reason = "timeout" if event_type == kCGEventTapDisabledByTimeout else "user input"
            print(f"WARNING: Event tap disabled by {reason} - re-enabling immediately")
            if self.tap:
                CGEventTapEnable(self.tap, True)
            return event

        try:
            # Get keycode
            keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)

            # Get modifier flags
            flags = CGEventGetFlags(event)

            # Check if our modifiers are pressed
            # Mask to only the modifiers we care about
            relevant_flags = flags & (
                kCGEventFlagMaskControl |
                kCGEventFlagMaskAlternate |
                kCGEventFlagMaskCommand
            )

            # Check if this is one of our hotkeys
            if relevant_flags == HOTKEY_MODIFIERS:
                shift_pressed = bool(flags & kCGEventFlagMaskShift)
                key = (keycode, shift_pressed)
                if key in self.callbacks:
                    try:
                        self.callbacks[key]()
                    except Exception as e:
                        print(f"Error in hotkey callback for keycode {keycode}: {e}")
                    return None

        except Exception as e:
            print(f"Error in event callback: {e}")

        # Pass through the event
        return event

    def force_recreate(self) -> bool:
        """Force full teardown and recreation of the event tap.

        Use after sleep/wake or when the tap silently stops working.
        Returns True if recreation succeeded.
        """
        print("Force-recreating event tap...")
        self.stop()
        success = self._create_tap()
        if success:
            print("Event tap force-recreated successfully")
        else:
            print("ERROR: Event tap force-recreation failed")
        return success

    def stop(self):
        """Stop listening for hotkeys."""
        # Properly remove the run loop source before discarding
        if self.run_loop_source:
            try:
                CFRunLoopRemoveSource(
                    CFRunLoopGetCurrent(),
                    self.run_loop_source,
                    kCFRunLoopCommonModes
                )
            except Exception as e:
                print(f"Warning: failed to remove run loop source: {e}")
        if self.tap:
            CGEventTapEnable(self.tap, False)
            self.tap = None
            self.run_loop_source = None
