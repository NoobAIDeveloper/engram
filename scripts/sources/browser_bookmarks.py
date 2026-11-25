#!/usr/bin/env python3
"""
Browser bookmarks source adapter.

Reads the Chrome/Brave/Edge `Bookmarks` JSON file (same profile dir we
already know about from cookies.py), flattens the folder tree, and emits
one Item per saved URL.

No auth, no network. Just a local file read.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

# Sibling import — this module lives next to cookies.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cookies import BROWSERS, _user_data_dir  # noqa: E402

from .base import Item


SOURCE_ID = "browser-bookmarks"

# Chrome uses WebKit time: microseconds since 1601-01-01 UTC.
_WEBKIT_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)


def _webkit_to_iso(value: str | int | None) -> str:
    if not value:
        return ""
    try:
        us = int(value)
    except (TypeError, ValueError):
        return ""
    if us == 0:
        return ""
    try:
        dt = _WEBKIT_EPOCH + timedelta(microseconds=us)
        return dt.isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError):
        return ""


def _bookmarks_file(browser_id: str, profile: str = "Default") -> Path:
    for b in BROWSERS:
        if b.id == browser_id:
            return _user_data_dir(b) / profile / "Bookmarks"
    raise ValueError(f"unknown browser {browser_id!r}")


def _profiles_with_bookmarks(browser_id: str) -> list[str]:
    """Profile dir names that have a `Bookmarks` file: ``Default`` first,
    then ``Profile N`` in numeric order, then anything else by name."""
    base = _bookmarks_file(browser_id).parent.parent
    if not base.is_dir():
        return []
    names = [
        d.name for d in base.iterdir()
        if d.is_dir() and (d / "Bookmarks").is_file()
    ]

    def order(name: str) -> tuple[int, int, str]:
        if name == "Default":
            return (0, 0, name)
        m = re.fullmatch(r"Profile (\d+)", name)
        if m:
            return (1, int(m.group(1)), name)
        return (2, 0, name)

    return sorted(names, key=order)


def _walk(node: dict[str, Any], folder_path: str) -> Iterable[dict[str, Any]]:
    if node.get("type") == "url":
        yield {
            "name": node.get("name") or "",
            "url": node.get("url") or "",
            "date_added": node.get("date_added"),
            "folder": folder_path,
            "guid": node.get("guid") or "",
        }
    for child in node.get("children") or []:
        sub = folder_path
        if node.get("name"):
            sub = f"{folder_path}/{node['name']}" if folder_path else node["name"]
        yield from _walk(child, sub)


def _collect(
    browser_id: str,
    profile: str = "Default",
    seen_urls: set[str] | None = None,
) -> list[Item]:
    """Items for one profile. URLs in `seen_urls` (already emitted by an
    earlier profile of the same browser) are skipped; this profile's URLs
    are added to it afterwards."""
    path = _bookmarks_file(browser_id, profile)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    roots = data.get("roots") or {}
    # Default-profile ids keep their original shape so existing KBs don't
    # see every bookmark change id; other profiles are namespaced.
    id_prefix = (
        f"{SOURCE_ID}:{browser_id}"
        if profile == "Default"
        else f"{SOURCE_ID}:{browser_id}:{profile}"
    )
    earlier = set(seen_urls or ())
    own_urls: set[str] = set()

    items: list[Item] = []
    for root_name, root in roots.items():
        if not isinstance(root, dict):
            continue
        for entry in _walk(root, root_name):
            if not entry["url"]:
                continue
            # Skip internal URLs — chrome://, javascript:, about:blank, etc.
            if entry["url"].startswith(("chrome://", "edge://", "brave://", "javascript:", "about:")):
                continue
            if entry["url"] in earlier:
                continue
            own_urls.add(entry["url"])
            text_parts: list[str] = []
            if entry["name"]:
                text_parts.append(entry["name"])
            text_parts.append(entry["url"])
            items.append(
                Item(
                    id=f"{id_prefix}:{entry['guid'] or entry['url']}",
                    source=SOURCE_ID,
                    text="\n".join(text_parts),
                    timestamp=_webkit_to_iso(entry["date_added"]),
                    author=None,
                    url=entry["url"],
                    engagement=None,
                    media=[],
                    metadata={
                        "title": entry["name"],
                        "folder": entry["folder"],
                        "browser": browser_id,
                        "profile": profile,
                    },
                )
            )
    if seen_urls is not None:
        seen_urls.update(own_urls)
    return items


def sync(kb_dir: Path | None = None, *, browsers: list[str] | None = None) -> list[dict[str, Any]]:
    """Collect bookmarks from the configured browsers.

    Defaults to all installed browsers with at least one profile that has a
    Bookmarks file. Every such profile (Default, "Profile N", ...) is read;
    a URL saved in several profiles of one browser is emitted once.
    """
    if not (sys.platform == "darwin" or sys.platform.startswith("linux")):
        raise NotImplementedError(
            f"browser-bookmarks is not supported on this platform "
            f"({sys.platform!r}); engram only knows where Chromium browsers "
            f"keep their Bookmarks file on macOS and Linux."
        )

    if browsers is None:
        browsers = [b.id for b in BROWSERS]

    all_items: list[Item] = []
    for bid in browsers:
        seen_urls: set[str] = set()
        for profile in _profiles_with_bookmarks(bid):
            try:
                all_items.extend(_collect(bid, profile, seen_urls))
            except (OSError, json.JSONDecodeError) as exc:
                print(
                    f"[browser-bookmarks] {bid}/{profile}: unreadable "
                    f"Bookmarks file ({type(exc).__name__}); skipped",
                    file=sys.stderr,
                )
                continue
    return [it.to_json() for it in all_items]


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Dump browser bookmarks as Items.")
    ap.add_argument("--browser", action="append", help="Restrict to one browser id")
    ap.add_argument("--limit", type=int, default=5)
    args = ap.parse_args()

    items = sync(browsers=args.browser)
    print(f"[browser-bookmarks] {len(items)} URL(s)")
    for it in items[: args.limit]:
        print(f"  {it['metadata']['browser']}/{it['metadata']['profile']} · {it['metadata']['folder']} · {it['metadata']['title'][:60]}")
