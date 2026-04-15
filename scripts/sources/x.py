#!/usr/bin/env python3
"""
X (Twitter) source adapter.

sync.py has its own bespoke pipeline for paginating the GraphQL bookmarks
endpoint and persisting raw records to `raw/bookmarks.jsonl`. That file is
the source-private intermediate — we keep it around for incremental sync
via snowflake ids.

This adapter's job is just to convert those stored bookmark dicts into the
common `Item` schema so preprocess.py can treat them like any other source.
"""

from __future__ import annotations

from typing import Any

from .base import Item


SOURCE_ID = "x"


def bookmark_to_item(bm: dict[str, Any]) -> Item:
    """Normalize a stored X bookmark dict into an `Item`."""
    raw_id = bm.get("id") or bm.get("tweetId") or ""
    handle = (bm.get("authorHandle") or "").lstrip("@") or None

    # Preserve X-specific detail in metadata so renderers can still produce
    # rich per-bookmark output (media count, quoted tweet preview, etc.).
    metadata: dict[str, Any] = {}
    if bm.get("authorName"):
        metadata["authorName"] = bm["authorName"]
    if bm.get("quotedTweet"):
        metadata["quotedTweet"] = bm["quotedTweet"]
    if bm.get("links"):
        metadata["links"] = bm["links"]
    if bm.get("tags"):
        metadata["tags"] = bm["tags"]

    return Item(
        id=f"{SOURCE_ID}:{raw_id}",
        source=SOURCE_ID,
        text=bm.get("text") or "",
        timestamp=bm.get("postedAt") or "",
        author=handle,
        url=bm.get("url"),
        engagement=bm.get("engagement") or None,
        media=bm.get("media") or [],
        metadata=metadata,
    )


def bookmarks_to_items(bookmarks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert a list of stored bookmark dicts to serializable item dicts."""
    return [bookmark_to_item(bm).to_json() for bm in bookmarks]
