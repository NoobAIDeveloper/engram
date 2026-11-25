---
description: Show sync and ingest stats for the current KB
---

The user wants a quick status readout. The current working directory should be a engram KB (it should contain a `CLAUDE.md` and a `.engram/` subdirectory). If it doesn't, tell the user to `cd` into their KB first or run `/engram:kb-init` to scaffold one.

There's no dedicated stats script — compute it yourself from files on disk:

- **Items**: line count of `raw/items.jsonl`, broken down by the `source` field (a one-line `python3 -c` over the file is fine). On older KBs that only have `raw/bookmarks.jsonl`, use its line count as the X count. Treat missing / empty as 0.
- **Last sync**: per source, from whichever `.engram/*sync-meta.json` files exist (`sync-meta.json` is X: `lastSyncAt`, `totalBookmarks`). "never synced" if there are none.
- **Topics**: count and names from `.engram/cluster-map.json`, or "not clustered yet" if the file is missing.
- **Wiki pages**: count of `wiki/*.md` (exclude `index.md`, `log.md`, and anything under `wiki/queries/`, which you can report separately).
- **Last ingest**: newest timestamp from `.engram/ingest-state.json`, or "never ingested" if missing.

Present it as a short bulleted summary. Then surface the obvious next action:

- If the newest sync is older than a few days, suggest `/engram:kb-sync`.
- If the item count exceeds what `ingest-state.json` reflects (or ingest-state is missing), suggest `/engram:kb-ingest`.
- If `_unsorted.md` exists and has a non-trivial count, mention it and suggest `/engram:kb-recluster`.

Never print the contents of `.engram/sources.json` — it can hold API tokens.

Read-only command — don't write anything.
