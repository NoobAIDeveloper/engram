#!/usr/bin/env python3
"""
Notion source adapter.

Hits the Notion v1 REST API as an internal integration. The user creates
an integration at https://notion.so/my-integrations, copies the secret
token into `<kb>/.engram/sources.json` under `notion.token`, and shares
individual pages/databases with the integration from Notion's UI. This
adapter has no allowlist — it syncs every page the integration can see.

One Notion page becomes N Items (one per H1/H2 section). Pages with no
headings fall back to size-based windowing. Item id format:
`notion:<page_id>:<chunk_index>`.

Incremental: persists `last_synced_at` in
`<kb>/.engram/notion-sync-meta.json` and client-side filters pages by
`last_edited_time` on subsequent runs. Edits to a page drop and replace
all of its chunks, so chunk-boundary shifts don't leave orphans.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .base import (
    Item,
    chunk_by_headings,
    chunk_by_size,
    drop_items_by_id_prefix,
    load_items,
    make_chunk_items,
)


SOURCE_ID = "notion"
API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
PAGE_SIZE = 100

# Headings we split along. keep in sync with chunk_by_headings default.
HEADING_TYPES = ("heading_1", "heading_2")

# Block types that contribute to a page's flat body text. heading types
# are handled separately — they become chunk boundaries, not body lines.
TEXT_BLOCK_TYPES = {
    "paragraph",
    "bulleted_list_item",
    "numbered_list_item",
    "to_do",
    "toggle",
    "quote",
    "callout",
    "code",
}


# ---- config / state --------------------------------------------------------

def _load_token(kb_dir: Path) -> str | None:
    cfg = kb_dir / ".engram" / "sources.json"
    if not cfg.exists():
        return None
    try:
        data = json.loads(cfg.read_text())
    except json.JSONDecodeError:
        return None
    n = (data.get("notion") or {}) if isinstance(data, dict) else {}
    token = n.get("token")
    return token.strip() if isinstance(token, str) and token.strip() else None


def _meta_path(kb_dir: Path) -> Path:
    return kb_dir / ".engram" / "notion-sync-meta.json"


def _load_meta(kb_dir: Path) -> dict[str, Any]:
    p = _meta_path(kb_dir)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {}


def _write_meta(kb_dir: Path, meta: dict[str, Any]) -> None:
    p = _meta_path(kb_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(meta, indent=2) + "\n")


# ---- HTTP ------------------------------------------------------------------

class NotionAuthError(RuntimeError):
    pass


class NotionRateLimitError(RuntimeError):
    pass


def _request(
    method: str,
    path: str,
    token: str,
    *,
    body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    max_retries: int = 5,
) -> dict[str, Any]:
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)

    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
        "User-Agent": "engram-notion/0.1",
    }
    req = urllib.request.Request(url, data=data, method=method, headers=headers)

    attempt = 0
    while True:
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise NotionAuthError(
                    "Notion rejected the token (401). Confirm notion.token in "
                    ".engram/sources.json is a valid internal integration secret."
                )
            if exc.code == 429:
                # Respect Retry-After if present; otherwise back off exponentially.
                retry_after = float(exc.headers.get("Retry-After") or 0) or (2 ** attempt)
                attempt += 1
                if attempt > max_retries:
                    raise NotionRateLimitError(
                        f"Notion rate-limit hit and retries exhausted: {exc}"
                    )
                time.sleep(min(retry_after, 60))
                continue
            if 500 <= exc.code < 600 and attempt < max_retries:
                time.sleep(2 ** attempt)
                attempt += 1
                continue
            try:
                err_body = exc.read().decode("utf-8")
            except Exception:
                err_body = ""
            raise RuntimeError(f"Notion {method} {path} → {exc.code}: {err_body}") from exc
        except urllib.error.URLError as exc:
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                attempt += 1
                continue
            raise RuntimeError(f"Notion {method} {path} network error: {exc}") from exc


# ---- search / list ---------------------------------------------------------

def _search_pages(token: str) -> Iterator[dict[str, Any]]:
    """Enumerate every page the integration can see, newest first."""
    cursor: str | None = None
    while True:
        body: dict[str, Any] = {
            "filter": {"value": "page", "property": "object"},
            "sort": {"direction": "descending", "timestamp": "last_edited_time"},
            "page_size": PAGE_SIZE,
        }
        if cursor:
            body["start_cursor"] = cursor
        resp = _request("POST", "/search", token, body=body)
        for page in resp.get("results") or []:
            yield page
        if not resp.get("has_more"):
            return
        cursor = resp.get("next_cursor")
        if not cursor:
            return


# ---- blocks ----------------------------------------------------------------

def _get_blocks(page_id: str, token: str) -> list[dict[str, Any]]:
    """Fetch every child block of a page, recursing into children as needed.

    Returns a flat list of blocks in document order. Each block is annotated
    with the keys chunk_by_headings expects: `type` and `plain_text`.
    """
    out: list[dict[str, Any]] = []
    _walk_blocks(page_id, token, out, depth=0)
    return out


def _walk_blocks(
    parent_id: str,
    token: str,
    out: list[dict[str, Any]],
    depth: int,
    max_depth: int = 4,
) -> None:
    if depth > max_depth:
        return
    cursor: str | None = None
    while True:
        params = {"page_size": PAGE_SIZE}
        if cursor:
            params["start_cursor"] = cursor
        resp = _request("GET", f"/blocks/{parent_id}/children", token, params=params)
        for block in resp.get("results") or []:
            flat = _flatten_block(block, depth)
            if flat is not None:
                out.append(flat)
            if block.get("has_children"):
                # Recurse — but don't recurse into child_page (that's a
                # separate Notion page in its own right; we'll reach it via
                # /search). Child databases are skipped too.
                btype = block.get("type")
                if btype in ("child_page", "child_database"):
                    continue
                _walk_blocks(block["id"], token, out, depth + 1, max_depth)
        if not resp.get("has_more"):
            return
        cursor = resp.get("next_cursor")
        if not cursor:
            return


def _rich_text_to_plain(rts: list[dict[str, Any]] | None) -> str:
    if not rts:
        return ""
    return "".join(rt.get("plain_text") or "" for rt in rts)


def _flatten_block(block: dict[str, Any], depth: int) -> dict[str, Any] | None:
    """Reduce a Notion block to {type, plain_text} or None if skippable."""
    btype = block.get("type")
    if not btype:
        return None
    payload = block.get(btype) or {}

    if btype in HEADING_TYPES:
        return {"type": btype, "plain_text": _rich_text_to_plain(payload.get("rich_text"))}
    if btype == "heading_3":
        # Treat H3 as a bolded prefix within its parent chunk rather than a
        # chunk boundary — keeps chunks from fragmenting too aggressively.
        text = _rich_text_to_plain(payload.get("rich_text"))
        return {"type": "paragraph", "plain_text": f"**{text}**"} if text else None
    if btype in TEXT_BLOCK_TYPES:
        text = _rich_text_to_plain(payload.get("rich_text"))
        if btype == "to_do":
            checked = "x" if payload.get("checked") else " "
            text = f"[{checked}] {text}"
        if btype == "bulleted_list_item":
            text = f"- {text}"
        elif btype == "numbered_list_item":
            text = f"1. {text}"
        elif btype == "quote":
            text = f"> {text}"
        elif btype == "code":
            lang = payload.get("language") or ""
            text = f"```{lang}\n{text}\n```"
        # Preserve indentation for nested blocks so chunk bodies read naturally.
        if depth > 0 and text:
            text = ("  " * depth) + text
        return {"type": "paragraph", "plain_text": text} if text else None

    # Skippable types: image, file, divider, table_of_contents, embed, etc.
    # They carry no ingestible text content.
    return None


# ---- titles / metadata -----------------------------------------------------

def _page_title(page: dict[str, Any]) -> str:
    """Extract a page's title regardless of whether it's a top-level page or
    a row in a database. Falls back to '(untitled)' if nothing resolves."""
    props = page.get("properties") or {}
    # Database rows: find the 'title' property (its key is user-chosen).
    for v in props.values():
        if isinstance(v, dict) and v.get("type") == "title":
            t = _rich_text_to_plain(v.get("title"))
            if t.strip():
                return t.strip()
    # Top-level page has a single 'title' property literally named 'title'.
    title = props.get("title")
    if isinstance(title, dict):
        t = _rich_text_to_plain(title.get("title"))
        if t.strip():
            return t.strip()
    return "(untitled)"


def _parent_info(page: dict[str, Any]) -> tuple[str | None, str | None]:
    parent = page.get("parent") or {}
    ptype = parent.get("type")
    if ptype == "database_id":
        return parent.get("database_id"), None  # title resolved lazily if needed
    if ptype == "page_id":
        return None, parent.get("page_id")
    return None, None


# ---- main sync -------------------------------------------------------------

def sync(
    kb_dir: Path,
    *,
    full: bool = False,
    max_pages: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch Notion pages and return a flat list of Item JSONs."""
    token = _load_token(kb_dir)
    if not token:
        print(
            "[notion] no token configured; skipping. "
            "Add to .engram/sources.json: {\"notion\": {\"token\": \"secret_...\"}}",
            file=sys.stderr,
        )
        return []

    meta = _load_meta(kb_dir)
    last_synced_at = None if full else meta.get("last_synced_at")

    # Collect page ids we've already emitted items for. A newly-shared page
    # may have last_edited_time < last_synced_at, but if we have no chunks
    # for it yet we still need to fetch it. Only pages we've _seen before_
    # can be safely skipped by the last_edited filter.
    known_page_ids: set[str] = set()
    if last_synced_at:
        for it in load_items(kb_dir / "raw" / "items.jsonl"):
            if it.get("source") == SOURCE_ID:
                pid = (it.get("metadata") or {}).get("page_id")
                if pid:
                    known_page_ids.add(pid)
        print(
            f"[notion] incremental: {len(known_page_ids)} known page(s); "
            f"re-syncing any edited since {last_synced_at} or not yet indexed",
            file=sys.stderr,
        )
    else:
        print("[notion] full sync", file=sys.stderr)

    all_items: list[Item] = []
    pages_seen = 0
    pages_changed = 0

    for page in _search_pages(token):
        pages_seen += 1
        if max_pages is not None and pages_seen > max_pages:
            break
        if page.get("archived"):
            # Drop any existing chunks from an archived page.
            drop_items_by_id_prefix(kb_dir, f"{SOURCE_ID}:{page['id']}:")
            continue

        last_edited = page.get("last_edited_time") or ""
        # Skip only if we've already indexed this page AND it hasn't changed.
        if (
            last_synced_at
            and last_edited
            and last_edited <= last_synced_at
            and page["id"] in known_page_ids
        ):
            continue

        try:
            blocks = _get_blocks(page["id"], token)
        except Exception as exc:
            print(f"[notion] page {page['id']} fetch failed: {exc}", file=sys.stderr)
            continue

        # Drop stale chunks for this page before emitting fresh ones.
        drop_items_by_id_prefix(kb_dir, f"{SOURCE_ID}:{page['id']}:")

        chunks = chunk_by_headings(blocks, heading_levels=HEADING_TYPES)
        # If there were no headings AND the single chunk is big, re-chunk by size.
        if len(chunks) == 1 and chunks[0].title is None and len(chunks[0].body) > 6000:
            chunks = chunk_by_size(chunks[0].body, max_chars=4000)

        # Skip TOC-style pages whose body is entirely subpage links —
        # Notion returns child_page blocks with no text content, so every
        # chunk body is empty. Keep the page if at least one chunk has body.
        if not any(c.body.strip() for c in chunks):
            continue

        title = _page_title(page)
        db_id, _parent_page = _parent_info(page)
        created_by = ((page.get("created_by") or {}).get("id")) or None
        last_edited_by = ((page.get("last_edited_by") or {}).get("id")) or None

        items = make_chunk_items(
            source=SOURCE_ID,
            parent_id=page["id"],
            parent_title=title,
            chunks=chunks,
            author=None,
            url=page.get("url"),
            timestamp=last_edited,
            base_metadata={
                "page_id": page["id"],
                "page_title": title,
                "parent_db_id": db_id,
                "created_time": page.get("created_time"),
                "last_edited_time": last_edited,
                "created_by": created_by,
                "last_edited_by": last_edited_by,
            },
        )
        all_items.extend(items)
        pages_changed += 1

    # Stamp a fresh sync cursor.
    now = datetime.now(timezone.utc).isoformat()
    _write_meta(kb_dir, {
        "last_synced_at": now,
        "last_run_pages_seen": pages_seen,
        "last_run_pages_changed": pages_changed,
    })

    print(
        f"[notion] {pages_seen} page(s) seen · {pages_changed} changed · "
        f"{len(all_items)} chunk(s) emitted",
        file=sys.stderr,
    )
    return [it.to_json() for it in all_items]


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Dump Notion pages as chunked Items.")
    ap.add_argument("--kb", type=Path, default=Path.cwd())
    ap.add_argument("--full", action="store_true", help="Ignore incremental cursor")
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--limit", type=int, default=5, help="Print first N items as a preview")
    args = ap.parse_args()

    items = sync(args.kb, full=args.full, max_pages=args.max_pages)
    print(f"[notion] {len(items)} item(s) total")
    for it in items[: args.limit]:
        meta = it.get("metadata") or {}
        print(
            f"  {it['id']} · {meta.get('page_title')!r} "
            f"chunk {meta.get('chunk_index')}/{meta.get('chunk_count')} "
            f"· {len(it['text'])} chars"
        )
