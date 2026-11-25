#!/usr/bin/env python3
"""
Apply the cluster map to the normalized item corpus and emit per-topic batches.

Reads `<kb>/.engram/cluster-map.json` and `<kb>/raw/items.jsonl` (falling
back to the legacy `<kb>/raw/bookmarks.jsonl` for older KBs), matches each
item against every topic's rules (multi-assign — a single item can land in
more than one batch), and writes:

    <kb>/raw/bookmarks/<topic>.md      one markdown file per topic
    <kb>/raw/bookmarks/_unsorted.md    items that matched no topic
    <kb>/raw/bookmarks/_manifest.md    index with counts

Claude generates cluster-map.json on first ingest by sampling the user's
actual items. This script is the deterministic applier — it never invents
topics, it just routes.

Usage:
    python3 scripts/preprocess.py --kb <kb-path>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---- cluster map ------------------------------------------------------------

@dataclass
class Topic:
    name: str
    description: str
    keywords: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)
    regexes: list[re.Pattern[str]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)  # empty = all sources

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Topic":
        if not isinstance(raw, dict) or not raw.get("name"):
            raise ValueError(f"each topic must be an object with a `name`, got {raw!r}")
        name = str(raw["name"]).strip()
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
            raise ValueError(
                f"topic name {name!r} must be kebab-case (lowercase, hyphens only)"
            )
        match = raw.get("match") or {}
        if not isinstance(match, dict):
            raise ValueError(f"topic {name!r}: `match` must be an object")

        def str_list(key: str) -> list[str]:
            # A bare string would be iterated per character ("recipe" →
            # r,e,c,i,p,e) and an empty string matches every item, so both
            # are rejected / dropped here rather than silently mis-routing.
            val = match.get(key) or []
            if isinstance(val, str):
                val = [val]
            if not isinstance(val, list) or not all(isinstance(v, str) for v in val):
                raise ValueError(f"topic {name!r}: `match.{key}` must be a list of strings")
            return [v.strip() for v in val if v.strip()]

        patterns = []
        for pat in str_list("regex"):
            try:
                patterns.append(re.compile(pat, re.IGNORECASE))
            except re.error as e:
                raise ValueError(f"topic {name!r}: invalid regex {pat!r}: {e}")
        return cls(
            name=name,
            description=str(raw.get("description", "")).strip(),
            keywords=[k.lower() for k in str_list("keywords")],
            hashtags=[h.lstrip("#").lower() for h in str_list("hashtags")],
            authors=[a.lstrip("@").lower() for a in str_list("authors")],
            regexes=patterns,
            sources=[s.lower() for s in str_list("sources")],
        )

    def matches(self, item: dict[str, Any]) -> bool:
        # Accept both normalized Item dicts (fields: text/author/source) and
        # legacy X bookmark dicts (fields: text/authorHandle) so preprocess
        # still works on KBs that haven't been re-synced after the refactor.
        source = (item.get("source") or "x").lower()
        if self.sources and source not in self.sources:
            return False

        text = (item.get("text") or "").lower()
        author = (item.get("author") or item.get("authorHandle") or "")
        author = author.lstrip("@").lower()

        has_positive_rule = bool(
            self.authors or self.keywords or self.hashtags or self.regexes
        )
        # Source-only topics (no other rules) treat the source match itself
        # as sufficient — i.e. "all items from this source go here."
        if self.sources and not has_positive_rule:
            return True

        if self.authors and author in self.authors:
            return True
        if self.keywords and any(kw in text for kw in self.keywords):
            return True
        if self.hashtags:
            tags = {m.group(1).lower() for m in re.finditer(r"#(\w+)", text)}
            if tags & set(self.hashtags):
                return True
        if self.regexes and any(p.search(text) for p in self.regexes):
            return True
        return False


def load_cluster_map(path: Path) -> list[Topic]:
    if not path.exists():
        sys.exit(
            f"error: {path} not found.\n"
            "Bootstrap it first by sampling bookmarks and writing the topic map."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"error: {path} is not valid JSON: {e}")
    topics_raw = data.get("topics") if isinstance(data, dict) else None
    if not isinstance(topics_raw, list) or not topics_raw:
        sys.exit(f"error: {path} must define a non-empty `topics` list")
    try:
        topics = [Topic.from_dict(t) for t in topics_raw]
    except ValueError as e:
        sys.exit(f"error: {path.name}: {e}")
    names = [t.name for t in topics]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        sys.exit(f"error: duplicate topic names in cluster-map.json: {sorted(dupes)}")
    return topics


# ---- bookmark rendering -----------------------------------------------------

def _fmt_count(n: Any) -> str:
    try:
        n = int(n or 0)
    except (TypeError, ValueError):
        return "0"
    if not n:
        return "0"
    if n >= 1000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    return str(n)


def _render_x(item: dict[str, Any]) -> str:
    # Supports both normalized Items and legacy bookmark dicts.
    meta = item.get("metadata") or {}
    handle = item.get("author") or item.get("authorHandle") or "unknown"
    name = meta.get("authorName") or item.get("authorName") or handle
    posted = item.get("timestamp") or item.get("postedAt") or ""
    url = item.get("url") or ""
    text = (item.get("text") or "").strip()

    eng = item.get("engagement") or {}
    likes = _fmt_count(eng.get("likeCount"))
    reposts = _fmt_count(eng.get("repostCount"))
    replies = _fmt_count(eng.get("replyCount"))

    lines = [
        f"### @{handle} — {name}",
        f"- posted: {posted}",
        f"- url: {url}",
        f"- engagement: {likes} likes · {reposts} reposts · {replies} replies",
    ]

    media = item.get("media") or []
    if media:
        lines.append(f"- media: {len(media)} item(s)")
    links = meta.get("links") or item.get("links") or []
    if links:
        lines.append("- links: " + ", ".join(links[:5]))

    quoted = meta.get("quotedTweet") or item.get("quotedTweet")
    if quoted:
        q_handle = quoted.get("authorHandle") or "unknown"
        q_text = (quoted.get("text") or "").strip().replace("\n", " ")
        if len(q_text) > 240:
            q_text = q_text[:237] + "..."
        lines.append(f"- quotes @{q_handle}: {q_text}")

    lines.append("")
    if text:
        for line in text.splitlines():
            lines.append(f"> {line}" if line else ">")

    return "\n".join(lines).rstrip() + "\n"


def _render_generic(item: dict[str, Any]) -> str:
    source = item.get("source") or "unknown"
    author = item.get("author")
    header = f"### [{source}]"
    if author:
        header += f" @{author}"
    ts = item.get("timestamp") or ""
    url = item.get("url") or ""

    lines = [header]
    if ts:
        lines.append(f"- at: {ts}")
    if url:
        lines.append(f"- url: {url}")
    meta = item.get("metadata") or {}
    for k in ("conversation_id", "book_title", "repo", "folder"):
        if k in meta:
            lines.append(f"- {k}: {meta[k]}")

    text = (item.get("text") or "").strip()
    lines.append("")
    if text:
        for line in text.splitlines():
            lines.append(f"> {line}" if line else ">")

    return "\n".join(lines).rstrip() + "\n"


def render_item(item: dict[str, Any]) -> str:
    source = (item.get("source") or "x").lower()
    if source == "x":
        return _render_x(item)
    return _render_generic(item)


# Legacy alias — preserved for any external callers.
def render_bookmark(bm: dict[str, Any]) -> str:
    return _render_x(bm)


def write_batch(
    path: Path, topic: Topic | None, items: list[dict[str, Any]]
) -> None:
    if topic is not None:
        header = [f"# {topic.name}", ""]
        if topic.description:
            header += [topic.description, ""]
    else:
        header = [
            "# _unsorted",
            "",
            "Items that matched no topic in cluster-map.json. Add a rule "
            "(or a new topic) and re-run preprocess to route them.",
            "",
        ]
    # Show source breakdown so Claude can see at a glance what's in each batch.
    source_counts: dict[str, int] = {}
    for it in items:
        s = (it.get("source") or "x").lower()
        source_counts[s] = source_counts.get(s, 0) + 1
    source_summary = ", ".join(
        f"{s}: {c}" for s, c in sorted(source_counts.items())
    ) or "empty"
    header += [
        f"Generated by preprocess.py · {len(items)} item(s) ({source_summary}).",
        "Do not hand-edit — regenerated on every preprocess run.",
        "",
        "---",
        "",
    ]
    body = "\n".join(render_item(it) for it in items)
    path.write_text("\n".join(header) + body, encoding="utf-8")


def write_manifest(
    path: Path,
    topics: list[Topic],
    counts: dict[str, int],
    unsorted_count: int,
    total: int,
    generated_at: str,
    source_counts: dict[str, int] | None = None,
) -> None:
    lines = [
        "# Item batch manifest",
        "",
        f"Generated: {generated_at}",
        f"Total items: {total}",
    ]
    if source_counts:
        summary = ", ".join(
            f"{s}: {c}" for s, c in sorted(source_counts.items())
        )
        lines.append(f"Sources: {summary}")
    lines += [
        "",
        "| Topic | Items | Description |",
        "|---|---:|---|",
    ]
    for t in topics:
        lines.append(f"| [{t.name}]({t.name}.md) | {counts.get(t.name, 0)} | {t.description} |")
    lines.append(f"| [_unsorted](_unsorted.md) | {unsorted_count} | No match |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---- main -------------------------------------------------------------------

def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL store, skipping (and reporting) lines that aren't JSON
    objects. One truncated line must not take the whole KB down. Split on
    "\n" — not splitlines() — because tweet text can contain U+2028."""
    out: list[dict[str, Any]] = []
    bad = 0
    for line in path.read_text(encoding="utf-8", errors="replace").split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(rec, dict):
            out.append(rec)
        else:
            bad += 1
    if bad:
        print(f"warning: {path.name}: skipped {bad} malformed line(s)", file=sys.stderr)
    return out


