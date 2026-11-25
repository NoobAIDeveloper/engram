#!/usr/bin/env python3
"""
Claude Code chat source adapter.

Walks `~/.claude/projects/*/<session-id>.jsonl`, pairs each real user prompt
with the assistant's text reply(s) that follow it, and emits one Item per
Q+A pair.

Sidechain messages (subagent conversations), tool_result messages, and
file-history snapshots are skipped — they're not user-authored knowledge.

The KB's own Claude Code sessions are skipped by default so a wiki about
"my engram work" doesn't pollute itself with self-references. Override
with include_self=True if desired.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

from .base import Item


SOURCE_ID = "claude-code"
PROJECTS_DIR = Path.home() / ".claude" / "projects"

# Hard caps so a single mega-session can't dominate the corpus.
MAX_USER_LEN = 4000
MAX_ASSISTANT_LEN = 4000


def _extract_assistant_text(msg: dict[str, Any]) -> str:
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            t = block.get("text") or ""
            if t:
                parts.append(t)
    return "\n\n".join(parts)


# Harness-generated "user" records: task notifications, slash-command
# plumbing, local shell echo, injected reminders, interrupt markers. None of
# these were typed by the human, so they never start a Q+A pair.
_HARNESS_PREFIXES = (
    "<task-notification>",
    "<local-command-caveat>",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<command-name>",
    "<command-message>",
    "<command-args>",
    "<command-contents>",
    "<system-reminder>",
    "<bash-input>",
    "<bash-stdout>",
    "<bash-stderr>",
    "<scheduled-task",
    "<user-prompt-submit-hook>",
    "<teammate-message",
    "Caveat:",
    "[Request interrupted",
)


def _is_harness_text(text: str) -> bool:
    return text.lstrip().startswith(_HARNESS_PREFIXES)


def _user_prompt_text(rec: dict[str, Any]) -> str:
    """Return the human-typed prompt text of a record, or "" if the record
    is not a real user prompt (tool result, harness wrapper, sidechain,
    meta/compaction record, slash-command invocation)."""
    if rec.get("type") != "user":
        return ""
    if rec.get("isSidechain") or rec.get("isMeta") or rec.get("isCompactSummary"):
        return ""
    msg = rec.get("message")
    if not isinstance(msg, dict):
        return ""
    content = msg.get("content")
    if isinstance(content, str):
        text = content.strip()
        return "" if _is_harness_text(text) else text
    if not isinstance(content, list):
        return ""
    # List content: tool results arrive as tool_result blocks; real prompts
    # are text blocks, optionally alongside image blocks.
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "tool_result":
            return ""
        if btype == "text":
            t = block.get("text")
            if isinstance(t, str) and t.strip() and not _is_harness_text(t):
                parts.append(t.strip())
    return "\n\n".join(parts)


def _is_real_user_prompt(rec: dict[str, Any]) -> bool:
    """True iff this is a human-typed prompt, not a tool result or wrapper."""
    return bool(_user_prompt_text(rec))


def _encode_project_path(path: str) -> str:
    # Claude Code names project dirs by replacing every non-alphanumeric
    # character of the cwd with "-" (so "/", ".", "_" and spaces all map).
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def _iter_session_files(skip_paths: Iterable[Path] = ()) -> Iterable[Path]:
    if not PROJECTS_DIR.exists():
        return
    skip_set = {str(p.resolve()) for p in skip_paths if p}
    for proj_dir in sorted(PROJECTS_DIR.iterdir()):
        if not proj_dir.is_dir():
            continue
        # The folder name is the encoded project path. Cheap skip for the
        # KB's own sessions.
        # Compared case-insensitively: on case-insensitive filesystems the
        # recorded cwd and the resolved KB path can differ in case.
        name = proj_dir.name.casefold()
        if any(name == _encode_project_path(s).casefold() for s in skip_set):
            continue
        for session in sorted(proj_dir.glob("*.jsonl")):
            yield session


def _project_label(session_path: Path, records: Iterable[dict[str, Any]] = ()) -> str:
    # Prefer the cwd recorded in the session itself: the folder encoding is
    # lossy ("twitter-wiki" and "twitter/wiki" both encode to "twitter-wiki").
    for rec in records:
        cwd = rec.get("cwd") if isinstance(rec, dict) else None
        if isinstance(cwd, str) and cwd.strip() and not rec.get("isSidechain"):
            name = os.path.basename(cwd.rstrip("/\\"))
            if name:
                return name
    # Fallback: ~/.claude/projects/-Users-bharat-Projects-engram/<uuid>.jsonl
    # → "engram" (last dash-separated component of the encoded cwd).
    folder = session_path.parent.name
    if folder.startswith("-"):
        folder = folder[1:]
    parts = folder.split("-")
    return parts[-1] if parts else folder


def _pair_turns(session_path: Path) -> list[Item]:
    session_id = session_path.stem
    # Folder name is already unique across the projects dir, so use it to
    # disambiguate session uuids that appear in multiple project subdirs.
    folder_tag = session_path.parent.name

    # Parse the file into an ordered list first so we can look ahead.
    records: list[dict[str, Any]] = []
    for line in session_path.read_text(encoding="utf-8", errors="replace").split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            records.append(rec)

    project = _project_label(session_path, records)

    items: list[Item] = []
    i = 0
    turn_index = 0
    while i < len(records):
        rec = records[i]
        user_text = _user_prompt_text(rec)
        if not user_text:
            i += 1
            continue
        if len(user_text) > MAX_USER_LEN:
            user_text = user_text[:MAX_USER_LEN] + "\n[...truncated]"
        user_ts = rec.get("timestamp") or ""

        # Collect assistant replies until the next real user prompt.
        assistant_parts: list[str] = []
        j = i + 1
        while j < len(records):
            nxt = records[j]
            if _is_real_user_prompt(nxt):
                break
            if (
                nxt.get("type") == "assistant"
                and not nxt.get("isSidechain")
                and isinstance(nxt.get("message"), dict)
            ):
                t = _extract_assistant_text(nxt["message"])
                if t.strip():
                    assistant_parts.append(t.strip())
            j += 1

        assistant_text = "\n\n".join(assistant_parts).strip()
        if len(assistant_text) > MAX_ASSISTANT_LEN:
            assistant_text = assistant_text[:MAX_ASSISTANT_LEN] + "\n[...truncated]"

        # Skip trivial turns (e.g. "continue", "ok") with no substantive reply.
        if len(user_text) < 20 and len(assistant_text) < 100:
            i = j
            continue

        body = f"**User:** {user_text}\n\n**Claude:** {assistant_text}" if assistant_text else f"**User:** {user_text}"

        items.append(
            Item(
                id=f"{SOURCE_ID}:{folder_tag}/{session_id}:{turn_index}",
                source=SOURCE_ID,
                text=body,
                timestamp=user_ts,
                author=None,
                url=None,
                engagement=None,
                media=[],
                metadata={
                    "conversation_id": session_id,
                    "turn_index": turn_index,
                    "project": project,
                },
            )
        )
        turn_index += 1
        i = j

    return items


def sync(kb_dir: Path | None = None, *, include_self: bool = False) -> list[dict[str, Any]]:
    """Collect all Q+A pairs from every Claude Code session on disk.

    By default, skips sessions whose project folder matches the KB's own
    path — otherwise the wiki fills up with meta-conversations about
    building the wiki. Pass include_self=True to override.
    """
    skip_paths: list[Path] = []
    if kb_dir and not include_self:
        skip_paths.append(kb_dir.expanduser().resolve())

    all_items: list[Item] = []
    for session in _iter_session_files(skip_paths=skip_paths):
        try:
            all_items.extend(_pair_turns(session))
        except (OSError, UnicodeDecodeError):
            continue
    return [it.to_json() for it in all_items]


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="List Claude Code Q+A pairs as Items.")
    ap.add_argument("--kb", type=Path, default=None)
    ap.add_argument("--include-self", action="store_true")
    ap.add_argument("--limit", type=int, default=5)
    args = ap.parse_args()

    items = sync(args.kb, include_self=args.include_self)
    print(f"[claude-code] {len(items)} Q+A pair(s)")
    for it in items[: args.limit]:
        print(f"  {it['id']} · {it['metadata']['project']} · {it['timestamp'][:10]} · {len(it['text'])} chars")
