# coding=utf-8
"""
Tests for CR presentation layer (PR9f).

Covers: binding, sorting, selection, text rendering, convenience helper,
and module-level no-forbidden-import guarantees.
"""

import unittest

from trendradar.cr.cluster import normalize_topic_text
from trendradar.cr.decision import (
    CRDecision,
    DECISION_ALERT,
    DECISION_SUPPRESS,
    DECISION_URGENT,
    DECISION_WATCH,
)
from trendradar.cr.models import CRCandidate
from trendradar.cr.presentation import (
    CRPresentedCandidate,
    CRPresentationRun,
    CRTextPresentationConfig,
    bind_cr_presented_candidates,
    render_cr_a_text,
    render_cr_a_text_from_parts,
    select_cr_a_candidates,
    sort_cr_presented_candidates,
)
from trendradar.cr.scoring import CRScoreResult


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_candidate(
    candidate_id: str = "c1",
    cluster_key: str = "key1",
    display_title: str = "Topic A",
    representative_url: str | None = "https://example.com",
) -> CRCandidate:
    return CRCandidate(
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        display_title=display_title,
        representative_url=representative_url,
    )


def _make_score(
    candidate_id: str = "c1",
    cluster_key: str = "key1",
    total_score: float = 70.0,
    trigger_reasons: list[str] | None = None,
) -> CRScoreResult:
    return CRScoreResult(
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        profile_version="test",
        total_score=total_score,
        trigger_reasons=trigger_reasons or [],
    )


def _make_decision(
    candidate_id: str = "c1",
    cluster_key: str = "key1",
    level: str = DECISION_ALERT,
    total_score: float = 70.0,
    push_eligible: bool = True,
    trigger_reasons: list[str] | None = None,
    suppress_labels: list[str] | None = None,
) -> CRDecision:
    return CRDecision(
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        profile_version="test",
        policy_version="test",
        level=level,
        total_score=total_score,
        push_eligible=push_eligible,
        trigger_reasons=trigger_reasons or [],
        suppress_labels=suppress_labels or [],
    )


# ===========================================================================
# A. Binding tests
# ===========================================================================


