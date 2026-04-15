---
description: Show the scheduled auto-sync for this KB (next run, last run)
---

The user wants to see whether autosync is configured for the current KB.

1. Read `<kb>/.twitter-wiki/autosync.json`. If missing, tell the user no autosync is scheduled.
2. Otherwise, call `CronList` and look up the entry with matching `cron_id`. Report: schedule (human-readable), next fire time, last run result if available, and the source list.
3. Also report the timestamp of the most recent successful sync by reading `<kb>/.twitter-wiki/sync-meta.json` (X) and `<kb>/.twitter-wiki/chatgpt-sync-meta.json` / `claude-ai-sync-meta.json` if they exist.
