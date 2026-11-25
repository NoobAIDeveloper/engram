"""Regression tests for the offline pipeline (no network, no cookies).

Run from the repo root:  python3 -m unittest discover -s tests -v
Stdlib only — works with any Python 3.10+.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from sources.base import chunk_by_size, load_items, replace_source_items  # noqa: E402


def run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        capture_output=True, text=True,
    )


def item(id_: str, source: str, text: str, **kw) -> dict:
    return {"id": id_, "source": source, "text": text,
            "timestamp": "2026-01-01T00:00:00Z", **kw}


class KBCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.kb = Path(self._tmp.name).resolve() / "kb"
        r = run("init.py", str(self.kb), "--no-git")
        self.assertEqual(r.returncode, 0, r.stderr)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_items(self, items: list[dict]) -> None:
        (self.kb / "raw" / "items.jsonl").write_text(
            "".join(json.dumps(i) + "\n" for i in items), encoding="utf-8")

    def write_map(self, topics: list[dict]) -> None:
        (self.kb / ".engram" / "cluster-map.json").write_text(
            json.dumps({"topics": topics}), encoding="utf-8")

    def manifest(self) -> str:
        return (self.kb / "raw" / "bookmarks" / "_manifest.md").read_text()


class ItemStore(KBCase):
    def test_malformed_line_does_not_wipe_other_sources(self):
        path = self.kb / "raw" / "items.jsonl"
        path.write_text(
            json.dumps(item("x:1", "x", "a")) + "\n"
            + json.dumps(item("chatgpt:1", "chatgpt", "b")) + "\n"
            + '{"id": "x:2", "source": "x", "te\n',  # truncated write
            encoding="utf-8")
        replace_source_items(self.kb, "kindle", [item("kindle:1", "kindle", "c")])
        ids = {i["id"] for i in load_items(path)}
        self.assertEqual(ids, {"x:1", "chatgpt:1", "kindle:1"})
        self.assertTrue(path.with_suffix(".jsonl.corrupt.bak").exists())

    def test_chunk_by_size_splits_text_without_spaces(self):
        chunks = chunk_by_size("字" * 10_000, max_chars=4000)
        self.assertTrue(all(len(c.body) <= 4000 for c in chunks))
        self.assertEqual(sum(len(c.body) for c in chunks), 10_000)

    def test_kindle_ids_are_stable_across_processes(self):
        clip = self.kb / "clip.txt"
        clip.write_text(
            "Book (Author)\n- Your Highlight on page 1 | Added on Monday, "
            "January 5, 2026 10:00:00 AM\n\nSome highlighted text\n==========\n",
            encoding="utf-8")
        code = ("import sys; sys.path.insert(0, %r); from sources import kindle; "
                "from pathlib import Path; "
                "print([i['id'] for i in kindle.sync(None, clippings_path=Path(%r))])"
                % (str(SCRIPTS), str(clip)))
        outs = {subprocess.run([sys.executable, "-c", code], capture_output=True,
                               text=True).stdout for _ in range(2)}
        self.assertEqual(len(outs), 1, outs)
        self.assertIn("kindle:", outs.pop())


class Preprocess(KBCase):
    def test_routes_and_source_only_topic(self):
        self.write_items([
            item("x:1", "x", "a great sourdough recipe", author="baker"),
            item("kindle:1", "kindle", "unrelated highlight"),
            item("x:2", "x", "nothing matches this"),
        ])
        self.write_map([
            {"name": "cooking", "match": {"keywords": ["recipe"]}},
            {"name": "books", "match": {"sources": ["kindle"]}},
        ])
        r = run("preprocess.py", "--kb", str(self.kb))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("cooking: 1", r.stdout)
        self.assertIn("books: 1", r.stdout)
        self.assertIn("_unsorted: 1", r.stdout)

    def test_bare_string_and_empty_keywords_do_not_match_everything(self):
        self.write_items([item("x:1", "x", "hello there")])
        self.write_map([
            {"name": "a", "match": {"keywords": "recipe"}},
            {"name": "b", "match": {"keywords": [""]}},
        ])
        r = run("preprocess.py", "--kb", str(self.kb))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("_unsorted: 1", r.stdout)

    def test_bad_map_is_a_clean_error_not_a_traceback(self):
        self.write_items([item("x:1", "x", "hello")])
        for topics in ([{"match": {}}], ["nope"], [{"name": "Bad Name"}],
                       [{"name": "a", "match": {"regex": ["("]}}]):
            self.write_map(topics)
            r = run("preprocess.py", "--kb", str(self.kb))
            self.assertEqual(r.returncode, 1)
            self.assertNotIn("Traceback", r.stderr)

    def test_legacy_bookmarks_survive_a_non_x_sync(self):
        (self.kb / "raw" / "bookmarks.jsonl").write_text(json.dumps({
            "id": "1", "tweetId": "1", "text": "legacy tweet",
            "authorHandle": "someone", "url": "https://x.com/someone/status/1",
            "postedAt": "2026-01-01T00:00:00Z"}) + "\n", encoding="utf-8")
        replace_source_items(self.kb, "kindle", [item("kindle:1", "kindle", "c")])
        self.write_map([{"name": "all-x", "match": {"sources": ["x"]}}])
        r = run("preprocess.py", "--kb", str(self.kb))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("all-x: 1", r.stdout)

    def test_classifications_persist_across_preprocess_runs(self):
        self.write_items([item("x:1", "x", "alpha"), item("x:2", "x", "beta")])
        self.write_map([{"name": "greek", "match": {"keywords": ["zzz"]}}])
        self.assertIn("_unsorted: 2", run("preprocess.py", "--kb", str(self.kb)).stdout)
        cls = self.kb / "raw" / "bookmarks" / "_classifications.json"
        cls.write_text(json.dumps({"classifications": {
            "x:1": ["greek", "greek"], "x:404": ["greek"], "x:2": ["no-such-topic"]}}))
        r = run("apply_classifications.py", "--kb", str(self.kb),
                "--classifications", "raw/bookmarks/_classifications.json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1 item(s) moved", r.stdout)
        self.assertIn("| 1 |", self.manifest())  # not appended twice
        r = run("preprocess.py", "--kb", str(self.kb))
        self.assertIn("greek: 1", r.stdout)
        self.assertIn("_unsorted: 1", r.stdout)


class InitAndLint(KBCase):
    def test_fresh_kb_lints_clean(self):
        r = run("lint.py", "--kb", str(self.kb))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("clean", r.stdout)

    def test_force_only_rewrites_claude_md(self):
        log = self.kb / "wiki" / "log.md"
        log.write_text(log.read_text() + "MY HISTORY\n")
        (self.kb / "CLAUDE.md").write_text("stale")
        r = run("init.py", str(self.kb), "--no-git", "--force")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("MY HISTORY", log.read_text())
        self.assertNotEqual((self.kb / "CLAUDE.md").read_text(), "stale")

    def test_tokens_file_is_gitignored(self):
        self.assertIn(".engram/sources.json", (self.kb / ".gitignore").read_text())

    def test_lint_accepts_template_style_page(self):
        (self.kb / "wiki" / "queries").mkdir(exist_ok=True)
        (self.kb / "wiki" / "queries" / "why.md").write_text(
            "---\ntitle: Why\ntype: query\ncreated: 2026-01-01\n"
            "updated: 2026-01-02\ntags: [a]\n---\n\n**TLDR:** because.\n")
        (self.kb / "wiki" / "topic.md").write_text(
            "﻿---\ntitle: \"Topic\"\ntype: reference\nsources:\n  - \"@someone\"\n"
            "  - https://example.com/a\ncreated: 2026-01-01\nupdated: 2026-01-02\n"
            "tags:\n  - one-tag\n---\n\n**TLDR:** Dense summary.\n\n"
            "| a | b |\n|---|---|\n| [[queries/why\\|alias]] | [[index]] |\n")
        (self.kb / "wiki" / "index.md").write_text(
            (self.kb / "wiki" / "index.md").read_text() + "\n[[topic]]\n")
        r = run("lint.py", "--kb", str(self.kb), "--json")
        report = json.loads(r.stdout)
        self.assertEqual(report["issues"], [], report)

    def test_lint_still_catches_real_problems(self):
        (self.kb / "wiki" / "Bad_Name.md").write_text("no frontmatter here\n")
        (self.kb / "wiki" / "concept.md").write_text(
            "---\ntitle: C\ntype: concept\nsources: [a]\ncreated: 2026-01-01\n"
            "updated: 2026-01-01\ntags: [a]\n---\n\nbody [[nowhere]]\n")
        r = run("lint.py", "--kb", str(self.kb), "--json")
        codes = {i["code"] for i in json.loads(r.stdout)["issues"]}
        self.assertEqual(r.returncode, 1)
        self.assertLessEqual(
            {"bad-filename", "missing-frontmatter", "missing-tldr",
             "missing-counterargs", "broken-wikilink"}, codes)


if __name__ == "__main__":
    unittest.main()
