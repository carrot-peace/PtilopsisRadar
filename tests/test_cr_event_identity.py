# coding=utf-8
"""
Tests for the pure CR event identity module (PR10a).

Covers title/URL normalization, deterministic key derivation, Run-2 regression
examples, and the optional candidate adapter.  These tests are pure — no I/O,
no network, no env, no Telegram.
"""

import unittest

from trendradar.cr.event_identity import (
    CR_EVENT_IDENTITY_KEY_VERSION,
    CREventIdentity,
    CREventIdentityInput,
    build_cr_event_identity_from_candidate,
    build_cr_event_identity_from_input,
    normalize_cr_event_title,
    normalize_cr_event_url,
)
from trendradar.cr.models import CRCandidate, CRSourceItem


# Run-2 finding (see docs/cr_event_identity_evidence.md).
_RUN2_TITLE = "广西兴安发生爆炸已致7死17伤"
_RUN2_CANDIDATE_ID_EARLY = "6e204d8621b7"
_RUN2_CANDIDATE_ID_LATE = "35a135d75a46"


# ===========================================================================
# A. Title normalization
# ===========================================================================


class TestTitleNormalization(unittest.TestCase):
    def test_trims_leading_trailing_whitespace(self):
        self.assertEqual(normalize_cr_event_title("  hello  "), "hello")

    def test_collapses_repeated_spaces(self):
        self.assertEqual(normalize_cr_event_title("a    b     c"), "a b c")

    def test_collapses_tabs_and_newlines(self):
        self.assertEqual(normalize_cr_event_title("a\tb\nc\r\nd"), "a b c d")

    def test_ascii_lowercased(self):
        self.assertEqual(normalize_cr_event_title("Hello WORLD"), "hello world")

    def test_chinese_remains_readable(self):
        # CJK content is preserved verbatim (lower() is a no-op for CJK).
        self.assertEqual(normalize_cr_event_title(_RUN2_TITLE), _RUN2_TITLE)

    def test_chinese_whitespace_collapsed_but_intact(self):
        self.assertEqual(
            normalize_cr_event_title("广西兴安  爆炸"), "广西兴安 爆炸"
        )

    def test_punctuation_is_preserved(self):
        # We deliberately do NOT strip punctuation (no aggressive semantic loss).
        self.assertEqual(
            normalize_cr_event_title("Breaking: 7 dead, 17 hurt!"),
            "breaking: 7 dead, 17 hurt!",
        )

    def test_nfkc_folds_fullwidth(self):
        # Full-width ASCII folds to half-width via NFKC.
        self.assertEqual(normalize_cr_event_title("ＡＢＣ"), "abc")

    def test_empty_returns_empty(self):
        self.assertEqual(normalize_cr_event_title(""), "")

    def test_whitespace_only_returns_empty(self):
        self.assertEqual(normalize_cr_event_title("   \t\n"), "")


# ===========================================================================
# B. URL normalization
# ===========================================================================


class TestURLNormalization(unittest.TestCase):
    def test_removes_fragment(self):
        self.assertEqual(
            normalize_cr_event_url("https://example.com/a#section"),
            "https://example.com/a",
        )

    def test_lowercases_scheme_and_host(self):
        self.assertEqual(
            normalize_cr_event_url("HTTPS://Example.COM/Path"),
            "https://example.com/Path",
        )

    def test_preserves_path_case_and_query(self):
        self.assertEqual(
            normalize_cr_event_url("https://example.com/Path?Q=1"),
            "https://example.com/Path?Q=1",
        )

    def test_trims_whitespace(self):
        self.assertEqual(
            normalize_cr_event_url("  https://example.com/a  "),
            "https://example.com/a",
        )

    def test_empty_returns_empty(self):
        self.assertEqual(normalize_cr_event_url(""), "")

    def test_bare_token_unchanged(self):
        self.assertEqual(normalize_cr_event_url("weibo"), "weibo")


