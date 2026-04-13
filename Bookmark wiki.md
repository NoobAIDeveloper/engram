# bookmark-kb: Twitter Bookmarks → Knowledge Base

## Context

People bookmark hundreds/thousands of tweets but never revisit them. This project combines Twitter bookmark syncing (inspired by fieldtheory-cli, MIT licensed) with Karpathy's LLM knowledge base pattern into a single tool. The user syncs their bookmarks, Claude classifies and synthesizes them into an interlinked markdown wiki viewable in Obsidian.

**Prior art:** We already built a working personal KB at `~/Documents/kb` with 1,008 bookmarks ingested into 15 wiki pages. This project extracts that into a distributable product.

**Reference repo:** https://github.com/afar1/fieldtheory-cli (MIT license, TypeScript, ~8K LOC)

---

## Architecture

```
bookmark-kb (npm package)
├── CLI: bkmrk sync / bkmrk init / bkmrk skill
├── Twitter sync: browser cookie extraction → GraphQL API
├── Storage: JSONL + metadata
└── Claude Code skill: classify → synthesize → wiki

User flow:
  npm install -g bookmark-kb
  bkmrk init ~/my-kb          # Scaffold Obsidian vault + CLAUDE.md
  bkmrk sync                  # Pull bookmarks from Twitter
  bkmrk skill install         # Install Claude Code skill
  # Then in Claude Code:
  /kb ingest                   # Claude classifies + builds wiki
  /kb query "question"         # Ask questions, results compound
  /kb lint                     # Health check
```

---

## Project Structure

```
~/Projects/bookmark-kb/
├── package.json
├── tsconfig.json
├── README.md
├── CLAUDE.md                    # Dev guide for contributors
├── LICENSE                      # MIT
├── bin/
│   └── bkmrk.mjs               # CLI entry point
├── src/
│   ├── cli.ts                   # Command definitions (commander)
│   ├── sync.ts                  # Bookmark sync orchestration
│   ├── graphql.ts               # GraphQL bookmark fetching
│   ├── cookies.ts               # Browser cookie extraction
│   ├── browsers.ts              # Browser detection & paths
│   ├── storage.ts               # JSONL read/write/merge
│   ├── scaffold.ts              # KB directory + CLAUDE.md generation
│   ├── skill.ts                 # Skill file installation
│   ├── types.ts                 # TypeScript interfaces
│   └── utils.ts                 # Shared helpers
├── skill/
│   └── kb.md                    # The Claude Code custom slash command
└── templates/
    └── schema.md                # Template CLAUDE.md for generated KBs
```

---

## Implementation Steps

### Step 1: Project scaffolding
Create `package.json`, `tsconfig.json`, `bin/bkmrk.mjs`, and base directory structure.

**package.json key fields:**
- name: `bookmark-kb`
- bin: `{ "bkmrk": "./bin/bkmrk.mjs" }`
- type: `module`
- engines: `{ "node": ">=20" }`

**Dependencies:**
- `commander` — CLI framework
- `dotenv` — env config (optional, for API keys)

**Dev dependencies:**
- `typescript`, `@types/node`, `tsx`

No SQLite dependency for v1 — JSONL is sufficient. Keep it minimal.

---

### Step 2: Type definitions (`src/types.ts`)
Define the core interfaces. Adapted from fieldtheory but simplified for our use case.

```typescript
interface Bookmark {
  id: string;
  url: string;
  text: string;
  authorHandle: string;
  authorName: string;
  authorBio?: string;
  postedAt: string;
  bookmarkedAt?: string;
  syncedAt: string;
  language?: string;
  engagement: {
    likeCount: number;
    repostCount: number;
    replyCount: number;
    bookmarkCount?: number;
  };
  media: string[];
  links: string[];
  quotedTweet?: { id: string; text: string; authorHandle: string };
  conversationId?: string;
}

interface SyncMeta {
  lastSyncAt?: string;
  totalBookmarks: number;
  lastCursor?: string;
}

interface KBConfig {
  dataDir: string;      // Where JSONL + sync state lives (~/.bookmark-kb/)
  wikiDir: string;      // Where the Obsidian vault lives (user-specified)
}
```

---

### Step 3: Browser detection & cookie extraction (`src/browsers.ts`, `src/cookies.ts`)

**browsers.ts** — Detect installed browsers and locate cookie databases.

Support matrix for v1:
| Browser | macOS | Linux | Windows |
|---------|-------|-------|---------|
| Chrome  | ✅    | ✅    | ❌ (later) |
| Brave   | ✅    | ✅    | ❌ (later) |
| Edge    | ✅    | ✅    | ❌ (later) |

Paths (macOS examples):
- Chrome: `~/Library/Application Support/Google/Chrome/Default/Cookies`
- Brave: `~/Library/Application Support/BraveSoftware/Brave-Browser/Default/Cookies`
- Edge: `~/Library/Application Support/Microsoft Edge/Default/Cookies`

**cookies.ts** — Extract and decrypt `ct0` and `auth_token` cookies from the browser's SQLite cookie database.

