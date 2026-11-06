"""Types for app-usage sampling: what was in front, and what counts as a distraction.

``AppRun`` is one stretch with a single app in the foreground, the unit written
to ``~/.etime/app_usage.jsonl``. ``BlockList`` is the set of apps and sites you
call distracting -- etime's own file at ``~/.etime/blocked_apps.json``, so none
of this needs Raycast installed. If you do use Raycast Focus,
``scripts/import_raycast_blocklist.py`` seeds the file from your categories once
and nothing reads Raycast again.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import BLOCKED_APPS_FILE


@dataclass
class AppRun:
    """One stretch of wall-clock time with a single app frontmost.

    A long stretch is written as several consecutive runs of the same app (see
    ``APP_SEGMENT_MAX_SECONDS``); readers coalesce them.
    """

    bundle_id: str
    app_name: str
    start: str                      # local wall-clock ISO, as the task log writes it
    end: str
    seconds: float
    # Seconds inside the run with no keyboard or mouse input at all. A run that
    # is nearly all idle is a window left open, not time spent.
    idle_seconds: float = 0.0

    @property
    def start_dt(self) -> datetime:
        return datetime.fromisoformat(self.start)

    @property
    def end_dt(self) -> datetime:
        return datetime.fromisoformat(self.end)

    def to_json(self) -> str:
        return json.dumps({
            "bundle_id": self.bundle_id,
            "app_name": self.app_name,
            "start": self.start,
            "end": self.end,
            "seconds": round(self.seconds, 3),
            "idle_seconds": round(self.idle_seconds, 3),
        })


@dataclass
class BlockList:
    """Apps (by bundle id) and websites you've called distracting."""

    apps: dict[str, str] = field(default_factory=dict)      # bundle id -> name
    websites: list[str] = field(default_factory=list)
    imported_from: str = ""        # provenance, shown in the dashboard footnote
    imported_at: str = ""
    source: Optional[Path] = None
    error: str = ""                # why it's empty, when it is

    def blocks(self, *, bundle_id: str) -> bool:
        return bundle_id in self.apps

    @property
    def is_empty(self) -> bool:
        return not self.apps and not self.websites

    def to_json(self) -> str:
        return json.dumps({
            "apps": self.apps,
            "websites": self.websites,
            "imported_from": self.imported_from,
            "imported_at": self.imported_at,
        }, indent=2)


def load_block_list(*, path: Path = BLOCKED_APPS_FILE) -> BlockList:
    """Read etime's blocked-app list.

    A missing or unreadable file comes back as an empty list carrying ``error``,
    which the dashboard prints next to the band -- an empty band must never be
    mistaken for a clean day.
    """
    if not path.exists():
        return BlockList(error=f"no {path.name} -- "
                               f"run scripts/import_raycast_blocklist.py or write it by hand")
    try:
        with open(path, "r") as fh:
            raw = json.load(fh)
    except (OSError, ValueError) as exc:
        return BlockList(error=f"can't read {path}: {exc}")
    if not isinstance(raw.get("apps"), dict):
        return BlockList(error=f"{path} has no 'apps' object mapping bundle id to name")
    return BlockList(
        apps={str(k): str(v) for k, v in raw["apps"].items()},
        websites=[str(w) for w in raw.get("websites") or []],
        imported_from=str(raw.get("imported_from", "")),
        imported_at=str(raw.get("imported_at", "")),
        source=path,
    )


def read_raycast_categories(*, path: Path, custom_only: bool = True) -> BlockList:
    """Read Raycast Focus's own categories file. Called by the importer only.

    Raycast ships curated categories (travel, streaming, ...) alongside the ones
    you make yourself. ``custom_only`` keeps just yours, which is the honest read
    of "what I consider a distraction" -- a built-in category you never selected
    says nothing about you.
    """
    with open(path, "r") as fh:
        raw = json.load(fh)
    if not isinstance(raw, list):
        raise ValueError(f"{path} is not a list of categories; Raycast's format changed")

    out = BlockList(source=path)
    names: list[str] = []
    for cat in raw:
        if custom_only and not bool(cat.get("kind", {}).get("custom")):
            continue
        names.append(str(cat.get("title", cat.get("categoryId", "?"))))
        for bundle_id in cat.get("apps") or []:
            out.apps.setdefault(str(bundle_id), str(bundle_id))
        for site in cat.get("websites") or []:
            if site not in out.websites:
                out.websites.append(str(site))
    out.imported_from = f"Raycast Focus categories: {', '.join(names) or '(none)'}"
    return out
