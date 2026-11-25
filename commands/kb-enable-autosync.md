---
description: Schedule kb-sync to run automatically while Claude Code is open
argument-hint: "[--every <dur>] [--at <HH:MM>] [--sources x,chatgpt,...]"
---

The user wants this KB to sync on a schedule using Claude Code's scheduled-task tool (`CronCreate`).

**Be upfront about what this is before scheduling.** Claude Code scheduled tasks are session-scoped: they fire only while Claude Code is running and idle on this machine, and recurring tasks expire on their own (after 7 days on older Claude Code versions, 30 days on newer ones). This is a convenience for people who keep Claude Code open — not an always-on background service. Say so in one sentence, then proceed.

Parse `$ARGUMENTS` into:
- `--every <dur>`: `30m`, `6h`, `24h` → cron expression. E.g. `6h` → `0 */6 * * *`, `30m` → `*/30 * * * *`.
- `--at <HH:MM>`: daily at a specific local time → `MM HH * * *`.
- `--sources`: comma-separated source list; default is `all`.

Exactly one of `--every` or `--at` must be provided. If neither, ask the user.

The current working directory should be a KB (contain `CLAUDE.md` and `.engram/`). Capture `$(pwd)` as the absolute KB path at schedule time.

Create the task with `CronCreate`. Check that tool's own parameter schema (load it first if it is deferred) and pass:

- the 5-field cron expression derived above,
- recurring: yes,
- a prompt for the run, with the absolute path filled in: `In <kb-path>, run: bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" scripts/sync.py --kb <kb-path> --source <sources>. Report the per-source counts in one line. Do not run ingest.`

If `CronCreate` is not available in this session, say so and stop — do not improvise with OS cron or launchd unless the user asks.

Record what was scheduled in `<kb>/.engram/autosync.json` (use whatever id `CronCreate` returned):

```json
{"cron_id": "<id>", "schedule": "<cron-expr>", "sources": "<sources>", "kb": "<abs-path>", "created": "<YYYY-MM-DD>"}
```

Tell the user:
- What was scheduled (human-readable: "every 6 hours" / "daily at 09:00"), and that it only runs while Claude Code is open and will expire.
- That they can check it with `/engram:kb-autosync-status` and cancel with `/engram:kb-disable-autosync`.
- Cookie-based sources (X, ChatGPT, Claude.ai) fail when the browser session expires — if an autosync run reports an auth error, log back in to that site in the browser and run `/engram:kb-sync` once by hand.
