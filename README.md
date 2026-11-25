# engram

Turn your Twitter/X bookmarks, ChatGPT and Claude.ai conversations, Claude Code
sessions, browser bookmarks, GitHub stars, and Kindle highlights into a living,
interlinked knowledge base that you can actually read. A Claude Code plugin
plus a small set of Python scripts.

You bookmark things, chat with AI assistants, and star repos intending to come
back to them. You don't. This tool syncs all of it to your machine, clusters
the content into topics derived from *your* material, and asks Claude to
synthesize each cluster into an Obsidian wiki page — TLDR, inline author
attribution, direct quotes for high-engagement content, counter-arguments,
wikilinks to related pages.

It works for any domain. No hardcoded topic list. If you bookmark recipes you
get cooking pages; if you bookmark trades you get finance pages; if both, you
get both.

---

## How it works

```
sources       →  sync.py         →  raw/items.jsonl
(X, ChatGPT, Claude.ai,            (per-source adapters: cookies,
 Claude Code, bookmarks,            APIs, local logs, zip imports)
 GitHub stars, Kindle)

items         →  Claude          →  .engram/cluster-map.json
                 (samples your content, derives 8–20 topics)

cluster map   →  preprocess.py   →  raw/bookmarks/<topic>.md
                 (deterministic router, multi-assign)

unsorted      →  Haiku subagent  →  _classifications.json → re-route
 (optional)     (via Claude Code, not a separate API key)

batches       →  Claude          →  wiki/<topic>.md
                 (synthesis: TLDR + prose + counter-args + wikilinks)
```

Claude handles judgment (clustering, synthesis, prose). The scripts handle
mechanical work (auth, fetching, routing, linting). The `wiki/` directory is
Claude's. The `notes/` directory is yours — the skill never reads it.

---

## Requirements