class TestBindCRPresentedCandidates(unittest.TestCase):
    """A. Binding tests."""

    def test_normal_bind(self):
        """candidate + score + decision normal binding."""
        c = _make_candidate()
        s = _make_score()
        d = _make_decision()
        result = bind_cr_presented_candidates([c], [s], [d])
        self.assertEqual(len(result), 1)
        pc = result[0]
        self.assertIs(pc.candidate, c)
        self.assertIs(pc.score_result, s)
        self.assertIs(pc.decision, d)
        self.assertEqual(pc.candidate_id, "c1")
        self.assertEqual(pc.cluster_key, "key1")
        self.assertEqual(pc.display_title, "Topic A")
        self.assertEqual(pc.representative_url, "https://example.com")
        self.assertEqual(pc.decision_level, DECISION_ALERT)
        self.assertEqual(pc.total_score, 70.0)

    def test_preserves_candidate_order(self):
        """Output preserves candidate input order."""
        c1 = _make_candidate("c1", "k1", "Alpha")
        c2 = _make_candidate("c2", "k2", "Beta")
        c3 = _make_candidate("c3", "k3", "Gamma")
        s1 = _make_score("c1", "k1")
        s2 = _make_score("c2", "k2")
        s3 = _make_score("c3", "k3")
        d1 = _make_decision("c1", "k1")
        d2 = _make_decision("c2", "k2")
        d3 = _make_decision("c3", "k3")
        # Pass in reverse order.
        result = bind_cr_presented_candidates(
            [c3, c1, c2], [s1, s2, s3], [d1, d2, d3]
        )
        self.assertEqual(
            [pc.candidate_id for pc in result], ["c3", "c1", "c2"]
        )

    def test_missing_score_raises(self):
        """Missing score raises ValueError."""
        c = _make_candidate()
        d = _make_decision()
        with self.assertRaises(ValueError) as ctx:
            bind_cr_presented_candidates([c], [], [d])
        self.assertIn("Missing score", str(ctx.exception))

    def test_missing_decision_raises(self):
        """Missing decision raises ValueError."""
        c = _make_candidate()
        s = _make_score()
        with self.assertRaises(ValueError) as ctx:
            bind_cr_presented_candidates([c], [s], [])
        self.assertIn("Missing decision", str(ctx.exception))

    def test_duplicate_score_id_raises(self):
        """Duplicate score candidate_id raises ValueError."""
        c = _make_candidate()
        s1 = _make_score("c1", "key1")
        s2 = _make_score("c1", "key1")
        d = _make_decision()
        with self.assertRaises(ValueError) as ctx:
            bind_cr_presented_candidates([c], [s1, s2], [d])
        self.assertIn("Duplicate score", str(ctx.exception))

    def test_duplicate_decision_id_raises(self):
        """Duplicate decision candidate_id raises ValueError."""
        c = _make_candidate()
        s = _make_score()
        d1 = _make_decision("c1", "key1")
        d2 = _make_decision("c1", "key1")
        with self.assertRaises(ValueError) as ctx:
            bind_cr_presented_candidates([c], [s], [d1, d2])
        self.assertIn("Duplicate decision", str(ctx.exception))

    def test_cluster_key_mismatch_score_raises(self):
        """Score cluster_key mismatch raises ValueError."""
        c = _make_candidate("c1", "key1")
        s = _make_score("c1", "WRONG_KEY")
        d = _make_decision("c1", "key1")
        with self.assertRaises(ValueError) as ctx:
            bind_cr_presented_candidates([c], [s], [d])
        self.assertIn("cluster_key mismatch", str(ctx.exception))
        self.assertIn("score", str(ctx.exception))

    def test_cluster_key_mismatch_decision_raises(self):
        """Decision cluster_key mismatch raises ValueError."""
        c = _make_candidate("c1", "key1")
        s = _make_score("c1", "key1")
        d = _make_decision("c1", "WRONG_KEY")
        with self.assertRaises(ValueError) as ctx:
            bind_cr_presented_candidates([c], [s], [d])
        self.assertIn("cluster_key mismatch", str(ctx.exception))
        self.assertIn("decision", str(ctx.exception))

    def test_trigger_reasons_copied(self):
        """trigger_reasons are copied, not aliased."""
        c = _make_candidate()
        s = _make_score(trigger_reasons=["sr_reason"])
        d = _make_decision(trigger_reasons=["dec_reason"])
        result = bind_cr_presented_candidates([c], [s], [d])
        pc = result[0]
        # Decision trigger_reasons preferred.
        self.assertEqual(pc.trigger_reasons, ["dec_reason"])
        # Mutating returned list should not affect source.
        pc.trigger_reasons.append("injected")
        self.assertEqual(d.trigger_reasons, ["dec_reason"])

    def test_trigger_reasons_fallback_to_score(self):
        """trigger_reasons fall back to score when decision has none."""
        c = _make_candidate()
        s = _make_score(trigger_reasons=["heat", "growth"])
        d = _make_decision(trigger_reasons=[])
        result = bind_cr_presented_candidates([c], [s], [d])
        pc = result[0]
        self.assertEqual(pc.trigger_reasons, ["heat", "growth"])

    def test_suppress_labels_copied(self):
        """suppress_labels are copied, not aliased."""
        c = _make_candidate()
        s = _make_score()
        d = _make_decision(suppress_labels=["low_quality"])
        result = bind_cr_presented_candidates([c], [s], [d])
        pc = result[0]
        self.assertEqual(pc.suppress_labels, ["low_quality"])
        pc.suppress_labels.append("injected")
        self.assertEqual(d.suppress_labels, ["low_quality"])

    def test_no_mutable_aliasing_lists(self):
        """No mutable aliasing between presented and source lists."""
        c = _make_candidate()
        s = _make_score(trigger_reasons=["r1"])
        d = _make_decision(
            trigger_reasons=["r2"], suppress_labels=["s1"]
        )
        result = bind_cr_presented_candidates([c], [s], [d])
        pc = result[0]
        # Modify presented lists.
        pc.trigger_reasons.clear()
        pc.suppress_labels.clear()
        # Source lists must be untouched.
        self.assertEqual(d.trigger_reasons, ["r2"])
        self.assertEqual(d.suppress_labels, ["s1"])
        self.assertEqual(s.trigger_reasons, ["r1"])


