---
description: Schedule /kb-sync to run automatically on a cadence (Claude Code cron)
argument-hint: [--every <dur>] [--at <HH:MM>] [--sources x,chatgpt,...]
---

The user wants this KB to sync automatically in the background using Claude Code's cron mechanism.

Parse `$ARGUMENTS` into:
- `--every <dur>`: `30m`, `6h`, `24h` → cron expression. E.g. `6h` → `0 */6 * * *`, `30m` → `*/30 * * * *`.
- `--at <HH:MM>`: daily at a specific local time → `MM HH * * *`.
- `--sources`: comma-separated source list; default is `all`.

Exactly one of `--every` or `--at` must be provided. If neither, ask the user.

The current working directory should be a KB (contain `CLAUDE.md`). Capture `$(pwd)` as the KB path at schedule time — the cron job needs an absolute path.

Use the `CronCreate` tool with:

- **command** the agent should run when it fires: a short natural-language instruction like `Run /kb-sync --source <sources> in <kb-path>, then /kb-ingest if any new items appeared.`
- **schedule** as the cron expression derived above.
- **name** like `personal-wiki autosync: <kb-folder-name>`.

Record what was scheduled in `<kb>/.engram/autosync.json`:

```json
{"cron_id": "<id-from-CronCreate>", "schedule": "<cron-expr>", "sources": "<sources>", "kb": "<abs-path>"}
```

Tell the user:
- What was scheduled (human-readable: "every 6 hours" / "daily at 09:00").
- That they can check status with `/kb-autosync-status` and cancel with `/kb-disable-autosync`.
- Cookie expiry reminder: "If your ChatGPT / Claude.ai session expires, the sync will fail silently — rerun `/kb-sync --source chatgpt` interactively to re-approve the keychain dialog."
