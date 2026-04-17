---
description: Cluster bookmarks and synthesize wiki pages from the current KB
argument-hint: [topic-name]
---

The user wants to ingest items into the wiki. The current working directory should be a engram KB (it should contain a `CLAUDE.md` and a `.engram/` subdirectory). If it doesn't, tell the user to `cd` into their KB first or run `/kb-init` to scaffold one.

Also confirm `raw/items.jsonl` (or legacy `raw/bookmarks.jsonl`) exists and is non-empty. If it's missing or empty, tell the user to run `/kb-sync` first and stop.

Then follow the **Ingest workflow** in SKILL.md end to end. In particular:

- If `.engram/cluster-map.json` does not exist, do the bootstrap step (sample items with the per-source 15% / [10, 200] rule described in SKILL.md, derive topics, write the map, confirm with the user) before running preprocess.
- Run `~/.claude/skills/engram/.venv/bin/python ~/.claude/skills/engram/scripts/preprocess.py --kb $(pwd)` once the map is in place.
- Synthesize or update wiki pages per the workflow, consulting `ingest-state.json` to skip batches that haven't grown.

## Optional: LLM-classify the _unsorted bucket

After `preprocess.py` runs, read `raw/bookmarks/_manifest.md` and note the `_unsorted` count. If it's non-zero, offer the user an LLM-powered classification pass over the unsorted items:

> *"[N] items went to `_unsorted` after rule-based routing. I can spawn a Haiku subagent to classify them against the existing topics — faster and cheaper than the main Sonnet/Opus model, and scoped to just classification. Run it? [y/N]"*

Only proceed if the user agrees. Then:

1. Spawn the classification subagent with the Agent tool, **pinning `model: "haiku"`**. Example prompt (adapt counts/paths):

   > *Classify the items in `<kb>/raw/bookmarks/_unsorted.jsonl` against the topics defined in `<kb>/.engram/cluster-map.json`. For each item, pick zero or more topic names from the existing `topics[].name` list. Multi-assign is allowed (an item can legitimately land in more than one topic). Do NOT invent new topic names. Write the result to `<kb>/raw/bookmarks/_classifications.json` with this exact shape: `{"classifications": {"<item_id>": ["topic-name", ...], ...}}`. Omit items you cannot confidently place or give them an empty list — they'll stay unsorted. Return a one-line summary of how many you matched.*

2. After the subagent finishes, apply its output:

   ```bash
   ~/.claude/skills/engram/.venv/bin/python \
     ~/.claude/skills/engram/scripts/apply_classifications.py \
     --kb $(pwd) \
     --classifications raw/bookmarks/_classifications.json
   ```

3. Tell the user how many moved and how many remain in `_unsorted`. Then continue with the normal synthesis workflow on the updated batches.

If the main model is already Haiku, the subagent still pins Haiku explicitly — no cost surprise. If any step fails (subagent writes invalid JSON, applier errors), fall back to proceeding with just the rule-based routing and report what went wrong.

## Scope argument

If `$ARGUMENTS` names a single topic (kebab-case), scope the synthesis step to just that topic's batch — still run preprocess in full, but only (re)write `wiki/<topic>.md` and refresh `index.md` / `log.md` accordingly. Otherwise process all changed batches.

When done, report what was created vs updated vs skipped, and flag anything still in `_unsorted.md` worth a new topic. Do NOT auto-run `/kb-lint` — suggest it if you noticed issues.