# ===========================================================================
# B. Sorting tests
# ===========================================================================


class TestSortCRPresentedCandidates(unittest.TestCase):
    """B. Sorting tests."""

    def _make_pc(
        self,
        cid: str,
        level: str,
        score: float,
        title: str,
    ) -> CRPresentedCandidate:
        return CRPresentedCandidate(
            candidate=_make_candidate(cid, cid, title),
            score_result=_make_score(cid, cid, score),
            decision=_make_decision(cid, cid, level, score),
            candidate_id=cid,
            cluster_key=cid,
            display_title=title,
            representative_url=None,
            decision_level=level,
            total_score=score,
        )

    def test_level_ordering(self):
        """urgent before alert before watch before suppress."""
        p_suppress = self._make_pc("s", DECISION_SUPPRESS, 90.0, "Z Topic")
        p_watch = self._make_pc("w", DECISION_WATCH, 50.0, "Y Topic")
        p_alert = self._make_pc("a", DECISION_ALERT, 70.0, "X Topic")
        p_urgent = self._make_pc("u", DECISION_URGENT, 85.0, "W Topic")

        result = sort_cr_presented_candidates(
            [p_suppress, p_watch, p_alert, p_urgent]
        )
        self.assertEqual(
            [pc.decision_level for pc in result],
            [DECISION_URGENT, DECISION_ALERT, DECISION_WATCH, DECISION_SUPPRESS],
        )

    def test_same_level_score_descending(self):
        """Same level: total_score descending."""
        p_high = self._make_pc("h", DECISION_ALERT, 90.0, "A")
        p_mid = self._make_pc("m", DECISION_ALERT, 70.0, "B")
        p_low = self._make_pc("l", DECISION_ALERT, 60.0, "C")

        result = sort_cr_presented_candidates([p_low, p_high, p_mid])
        self.assertEqual(
            [pc.candidate_id for pc in result], ["h", "m", "l"]
        )

    def test_same_score_title_lexicographic(self):
        """Same score: display_title normalized lexicographic."""
        p_z = self._make_pc("z", DECISION_ALERT, 70.0, "Zebra topic")
        p_a = self._make_pc("a", DECISION_ALERT, 70.0, "Alpha topic")
        p_m = self._make_pc("m", DECISION_ALERT, 70.0, "Middle topic")

        result = sort_cr_presented_candidates([p_z, p_a, p_m])
        normalized = [normalize_topic_text(pc.display_title) for pc in result]
        self.assertEqual(normalized, sorted(normalized))

    def test_same_title_candidate_id_ascending(self):
        """Same title: candidate_id ascending."""
        p_c = self._make_pc("c3", DECISION_ALERT, 70.0, "Same Topic")
        p_a = self._make_pc("c1", DECISION_ALERT, 70.0, "Same Topic")
        p_b = self._make_pc("c2", DECISION_ALERT, 70.0, "Same Topic")

        result = sort_cr_presented_candidates([p_c, p_a, p_b])
        self.assertEqual(
            [pc.candidate_id for pc in result], ["c1", "c2", "c3"]
        )

    def test_input_not_mutated(self):
        """Input list is not mutated."""
        p1 = self._make_pc("c1", DECISION_ALERT, 70.0, "A")
        p2 = self._make_pc("c2", DECISION_URGENT, 90.0, "B")
        original = [p1, p2]
        original_ids = [pc.candidate_id for pc in original]
        sort_cr_presented_candidates(original)
        self.assertEqual(
            [pc.candidate_id for pc in original], original_ids
        )


# ===========================================================================
# C. CR-A selection tests
# ===========================================================================


