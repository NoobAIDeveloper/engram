---
description: Show the scheduled auto-sync for this KB (next run, last run)
---

The user wants to see whether autosync is configured for the current KB.

1. Read `<kb>/.engram/autosync.json`. If missing, tell the user no autosync is scheduled.
2. Otherwise, call `CronList` and look up the entry with the matching `cron_id`. Report: schedule (human-readable), next fire time if shown, and the source list.
3. If the id is **not** in `CronList`, the task has expired or belonged to an earlier Claude Code session (scheduled tasks are session-scoped and recurring ones expire automatically). Say so plainly and offer to re-create it with `/engram:kb-enable-autosync`.
4. Also report the most recent sync per source from `<kb>/.engram/*sync-meta.json` (e.g. `sync-meta.json` for X, `chatgpt-sync-meta.json`, `claude-ai-sync-meta.json`, `notion-sync-meta.json`), whichever exist.

Read-only apart from the tool calls above.
