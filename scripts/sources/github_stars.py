#!/usr/bin/env python3
"""
GitHub stars source adapter.

Hits the public `GET /users/{user}/starred` endpoint (no auth required for
public stars) and emits one Item per starred repo.

Configuration: the user's GitHub handle is read from
`<kb>/.engram/sources.json` under the key `github.handle`. If that
file doesn't exist or doesn't specify a handle, this adapter is a no-op.

No token is used: the public endpoint allows 60 requests an hour without
authentication, which covers 6,000 stars per sync.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .base import Item


SOURCE_ID = "github-stars"
API = "https://api.github.com"
PAGE_SIZE = 100
MAX_PAGES = 50  # hard cap: 5000 stars


def _read_github_config(kb_dir: Path) -> dict[str, Any]:
    cfg = kb_dir / ".engram" / "sources.json"
    if not cfg.exists():
        return {}
    try:
        data = json.loads(cfg.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    gh = (data.get("github") or {}) if isinstance(data, dict) else {}
    return gh if isinstance(gh, dict) else {}


def _rate_limit_reset(headers: Any) -> str:
    """Human-readable "resets at ..." suffix from rate-limit headers."""
    try:
        reset = int(headers.get("x-ratelimit-reset") or 0)
    except (TypeError, ValueError, AttributeError):
        reset = 0
    if reset > 0:
        return " The limit resets at " + time.strftime("%H:%M:%S", time.localtime(reset)) + "."
    try:
        retry_after = int(headers.get("Retry-After") or 0)
    except (TypeError, ValueError, AttributeError):
        retry_after = 0
    return f" Retry in about {retry_after}s." if retry_after > 0 else ""


def _load_handle(kb_dir: Path) -> str | None:
    gh = _read_github_config(kb_dir)
    handle = gh.get("handle")
    return handle.strip().lstrip("@") if isinstance(handle, str) and handle.strip() else None


def _fetch_page(handle: str, page: int) -> list[dict[str, Any]]:
    url = f"{API}/users/{handle}/starred?per_page={PAGE_SIZE}&page={page}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github.v3.star+json",
            "User-Agent": "engram",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def sync(kb_dir: Path, *, handle: str | None = None) -> list[dict[str, Any]]:
    """Fetch all starred repos for the configured GitHub handle."""
    if handle is None:
        handle = _load_handle(kb_dir)
    if not handle:
        return []

    all_items: list[Item] = []
    for page in range(1, MAX_PAGES + 1):
        try:
            page_data = _fetch_page(handle, page)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise RuntimeError(
                    f"GitHub returned 404 for user {handle!r}. "
                    f"Check the handle in sources.json."
                )
            headers = exc.headers
            remaining = (headers.get("x-ratelimit-remaining") or "") if headers else ""
            retry_after = (headers.get("Retry-After") or "") if headers else ""
            # Primary limit: 403/429 with remaining == 0. Secondary limit:
            # 403/429 with Retry-After. Any other 403 is a permission issue.
            if exc.code == 429 or (
                exc.code == 403 and (remaining.strip() == "0" or retry_after.strip())
            ):
                raise RuntimeError(
                    f"GitHub rate-limited us ({exc.code})."
                    f"{_rate_limit_reset(headers)}"
                    " Unauthenticated requests are limited to 60 per hour."
                )
            if exc.code == 403:
                try:
                    detail = json.loads(exc.read().decode("utf-8")).get("message") or ""
                except Exception:
                    detail = ""
                raise RuntimeError(
                    f"GitHub refused the request (403) for user {handle!r}"
                    + (f": {detail}" if detail else ".")
                    + " This is not a rate limit."
                )
            raise
        if not page_data:
            break

        for entry in page_data:
            # With the v3.star+json Accept header, entries are
            # {"starred_at": ..., "repo": {...}}.
            if "repo" in entry:
                repo = entry.get("repo") or {}
                starred_at = entry.get("starred_at") or ""
            else:
                repo = entry
                starred_at = ""
            full_name = repo.get("full_name") or ""
            if not full_name:
                continue
            description = (repo.get("description") or "").strip()
            topics = repo.get("topics") or []
            lang = repo.get("language") or ""

            text_parts = [full_name]
            if description:
                text_parts.append(description)
            if topics:
                text_parts.append("Topics: " + ", ".join(topics))
            if lang:
                text_parts.append(f"Language: {lang}")

            all_items.append(
                Item(
                    id=f"{SOURCE_ID}:{repo.get('id') or full_name}",
                    source=SOURCE_ID,
                    text="\n".join(text_parts),
                    timestamp=starred_at,
                    author=(repo.get("owner") or {}).get("login"),
                    url=repo.get("html_url"),
                    engagement={"stars": repo.get("stargazers_count") or 0},
                    media=[],
                    metadata={
                        "repo": full_name,
                        "language": lang,
                        "topics": topics,
                        "archived": bool(repo.get("archived")),
                    },
                )
            )

        if len(page_data) < PAGE_SIZE:
            break
        time.sleep(0.3)  # be polite
    else:
        print(
            f"[github-stars] warning: stopped at the {MAX_PAGES}-page cap "
            f"({MAX_PAGES * PAGE_SIZE} stars); older stars were not fetched.",
            file=sys.stderr,
        )

    return [it.to_json() for it in all_items]


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Dump GitHub stars as Items.")
    ap.add_argument("--kb", type=Path, default=Path.cwd())
    ap.add_argument("--handle", help="Override handle from sources.json")
    ap.add_argument("--limit", type=int, default=5)
    args = ap.parse_args()

    items = sync(args.kb, handle=args.handle)
    print(f"[github-stars] {len(items)} starred repo(s)")
    for it in items[: args.limit]:
        print(f"  {it['metadata']['repo']} · ⭐{it['engagement']['stars']} · {it['metadata']['language']}")
