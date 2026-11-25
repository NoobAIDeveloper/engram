---
description: Configure a new data source (GitHub, etc.) for this KB
argument-hint: "<source-name> [source-specific args]"
---

The user wants to enable a new data source for the current KB. Supported source names: `github-stars`, `claude-code`, `browser-bookmarks`, `kindle`, `chatgpt`, `claude-ai`, `notion`.

The current working directory should be a KB (contain `CLAUDE.md`). If not, tell them to `cd` into their KB first or run `/engram:kb-init`.

## How to configure each source

Read `$(pwd)/.engram/sources.json` (create if missing, JSON object root). Add the relevant block and write the file back.

`sources.json` can hold API tokens. Whenever you write a token into it, make sure the KB's `.gitignore` contains the line `.engram/sources.json` (KBs created by older versions do not) and add it if missing. Never echo a token back to the user or into `wiki/log.md`.

### `github-stars`
Ask the user for their GitHub handle if `$ARGUMENTS` didn't include one. Merge into `sources.json`:

```json
{"github": {"handle": "their-handle"}}
```


After updating `sources.json`, tell them to run `/engram:kb-sync --source github-stars`.

### `claude-code`
No config required — the adapter discovers sessions automatically. Just tell them to run `/engram:kb-sync --source claude-code`. Warn that by default sessions from this KB's own directory are skipped; they can override with `--include-self`.

### `browser-bookmarks`
No config required. Tell them to run `/engram:kb-sync --source browser-bookmarks`.

### `kindle`
One-shot import, not an ongoing sync. Tell the user to:
1. Plug their Kindle in via USB.
2. Find the `My Clippings.txt` file on the Kindle drive.
3. Run `/engram:kb-sync --source kindle --clippings /path/to/My\ Clippings.txt`.

### `chatgpt`
No config required — cookies are extracted from the user's browser. Tell them to:
1. Make sure they're logged in at https://chatgpt.com in their default browser.
2. Run `/engram:kb-sync --source chatgpt`.

Privacy note: pulls Q+A pairs from the user's ChatGPT history into `raw/items.jsonl`. If the live sync ever breaks (Cloudflare, cookie expiry), the fallback is `/engram:kb-request-chatgpt-export` → `/engram:kb-import-chatgpt <zip>`.

### `claude-ai`
No config required — same cookie-based approach as ChatGPT. Tell them to:
1. Make sure they're logged in at https://claude.ai.
2. Run `/engram:kb-sync --source claude-ai`.

Fallback if live sync breaks: export from Settings → Account → Export Account Data, then run `/engram:kb-import-claude <zip>`.

### `notion`
Notion uses an internal integration token, not cookies. Walk the user through:

1. Go to https://notion.so/my-integrations and click **+ New integration**.
2. Give it a name (e.g. "engram"), pick the workspace, submit. Capabilities can stay at the defaults (read content is enough).
3. Copy the **Internal Integration Secret** (starts with `secret_` or `ntn_`).
4. Merge it into `.engram/sources.json`:
   ```json
   {"notion": {"token": "secret_..."}}
   ```
5. In Notion, open each page or database they want indexed → click the `•••` menu → **Connections** → add the integration. Access is additive: nested pages inherit from their parent.

Long pages are split along H1/H2 headings into multiple chunks; pages without headings fall back to size-based windowing. Each chunk becomes its own item so a 10k-word doc still surfaces all of its content to synthesis.

Privacy note: during `/engram:kb-ingest`, page content is sent to Anthropic's API (same as every other source). Anything the user doesn't want synthesized should not be shared with the integration in Notion's UI.

After updating `sources.json`, tell them to run `/engram:kb-sync --source notion`.
