---
description: Configure a new data source (GitHub, etc.) for this KB
argument-hint: <source-name> [source-specific args]
---

The user wants to enable a new data source for the current KB. Supported source names: `github-stars`, `claude-code`, `browser-bookmarks`, `kindle`, `chatgpt`, `claude-ai`, `notion`, `granola`.

The current working directory should be a KB (contain `CLAUDE.md`). If not, tell them to `cd` into their KB first or run `/kb-init`.

## How to configure each source

Read `$(pwd)/.engram/sources.json` (create if missing, JSON object root). Add the relevant block, then commit with an atomic write.

### `github-stars`
Ask the user for their GitHub handle if `$ARGUMENTS` didn't include one. Merge into `sources.json`:

```json
{"github": {"handle": "their-handle"}}
```

Optionally mention: setting `GITHUB_TOKEN` env var raises the rate limit from 60/hr to 5000/hr. They can do this in their shell profile — don't ask them to paste a token here.

After updating `sources.json`, tell them to run `/kb-sync --source github-stars`.

### `claude-code`
No config required — the adapter discovers sessions automatically. Just tell them to run `/kb-sync --source claude-code`. Warn that by default sessions from this KB's own directory are skipped; they can override with `--include-self`.

### `browser-bookmarks`
No config required. Tell them to run `/kb-sync --source browser-bookmarks`.

### `kindle`
One-shot import, not an ongoing sync. Tell the user to:
1. Plug their Kindle in via USB.
2. Find the `My Clippings.txt` file on the Kindle drive.
3. Run `/kb-sync --source kindle --clippings /path/to/My\ Clippings.txt`.

### `chatgpt`
No config required — cookies are extracted from the user's browser. Tell them to:
1. Make sure they're logged in at https://chatgpt.com in their default browser.
2. Run `/kb-sync --source chatgpt`.

Privacy note: pulls Q+A pairs from the user's ChatGPT history into `raw/items.jsonl`. If the live sync ever breaks (Cloudflare, cookie expiry), the fallback is `/kb-request-chatgpt-export` → `/kb-import-chatgpt <zip>`.

### `claude-ai`
No config required — same cookie-based approach as ChatGPT. Tell them to:
1. Make sure they're logged in at https://claude.ai.
2. Run `/kb-sync --source claude-ai`.

Fallback if live sync breaks: export from Settings → Account → Export Account Data, then run `/kb-import-claude <zip>`.

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

Privacy note: during `/kb-ingest`, page content is sent to Anthropic's API (same as every other source). Anything the user doesn't want synthesized should not be shared with the integration in Notion's UI.

After updating `sources.json`, tell them to run `/kb-sync --source notion`.

### `granola`
macOS-only. Granola stores every meeting in a local JSON cache at `~/Library/Application Support/Granola/cache-v6.json` (older builds used v3/v5; the adapter resolves whichever is newest). No API, no token, no browser cookies — if the cache is in the default location, no path config is needed.

Walk the user through ONE question. Present the options as a numbered list and let them reply with a letter, a number, or the mode name. If their reply is ambiguous or empty, default to `both` and tell them you've done so.

> What do you want ingested per meeting?
>
> [a] **Notes only** — just what you typed in the Granola editor.
> [b] **Transcript only** — raw dialogue captured from mic + system audio.
> [c] **Both** — notes first, then transcript appended. *(recommended)*
> [d] **Auto** — notes if you typed anything substantive (>200 chars), otherwise transcript.

Map their answer to a mode string: `notes` | `transcript` | `both` | `auto`. Then merge into `.engram/sources.json`:

```json
{"granola": {"content_mode": "<chosen-mode>"}}
```

If the user volunteers that their cache lives somewhere unusual (moved drive, backup, multiple Granola installs), also set `cache_path` in the same `granola` block:

```json
{"granola": {"content_mode": "both", "cache_path": "/path/to/cache-v6.json"}}
```

Don't volunteer `cache_path` unprompted — most users don't need it.

Chunking behavior given the chosen mode: `notes` and `transcript` produce a single stream of chunks. `both` emits notes chunks first (heading-split) followed by transcript chunks (size-windowed) under a single `granola:<doc_id>:<chunk_index>` id family. `auto` picks notes if it's substantive, else transcript, else both as a last resort. Meetings with no usable content in the chosen stream(s) are skipped.

Privacy note: meeting content is sent to Anthropic's API during `/kb-ingest` for synthesis, same as every other source. If the user is squeamish about transcript text leaving their machine, steer them to `notes` mode.

After updating `sources.json`, tell them to run `/kb-sync --source granola`.

## After configuring

Don't automatically run the sync — let the user trigger it. But say exactly which `/kb-sync` invocation they should use next.