def load_items_or_bookmarks(kb: Path) -> list[dict[str, Any]]:
    """Read raw/items.jsonl (normalized, multi-source) plus, for KBs first
    synced before the Item refactor, any X bookmarks that only exist in the
    legacy raw/bookmarks.jsonl.

    The legacy merge matters: on an old KB the first non-X sync or chat
    import creates items.jsonl without any X items, and preferring that
    file outright would make every bookmark vanish from the batches."""
    items_path = kb / "raw" / "items.jsonl"
    legacy_path = kb / "raw" / "bookmarks.jsonl"

    if not items_path.exists() and not legacy_path.exists():
        sys.exit(f"error: neither {items_path} nor {legacy_path} found. Run sync.py first.")

    items = _read_jsonl(items_path) if items_path.exists() else []
    has_x = any((it.get("source") or "x").lower() == "x" for it in items)
    if not has_x and legacy_path.exists():
        legacy = _read_jsonl(legacy_path)
        if legacy:
            from sources.x import bookmarks_to_items

            print(
                f"note: merging {len(legacy)} X bookmark(s) from legacy "
                "raw/bookmarks.jsonl. Run /kb-sync once to fold them into "
                "raw/items.jsonl.",
                file=sys.stderr,
            )
            items = bookmarks_to_items(legacy) + items
    return items


