---
description: Cancel the scheduled auto-sync for this KB
---

The user wants to stop the background auto-sync for the current KB.

Read `<kb>/.engram/autosync.json`. If missing, tell the user no autosync is scheduled for this KB.

Otherwise, call `CronDelete` with the `cron_id` from the file, then remove `autosync.json`. Confirm to the user.
