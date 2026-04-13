---
description: Answer a question grounded in the current wiki
argument-hint: <question>
---

The user wants an answer from their wiki. The current working directory should be a twitter-wiki KB (it should contain a `CLAUDE.md` and a `.twitter-wiki/` subdirectory). If it doesn't, tell the user to `cd` into their KB first or run `/kb-init` to scaffold one.

`$ARGUMENTS` is the question. If it's empty, ask the user what they want to know — don't guess.

If `wiki/index.md` doesn't exist or the wiki is empty, tell the user there's nothing to query yet and suggest `/kb-sync` then `/kb-ingest`.

Otherwise follow the **Query workflow** in SKILL.md: consult `wiki/index.md`, read only the pages that look relevant, answer grounded in what's there, and cite pages with `[[wikilinks]]`. Be explicit when the wiki doesn't cover something — don't invent.

Use judgment on whether to save the answer to `wiki/queries/<kebab-case-question>.md` per the workflow's criteria (novel + substantive). When in doubt, ask the user whether to save it before writing.