# ===========================================================================
# C. Deterministic key
# ===========================================================================


class TestDeterministicKey(unittest.TestCase):
    def test_same_title_gives_same_event_key(self):
        a = build_cr_event_identity_from_input(CREventIdentityInput(title="Quake"))
        b = build_cr_event_identity_from_input(CREventIdentityInput(title="Quake"))
        self.assertEqual(a.event_key, b.event_key)

    def test_candidate_id_change_does_not_change_event_key(self):
        a = build_cr_event_identity_from_input(
            CREventIdentityInput(title="Quake", candidate_id="aaa")
        )
        b = build_cr_event_identity_from_input(
            CREventIdentityInput(title="Quake", candidate_id="bbb")
        )
        self.assertEqual(a.event_key, b.event_key)

    def test_cluster_key_change_does_not_change_event_key(self):
        a = build_cr_event_identity_from_input(
            CREventIdentityInput(title="Quake", cluster_key="k1")
        )
        b = build_cr_event_identity_from_input(
            CREventIdentityInput(title="Quake", cluster_key="k1|zhihu")
        )
        self.assertEqual(a.event_key, b.event_key)

    def test_platform_order_does_not_change_fingerprint(self):
        a = build_cr_event_identity_from_input(
            CREventIdentityInput(title="Quake", platforms=("weibo", "baidu"))
        )
        b = build_cr_event_identity_from_input(
            CREventIdentityInput(title="Quake", platforms=("baidu", "weibo"))
        )
        self.assertEqual(a.platform_fingerprint, b.platform_fingerprint)

    def test_source_url_order_and_fragment_do_not_change_fingerprint(self):
        a = build_cr_event_identity_from_input(
            CREventIdentityInput(
                title="Quake",
                source_urls=("https://a.com/x#f", "https://b.com/y"),
            )
        )
        b = build_cr_event_identity_from_input(
            CREventIdentityInput(
                title="Quake",
                source_urls=("https://b.com/y", "https://a.com/x"),
            )
        )
        self.assertEqual(a.source_fingerprint, b.source_fingerprint)

    def test_event_key_includes_version(self):
        identity = build_cr_event_identity_from_input(
            CREventIdentityInput(title="Quake")
        )
        self.assertTrue(identity.event_key.startswith(f"{CR_EVENT_IDENTITY_KEY_VERSION}:"))
        self.assertEqual(identity.version, CR_EVENT_IDENTITY_KEY_VERSION)

    def test_key_basis_is_normalized_title(self):
        identity = build_cr_event_identity_from_input(
            CREventIdentityInput(title="Quake")
        )
        self.assertEqual(identity.key_basis, "normalized_title")

    def test_event_key_is_storage_safe_ascii(self):
        identity = build_cr_event_identity_from_input(
            CREventIdentityInput(title=_RUN2_TITLE)
        )
        # Storage-safe: ASCII, no whitespace, no raw title characters.
        self.assertTrue(identity.event_key.isascii())
        self.assertNotIn(" ", identity.event_key)
        self.assertNotIn("广", identity.event_key)

    def test_different_titles_give_different_keys(self):
        a = build_cr_event_identity_from_input(CREventIdentityInput(title="Quake"))
        b = build_cr_event_identity_from_input(CREventIdentityInput(title="Flood"))
        self.assertNotEqual(a.event_key, b.event_key)

    def test_result_is_frozen(self):
        identity = build_cr_event_identity_from_input(
            CREventIdentityInput(title="Quake")
        )
        self.assertIsInstance(identity, CREventIdentity)
        with self.assertRaises(Exception):
            identity.event_key = "mutated"  # type: ignore[misc]


# ===========================================================================
# D. Run-2 regression examples
# ===========================================================================


