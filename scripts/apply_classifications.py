#!/usr/bin/env python3
"""
Apply a Haiku-produced classification overlay to the rule-based routing.

The Haiku subagent spawned by /kb-ingest reads `raw/bookmarks/_unsorted.jsonl`
and `.twitter-wiki/cluster-map.json`, then writes a classification mapping:

    {"classifications": {"item_id_1": ["topic-a"], "item_id_2": ["topic-a", "topic-b"], ...}}

Items not classifiable get omitted (or listed with empty []) and stay unsorted.

This script overlays those assignments on the rule-based buckets produced by
preprocess.py and rewrites every batch file (plus `_unsorted.md` /
`_unsorted.jsonl` / `_manifest.md`) atomically.

Usage:
    python3 scripts/apply_classifications.py --kb <kb-path> \
        --classifications <path-to-classifications.json>
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from preprocess import (  # noqa: E402
    clean_batch_dir,
    load_cluster_map,
    load_items_or_bookmarks,
    write_batch,
    write_manifest,
)


def _route_rules(topics, items: list[dict[str, Any]]):
    buckets: dict[str, list[dict[str, Any]]] = {t.name: [] for t in topics}
    unsorted: list[dict[str, Any]] = []
    for it in items:
        hit = False
        for t in topics:
            if t.matches(it):
                buckets[t.name].append(it)
                hit = True
        if not hit:
            unsorted.append(it)
    return buckets, unsorted


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Overlay Haiku classifications onto rule-based routing."
    )
    ap.add_argument("--kb", required=True, type=Path)
    ap.add_argument(
        "--classifications",
        required=True,
        type=Path,
        help="Path to the JSON file produced by the classifier subagent.",
    )
    args = ap.parse_args()

    kb: Path = args.kb.resolve()
    map_path = kb / ".twitter-wiki" / "cluster-map.json"
    batch_dir = kb / "raw" / "bookmarks"

    topics = load_cluster_map(map_path)
    topic_names = {t.name for t in topics}
    items = load_items_or_bookmarks(kb)

    try:
        raw = json.loads(args.classifications.read_text())
    except FileNotFoundError:
        sys.exit(f"error: {args.classifications} not found.")
    except json.JSONDecodeError as e:
        sys.exit(f"error: {args.classifications} is not valid JSON: {e}")

    classifications = raw.get("classifications") if isinstance(raw, dict) else None
    if not isinstance(classifications, dict):
        sys.exit(
            f"error: {args.classifications} must have shape "
            "{\"classifications\": {item_id: [topic, ...]}}"
        )

    buckets, unsorted = _route_rules(topics, items)
    rule_ids = {it.get("id") for bucket in buckets.values() for it in bucket}
    unsorted_by_id = {it.get("id"): it for it in unsorted if it.get("id")}

    # Track what actually moved, ignore classifications that refer to items the
    # rules already matched (they're not unsorted anymore) or to unknown topics.
    moved = 0
    skipped_unknown_item = 0
    skipped_unknown_topic = 0
    still_unsorted: list[dict[str, Any]] = []
    dispatched_ids: set[str] = set()

    for item_id, assigned_topics in classifications.items():
        if item_id in rule_ids:
            continue
        if item_id not in unsorted_by_id:
            skipped_unknown_item += 1
            continue
        if not isinstance(assigned_topics, list) or not assigned_topics:
            continue
        item = unsorted_by_id[item_id]
        for topic_name in assigned_topics:
            if topic_name not in topic_names:
                skipped_unknown_topic += 1
                continue
            buckets[topic_name].append(item)
        if any(t in topic_names for t in assigned_topics):
            dispatched_ids.add(item_id)
            moved += 1

    for it in unsorted:
        if it.get("id") in dispatched_ids:
            continue
        still_unsorted.append(it)

    clean_batch_dir(batch_dir)
    for t in topics:
        write_batch(batch_dir / f"{t.name}.md", t, buckets[t.name])
    write_batch(batch_dir / "_unsorted.md", None, still_unsorted)
    unsorted_jsonl = batch_dir / "_unsorted.jsonl"
    if still_unsorted:
        unsorted_jsonl.write_text(
            "".join(json.dumps(it) + "\n" for it in still_unsorted)
        )
    elif unsorted_jsonl.exists():
        unsorted_jsonl.unlink()

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    counts = {name: len(bms) for name, bms in buckets.items()}
    source_counts: dict[str, int] = {}
    for it in items:
        s = (it.get("source") or "x").lower()
        source_counts[s] = source_counts.get(s, 0) + 1
    write_manifest(
        batch_dir / "_manifest.md",
        topics,
        counts,
        unsorted_count=len(still_unsorted),
        total=len(items),
        generated_at=generated_at,
        source_counts=source_counts,
    )

    print(
        f"applied: {moved} item(s) moved from _unsorted into topic batches · "
        f"{len(still_unsorted)} still unsorted"
    )
    if skipped_unknown_item:
        print(
            f"  warning: {skipped_unknown_item} classification(s) referenced "
            f"unknown item IDs — skipped",
            file=sys.stderr,
        )
    if skipped_unknown_topic:
        print(
            f"  warning: {skipped_unknown_topic} classification(s) referenced "
            f"unknown topic names — skipped",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