class TestSelectCRACandidates(unittest.TestCase):
    """C. CR-A selection tests."""

    def _make_pc(
        self,
        cid: str,
        level: str,
        score: float,
        push_eligible: bool,
        title: str = "Topic",
    ) -> CRPresentedCandidate:
        return CRPresentedCandidate(
            candidate=_make_candidate(cid, cid, title),
            score_result=_make_score(cid, cid, score),
            decision=_make_decision(
                cid, cid, level, score, push_eligible=push_eligible
            ),
            candidate_id=cid,
            cluster_key=cid,
            display_title=title,
            representative_url=None,
            decision_level=level,
            total_score=score,
        )

    def test_urgent_selected(self):
        """urgent + push_eligible is selected."""
        pc = self._make_pc("u", DECISION_URGENT, 90.0, True)
        result = select_cr_a_candidates([pc])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].candidate_id, "u")

    def test_alert_selected(self):
        """alert + push_eligible is selected."""
        pc = self._make_pc("a", DECISION_ALERT, 70.0, True)
        result = select_cr_a_candidates([pc])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].candidate_id, "a")

    def test_watch_not_selected(self):
        """watch is NOT selected."""
        pc = self._make_pc("w", DECISION_WATCH, 50.0, False)
        result = select_cr_a_candidates([pc])
        self.assertEqual(len(result), 0)

    def test_suppress_not_selected(self):
        """suppress is NOT selected."""
        pc = self._make_pc("s", DECISION_SUPPRESS, 90.0, False)
        result = select_cr_a_candidates([pc])
        self.assertEqual(len(result), 0)

    def test_push_eligible_false_not_selected(self):
        """push_eligible=False not selected even if level is alert."""
        pc = self._make_pc("a", DECISION_ALERT, 70.0, False)
        result = select_cr_a_candidates([pc])
        self.assertEqual(len(result), 0)

    def test_respects_max_candidates(self):
        """Selection respects max_candidates."""
        config = CRTextPresentationConfig(max_candidates=2)
        p1 = self._make_pc("c1", DECISION_URGENT, 90.0, True, "A")
        p2 = self._make_pc("c2", DECISION_ALERT, 80.0, True, "B")
        p3 = self._make_pc("c3", DECISION_ALERT, 70.0, True, "C")
        result = select_cr_a_candidates([p1, p2, p3], config=config)
        self.assertEqual(len(result), 2)

    def test_selection_sorted(self):
        """Selection is sorted."""
        p_low = self._make_pc("c1", DECISION_ALERT, 60.0, True, "Low")
        p_high = self._make_pc("c2", DECISION_URGENT, 90.0, True, "High")
        result = select_cr_a_candidates([p_low, p_high])
        self.assertEqual(result[0].decision_level, DECISION_URGENT)
        self.assertEqual(result[1].decision_level, DECISION_ALERT)


# ===========================================================================
# D. Text rendering tests
# ===========================================================================