- macOS or Linux (Windows not supported in v1 — cookie decryption uses DPAPI there).
- Python 3.10+.
- [Claude Code](https://claude.com/claude-code) installed and working.
- A browser (Chrome, Brave, or Edge) logged into x.com.
- Optional: [Obsidian](https://obsidian.md) to read the wiki. Plain markdown works too.

---

## Install

### Option A: Plugin marketplace (recommended)

```bash
claude plugin marketplace add NoobAIDeveloper/engram
claude plugin install engram@engram
```

That's it. The Python environment and dependencies are set up automatically
the first time a command runs (about 10 seconds, once). The only requirement
is Python 3.10+, which macOS and most Linux distros already have.

Commands are namespaced under the plugin: `/engram:kb-sync`, `/engram:kb-ingest`, …

**Updating:** `claude plugin update engram@engram`. X, ChatGPT and Claude.ai
change their private APIs without notice — if a sync starts failing, update
first.

**Installed before December 2026?** Older releases pinned a version number
that never changed, so your copy stopped receiving updates. Run the update
command above once; if it reports "already at the latest version", run
`claude plugin marketplace update engram` and try again. If you used the old
`./install.sh` (symlinks into `~/.claude/`), run the new `./install.sh` once
— it removes those links and installs the plugin properly.

### Option B: From a clone

```bash
git clone https://github.com/NoobAIDeveloper/engram ~/src/engram
cd ~/src/engram
./install.sh
```

`install.sh` just runs the two commands from Option A (and cleans up links
left by older versions). To hack on engram and run it straight from your
checkout, use `claude --plugin-dir ~/src/engram`.

Uninstall: `./install.sh --uninstall` or `claude plugin uninstall engram@engram`.

---

## Quickstart

```bash
# 1. Scaffold a KB. Do this from any shell.
claude
> /engram:kb-init ~/my-kb

# 2. Start a fresh Claude session inside the KB so CLAUDE.md loads.
cd ~/my-kb
claude

# 3. Pull bookmarks from your browser.
> /engram:kb-sync

# 4. Let Claude cluster + synthesize.
> /engram:kb-ingest
# On first run, Claude samples your bookmarks, derives 8–20 topics, and shows
# you the cluster map before proceeding. You get one round of edits.

# 5. Ask questions.
> /engram:kb-query what do people I follow say about prompt injection?

# 6. Health check.
> /engram:kb-lint
```

Open `~/my-kb` in Obsidian for the full experience (wikilink graph, page
preview). Plain markdown readers work too.

---

## Common workflows

**First-time setup with multiple sources.**
```
> /engram:kb-init ~/my-kb
> cd ~/my-kb && claude                  # fresh session so CLAUDE.md loads
> /engram:kb-add-source github-stars           # configure what needs config
> /engram:kb-sync --source all                 # pull everything
> /engram:kb-ingest                            # cluster + synthesize
```

**Daily-ish refresh.**
```
> /engram:kb-sync --source all
> /engram:kb-ingest                            # only regenerates changed batches
```

**Keep it fresh while you work.** Schedule a sync for whenever Claude Code is open:
```
> /engram:kb-enable-autosync --at 07:00 --sources x,chatgpt,claude-ai
```

**ChatGPT live sync blocked by Cloudflare.** Use the export path:
```
> /engram:kb-request-chatgpt-export            # OpenAI emails you a zip (hours)
> /engram:kb-import-chatgpt ~/Downloads/<zip>  # ingest when it arrives
```

**Topics feel wrong.** Re-cluster with a hint:
```
> /engram:kb-recluster merge business and entrepreneurship
```

**Ask the wiki a question.**
```
> /engram:kb-query what's the consensus in my bookmarks on RAG vs long-context?
```

---

## Data sources

| Source | Config | How it syncs |
|---|---|---|
| `x` | none | Browser cookies → X's internal GraphQL. Default source. |
| `chatgpt` | none | Browser cookies → ChatGPT's backend API. Q+A pairs extracted from conversation history. Fallback: `/engram:kb-request-chatgpt-export` + `/engram:kb-import-chatgpt <zip>`. |
| `claude-ai` | none | Browser cookies → Claude.ai's backend API. Fallback: manual export + `/engram:kb-import-claude <zip>`. |
| `claude-code` | none | Reads local Claude Code session logs under `~/.claude/projects/`. |
| `notion` | integration token | Notion v1 REST API as an internal integration. Long pages split along H1/H2 into chunks. Access is scoped per-page in Notion's UI. |
| `granola` | optional `content_mode`, `use_api` (macOS only) | Reads Granola's local `cache-v*.json`. By default ingests notes + transcript per meeting (notes heading-chunked, transcript size-windowed). Set `granola.content_mode` to `notes`, `transcript`, `both`, or `auto` in `.engram/sources.json`. `granola.use_api` (default `true`) additionally fetches the AI-enhanced summary from Granola's internal API when available (auth auto-detected from `supabase.json`); works on both free and paid plans, paid users get the richest content. |
| `browser-bookmarks` | none | Reads Chrome/Brave/Edge bookmark JSON. |
| `github-stars` | GitHub handle | Public API. `GITHUB_TOKEN` env var optional for higher rate limit. |
| `kindle` | `--clippings` path | One-shot import from `My Clippings.txt` on the Kindle drive. |

Run `/engram:kb-sync --source <name>` or `/engram:kb-sync --source all`. For most sources, `/engram:kb-add-source <name>` walks you through the dialog interactively. The two sources below need a one-time external setup step before the wizard can finish.

### Notion setup

Notion needs an internal integration token (cookies don't work — Notion's API is auth'd separately).

1. Go to <https://notion.so/my-integrations> and click **+ New integration**.
2. Name it (e.g. `engram`), pick the workspace, submit. Default capabilities (read content) are enough.
3. Copy the **Internal Integration Secret** — starts with `secret_` or `ntn_`.
4. Run `/engram:kb-add-source notion` from your KB and paste the token when asked, or write it directly:
   ```json
   {"notion": {"token": "secret_..."}}
   ```
   in `.engram/sources.json`.
5. In Notion, open each page or database you want indexed → `•••` menu → **Connections** → add the integration. Nested pages inherit access.
6. `/engram:kb-sync --source notion`.

Long pages split along H1/H2 headings into multiple chunks; pages without headings fall back to size-based windowing.

### Granola setup

> **Status (Nov 2026): currently broken on up-to-date Granola.** Since mid-2026
> the Granola desktop app encrypts its local cache (`cache-v*.json.enc`) and
> keeps the key in an app-only Keychain item, so engram can no longer read
> meetings from disk. The sync now detects this and says so instead of
> reporting "0 meetings". Everything below describes the adapter as it works
> against older, unencrypted caches. Moving to Granola's official API or
> export is tracked as follow-up work.

macOS only. Granola stores meetings in `~/Library/Application Support/Granola/cache-v*.json`. **No token paste required** — the WorkOS auth token is auto-detected from Granola's own `supabase.json`. Just install Granola and record at least one meeting.

`/engram:kb-add-source granola` asks two questions:

1. **What to ingest** (`content_mode`):
   - `notes` — only what you typed
   - `transcript` — only the raw dialogue
   - `both` (default) — notes first, transcript appended
   - `auto` — notes if substantive (>200 body chars), else transcript

2. **Use Granola's API for AI-enhanced summaries** (`use_api`, default yes): pulls the richer AI-generated summary panel that doesn't persist to the local cache. Works on both free and paid plans; paid users get the most enhanced content. Set to `no` for purely local operation, no network calls.

Then `/engram:kb-sync --source granola`. Re-running after editing/recording new meetings is incremental.

---

## Slash commands

Every command is run from inside a Claude Code session. `/engram:kb-init` is the only
one you can run from outside a KB — all the others expect you to be `cd`'d into
a KB directory so `CLAUDE.md` loads.

### Setup

**`/engram:kb-init <path> [--no-obsidian] [--no-git] [--force]`**
Scaffolds a new KB at `<path>` — directory tree, `CLAUDE.md`, `.gitignore`,
Obsidian vault config. Run once per KB, from anywhere.
```
> /engram:kb-init ~/my-kb
```

**`/engram:kb-add-source <source-name>`**
Walks you through per-source config. Most sources need nothing (cookies
handle auth); `github-stars` needs your handle, `kindle` needs a clippings
path. Writes to `.engram/sources.json`.
```
> /engram:kb-add-source github-stars
> /engram:kb-add-source kindle --clippings "/Volumes/Kindle/documents/My Clippings.txt"
```

### Sync

**`/engram:kb-sync [--source <name>] [--full] [--browser chrome|brave|edge]`**
Pulls data from one or more configured sources. Default source is `x`.
Use `--source all` to run every configured source, or name one explicitly.
Incremental by default — only new items. Pass `--full` to re-pull everything.
```
> /engram:kb-sync                          # just X bookmarks
> /engram:kb-sync --source chatgpt         # only ChatGPT
> /engram:kb-sync --source all             # every configured source
> /engram:kb-sync --source x --full        # ignore cursor, refetch
```

**`/engram:kb-request-chatgpt-export`**
Fallback when `/engram:kb-sync --source chatgpt` is Cloudflare-blocked. POSTs to
OpenAI's data-export endpoint so they email you a zip. Wait for the email
(can take hours), then run `/engram:kb-import-chatgpt` on the downloaded file.

**`/engram:kb-import-chatgpt <path-to-export.zip>`**
Ingests an OpenAI-issued ChatGPT export zip. Use when live sync fails or
you want a guaranteed full snapshot.
```
> /engram:kb-import-chatgpt ~/Downloads/chatgpt-export-2026-04.zip
```

**`/engram:kb-import-claude <path-to-export.zip>`**
Same as above for Claude.ai. Export is manual: Claude.ai → Settings →
Privacy → Export data.

### Cluster + synthesize

**`/engram:kb-ingest [topic-name]`**
The core loop: cluster items into topic batches, then synthesize a wiki
page per batch. On first run, samples 15% of each source (clamped [10, 200]
per source), derives 8–20 topics, and shows you the cluster map before
proceeding. On subsequent runs, only regenerates pages whose batches grew.
Pass a topic name to scope synthesis to just that page.
```
> /engram:kb-ingest                        # all batches
> /engram:kb-ingest finance                # just wiki/finance.md
```
After rule-based routing, if items remain in `_unsorted`, `/engram:kb-ingest`
offers to classify them via a Haiku subagent (uses your Claude Code quota,
not a separate API key) against the existing topics.

**`/engram:kb-recluster [hint]`**
Re-derives the topic map when topics drift (too big, too small, near-dupes,
or unsorted items suggest a missing topic). Optional natural-language hint
guides the re-derivation. Reconciles existing wiki pages — renames, merges,
splits — preserving content and updating wikilinks.
```
> /engram:kb-recluster
> /engram:kb-recluster split finance from business
> /engram:kb-recluster merge llm-evals and ai-tooling
```

### Query + maintain

**`/engram:kb-query <question>`**
Asks a question grounded in the wiki. Claude reads `wiki/index.md`, opens
the relevant pages, and answers with wikilink citations. Substantive novel
answers get saved to `wiki/queries/<slug>.md` so they join the graph.
```
> /engram:kb-query what do people I follow say about prompt injection?
> /engram:kb-query summarize the best arguments against index investing from my bookmarks
```

**`/engram:kb-lint`**
Runs the lint script and fixes what it can: missing frontmatter, missing
TLDRs, missing counter-args on concept pages, broken wikilinks, orphan
pages. Reports issues requiring judgment.

**`/engram:kb-status`**
One-screen readout: per-source item counts, last sync timestamps, ingest
freshness (which batches grew since last synthesis), autosync schedule.

### Autosync

> Autosync uses Claude Code's scheduled tasks, which are **session-scoped**:
> they fire only while Claude Code is open and idle on your machine, and
> recurring tasks expire on their own after a few weeks. Treat it as a
> convenience while you work, not an always-on background service.

**`/engram:kb-enable-autosync [--every <dur>] [--at <HH:MM>] [--sources x,chatgpt,...]`**
Schedules `/engram:kb-sync` to run on a cadence via Claude Code's cron support.
```
> /engram:kb-enable-autosync --every 6h
> /engram:kb-enable-autosync --at 07:00 --sources x,chatgpt,claude-ai
```

**`/engram:kb-autosync-status`**
Shows the current schedule, next run, and last run result.

**`/engram:kb-disable-autosync`**
Cancels the scheduled auto-sync for the current KB.

---

## What a KB looks like

```
my-kb/
├── CLAUDE.md                          # KB-level rules (generated)
├── .engram/
│   ├── cluster-map.json               # Claude-generated topic → match rules
│   ├── sync-meta.json                 # Owned by sync.py
│   └── ingest-state.json              # Tracks what's been synthesized
├── raw/
│   ├── bookmarks.jsonl                # Canonical bookmark store
│   └── bookmarks/
│       ├── _manifest.md               # Counts per topic
│       ├── _unsorted.md               # Bookmarks matching no topic
│       └── <topic>.md                 # One file per topic
├── wiki/                              # Claude's output. Synthesized pages.
│   ├── index.md                       # Catalog table
│   ├── log.md                         # Chronological audit log
│   ├── queries/                       # Saved /engram:kb-query answers
│   └── <topic>.md
├── notes/                             # Yours. The skill never reads this.
└── .obsidian/                         # Obsidian vault config
```

---

## How bookmark sync actually works

X has no public bookmark API. The skill does what your browser does:

1. Reads the encrypted cookie store from Chrome/Brave/Edge on disk.
2. Decrypts the `ct0` (CSRF) and `auth_token` cookies using the key stored in
   macOS Keychain (or GNOME Keyring on Linux).
3. Calls X's internal GraphQL `Bookmarks` endpoint with those cookies plus
   the standard public Bearer token the web client uses.
4. Paginates until it hits a bookmark already known locally (incremental) or
   runs out (full sync).

Implications:
- You need to be **logged into X in your browser** — the cookies are the auth.
- Fragile by design. If X rotates their GraphQL query ID or changes cookie
  encryption, sync breaks until the skill is updated.
- No tokens, no API keys, no developer account required.
- If you use multiple browsers, pass `--browser chrome|brave|edge` to pin one.

---

## How clustering actually works

There is **no built-in topic list**. On first `/engram:kb-ingest`:

1. Claude samples 15% of each source (clamped [10, 200] per source) from your
   items corpus with diversity across time, authors, and hashtags.
2. Claude derives 8–20 kebab-case topics from what it sees. If your bookmarks
   are mostly recipes, you get cooking topics. If they're mostly trades,
   finance topics. The skill is domain-agnostic.
3. Claude writes `.engram/cluster-map.json` — topic name, description,
   and match rules (keywords / hashtags / authors / regex). It's plain JSON
   so you can hand-edit it in any text editor.
4. You review. One round of edits, then proceed.
5. `preprocess.py` applies the map deterministically. **Multi-assign**: a
   bookmark can land in multiple batches (a tweet about "LLM evals in
   finance" lands in both an ML topic and a finance topic).

`/engram:kb-recluster` re-runs the derivation when topics drift. You can pass a hint
like `"merge business and entrepreneurship"` and Claude will reconcile the
wiki pages — renames, merges, splits — preserving content and updating
wikilinks.

---

## Synthesis rules

Every synthesized wiki page has:

- **YAML frontmatter** — title, type, sources, created, updated, tags.
- **TLDR** — 3–5 dense sentences. The entire page collapsed.
- **Body** — grouped by sub-theme, inline author attribution.
- **Counter-arguments** — required on `type: concept` pages.
- **Wikilinks** — `[[kebab-case]]` to related pages (stubs OK, lint flags orphans).
- **Direct quotes** for tweets with >1000 likes (short, attributed).

Full spec: [`references/extraction-rules.md`](references/extraction-rules.md)
and [`references/frontmatter-schema.md`](references/frontmatter-schema.md).

---

## Privacy

- Everything runs locally. Bookmarks go from X → your browser's cookie jar →
  your disk. Nothing leaves your machine except the requests to `x.com` that
  the sync script makes on your behalf.
- Synthesis uses Claude via your existing Claude Code session, which talks to
  Anthropic's API under your account. The bookmarks themselves are sent to
  Claude as part of that synthesis context. If that's a concern, don't ingest
  DMs or private content.
- The `notes/` directory is never read by the skill. Use it for anything you
  don't want Claude to see.

---

## Troubleshooting

**`/engram:kb-sync` fails with an auth error.** Cookies are stale. Log out and back
into X in your browser, then retry. If the browser wasn't running recently,
the cookie database may be locked — close it.

**`/engram:kb-sync` fails with "keychain dialog timed out".** On the first sync, macOS
pops a dialog asking permission for `security` to read the browser's Safe
Storage password. You now have 2 minutes to enter your password — but if you
miss it, just rerun `/engram:kb-sync`. **Tip:** click **Always Allow** the first time
so you're never prompted again.

**`/engram:kb-sync` says no browser found.** The skill looks for Chrome, Brave, and
Edge at their standard paths on macOS/Linux. Make sure you're logged in.

**`/engram:kb-sync --source chatgpt` fails with a Cloudflare block.** CF puts the
session in cooldown. Visit chatgpt.com in your browser once (to refresh
`cf_clearance`), wait a few minutes, and retry. If it keeps happening, use
the export fallback: `/engram:kb-request-chatgpt-export` → wait for email →
`/engram:kb-import-chatgpt <zip>`.

**`/engram:kb-sync --source chatgpt` hits a 429 rate-limit.** The adapter
auto-retries with backoff; a single run of ~200 conversations takes ~20 min.
If it halts anyway, just rerun — sync is incremental and resumes.

**Sync works but `/engram:kb-ingest` never starts clustering.** Check that
`raw/bookmarks.jsonl` has content. On very small corpora (<20 bookmarks),
Claude may ask whether you really want to cluster yet — wait until you have
more.

**Lint errors on `wiki/index.md` or `wiki/log.md`.** These should pass as
`type: index` / `type: log`. If your scaffold predates the fix, regenerate
with `/engram:kb-init ~/new-kb` or edit the types manually.

**X rotated their GraphQL.** The query ID is pinned in
`scripts/graphql.py`. When it breaks, the fix is updating that constant.
File an issue.

---

## Layout of this repo

```
engram/
├── .claude-plugin/                # Plugin manifest + marketplace listing
│   ├── plugin.json
│   └── marketplace.json
├── skills/engram/SKILL.md         # The skill manifest — loaded into Claude's context
├── install.sh                     # Wrapper around `claude plugin install`
├── bin/engram-py                  # Self-bootstrapping Python runner
├── commands/                      # Slash command definitions
│   └── kb-*.md
├── scripts/                       # Python scripts, run via bin/engram-py (self-bootstrapping venv)
│   ├── init.py                    # Scaffold a KB
│   ├── sync.py                    # Pull bookmarks from X
│   ├── cookies.py                 # Browser cookie extraction (internal)
│   ├── graphql.py                 # X GraphQL client (internal)
│   ├── preprocess.py              # Apply cluster map → topic batches
│   └── lint.py                    # KB health check
├── references/                    # Verbose specs Claude loads on-demand
│   ├── clustering-guide.md
│   ├── extraction-rules.md
│   └── frontmatter-schema.md
└── templates/                     # Files copied into new KBs
    ├── CLAUDE.md.tmpl
    ├── gitignore.tmpl
    └── obsidian/
```

---

## License

MIT. See [LICENSE](LICENSE).

Cookie extraction and GraphQL fetching techniques are adapted from
[fieldtheory-cli](https://github.com/afar1/fieldtheory-cli) (also MIT).
