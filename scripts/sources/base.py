#!/usr/bin/env python3
"""
Common Item schema and helpers shared by every source adapter.

Each source module (x, claude_code, chatgpt, ...) normalizes its raw data
into a list of Items. The KB stores all Items from all sources in a single
file, `raw/items.jsonl`, which preprocess.py consumes — so preprocess never
has to know whether a given record came from a tweet or a chat turn.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence


@dataclass
class Item:
    """Normalized unit that flows through preprocess and synthesis.

    Fields:
        id: Source-prefixed unique id, e.g. "x:1930244636578119863" or
            "chatgpt:conv_abc/turn_3". Must be stable across syncs so we
            can dedupe.
        source: Short source identifier. One of "x", "claude-code",
            "chatgpt", "claude-ai", "kindle", "github", "chrome", ...
        author: Handle/username of the content's author, or None for
            content the user produced themselves (e.g. their own chat
            turns).
        text: Primary textual content. For chats, this is the Q+A pair
            concatenated with role labels.
        url: Canonical link back to the source, if one exists.
        timestamp: ISO 8601 string (UTC preferred).
        engagement: Optional source-specific dict (e.g. {"likeCount": 12}).
        media: Optional list of media URLs / descriptors.
        metadata: Arbitrary source-specific extras (conversation_id,
            book title, repo stars, etc.).
    """

    id: str
    source: str
    text: str
    timestamp: str
    author: str | None = None
    url: str | None = None
    engagement: dict[str, Any] | None = None
    media: list[Any] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def load_items(path: Path) -> list[dict[str, Any]]:
    """Load items.jsonl. Returns raw dicts (not Item) so downstream code can
    treat source-specific fields loosely. Split on "\n" to tolerate Unicode
    line separators inside text fields."""
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"items.jsonl line {i}: {exc}") from exc
    return out


def write_items(path: Path, items: list[dict[str, Any]]) -> None:
    """Atomically rewrite items.jsonl."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    body = "\n".join(json.dumps(it, ensure_ascii=False) for it in items)
    if body:
        body += "\n"
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)