class TestRenderCRAText(unittest.TestCase):
    """D. Text rendering tests."""

    def _make_pc(
        self,
        cid: str = "c1",
        level: str = DECISION_ALERT,
        score: float = 70.0,
        title: str = "Topic title",
        url: str | None = "https://example.com",
        trigger_reasons: list[str] | None = None,
        push_eligible: bool = True,
    ) -> CRPresentedCandidate:
        return CRPresentedCandidate(
            candidate=_make_candidate(cid, cid, title, url),
            score_result=_make_score(cid, cid, score, trigger_reasons),
            decision=_make_decision(
                cid,
                cid,
                level,
                score,
                push_eligible=push_eligible,
                trigger_reasons=trigger_reasons,
            ),
            candidate_id=cid,
            cluster_key=cid,
            display_title=title,
            representative_url=url,
            decision_level=level,
            total_score=score,
            trigger_reasons=trigger_reasons or [],
        )

    def test_header_title(self):
        """Header title is correct."""
        pc = self._make_pc(push_eligible=True)
        run = CRPresentationRun(run_label="2026-06-09 23:30", candidates=[pc])
        text = render_cr_a_text(run)
        self.assertTrue(text.startswith("Ptilopsis Radar｜CR-A"))

    def test_datetime_line_parsed(self):
        """Standard run_label is formatted as YYYY-MM-DD HH:MM UTC+8."""
        pc = self._make_pc(push_eligible=True)
        run = CRPresentationRun(run_label="current-20260609-233000", candidates=[pc])
        text = render_cr_a_text(run)
        self.assertIn("2026-06-09 23:30 UTC+8", text)
        self.assertNotIn("Run:", text)

    def test_datetime_line_fallback(self):
        """Non-standard run_label is passed through unchanged."""
        pc = self._make_pc(push_eligible=True)
        run = CRPresentationRun(run_label="custom-label", candidates=[pc])
        text = render_cr_a_text(run)
        self.assertIn("custom-label", text)

    def test_candidates_count(self):
        """Candidates count is correct."""
        pc = self._make_pc(push_eligible=True)
        run = CRPresentationRun(run_label="T", candidates=[pc])
        text = render_cr_a_text(run)
        self.assertIn("Candidates: 1", text)

    def test_candidate_numbering(self):
        """Candidate numbering is correct."""
        p1 = self._make_pc("c1", DECISION_ALERT, 80.0, "Alpha", push_eligible=True)
        p2 = self._make_pc("c2", DECISION_ALERT, 70.0, "Beta", push_eligible=True)
        run = CRPresentationRun(run_label="T", candidates=[p1, p2])
        text = render_cr_a_text(run)
        self.assertIn("1. Alpha", text)
        self.assertIn("2. Beta", text)

    def test_decision_line(self):
        """Decision level shown without 'Decision:' prefix."""
        pc = self._make_pc(level=DECISION_URGENT, push_eligible=True)
        run = CRPresentationRun(run_label="T", candidates=[pc])
        text = render_cr_a_text(run)
        self.assertIn("\nurgent\n", text)
        self.assertNotIn("Decision:", text)

    def test_trigger_summary_top3_by_score(self):
        """Trigger line shows top-3 by score in semicolon format."""
        pc = self._make_pc(
            trigger_reasons=[
                "rank_movement=21.0",
                "new_burst=13.0",
                "recency_momentum=8.0",
                "best_rank_heat=30(rank=1)",
                "source_coverage_heat=2(n=1)",
                "item_count_heat=1(n=1)",
                "source_diversity=1(hotlist)",
                "source_count_support=0(n=1)",
            ],
            push_eligible=True,
        )
        run = CRPresentationRun(run_label="T", candidates=[pc])
        text = render_cr_a_text(run)
        # best_rank_heat=30 > rank_movement=21 > new_burst=13 → top-3
        self.assertIn("#1; rank↑21.0; burst+13.0; src 1", text)

    def test_trigger_summary_zero_score_filtered(self):
        """Zero-score reasons are not shown."""
        pc = self._make_pc(
            trigger_reasons=["source_count_support=0(n=1)", "rank_movement=15.0",
                             "source_coverage_heat=2(n=1)"],
            push_eligible=True,
        )
        run = CRPresentationRun(run_label="T", candidates=[pc])
        text = render_cr_a_text(run)
        self.assertIn("rank↑15.0", text)
        self.assertNotIn("support", text)

    def test_trigger_summary_src_count(self):
        """src N extracted from source_coverage_heat."""
        pc = self._make_pc(
            trigger_reasons=["rank_movement=10.0", "source_coverage_heat=8(n=3)"],
            push_eligible=True,
        )
        run = CRPresentationRun(run_label="T", candidates=[pc])
        text = render_cr_a_text(run)
        self.assertIn("src 3", text)

    def test_trigger_summary_fallback_empty(self):
        """Empty trigger_reasons → 'score threshold'."""
        pc = self._make_pc(trigger_reasons=[], push_eligible=True)
        run = CRPresentationRun(run_label="T", candidates=[pc])
        text = render_cr_a_text(run)
        self.assertIn("score threshold", text)

    def test_trigger_summary_fallback_all_filtered(self):
        """Non-empty reasons but all filtered (zero score / unknown key) → 'score threshold'."""
        pc = self._make_pc(
            trigger_reasons=[
                "source_coverage_heat=0(n=0)",
                "item_count_heat=0(n=0)",
                "source_diversity=1(hotlist)",
            ],
            push_eligible=True,
        )
        run = CRPresentationRun(run_label="T", candidates=[pc])
        text = render_cr_a_text(run)
        self.assertIn("score threshold", text)
        self.assertNotIn("src", text)

    def test_link_included_when_enabled_and_url(self):
        """Link line included when enabled and URL exists."""
        pc = self._make_pc(
            url="https://example.com", push_eligible=True
        )
        config = CRTextPresentationConfig(include_links=True)
        run = CRPresentationRun(run_label="T", candidates=[pc])
        text = render_cr_a_text(run, config=config)
        self.assertIn("Link: https://example.com", text)

    def test_link_omitted_when_url_missing(self):
        """Link omitted when URL is None."""
        pc = self._make_pc(url=None, push_eligible=True)
        config = CRTextPresentationConfig(include_links=True)
        run = CRPresentationRun(run_label="T", candidates=[pc])
        text = render_cr_a_text(run, config=config)
        self.assertNotIn("Link:", text)

    def test_link_omitted_when_disabled(self):
        """Link omitted when include_links=False."""
        pc = self._make_pc(
            url="https://example.com", push_eligible=True
        )
        config = CRTextPresentationConfig(include_links=False)
        run = CRPresentationRun(run_label="T", candidates=[pc])
        text = render_cr_a_text(run, config=config)
        self.assertNotIn("Link:", text)

    def test_no_score_by_default(self):
        """include_scores=False by default — no Score line."""
        pc = self._make_pc(push_eligible=True)
        run = CRPresentationRun(run_label="T", candidates=[pc])
        text = render_cr_a_text(run)
        self.assertNotIn("Score:", text)

    def test_score_shown_when_enabled(self):
        """include_scores=True adds Score line."""
        pc = self._make_pc(score=83.5, push_eligible=True)
        config = CRTextPresentationConfig(include_scores=True)
        run = CRPresentationRun(run_label="T", candidates=[pc])
        text = render_cr_a_text(run, config=config)
        self.assertIn("Score: 83.5", text)

    def test_candidates_shows_eligible_total(self):
        """Candidates line shows total_eligible_count when set."""
        pc = self._make_pc(push_eligible=True)
        run = CRPresentationRun(run_label="T", candidates=[pc], total_eligible_count=5)
        text = render_cr_a_text(run)
        self.assertIn("Candidates: 5", text)

    def test_candidates_falls_back_to_shown_count(self):
        """Candidates line falls back to len(candidates) when total_eligible_count=0."""
        pc = self._make_pc(push_eligible=True)
        run = CRPresentationRun(run_label="T", candidates=[pc])
        text = render_cr_a_text(run)
        self.assertIn("Candidates: 1", text)

    def test_high_score_suppressed_count_shown_when_positive(self):
        """Suppressed high-score candidates are visible in the header."""
        run = CRPresentationRun(
            run_label="T",
            candidates=[],
            high_score_suppressed_count=2,
        )
        text = render_cr_a_text(run)
        self.assertIn("Suppressed (high-score): 2", text)

    def test_high_score_suppressed_count_omitted_when_zero(self):
        """The header stays compact when no high-score candidate was suppressed."""
        run = CRPresentationRun(run_label="T", candidates=[])
        text = render_cr_a_text(run)
        self.assertNotIn("Suppressed (high-score):", text)

    def test_suppression_count_precedes_coverage_warning(self):
        """Combined observability headers retain a stable, readable order."""
        warning = "Collection coverage: 1/4 (3 failed)"
        run = CRPresentationRun(
            run_label="T",
            candidates=[],
            high_score_suppressed_count=2,
            coverage_warning=warning,
        )

        lines = render_cr_a_text(run).splitlines()

        self.assertLess(
            lines.index("Suppressed (high-score): 2"),
            lines.index(warning),
        )

    def test_no_summary_line(self):
        """No Summary line fabricated."""
        pc = self._make_pc(push_eligible=True)
        run = CRPresentationRun(run_label="T", candidates=[pc])
        text = render_cr_a_text(run)
        self.assertNotIn("Summary", text)

    def test_no_emoji(self):
        """No emoji in output."""
        pc = self._make_pc(push_eligible=True)
        run = CRPresentationRun(run_label="T", candidates=[pc])
        text = render_cr_a_text(run)
        # Check common emoji ranges.
        for ch in text:
            cp = ord(ch)
            self.assertFalse(
                0x1F300 <= cp <= 0x1F9FF,
                f"Emoji found: {ch} (U+{cp:04X})",
            )

    def test_no_boundary_note(self):
        """No boundary note."""
        pc = self._make_pc(push_eligible=True)
        run = CRPresentationRun(run_label="T", candidates=[pc])
        text = render_cr_a_text(run)
        self.assertNotIn("boundary", text.lower())
        self.assertNotIn("fact check", text.lower())

    def test_no_trailing_blank_lines(self):
        """No trailing blank lines."""
        pc = self._make_pc(push_eligible=True)
        run = CRPresentationRun(run_label="T", candidates=[pc])
        text = render_cr_a_text(run)
        self.assertFalse(text.endswith("\n\n"))
        self.assertFalse(text.endswith("\n"))

    def test_custom_title(self):
        """Custom title via config."""
        pc = self._make_pc(push_eligible=True)
        config = CRTextPresentationConfig(title="Custom Title")
        run = CRPresentationRun(run_label="T", candidates=[pc])
        text = render_cr_a_text(run, config=config)
        self.assertTrue(text.startswith("Custom Title"))


