---
description: Sync data from one or more configured sources into this KB
argument-hint: [--source x|claude-code|chatgpt|claude-ai|notion|granola|browser-bookmarks|github-stars|kindle|all] [source-specific flags]
---

The user wants to sync data into the current KB. The current working directory should be a KB (it should contain a `CLAUDE.md` and a `.engram/` subdirectory). If it doesn't, tell the user to `cd` into their KB first or run `/engram:kb-init` to scaffold one.

Run the sync dispatcher:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/engram-py" scripts/sync.py --kb "$(pwd)" $ARGUMENTS
```

Supported sources:

- **x** (default) — Twitter/X bookmarks via browser cookies. Flags: `--browser auto|chrome|brave|edge`, `--full`, `--max-pages N`.
- **claude-code** — Local Claude Code chat sessions from `~/.claude/projects/`. Flag: `--include-self` to include sessions from this KB's own directory.
- **chatgpt** — ChatGPT conversations via browser cookie (`__Secure-next-auth.session-token`). Flags: `--browser`, `--full`. Fragile — if it breaks, use `/engram:kb-import-chatgpt` with an export zip.
- **claude-ai** — Claude.ai conversations via browser cookie (`sessionKey`). Flags: `--browser`, `--full`. Fragile — if it breaks, use `/engram:kb-import-claude` with an export zip.
- **notion** — Pages shared with the Notion integration token in `.engram/sources.json` (set up with `/engram:kb-add-source`).
- **granola** — Granola meeting notes (set up with `/engram:kb-add-source`). Newer Granola versions encrypt the local cache; if the script reports that, relay its message as-is.
- **browser-bookmarks** — Chrome/Brave/Edge saved bookmarks (local JSON files, all profiles).
- **github-stars** — Public GitHub stars for the handle in `.engram/sources.json`. Set `GITHUB_TOKEN` env for higher rate limit.
- **kindle** — One-shot import. Requires `--clippings <path-to-My Clippings.txt>`.
- **all** — Run all configured sources in one go (kindle is skipped unless `--clippings` is given).

All sources write into the shared `raw/items.jsonl`. The X source also maintains `raw/bookmarks.jsonl` for incremental sync via snowflake ids. Stdout is a one-line summary per source; stderr is verbose progress.

After it finishes:

- **Success with new items:** report the count per source and suggest `/engram:kb-ingest` to weave them into the wiki.
- **Success with no new items:** say so plainly.
- **X auth error (exit 4):** cookies are stale — log out and back into X, then retry.
- **X private API changed (exit 6):** the plugin needs updating — `claude plugin update engram@engram`. Don't retry.
- **"sync incomplete":** an error hit part-way; what was fetched is saved and a re-run continues from there.
- **Keychain dialog timeout (macOS):** the user has 2 minutes to approve. Rerun and tell them to click **Always Allow**.
- **GitHub 404:** the handle in `sources.json` is wrong.
- **Rate limit / no browser / missing clippings file:** surface the script's error.

Do NOT auto-run `/engram:kb-ingest` after sync — let the user decide.