# Kept for backward compatibility with external imports.
def load_bookmarks(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        sys.exit(f"error: {path} not found. Run sync.py first.")
    return _read_jsonl(path)


def clean_batch_dir(batch_dir: Path) -> None:
    # Only remove files we own: *.md at the top level. Leave subdirs alone.
    if not batch_dir.exists():
        batch_dir.mkdir(parents=True)
        return
    for child in batch_dir.iterdir():
        if child.is_file() and child.suffix == ".md":
            child.unlink()


# LLM classifications for items the rules couldn't place. Lives in .engram/
# (not raw/bookmarks/) so it survives every preprocess run — otherwise each
# /kb-ingest would dump those items back into _unsorted and batch sizes
# would flap against ingest-state.json.
OVERLAY_REL = Path(".engram") / "classifications.json"


def load_overlay(kb: Path) -> dict[str, list[str]]:
    path = kb / OVERLAY_REL
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"warning: ignoring unreadable {OVERLAY_REL}: {e}", file=sys.stderr)
        return {}
    data = raw.get("classifications") if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        return {}
    return {
        str(k): [t for t in v if isinstance(t, str)]
        for k, v in data.items()
        if isinstance(v, list)
    }


def route(
    topics: list[Topic],
    items: list[dict[str, Any]],
    overlay: dict[str, list[str]] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], int]:
    """Assign items to topic buckets. Rules win; the overlay only places
    items no rule matched. Returns (buckets, unsorted, overlay_placed)."""
    overlay = overlay or {}
    buckets: dict[str, list[dict[str, Any]]] = {t.name: [] for t in topics}
    unsorted: list[dict[str, Any]] = []
    placed = 0
    for it in items:
        hit = False
        for t in topics:
            if t.matches(it):
                buckets[t.name].append(it)
                hit = True
        if hit:
            continue
        # dict.fromkeys: dedupe while keeping order, so ["a", "a"] can't
        # append the item twice. Unknown topics (e.g. after a recluster)
        # are ignored.
        assigned = [
            name for name in dict.fromkeys(overlay.get(str(it.get("id")), []))
            if name in buckets
        ]
        if assigned:
            for name in assigned:
                buckets[name].append(it)
            placed += 1
        else:
            unsorted.append(it)
    return buckets, unsorted, placed


