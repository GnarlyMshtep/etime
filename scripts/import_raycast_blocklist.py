"""Seed etime's blocked-app list from your Raycast Focus categories.

etime keeps its own list at ``~/.etime/blocked_apps.json`` -- the dashboard never
reads Raycast. This copies the list across once, so you don't maintain it twice.
Run it again when you change your categories in Raycast.

Only the categories you created yourself are copied. Raycast ships curated ones
(travel, streaming, ...) that you may never have selected, and importing those
would invent a definition of distraction you never gave.

Note: the categories file lives in a macOS Group Container, so the first run may
raise a permission prompt. Nothing else in etime touches that path, and if you'd
rather not grant it, write ``blocked_apps.json`` by hand -- the format is in the
dry-run output below.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app_usage_types import BlockList, load_block_list, read_raycast_categories  # noqa: E402
from config import BLOCKED_APPS_FILE, ETIME_DIR, RAYCAST_FOCUS_CATEGORIES  # noqa: E402

BACKUP_DIR = Path(__file__).resolve().parent.parent / "claude_data"


def describe(*, bl: BlockList, label: str) -> None:
    print(f"{label}:")
    if bl.error:
        print(f"  (empty -- {bl.error})")
        return
    for bundle_id, name in sorted(bl.apps.items(), key=lambda kv: kv[1].lower()):
        print(f"  app   {name}  [{bundle_id}]")
    for site in sorted(bl.websites):
        print(f"  site  {site}")
    if bl.is_empty:
        print("  (nothing)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from-file", type=Path, default=RAYCAST_FOCUS_CATEGORIES,
                    help="Raycast's categories.json (default: the standard location)")
    ap.add_argument("--all-categories", action="store_true",
                    help="also import Raycast's built-in categories, not just yours")
    ap.add_argument("--apply", action="store_true", help="write the file")
    args = ap.parse_args()

    if not args.from_file.exists():
        sys.exit(f"no Raycast categories at {args.from_file}\n"
                 f"If Raycast isn't installed, write {BLOCKED_APPS_FILE} by hand instead.")
    try:
        fresh = read_raycast_categories(path=args.from_file,
                                        custom_only=not args.all_categories)
    except PermissionError:
        sys.exit(f"macOS wouldn't let this read {args.from_file}.\n"
                 f"Grant the prompt and retry, or write {BLOCKED_APPS_FILE} by hand.")

    current = load_block_list()
    describe(bl=current, label=f"now in {BLOCKED_APPS_FILE}")
    print()
    describe(bl=fresh, label=f"from {args.from_file.name}")

    if fresh.is_empty:
        sys.exit("\nRefusing to write an empty list -- that would read as "
                 "'nothing distracts me'. Make a category in Raycast first, "
                 "or pass --all-categories.")

    fresh.imported_at = datetime.now().isoformat(timespec="seconds")
    if not args.apply:
        print("\n--- dry run; pass --apply to write ---")
        print(fresh.to_json())
        return

    ETIME_DIR.mkdir(parents=True, exist_ok=True)
    if BLOCKED_APPS_FILE.exists():
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = BACKUP_DIR / f"{BLOCKED_APPS_FILE.name}.{stamp}.bak"
        shutil.copy2(BLOCKED_APPS_FILE, backup)
        print(f"\nbacked up to {backup}")
    BLOCKED_APPS_FILE.write_text(fresh.to_json() + "\n")
    print(f"wrote {BLOCKED_APPS_FILE}")


if __name__ == "__main__":
    main()