def merge_items(
    existing: list[dict[str, Any]],
    new: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Dedupe by id; newer record wins. Returns (merged, added_count)."""
    by_id: dict[str, dict[str, Any]] = {}
    for rec in existing:
        rid = rec.get("id")
        if rid:
            by_id[rid] = rec
    added = 0
    for rec in new:
        rid = rec.get("id")
        if not rid:
            continue
        if rid not in by_id:
            added += 1
        by_id[rid] = rec
    merged = sorted(
        by_id.values(),
        key=lambda r: r.get("timestamp") or "",
        reverse=True,
    )
    return merged, added


def replace_source_items(
    kb_dir: Path,
    source_id: str,
    new_items: list[dict[str, Any]],
) -> tuple[int, int]:
    """Rewrite raw/items.jsonl, replacing all items with the given source.

    Other sources' items are preserved untouched. Returns (total_items,
    items_in_this_source).
    """
    items_path = kb_dir / "raw" / "items.jsonl"
    try:
        existing = load_items(items_path)
    except ValueError:
        existing = []
    kept = [it for it in existing if it.get("source") != source_id]
    combined, _ = merge_items(kept, new_items)
    write_items(items_path, combined)
    return len(combined), len(new_items)


def drop_items_by_id_prefix(kb_dir: Path, prefix: str) -> int:
    """Remove every item whose id starts with `prefix` from raw/items.jsonl.

    Used by chunked sources before emitting fresh chunks for a parent
    document so chunk-boundary shifts (e.g. after a Notion page edit) don't
    leave orphans behind. Returns the number of items dropped.
    """
    items_path = kb_dir / "raw" / "items.jsonl"
    try:
        existing = load_items(items_path)
    except ValueError:
        return 0
    kept = [it for it in existing if not str(it.get("id") or "").startswith(prefix)]
    dropped = len(existing) - len(kept)
    if dropped:
        write_items(items_path, kept)
    return dropped


# ---- chunking helpers ------------------------------------------------------
#
# Long-form sources (Notion pages, meeting transcripts) are split into N
# semantically-bounded chunks and each chunk becomes its own Item. Every
# chunk carries light parent context so a single chunk remains readable in
# isolation during synthesis. Id format: `<source>:<parent_id>:<chunk_index>`.

@dataclass
class Chunk:
    """A semantically-bounded slice of a parent document."""

    index: int                 # 0-based position within the parent
    title: str | None          # heading/chapter title; None for unnamed chunks
    body: str                  # chunk content (plain text)
    char_range: tuple[int, int]  # (start, end) in parent's linear text, for debugging


def chunk_by_headings(
    blocks: Sequence[dict[str, Any]],
    heading_levels: Iterable[str] = ("heading_1", "heading_2"),
) -> list[Chunk]:
    """Split a Notion-style block list along heading boundaries.

    Expects each block to be a dict with at least `type` and a `plain_text`
    field (or a nested Notion-style rich-text list) — callers must flatten
    rich text first. Blocks before the first heading form an implicit
    preamble chunk (title=None). If no headings appear anywhere, returns
    a single chunk containing the whole body.
    """
    levels = set(heading_levels)
    chunks: list[Chunk] = []
    current_title: str | None = None
    current_lines: list[str] = []
    cursor = 0
    chunk_start = 0

    def flush() -> None:
        nonlocal cursor, chunk_start, current_lines, current_title
        body = "\n".join(current_lines).strip()
        # Skip fully-empty chunks unless they carry a heading (e.g. empty section).
        if not body and current_title is None:
            current_lines = []
            return
        end = cursor
        chunks.append(
            Chunk(
                index=len(chunks),
                title=current_title,
                body=body,
                char_range=(chunk_start, end),
            )
        )
        current_lines = []
        chunk_start = end

    for b in blocks:
        btype = str(b.get("type") or "")
        text = str(b.get("plain_text") or "").rstrip()
        if btype in levels:
            flush()
            current_title = text or None
            # Advance the cursor past the heading text so next chunk's
            # char_range starts at the body, not the heading.
            cursor += len(text) + 1
            chunk_start = cursor
            continue
        if text:
            current_lines.append(text)
            cursor += len(text) + 1

    flush()
    if not chunks:
        # Empty doc — return a single empty chunk so callers can still emit
        # a (possibly-empty) item and preserve the parent's existence.
        chunks.append(Chunk(index=0, title=None, body="", char_range=(0, 0)))
    return chunks


def chunk_by_size(
    text: str,
    max_chars: int = 4000,
    soft_break: str = "\n\n",
) -> list[Chunk]:
    """Paragraph-aware windowing for text with no semantic structure.

    Greedily packs paragraphs (split on `soft_break`) into windows of up to
    `max_chars`. Individual paragraphs longer than max_chars are hard-split
    at word boundaries.
    """
    text = text.strip()
    if not text:
        return [Chunk(index=0, title=None, body="", char_range=(0, 0))]

    paragraphs = [p for p in text.split(soft_break) if p.strip()]
    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_len = 0
    cursor = 0
    chunk_start = 0

    def flush() -> None:
        nonlocal buf, buf_len, chunk_start
        if not buf:
            return
        body = soft_break.join(buf).strip()
        end = chunk_start + len(body)
        chunks.append(
            Chunk(index=len(chunks), title=None, body=body, char_range=(chunk_start, end))
        )
        chunk_start = end
        buf = []
        buf_len = 0

    for p in paragraphs:
        # Hard-split overlong paragraphs at word boundaries.
        while len(p) > max_chars:
            split_at = p.rfind(" ", 0, max_chars) or max_chars
            head, p = p[:split_at].strip(), p[split_at:].strip()
            if buf_len + len(head) > max_chars:
                flush()
            buf.append(head)
            buf_len += len(head) + len(soft_break)
            flush()
        if buf_len + len(p) + len(soft_break) > max_chars and buf:
            flush()
        buf.append(p)
        buf_len += len(p) + len(soft_break)
        cursor += len(p) + len(soft_break)
    flush()
    return chunks


def make_chunk_items(
    *,
    source: str,
    parent_id: str,
    parent_title: str,
    chunks: Sequence[Chunk],
    author: str | None,
    url: str | None,
    timestamp: str,
    base_metadata: dict[str, Any] | None = None,
    preamble: str | None = None,
) -> list[Item]:
    """Build one Item per chunk with a consistent text template and id.

    text layout:
        # <parent_title>
        ## <chunk.title>    (only if present)

        <preamble>          (only on chunk 0, if provided)

        <chunk.body>

    Metadata merges `base_metadata` with chunk-specific fields: chunk_index,
    chunk_count, chunk_title.
    """
    base_metadata = dict(base_metadata or {})
    out: list[Item] = []
    total = len(chunks)
    for c in chunks:
        lines: list[str] = []
        if parent_title:
            lines.append(f"# {parent_title}")
        if c.title:
            lines.append(f"## {c.title}")
        if lines:
            lines.append("")
        if c.index == 0 and preamble:
            lines.append(preamble.strip())
            lines.append("")
        if c.body:
            lines.append(c.body)
        text = "\n".join(lines).strip()

        meta = dict(base_metadata)
        meta.update({
            "parent_id": parent_id,
            "parent_title": parent_title,
            "chunk_index": c.index,
            "chunk_count": total,
            "chunk_title": c.title,
        })
        out.append(
            Item(
                id=f"{source}:{parent_id}:{c.index}",
                source=source,
                text=text,
                timestamp=timestamp,
                author=author,
                url=url,
                metadata=meta,
            )
        )
    return out