# ===========================================================================
# E. Empty CR-A tests
# ===========================================================================


class TestEmptyCRAText(unittest.TestCase):
    """E. Empty CR-A tests."""

    def test_empty_candidates_zero(self):
        """Candidates: 0 for empty run."""
        run = CRPresentationRun(run_label="2026-06-09 23:30", candidates=[])
        text = render_cr_a_text(run)
        self.assertIn("Candidates: 0", text)

    def test_empty_no_alert_message(self):
        """Contains 'No alert candidates.' for empty run."""
        run = CRPresentationRun(run_label="T", candidates=[])
        text = render_cr_a_text(run)
        self.assertIn("No alert candidates.", text)

    def test_empty_no_crash(self):
        """No crash on empty candidates."""
        run = CRPresentationRun(run_label="T", candidates=[])
        text = render_cr_a_text(run)
        self.assertIsInstance(text, str)
        self.assertTrue(len(text) > 0)

    def test_renders_exactly_what_run_gives(self):
        """render_cr_a_text renders exactly run.candidates, no filtering."""
        # A watch-level candidate — renderer does NOT filter it out.
        pc = CRPresentedCandidate(
            candidate=_make_candidate("c1", "k1", "Topic"),
            score_result=_make_score("c1", "k1"),
            decision=_make_decision(
                "c1", "k1", DECISION_WATCH, push_eligible=False
            ),
            candidate_id="c1",
            cluster_key="k1",
            display_title="Topic",
            representative_url=None,
            decision_level=DECISION_WATCH,
            total_score=50.0,
        )
        run = CRPresentationRun(run_label="T", candidates=[pc])
        text = render_cr_a_text(run)
        self.assertIn("Candidates: 1", text)
        self.assertIn("1. Topic", text)


