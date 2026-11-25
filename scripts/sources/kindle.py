#!/usr/bin/env python3
"""
Kindle clippings source adapter.

Parses the idiosyncratic `My Clippings.txt` file that Kindle devices write
to their root when plugged in via USB. Emits one Item per highlight.

Format (each entry is 4+ lines separated by `==========`):

    Book Title (Author Name)
    - Your Highlight on Location 1234-1256 | Added on Monday, April 5, 2024 9:42:01 PM

    Highlight text spanning one or more lines.
    ==========

Notes and bookmarks follow the same shape but with different metadata lines;
we keep highlights and notes, skip pure bookmark entries (no text body).
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .base import Item


SOURCE_ID = "kindle"
SEPARATOR = "=========="

_META_RE = re.compile(
    r"^-\s*(?:Your\s+)?(?P<kind>Highlight|Note|Bookmark)\b.*?"
    r"(?:Added\s+on\s+(?P<date>.+))?$",
    re.IGNORECASE,
)

# English-locale shapes only (US and UK devices). Weekday is stripped before
# matching, so these start at the month/day.
_DATE_FORMATS = (
    "%B %d, %Y %I:%M:%S %p",
    "%B %d, %Y %I:%M %p",
    "%B %d, %Y %H:%M:%S",
    "%d %B %Y %H:%M:%S",
    "%d %B %Y %I:%M:%S %p",
    "%d %B %Y %H:%M",
    "%B %d, %Y",
    "%d %B %Y",
)

_WEEKDAY_RE = re.compile(r"^[^\W\d_]+,?\s+(?=\S+\s+\S+)")


def _parse_date(s: str | None) -> str:
    """Parse a clipping date to ISO-8601, or "" if we can't.

    Never returns the raw string: a non-ISO timestamp would sort wrongly
    downstream, and an empty one is handled everywhere.
    """
    if not s:
        return ""
    s = " ".join(s.replace("\u202f", " ").replace("\xa0", " ").split())
    candidates = [s]
    stripped = _WEEKDAY_RE.sub("", s, count=1)
    if stripped != s:
        candidates.append(stripped)
    for cand in candidates:
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(cand, fmt).isoformat()
            except ValueError:
                continue
    return ""


def _parse_entry(block: str) -> dict[str, Any] | None:
    """Parse one clipping entry into a dict, or None if unparseable/bookmark."""
    lines = [ln.rstrip() for ln in block.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None

    title_line = lines[0].lstrip("\ufeff").strip()  # strip BOM on first entry
    meta_line = lines[1]
    body = "\n".join(lines[2:]).strip()

    # Title + author: "Title (Author Name)" — split on the last paren.
    title = title_line
    author = None
    if title_line.endswith(")") and "(" in title_line:
        idx = title_line.rfind("(")
        title = title_line[:idx].strip()
        author = title_line[idx + 1 : -1].strip() or None

    m = _META_RE.search(meta_line)
    kind = "Highlight"
    date_str = None
    if m:
        kind = m.group("kind").title()
        date_str = m.group("date")

    if kind.lower() == "bookmark":
        return None  # pure location marker, no content
    if not body:
        return None

    return {
        "title": title,
        "author": author,
        "kind": kind,
        "timestamp": _parse_date(date_str),
        "body": body,
    }


def parse_clippings(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    entries: list[dict[str, Any]] = []
    for block in raw.split(SEPARATOR):
        if not block.strip():
            continue
        entry = _parse_entry(block)
        if entry:
            entries.append(entry)
    return entries


def sync(kb_dir: Path | None, *, clippings_path: Path) -> list[dict[str, Any]]:
    """Import highlights from a `My Clippings.txt` file."""
    path = clippings_path.expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Kindle clippings file not found: {path}")

    entries = parse_clippings(path)
    items: list[Item] = []
    # Dedupe exact duplicates (same book + same text). The id is a stable
    # content hash of that key — NOT hash(), which is salted per process —
    # so re-importing the same file yields the same ids.
    seen: set[str] = set()
    for entry in entries:
        key = f"{entry['title']}\x00{entry['body']}"
        if key in seen:
            continue
        seen.add(key)

        text = entry["body"]
        if entry["author"]:
            header = f"{entry['title']} — {entry['author']}"
        else:
            header = entry["title"]
        text = f"{header}\n\n{text}"

        items.append(
            Item(
                id=f"{SOURCE_ID}:{hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]}",
                source=SOURCE_ID,
                text=text,
                timestamp=entry["timestamp"],
                author=entry["author"],
                url=None,
                engagement=None,
                media=[],
                metadata={
                    "book_title": entry["title"],
                    "kind": entry["kind"],
                },
            )
        )
    return [it.to_json() for it in items]


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Dump Kindle clippings as Items.")
    ap.add_argument("clippings", type=Path, help="Path to My Clippings.txt")
    ap.add_argument("--limit", type=int, default=5)
    args = ap.parse_args()

    items = sync(None, clippings_path=args.clippings)
    print(f"[kindle] {len(items)} highlight(s)")
    for it in items[: args.limit]:
        print(f"  {it['metadata']['book_title'][:60]} · {it['text'][:80]!r}")
