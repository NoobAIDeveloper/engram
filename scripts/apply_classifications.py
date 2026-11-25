#!/usr/bin/env python3
"""
Apply a Haiku-produced classification overlay to the rule-based routing.

The Haiku subagent spawned by /kb-ingest reads `raw/bookmarks/_unsorted.jsonl`
and `.engram/cluster-map.json`, then writes a classification mapping:

    {"classifications": {"item_id_1": ["topic-a"], "item_id_2": ["topic-a", "topic-b"], ...}}

Items not classifiable get omitted (or listed with empty []) and stay unsorted.

This script merges those assignments into the persistent overlay at
`.engram/classifications.json` and regenerates every batch file. Because
preprocess.py reads the same overlay, classified items stay in their topics
on every later preprocess run instead of falling back into `_unsorted`.

Usage:
    python3 scripts/apply_classifications.py --kb <kb-path> \
        --classifications <path-to-classifications.json>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from preprocess import (  # noqa: E402
    OVERLAY_REL,
    build_batches,
    load_cluster_map,
    load_items_or_bookmarks,
    load_overlay,
    route,
)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Overlay LLM classifications onto rule-based routing."
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
    cls_path = args.classifications
    if not cls_path.is_absolute() and not cls_path.exists():
        cls_path = kb / cls_path  # allow paths relative to the KB

    try:
        raw = json.loads(cls_path.read_text(encoding="utf-8"))
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

    topics = load_cluster_map(kb / ".engram" / "cluster-map.json")
    topic_names = {t.name for t in topics}
    items = load_items_or_bookmarks(kb)
    overlay = load_overlay(kb)

    # What is unsorted right now (rules + whatever was already saved)?
    _, unsorted_before, _ = route(topics, items, overlay)
    unsorted_ids = {str(it.get("id")) for it in unsorted_before if it.get("id")}
    known_ids = {str(it.get("id")) for it in items if it.get("id")}

    moved = 0
    skipped_unknown_item = 0
    skipped_unknown_topic = 0
    for item_id, assigned in classifications.items():
        item_id = str(item_id)
        if item_id not in known_ids:
            skipped_unknown_item += 1
            continue
        if item_id not in unsorted_ids:
            continue  # already placed by a rule or an earlier classification
        if not isinstance(assigned, list):
            continue
        valid = [n for n in dict.fromkeys(assigned) if n in topic_names]
        skipped_unknown_topic += len(set(map(str, assigned))) - len(valid)
        if valid:
            overlay[item_id] = valid
            moved += 1

    # Drop entries for items that no longer exist so the file can't grow
    # without bound.
    overlay = {k: v for k, v in overlay.items() if k in known_ids}
    overlay_path = kb / OVERLAY_REL
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = overlay_path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"classifications": overlay}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(overlay_path)

    result = build_batches(kb)

    print(
        f"applied: {moved} item(s) moved from _unsorted into topic batches · "
        f"{len(result['unsorted'])} still unsorted"
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