# ===========================================================================
# F. Convenience helper tests
# ===========================================================================


class TestRenderCRATextFromParts(unittest.TestCase):
    """F. Convenience helper tests."""

    def test_same_result_as_manual(self):
        """render_cr_a_text_from_parts produces same as manual bind→select→run→render."""
        c = _make_candidate("c1", "k1", "Topic A", "https://a.com")
        s = _make_score("c1", "k1", 80.0, ["heat"])
        d = _make_decision(
            "c1", "k1", DECISION_URGENT, 80.0, True, ["heat"]
        )

        # Manual path: bind → select → run(selected) → render.
        presented = bind_cr_presented_candidates([c], [s], [d])
        selected = select_cr_a_candidates(presented)
        run = CRPresentationRun(run_label="Test Run", candidates=selected)
        manual_text = render_cr_a_text(run)

        # Convenience path.
        auto_text = render_cr_a_text_from_parts(
            [c], [s], [d], run_label="Test Run"
        )

        self.assertEqual(manual_text, auto_text)

    def test_binding_errors_propagate(self):
        """Missing binding errors propagate."""
        c = _make_candidate("c1", "k1")
        with self.assertRaises(ValueError):
            render_cr_a_text_from_parts(
                [c], [], [], run_label="T"
            )

    def test_with_config(self):
        """Config is passed through."""
        c = _make_candidate("c1", "k1", "Topic", "https://x.com")
        s = _make_score("c1", "k1", 85.0, ["heat"])
        d = _make_decision(
            "c1", "k1", DECISION_URGENT, 85.0, True, ["heat"]
        )
        config = CRTextPresentationConfig(include_scores=True)
        text = render_cr_a_text_from_parts(
            [c], [s], [d], run_label="T", config=config
        )
        self.assertIn("Score: 85.0", text)

    def test_watch_not_in_output(self):
        """watch candidates do not appear in render_cr_a_text_from_parts output."""
        c = _make_candidate("c1", "k1", "Watched Topic")
        s = _make_score("c1", "k1", 40.0)
        d = _make_decision(
            "c1", "k1", DECISION_WATCH, 40.0, push_eligible=False
        )
        text = render_cr_a_text_from_parts(
            [c], [s], [d], run_label="T"
        )
        self.assertIn("Candidates: 0", text)
        self.assertNotIn("Watched Topic", text)

    def test_suppress_not_in_output(self):
        """suppress candidates do not appear in render_cr_a_text_from_parts output."""
        c = _make_candidate("c1", "k1", "Suppressed Topic")
        s = _make_score("c1", "k1", 90.0)
        d = _make_decision(
            "c1", "k1", DECISION_SUPPRESS, 90.0, push_eligible=False
        )
        text = render_cr_a_text_from_parts(
            [c], [s], [d], run_label="T"
        )
        self.assertIn("Candidates: 0", text)
        self.assertIn("Suppressed (high-score): 1", text)
        self.assertNotIn("Suppressed Topic", text)

    def test_custom_urgent_threshold_controls_suppressed_count(self):
        c = _make_candidate("c1", "k1", "Suppressed Topic")
        s = _make_score("c1", "k1", 75.0)
        d = _make_decision(
            "c1", "k1", DECISION_SUPPRESS, 75.0, push_eligible=False
        )

        default_text = render_cr_a_text_from_parts(
            [c], [s], [d], run_label="T"
        )
        custom_text = render_cr_a_text_from_parts(
            [c], [s], [d], run_label="T", urgent_threshold=70.0
        )

        self.assertNotIn("Suppressed (high-score):", default_text)
        self.assertIn("Suppressed (high-score): 1", custom_text)