class TestRun2Regression(unittest.TestCase):
    def _build(self, candidate_id, cluster_key):
        return build_cr_event_identity_from_input(
            CREventIdentityInput(
                title=_RUN2_TITLE,
                platforms=("weibo", "baidu"),
                source_urls=("https://news.example.com/guangxi",),
                candidate_id=candidate_id,
                cluster_key=cluster_key,
            )
        )

    def test_same_title_different_candidate_id_same_event_key(self):
        early = self._build(_RUN2_CANDIDATE_ID_EARLY, "grp")
        late = self._build(_RUN2_CANDIDATE_ID_LATE, "grp")
        self.assertEqual(early.event_key, late.event_key)

    def test_same_title_different_cluster_key_same_event_key(self):
        before = self._build(_RUN2_CANDIDATE_ID_EARLY, "grp")
        after = self._build(_RUN2_CANDIDATE_ID_EARLY, "grp|zhihu")
        self.assertEqual(before.event_key, after.event_key)

    def test_candidate_id_preserved_as_evidence(self):
        early = self._build(_RUN2_CANDIDATE_ID_EARLY, "grp")
        late = self._build(_RUN2_CANDIDATE_ID_LATE, "grp")
        self.assertEqual(early.candidate_id, _RUN2_CANDIDATE_ID_EARLY)
        self.assertEqual(late.candidate_id, _RUN2_CANDIDATE_ID_LATE)

    def test_cluster_key_fingerprint_changes_when_cluster_key_changes(self):
        before = self._build(_RUN2_CANDIDATE_ID_EARLY, "grp")
        after = self._build(_RUN2_CANDIDATE_ID_EARLY, "grp|zhihu")
        self.assertIsNotNone(before.cluster_key_fingerprint)
        self.assertNotEqual(
            before.cluster_key_fingerprint, after.cluster_key_fingerprint
        )

    def test_no_cluster_key_yields_no_fingerprint(self):
        identity = self._build(_RUN2_CANDIDATE_ID_EARLY, "")
        self.assertIsNone(identity.cluster_key_fingerprint)


# ===========================================================================
# E. Candidate adapter
# ===========================================================================


class TestCandidateAdapter(unittest.TestCase):
    def _candidate(self):
        return CRCandidate(
            candidate_id=_RUN2_CANDIDATE_ID_EARLY,
            cluster_key="grp|weibo|zhihu",
            display_title=_RUN2_TITLE,
            representative_url="https://news.example.com/guangxi",
            source_names=["weibo", "zhihu"],
            source_items=[
                CRSourceItem(title="t1", url="https://a.example.com/1"),
                CRSourceItem(title="t2", url="https://b.example.com/2"),
            ],
        )

    def test_builds_identity_from_actual_candidate(self):
        identity = build_cr_event_identity_from_candidate(self._candidate())
        expected_title_key = build_cr_event_identity_from_input(
            CREventIdentityInput(title=_RUN2_TITLE)
        ).event_key
        self.assertEqual(identity.event_key, expected_title_key)
        self.assertEqual(identity.candidate_id, _RUN2_CANDIDATE_ID_EARLY)
        self.assertIsNotNone(identity.cluster_key_fingerprint)

    def test_missing_display_title_raises_type_error(self):
        class NotACandidate:
            candidate_id = "x"

        with self.assertRaises(TypeError):
            build_cr_event_identity_from_candidate(NotACandidate())

    def test_non_string_display_title_raises_type_error(self):
        class Weird:
            display_title = 123

        with self.assertRaises(TypeError):
            build_cr_event_identity_from_candidate(Weird())

    def test_does_not_mutate_candidate(self):
        cand = self._candidate()
        before = (
            cand.candidate_id,
            cand.cluster_key,
            cand.display_title,
            tuple(cand.source_names),
            len(cand.source_items),
        )
        build_cr_event_identity_from_candidate(cand)
        after = (
            cand.candidate_id,
            cand.cluster_key,
            cand.display_title,
            tuple(cand.source_names),
            len(cand.source_items),
        )
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