**macOS decryption flow:**
1. Read the encryption key from macOS Keychain: `security find-generic-password -s "Chrome Safe Storage" -w`
2. Derive the actual key using PBKDF2 (SHA1, 1003 iterations, 16-byte key length)
3. Query the Cookies SQLite file: `SELECT encrypted_value FROM cookies WHERE host_key LIKE '%twitter.com%' AND name IN ('ct0', 'auth_token')`
4. Decrypt: AES-128-CBC with the derived key, IV = 16 bytes of space (0x20)
5. Strip PKCS7 padding

**Linux decryption flow:**
1. Try to get key from GNOME Keyring (Secret Service API) via `secret-tool lookup`
2. Fall back to hardcoded Chromium key `peanuts` if Secret Service unavailable
3. Same PBKDF2 → AES-128-CBC flow as macOS but with 1 iteration

**Important:** The cookie DB is locked while the browser is running. We need to:
- Copy the Cookies file to a temp location before reading
- Clean up after extraction
- Warn the user if cookies are stale

**Dependencies for SQLite reading:** Use Node.js `child_process` to call `sqlite3` (available on macOS/Linux by default) rather than bundling a SQLite library. This keeps the package small. If `sqlite3` isn't available, fall back to a helpful error message.

Alternative: Use `better-sqlite3` npm package for cross-platform reliability. Decision: use `better-sqlite3` — it's more reliable than shelling out.

Updated dependencies: add `better-sqlite3` + `@types/better-sqlite3`.

---

### Step 4: GraphQL bookmark fetching (`src/graphql.ts`)

Uses X's internal GraphQL API (same endpoint the browser uses).

**Constants:**
```
BEARER_TOKEN = 'AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D...'
BOOKMARKS_QUERY_ID = 'Z9GWmP0kP2dajyckAaDUBw'
BOOKMARKS_OPERATION = 'Bookmarks'
GRAPHQL_FEATURES = { /* feature flags from fieldtheory */ }
```

**Request flow:**
1. Build URL: `https://x.com/i/api/graphql/{QUERY_ID}/{OPERATION}?variables={...}&features={...}`
2. Headers: `Authorization: Bearer {TOKEN}`, `x-csrf-token: {ct0}`, `Cookie: ct0={ct0}; auth_token={auth_token}`
3. Paginate: 20 bookmarks per page, cursor-based
4. Parse response: `data.bookmark_timeline_v2.timeline.instructions` → extract tweet entries
5. Map each entry to our `Bookmark` interface

**Pagination logic:**
- Incremental sync: stop when we hit a bookmark we already have (by ID)
- Full sync: paginate up to 200 pages (max ~4000 bookmarks)
- Rate limit handling: exponential backoff (15s → 30s → 60s → 120s) on 429 responses
- Delay between pages: 600ms default

**Snowflake ID → timestamp:**
```typescript
const TWITTER_EPOCH = 1288834974657n;
function snowflakeToDate(id: string): Date {
  return new Date(Number(BigInt(id) >> 22n) + Number(TWITTER_EPOCH));
}
```

---

### Step 5: Storage (`src/storage.ts`)

Simple JSONL file operations. No database for v1.

**Data directory:** `~/.bookmark-kb/`

**Files:**
- `bookmarks.jsonl` — one JSON bookmark per line, newest first
- `sync-meta.json` — `{ lastSyncAt, totalBookmarks, lastCursor }`

**Operations:**
- `loadBookmarks()` → read JSONL, parse to Bookmark[]
- `saveBookmarks(bookmarks[])` → write JSONL
- `mergeBookmarks(existing[], new[])` → deduplicate by ID, keep richer record
- `loadMeta()` / `saveMeta()` — sync state

---

### Step 6: KB scaffold (`src/scaffold.ts`)

Creates the Obsidian vault directory structure and CLAUDE.md.

**`bkmrk init <path>`** creates:
```
<path>/
├── CLAUDE.md              # Generated from templates/schema.md
├── raw/
│   └── bookmarks/         # Symlink or copy from ~/.bookmark-kb/bookmarks.jsonl
├── wiki/
│   ├── index.md
│   └── log.md
├── notes/
├── .obsidian/
│   ├── app.json           # useMarkdownLinks: false, etc.
│   └── appearance.json
└── .gitignore
```

**templates/schema.md** — The CLAUDE.md template. Adapted from what we built at `~/Documents/kb/CLAUDE.md` but parameterized (no hardcoded paths). This is the core IP of the product — the opinionated rules that make the wiki high quality:
- Source classification table
- TLDR requirement
- Counter-arguments requirement
- Frontmatter schema
- Ingest/query/lint workflows
- Bookmark-specific ingestion rules

---

### Step 7: Claude Code skill (`skill/kb.md`)

This is the main user-facing interface. A custom slash command file that gets installed to `~/.claude/commands/kb.md`.

**The skill instructs Claude to:**

