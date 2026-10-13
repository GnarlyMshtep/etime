"""Parsing for a past block of time, written the way you'd say it out loud.

Backfilling a meeting shouldn't mean thinking in 24-hour time. "2:30-4" is what
you'd write on paper, so that's what this takes -- and because the guesses it
makes (which 2:30? which day?) are guesses, the caller is expected to show the
resolved range back before anything is created.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

# "9/26", "9/26/25", "2026-09-26", "yesterday", "today"
_DATE_PREFIX = re.compile(
    r"^\s*(?:(?P<word>yesterday|today)"
    r"|(?P<iso>\d{4}-\d{1,2}-\d{1,2})"
    r"|(?P<us>\d{1,2}/\d{1,2}(?:/\d{2,4})?))\s+",
    re.I,
)

# "2:30", "14:30", "4", "2:30pm", "4 pm"
_CLOCK = re.compile(r"^(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<meridiem>am|pm)?$", re.I)

# Bare hours in this range mean afternoon. Someone logging "2:30-4" means after
# lunch, not the small hours; "9-10:30" means morning. Spelling out am/pm always
# wins over this.
_AFTERNOON_HOURS = range(1, 7)

# Past this, a range is far likelier to be a typo than a real sitting.
MAX_BLOCK_HOURS = 12


@dataclass(frozen=True)
class TimeRange:
    start: datetime
    end: datetime

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()

    @property
    def minutes(self) -> int:
        return int(round(self.seconds / 60))

    def describe(self) -> str:
        same_day = self.start.date() == date.today()
        day = "today" if same_day else self.start.strftime("%a %-d %b")
        return f"{day} {self.start:%H:%M}–{self.end:%H:%M} ({self.minutes} min)"


def _parse_date_prefix(text: str, *, today: date) -> tuple[date, str]:
    m = _DATE_PREFIX.match(text)
    if not m:
        return today, text
    rest = text[m.end():]
    if m.group("word"):
        word = m.group("word").lower()
        return (today - timedelta(days=1) if word == "yesterday" else today), rest
    if m.group("iso"):
        return date.fromisoformat(m.group("iso")), rest
    parts = [int(p) for p in m.group("us").split("/")]
    month, day = parts[0], parts[1]
    year = today.year if len(parts) < 3 else (parts[2] + 2000 if parts[2] < 100 else parts[2])
    return date(year, month, day), rest


def _match_clock(text: str):
    m = _CLOCK.match(text.strip())
    if not m:
        raise ValueError(f"can't read {text.strip()!r} as a time")
    return m


def _meridiem_of(text: str) -> str:
    """"am"/"pm" if it was written, else "". Zero-padded hours count as neither."""
    return (_match_clock(text).group("meridiem") or "").lower()


def _is_written_24h(text: str) -> bool:
    """A zero-padded hour ("04:00") is someone writing 24-hour time on purpose."""
    hour = _match_clock(text).group("hour")
    return hour.startswith("0") and len(hour) == 2


def _parse_clock(text: str, *, on: date, assume_meridiem: str = "") -> datetime:
    m = _match_clock(text)
    hour = int(m.group("hour"))
    minute = int(m.group("minute") or 0)
    meridiem = (m.group("meridiem") or "").lower()
    written_24h = _is_written_24h(text)

    # An am/pm borrowed from the other end of the range, when this end didn't
    # say. Never applied to 24-hour notation.
    if not meridiem and assume_meridiem and not written_24h:
        meridiem = assume_meridiem

    if meridiem == "pm":
        hour = hour % 12 + 12
    elif meridiem == "am":
        hour = hour % 12
    elif hour in _AFTERNOON_HOURS and not written_24h:
        hour += 12

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"{text.strip()!r} isn't a real time of day")
    return datetime.combine(on, datetime.min.time().replace(hour=hour, minute=minute))


def parse_time_range(text: str, *, today: Optional[date] = None) -> Optional[TimeRange]:
    """Read "2:30-4", "14:30-16:00", "9/26 9-10:30", "yesterday 2-3".

    Returns None for empty input -- that means "no backdating", not an error.
    Raises ValueError when there *is* input and it can't be read, so a typo is
    never silently treated as "now".
    """
    text = (text or "").strip()
    if not text:
        return None

    on, rest = _parse_date_prefix(text, today=today or date.today())
    # En/em dashes get typed too, and "to" reads naturally.
    rest = rest.replace("–", "-").replace("—", "-")
    parts = re.split(r"\s*(?:-|\bto\b)\s*", rest.strip(), maxsplit=1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"{text!r} needs a start and an end, like 2:30-4")

    # "9-10:06 pm" says pm once and means it for both ends, which is how people
    # write it. Try that reading first — but only keep it if it actually orders,
    # because "9-5pm" is nine in the morning to five in the evening, not 9pm.
    end_meridiem = _meridiem_of(parts[1])
    if end_meridiem and not _meridiem_of(parts[0]):
        shared_start = _parse_clock(parts[0], on=on, assume_meridiem=end_meridiem)
        shared_end = _parse_clock(parts[1], on=on)
        if shared_start < shared_end:
            return _checked(start=shared_start, end=shared_end)

    start = _parse_clock(parts[0], on=on)
    end = _parse_clock(parts[1], on=on)

    if end == start:
        raise ValueError(f"{parts[0].strip()!r} and {parts[1].strip()!r} are the same time")
    # "11-1" means 11:00 to 13:00, not a negative hour. Only nudge if that keeps
    # the block inside the same day — otherwise it's a typo, not a pm/am slip.
    if end < start:
        nudged = end + timedelta(hours=12)
        if nudged > start and nudged.date() == start.date():
            end = nudged
        else:
            raise ValueError(f"{parts[1].strip()!r} isn't after {parts[0].strip()!r}")
    return _checked(start=start, end=end)


def _checked(*, start: datetime, end: datetime) -> TimeRange:
    """Guards that apply however the endpoints were arrived at."""
    if end.date() != start.date():
        raise ValueError("that block would cross midnight")
    if (end - start) > timedelta(hours=MAX_BLOCK_HOURS):
        raise ValueError(f"that's a {(end - start).total_seconds() / 3600:.0f}-hour block — "
                         f"longer than {MAX_BLOCK_HOURS}h is almost always a typo")
    return TimeRange(start=start, end=end)
