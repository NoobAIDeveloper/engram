# Extraction rules

Loaded during `/kb-ingest` and `/kb-recluster`. Defines how to turn a
`raw/bookmarks/<topic>.md` batch into a `wiki/<topic>.md` page.

The batch is a list of bookmarks pre-routed by `preprocess.py`. Your
job is to **synthesize**, not transcribe. A reader of the wiki page
should learn what the bookmarks collectively say about the topic —
they should not need to click through every source.

## Page shape

Every synthesized page has, in order:

1. **YAML frontmatter** — see `frontmatter-schema.md`.
2. **TLDR** — a 3–5 sentence high-density summary. No bullets, no
   filler ("This page covers..."). Lead with the most important claim.
3. **Body** — grouped into sub-theme sections (`##`). Each section
   synthesizes what multiple sources say. Cite authors inline.
4. **Counter-arguments** — **required** when `type: concept`. One
   paragraph or 3–5 bullets covering substantive disagreement found in
   the bookmarks or obvious steelmen against the dominant view.
   Optional for other types.
5. **Sources** — a short bullet list of the handles / URLs the page
   draws from. Full attribution — the reader can jump to X directly.

## Synthesis approach

- **Group by sub-theme, not by bookmark.** If five authors make the
  same point, write one paragraph that states the point and attributes
  it to all five, not five paragraphs.
- **Attribute inline.** `@handle argues that X`, or `several authors
  (@a, @b, @c) converge on Y`. Don't make the reader guess who said
  what.
- **AI chats use a different attribution format.** Items with
  `source: chatgpt`, `source: claude-ai`, or `source: claude-code`
  are conversations between the user and a model. Attribute as
  `I asked ChatGPT about X; the answer held that Y`, or
  `in a Claude Code session I worked through Z`. Never attribute an
  AI-chat item to a public handle. Distinguish user intent (what I
  asked) from model content (what the answer said) so the reader can
  judge weight — the user's question signals interest, the model's
  answer is not an external source of authority.
- **Mixed-source pages:** if a page draws from both public tweets
  and private chats, separate them in the Sources section under
  distinct subheadings ("Public posts" / "My AI chats"), and mark
  the page `private: true` in frontmatter so any future publish
  tooling excludes it.
- **Quote high-engagement tweets verbatim.** If a tweet has >1000
  likes, include a short direct quote (1–2 sentences) inside a
  blockquote with attribution. This rule is a hard invariant from
  SKILL.md. For lower-engagement tweets, paraphrase is fine.
- **Length scales with batch size.** A batch of 8 bookmarks → a tight
  300-word page. A batch of 80 → 800–1500 words with more sub-themes.
  Do not pad.
- **Prefer claims over lists.** `LLM agents fail on long-horizon tasks
  because of context rot (@karpathy, @hamel)` beats a bulleted list of
  "things people said about agents."

## Wikilinks

- Link to other wiki pages with `[[kebab-case-name]]`. The page doesn't
  need to exist yet — stubs are fine, lint will flag orphans.
- Use wikilinks when a sub-theme belongs more properly to another
  page, or when a concept is covered in depth elsewhere.
- External links use markdown `[text](url)` — never wrap an `http://`
  URL in double brackets.
- Don't over-link. One or two wikilinks per section is plenty. A page
  linking to every other page in the wiki is noise.

## What NOT to do

- Don't paste raw tweet text into the body. The batch file already has
  it; the wiki page is a distillation.
- Don't write an "Introduction" section. The TLDR is the intro.
- Don't editorialize beyond what the sources support. If three tweets
  claim X, write "three authors claim X," not "X is true."
- Don't drop attribution. Anonymous synthesis erases the user's
  ability to go verify.
- Don't invent counter-arguments that aren't defensible. If there's
  genuinely no substantive counter in the batch, write one short
  steelman; don't fabricate a fake debate.

## Idempotence

When re-ingesting an existing wiki page because the batch grew:

- Preserve the page's existing structure and voice where the new
  bookmarks don't contradict it.
- Add new sub-themes or extend existing ones; don't rewrite from
  scratch unless the new material fundamentally changes the picture.
- Update `updated:` in frontmatter. Do not touch `created:`.
- Append any new sources to the sources list.