# ===========================================================================
# G. Module no-forbidden-import tests
# ===========================================================================


class TestNoForbiddenImports(unittest.TestCase):
    """G. Module does not import forbidden modules."""

    def test_no_telegram_import(self):
        """presentation module does not import telegram."""
        import trendradar.cr.presentation as mod

        source_file = mod.__file__
        assert source_file is not None
        with open(source_file) as f:
            source = f.read()
        self.assertNotIn("from trendradar.telegram", source)
        self.assertNotIn("import telegram", source.lower())

    def test_no_report_archive_import(self):
        """presentation module does not import report or archive."""
        import trendradar.cr.presentation as mod

        source_file = mod.__file__
        assert source_file is not None
        with open(source_file) as f:
            source = f.read()
        self.assertNotIn("from trendradar.report", source)
        self.assertNotIn("from trendradar.archive", source)

    def test_no_storage_config_import(self):
        """presentation module does not import storage or config."""
        import trendradar.cr.presentation as mod

        source_file = mod.__file__
        assert source_file is not None
        with open(source_file) as f:
            source = f.read()
        self.assertNotIn("from trendradar.storage", source)
        self.assertNotIn("from trendradar.config", source)

    def test_no_ai_analysis_result(self):
        """presentation module does not import AIAnalysisResult."""
        import trendradar.cr.presentation as mod

        source_file = mod.__file__
        assert source_file is not None
        with open(source_file) as f:
            source = f.read()
        self.assertNotIn("AIAnalysisResult", source)


if __name__ == "__main__":
    unittest.main()
