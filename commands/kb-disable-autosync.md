---
description: Cancel the scheduled auto-sync for this KB
---

The user wants to stop the scheduled auto-sync for the current KB.

Read `<kb>/.engram/autosync.json`. If missing, tell the user no autosync is scheduled for this KB.

Otherwise, call `CronDelete` with the `cron_id` from the file. If the task no longer exists (scheduled tasks are session-scoped and expire on their own), that is fine — treat it as already cancelled. Then remove `autosync.json` and confirm to the user.