1. **On `/kb ingest`:**
   - Read `~/.bookmark-kb/bookmarks.jsonl`
   - Read existing `wiki/index.md` to know what's already ingested
   - Classify bookmarks by topic using Claude's own judgment (not keyword matching)
   - Group into topic clusters
   - For each cluster, create/update a wiki page with synthesized insights
   - Add TLDR, counter-arguments, wikilinks
   - Update index.md and log.md

2. **On `/kb query <question>`:**
   - Read wiki/index.md for content map
   - Read relevant wiki pages
   - Synthesize an answer
   - If valuable, save as a query-result wiki page

3. **On `/kb lint`:**
   - Check all wiki pages for missing frontmatter, TLDR, counter-arguments
   - Check for broken wikilinks, orphan pages
   - Report and fix autonomously where possible

4. **On `/kb sync`:**
   - Run `bkmrk sync` via shell
   - Report results
   - Suggest running `/kb ingest` if new bookmarks found

**Skill file format:**
```markdown
---
name: kb
description: Manage your Twitter bookmarks knowledge base
---

[Full instructions for Claude here...]
```

---

### Step 8: CLI (`src/cli.ts`)

Ties everything together with `commander`.

**Commands:**

```
bkmrk init <path>          # Scaffold KB directory
  --no-obsidian            # Skip .obsidian config
  --no-git                 # Skip git init

bkmrk sync                 # Incremental bookmark sync
  --full                   # Full rebuild from scratch
  --browser <name>         # chrome, brave, edge (default: auto-detect)
  --continue               # Resume interrupted sync
  --delay <ms>             # Delay between pages (default: 600)

bkmrk status               # Show sync stats
  
bkmrk skill install        # Install Claude Code skill to ~/.claude/commands/
bkmrk skill uninstall      # Remove the skill

bkmrk export <path>        # Export bookmarks.jsonl to a path
```

---

### Step 9: Build & distribution

**Build:**
```bash
npm run build              # tsc → dist/
```

**Distribution:**
```bash
npm publish                # Publish to npm as 'bookmark-kb'
```

**Installation by users:**
```bash
npm install -g bookmark-kb
```

---

## Implementation Order

| # | Task | Files | Est. Complexity |
|---|------|-------|----------------|
| 1 | Project scaffold | package.json, tsconfig, bin/ | Low |
| 2 | Types | src/types.ts | Low |
| 3 | Browser detection | src/browsers.ts | Medium |
| 4 | Cookie extraction | src/cookies.ts | High (crypto) |
| 5 | GraphQL fetching | src/graphql.ts | High (pagination, parsing) |
| 6 | Storage | src/storage.ts | Low |
| 7 | KB scaffold | src/scaffold.ts, templates/ | Medium |
| 8 | Skill file | skill/kb.md | Medium (prompt engineering) |
| 9 | CLI | src/cli.ts | Medium |
| 10 | Build + test | tsconfig, manual testing | Low |

**Critical path:** Steps 3-5 (cookie extraction → GraphQL sync) are the hardest and most fragile. Everything else is straightforward.

---

## Key Decisions

1. **No SQLite for v1** — JSONL is enough for <10K bookmarks. Add FTS5 later if needed.
2. **`better-sqlite3` for cookie reading only** — needed to read browser cookie databases, not for our own storage.
3. **No OAuth for v1** — Browser cookie extraction is simpler and doesn't require Twitter developer credentials. OAuth can be added later as an alternative auth method.
4. **No Windows for v1** — macOS and Linux only. Windows cookie decryption uses DPAPI which is significantly more complex.
5. **No media download for v1** — Focus on text content. Media URLs are stored in the bookmark data but not downloaded locally.
6. **Classification by Claude, not regex** — The whole point is that Claude does the classification during `/kb ingest`. No built-in classifier needed in the CLI.

---

## Verification

1. **Sync test:** Run `bkmrk sync` with a logged-in Chrome session on macOS. Verify bookmarks.jsonl is populated with correct data.
2. **Scaffold test:** Run `bkmrk init ~/test-kb`. Open in Obsidian. Verify CLAUDE.md, directory structure, and vault config are correct.
3. **Skill test:** Run `bkmrk skill install`. Open Claude Code in the KB directory. Run `/kb ingest`. Verify wiki pages are created with proper frontmatter, TLDR, counter-arguments, and wikilinks.
4. **End-to-end:** Sync → init → install skill → ingest → query → lint. Verify the full lifecycle works.

---

## Risk & Mitigation

| Risk | Mitigation |
|------|-----------|
| X changes GraphQL endpoint/query ID | Version-pin the query ID; add a `--query-id` override flag; monitor for breakage |
| Cookie encryption changes | The encryption scheme hasn't changed in years; abstract behind a clean interface for easy updates |
| `better-sqlite3` native module issues | It's the most popular native SQLite package; well-tested on macOS/Linux. Fallback: use `sql.js` (WASM, no native code) |
| Large bookmark sets (10K+) | JSONL handles this fine; classification batching in the skill prevents context overflow |
| Rate limiting on GraphQL | Exponential backoff + configurable delay already handles this |
