"""Offline tests for the X bookmarks client's query-profile fallback."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import graphql  # noqa: E402

EMPTY_TIMELINE = {"data": {"bookmark_timeline_v2": {"timeline": {"instructions": []}}}}
REJECTED = {"errors": [{"message": "Query not found"}]}


def opts() -> graphql.FetchOptions:
    return graphql.FetchOptions(ct0="c", auth_token="a", max_pages=1, page_delay_ms=0)


class ProfileFallback(unittest.TestCase):
    def run_with(self, responses: dict[str, dict]) -> list[str]:
        """Drive fetch_bookmarks with canned per-query-id responses; return
        the query ids requested, in order."""
        asked: list[str] = []

        def fake_fetch(url: str, headers: dict) -> dict:
            qid = url.split("/graphql/")[1].split("/")[0]
            asked.append(qid)
            return responses.get(qid, REJECTED)

        with mock.patch.object(graphql, "_fetch_page", fake_fetch), \
             mock.patch.object(graphql, "_remote_profile", lambda: None):
            list(graphql.fetch_bookmarks(opts()))
        return asked

    def test_first_profile_used_when_accepted(self):
        first = graphql.QUERY_PROFILES[0].query_id
        self.assertEqual(self.run_with({first: EMPTY_TIMELINE}), [first])

    def test_falls_back_to_next_profile(self):
        ids = [p.query_id for p in graphql.QUERY_PROFILES]
        self.assertEqual(self.run_with({ids[-1]: EMPTY_TIMELINE}), ids)

    def test_all_rejected_raises_stale_error(self):
        with self.assertRaises(graphql.QueryIdStaleError):
            self.run_with({})

    def test_remote_profile_is_last_resort(self):
        remote = graphql.QueryProfile("remote", "R" * 22, {"a": True})
        asked: list[str] = []

        def fake_fetch(url: str, headers: dict) -> dict:
            asked.append(url.split("/graphql/")[1].split("/")[0])
            return EMPTY_TIMELINE if asked[-1] == remote.query_id else REJECTED

        with mock.patch.object(graphql, "_fetch_page", fake_fetch), \
             mock.patch.object(graphql, "_remote_profile", lambda: remote):
            list(graphql.fetch_bookmarks(opts()))
        self.assertEqual(asked[-1], remote.query_id)
        self.assertEqual(len(asked), len(graphql.QUERY_PROFILES) + 1)

    def test_each_profile_sends_its_own_flags(self):
        for p in graphql.QUERY_PROFILES:
            url = graphql._build_url(None, 20, p)
            self.assertIn(p.query_id, url)
            self.assertIn("longform_notetweets_consumption_enabled", url)

    def test_tco_filter_is_hostname_based(self):
        self.assertTrue(graphql._is_tco("https://t.co/abc"))
        self.assertFalse(graphql._is_tco("https://reddit.com/r/x"))
        self.assertFalse(graphql._is_tco("https://microsoft.com/"))


if __name__ == "__main__":
    unittest.main()