def build_batches(kb: Path) -> dict[str, Any]:
    """Route every item and rewrite raw/bookmarks/. Shared by preprocess and
    apply_classifications so both always produce identical output."""
    map_path = kb / ".engram" / "cluster-map.json"
    batch_dir = kb / "raw" / "bookmarks"

    topics = load_cluster_map(map_path)
    items = load_items_or_bookmarks(kb)
    buckets, unsorted, placed = route(topics, items, load_overlay(kb))

    clean_batch_dir(batch_dir)
    for t in topics:
        write_batch(batch_dir / f"{t.name}.md", t, buckets[t.name])
    write_batch(batch_dir / "_unsorted.md", None, unsorted)
    # Structured form of the unsorted bucket so a classifier subagent
    # (/kb-ingest) can consume items directly without re-parsing markdown.
    unsorted_jsonl = batch_dir / "_unsorted.jsonl"
    if unsorted:
        unsorted_jsonl.write_text(
            "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in unsorted),
            encoding="utf-8",
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
        unsorted_count=len(unsorted),
        total=len(items),
        generated_at=generated_at,
        source_counts=source_counts,
    )
    return {
        "topics": topics,
        "items": items,
        "counts": counts,
        "unsorted": unsorted,
        "overlay_placed": placed,
        "source_counts": source_counts,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Apply cluster-map.json to bookmarks.")
    ap.add_argument("--kb", required=True, type=Path, help="KB root directory")
    args = ap.parse_args()

    kb: Path = args.kb.resolve()
    r = build_batches(kb)
    topics, counts = r["topics"], r["counts"]

    print(f"preprocessed {len(r['items'])} item(s) into {len(topics)} topic(s)")
    for t in topics:
        print(f"  {t.name}: {counts[t.name]}")
    print(f"  _unsorted: {len(r['unsorted'])}")
    if r["overlay_placed"]:
        print(f"  ({r['overlay_placed']} placed by saved LLM classifications)")
    if r["source_counts"]:
        src_summary = ", ".join(f"{s}: {c}" for s, c in sorted(r["source_counts"].items()))
        print(f"  sources: {src_summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
