# coding=utf-8
"""
Tests for CR Markdown audit renderer (PR9g).

Covers: basic rendering, candidate rendering, ordering, score components,
source items, debug, Markdown safety, suppress audit, and no-forbidden-behavior
guarantees.
"""

import unittest

from trendradar.cr.decision import (
    CRDecision,
    DECISION_ALERT,
    DECISION_SUPPRESS,
    DECISION_URGENT,
    DECISION_WATCH,
)
from trendradar.cr.markdown import (
    CRMarkdownRenderConfig,
    _escape_markdown_text,
    _format_field_value,
    render_cr_markdown_audit,
)
from trendradar.cr.models import CRCandidate, CRSourceItem
from trendradar.cr.presentation import CRPresentedCandidate
from trendradar.cr.scoring import CRComponentScore, CRScoreResult
from trendradar.cr.state_snapshot import (
    CR_EVENT_STATE_SCHEMA_VERSION,
    CREventStateEntry,
    CREventStateSnapshot,
)
from trendradar.cr.state_transition_preview import (
    CREventStateTransitionPreview,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_source_item(
    title: str = "Source A",
    url: str | None = "https://example.com",
    source_type: str = "hotlist",
    source_name: str = "weibo",
    source_id: str = "weibo",
    feed_id: str | None = None,
    current_rank: int | None = 3,
    normalized_rank: int | None = 1,
    is_new: bool | None = False,
    is_new_semantics: str = "new_titles_detection",
    first_time: str | None = None,
    last_time: str | None = None,
    published_at: str | None = None,
) -> CRSourceItem:
    return CRSourceItem(
        title=title,
        url=url,
        source_type=source_type,
        source_name=source_name,
        source_id=source_id,
        feed_id=feed_id,
        current_rank=current_rank,
        normalized_rank=normalized_rank,
        is_new=is_new,
        is_new_semantics=is_new_semantics,
        first_time=first_time,
        last_time=last_time,
        published_at=published_at,
    )


def _make_score_result(
    candidate_id: str = "c1",
    cluster_key: str = "key1",
    total_score: float = 70.0,
    trigger_reasons: list[str] | None = None,
    profile_version: str = "cr-score-v0.1",
) -> CRScoreResult:
    return CRScoreResult(
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        profile_version=profile_version,
        total_score=total_score,
        trigger_reasons=trigger_reasons or [],
        debug={"profile_version": profile_version, "total_raw": total_score},
    )


def _make_decision(
    candidate_id: str = "c1",
    cluster_key: str = "key1",
    level: str = DECISION_ALERT,
    total_score: float = 70.0,
    suppress_labels: list[str] | None = None,
    trigger_reasons: list[str] | None = None,
    policy_version: str = "cr-decision-v0.1",
) -> CRDecision:
    return CRDecision(
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        profile_version="cr-score-v0.1",
        policy_version=policy_version,
        level=level,
        total_score=total_score,
        push_eligible=level in (DECISION_ALERT, DECISION_URGENT),
        suppress_labels=suppress_labels or [],
        trigger_reasons=trigger_reasons or [],
        debug={
            "alert_threshold": 60.0,
            "urgent_threshold": 80.0,
            "suppress_overrides_all": True,
        },
    )


def _make_candidate(
    candidate_id: str = "c1",
    cluster_key: str = "key1",
    display_title: str = "Topic A",
    representative_url: str | None = "https://example.com",
    source_items: list[CRSourceItem] | None = None,
) -> CRCandidate:
    return CRCandidate(
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        display_title=display_title,
        representative_url=representative_url,
        source_items=source_items or [],
    )


def _make_presented(
    candidate_id: str = "c1",
    cluster_key: str = "key1",
    display_title: str = "Topic A",
    representative_url: str | None = "https://example.com",
    decision_level: str = DECISION_ALERT,
    total_score: float = 70.0,
    trigger_reasons: list[str] | None = None,
    suppress_labels: list[str] | None = None,
    source_items: list[CRSourceItem] | None = None,
) -> CRPresentedCandidate:
    cand = _make_candidate(
        candidate_id, cluster_key, display_title, representative_url,
        source_items=source_items,
    )
    sr = _make_score_result(
        candidate_id, cluster_key, total_score, trigger_reasons,
    )
    dec = _make_decision(
        candidate_id, cluster_key, decision_level, total_score,
        suppress_labels=suppress_labels, trigger_reasons=trigger_reasons,
    )
    return CRPresentedCandidate(
        candidate=cand,
        score_result=sr,
        decision=dec,
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        display_title=display_title,
        representative_url=representative_url,
        decision_level=decision_level,
        total_score=total_score,
        trigger_reasons=trigger_reasons or [],
        suppress_labels=suppress_labels or [],
    )


# ===========================================================================
# A. Basic Rendering
# ===========================================================================


class TestBasicRendering(unittest.TestCase):
    """A. Basic rendering — header, sections, empty sections."""

    def test_title_line(self):
        """Title line exists."""
        text = render_cr_markdown_audit([], run_label="T")
        self.assertIn("# Ptilopsis Radar｜CR Markdown Audit", text)

    def test_custom_title(self):
        """Custom title via config."""
        config = CRMarkdownRenderConfig(title="Custom Title")
        text = render_cr_markdown_audit([], run_label="T", config=config)
        self.assertIn("# Custom Title", text)

    def test_run_label(self):
        """Run label exists."""
        text = render_cr_markdown_audit([], run_label="2026-06-09 23:30")
        self.assertIn("Run: 2026-06-09 23:30", text)

    def test_candidate_count(self):
        """Candidate count exists."""
        pc = _make_presented()
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("Candidates: 1", text)

    def test_candidate_count_empty(self):
        """Candidate count is 0 for empty input."""
        text = render_cr_markdown_audit([], run_label="T")
        self.assertIn("Candidates: 0", text)

    def test_high_score_suppressed_count(self):
        """High-score suppressed count line exists."""
        text = render_cr_markdown_audit([], run_label="T")
        self.assertIn("High-score suppressed candidates: 0", text)

    def test_all_four_sections_exist(self):
        """All four sections exist even when empty."""
        text = render_cr_markdown_audit([], run_label="T")
        self.assertIn("## urgent", text)
        self.assertIn("## alert", text)
        self.assertIn("## watch", text)
        self.assertIn("## suppress", text)

    def test_empty_sections_show_no_candidates(self):
        """Empty sections show '_No candidates._'."""
        text = render_cr_markdown_audit([], run_label="T")
        # All four sections are empty.
        self.assertEqual(text.count("_No candidates._"), 4)

    def test_non_empty_section_does_not_show_no_candidates(self):
        """Non-empty section does not show '_No candidates._'."""
        pc = _make_presented(decision_level=DECISION_URGENT, total_score=90.0)
        text = render_cr_markdown_audit([pc], run_label="T")
        # urgent section has a candidate.
        urgent_section = text.split("## alert")[0]
        self.assertNotIn("_No candidates._", urgent_section)


# ===========================================================================
# B. Candidate Rendering
# ===========================================================================


class TestCandidateRendering(unittest.TestCase):
    """B. Candidate field rendering."""

    def test_candidate_title_shown(self):
        """Candidate title shown."""
        pc = _make_presented(display_title="My Topic Title")
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("My Topic Title", text)

    def test_candidate_id_shown(self):
        """Candidate ID shown."""
        pc = _make_presented(candidate_id="abc123")
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("Candidate ID: abc123", text)

    def test_cluster_key_shown(self):
        """Cluster key shown."""
        pc = _make_presented(cluster_key="my_cluster_key")
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("Cluster Key: my_cluster_key", text)

    def test_decision_shown(self):
        """Decision shown."""
        pc = _make_presented(decision_level=DECISION_URGENT, total_score=90.0)
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("Decision: urgent", text)

    def test_total_score_shown(self):
        """Total score shown with one decimal."""
        pc = _make_presented(total_score=83.5)
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("Total Score: 83.5", text)

    def test_triggers_joined(self):
        """Triggers joined by '; '."""
        pc = _make_presented(trigger_reasons=["high heat", "rapid growth"])
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("Triggers: high heat; rapid growth", text)

    def test_fallback_trigger_score_threshold(self):
        """Fallback trigger: 'score threshold'."""
        pc = _make_presented(trigger_reasons=[])
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("Triggers: score threshold", text)

    def test_link_shown_when_exists(self):
        """Link shown when representative_url exists."""
        pc = _make_presented(representative_url="https://example.com")
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("Link: https://example.com", text)

    def test_link_omitted_when_absent(self):
        """Link omitted when representative_url is None."""
        pc = _make_presented(representative_url=None)
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertNotIn("Link:", text)

    def test_suppress_labels_shown_when_present(self):
        """Suppress labels shown when present."""
        pc = _make_presented(
            decision_level=DECISION_SUPPRESS,
            total_score=50.0,
            suppress_labels=["low_quality", "off_topic"],
        )
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("Suppress Labels: low_quality; off_topic", text)

    def test_suppress_labels_omitted_when_empty(self):
        """Suppress labels omitted when empty."""
        pc = _make_presented(decision_level=DECISION_ALERT, total_score=70.0)
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertNotIn("Suppress Labels:", text)


# ===========================================================================
# C. Ordering
# ===========================================================================


class TestOrdering(unittest.TestCase):
    """C. Ordering within Markdown output."""

    def test_urgent_before_alert(self):
        """urgent section appears before alert."""
        p_alert = _make_presented("a", "ka", "Alert", decision_level=DECISION_ALERT, total_score=70.0)
        p_urgent = _make_presented("u", "ku", "Urgent", decision_level=DECISION_URGENT, total_score=90.0)
        text = render_cr_markdown_audit([p_alert, p_urgent], run_label="T")
        self.assertLess(text.index("## urgent"), text.index("## alert"))

    def test_alert_before_watch(self):
        """alert section appears before watch."""
        p_watch = _make_presented("w", "kw", "Watch", decision_level=DECISION_WATCH, total_score=50.0)
        p_alert = _make_presented("a", "ka", "Alert", decision_level=DECISION_ALERT, total_score=70.0)
        text = render_cr_markdown_audit([p_watch, p_alert], run_label="T")
        self.assertLess(text.index("## alert"), text.index("## watch"))

    def test_watch_before_suppress(self):
        """watch section appears before suppress."""
        p_suppress = _make_presented("s", "ks", "Suppress", decision_level=DECISION_SUPPRESS, total_score=90.0, suppress_labels=["x"])
        p_watch = _make_presented("w", "kw", "Watch", decision_level=DECISION_WATCH, total_score=50.0)
        text = render_cr_markdown_audit([p_suppress, p_watch], run_label="T")
        self.assertLess(text.index("## watch"), text.index("## suppress"))

    def test_same_level_sorted_by_score_desc(self):
        """Same level: sorted by total_score descending."""
        p_low = _make_presented("c_low", "k", "Low Score", decision_level=DECISION_ALERT, total_score=60.0)
        p_high = _make_presented("c_high", "k", "High Score", decision_level=DECISION_ALERT, total_score=90.0)
        text = render_cr_markdown_audit([p_low, p_high], run_label="T")
        # In alert section, high score candidate appears first.
        alert_section = text.split("## watch")[0]
        high_pos = alert_section.index("High Score")
        low_pos = alert_section.index("Low Score")
        self.assertLess(high_pos, low_pos)

    def test_input_list_not_mutated(self):
        """Input list is not mutated."""
        p1 = _make_presented("c1", "k1", "A", decision_level=DECISION_ALERT, total_score=70.0)
        p2 = _make_presented("c2", "k2", "B", decision_level=DECISION_URGENT, total_score=90.0)
        original = [p1, p2]
        original_ids = [pc.candidate_id for pc in original]
        render_cr_markdown_audit(original, run_label="T")
        self.assertEqual([pc.candidate_id for pc in original], original_ids)


# ===========================================================================
# D. Score Components
# ===========================================================================


class TestScoreComponents(unittest.TestCase):
    """D. Score components table."""

    def test_score_table_included_by_default(self):
        """Score table included by default."""
        pc = _make_presented()
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("#### Score Components", text)
        self.assertIn("| Component | Raw | Capped | Cap |", text)

    def test_all_six_components_included(self):
        """All six components included."""
        pc = _make_presented()
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("Growth Raw", text)
        self.assertIn("Current Heat Raw", text)
        self.assertIn("Heat", text)
        self.assertIn("Cross Layer Raw", text)
        self.assertIn("Background Support Raw", text)
        self.assertIn("Cross Evidence", text)

    def test_score_table_hidden_when_disabled(self):
        """include_score_components=False hides table."""
        config = CRMarkdownRenderConfig(include_score_components=False)
        pc = _make_presented()
        text = render_cr_markdown_audit([pc], run_label="T", config=config)
        self.assertNotIn("#### Score Components", text)
        self.assertNotIn("| Component |", text)


# ===========================================================================
# E. Source Items
# ===========================================================================


class TestSourceItems(unittest.TestCase):
    """E. Source items rendering."""

    def test_source_items_included_by_default(self):
        """Source items included by default."""
        si = _make_source_item()
        pc = _make_presented(source_items=[si])
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("#### Source Items", text)

    def test_source_title_shown(self):
        """Source title shown."""
        si = _make_source_item(title="My Source Title")
        pc = _make_presented(source_items=[si])
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("My Source Title", text)

    def test_source_link_shown(self):
        """Source link shown."""
        si = _make_source_item(url="https://source.example.com")
        pc = _make_presented(source_items=[si])
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("https://source.example.com", text)

    def test_source_metadata_shown(self):
        """Source metadata shown."""
        si = _make_source_item(
            source_type="hotlist",
            source_name="weibo",
            source_id="weibo",
            current_rank=3,
            normalized_rank=1,
        )
        pc = _make_presented(source_items=[si])
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("Source Type: hotlist", text)
        self.assertIn("Source Name: weibo", text)
        self.assertIn("Source ID: weibo", text)
        self.assertIn("Current Rank: 3", text)
        self.assertIn("Normalized Rank: 1", text)

    def test_none_fields_skipped(self):
        """None / empty fields skipped."""
        si = CRSourceItem(title="T", url=None, source_type="hotlist", feed_id=None)
        pc = _make_presented(source_items=[si])
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertNotIn("Feed ID:", text)
        self.assertNotIn("Current Rank:", text)
        self.assertNotIn("Normalized Rank:", text)

    def test_source_items_hidden_when_disabled(self):
        """include_source_items=False hides source section."""
        config = CRMarkdownRenderConfig(include_source_items=False)
        si = _make_source_item()
        pc = _make_presented(source_items=[si])
        text = render_cr_markdown_audit([pc], run_label="T", config=config)
        self.assertNotIn("#### Source Items", text)


# ===========================================================================
# F. Debug
# ===========================================================================


class TestDebug(unittest.TestCase):
    """F. Debug section."""

    def test_debug_included_by_default(self):
        """Debug section included by default."""
        pc = _make_presented()
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("#### Debug", text)
        self.assertIn("```text", text)

    def test_debug_hidden_when_disabled(self):
        """include_debug=False hides debug section."""
        config = CRMarkdownRenderConfig(include_debug=False)
        pc = _make_presented()
        text = render_cr_markdown_audit([pc], run_label="T", config=config)
        self.assertNotIn("#### Debug", text)

    def test_debug_does_not_dump_full_object_repr(self):
        """Debug does not dump full object repr."""
        pc = _make_presented()
        text = render_cr_markdown_audit([pc], run_label="T")
        # Should not contain Python object repr.
        self.assertNotIn("CRScoreResult(", text)
        self.assertNotIn("CRDecision(", text)
        self.assertNotIn("CRComponentScore(", text)
        self.assertNotIn("CRSourceItem(", text)


# ===========================================================================
# G. Markdown Safety
# ===========================================================================


class TestMarkdownSafety(unittest.TestCase):
    """G. Markdown escaping and safety."""

    def test_pipe_in_title_does_not_break_table(self):
        """Pipe in title is escaped."""
        pc = _make_presented(display_title="Topic | with pipes")
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("Topic \\| with pipes", text)

    def test_newlines_in_title_collapsed(self):
        """Newlines in title are collapsed to spaces."""
        pc = _make_presented(display_title="Topic\nwith\nnewlines")
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("Topic with newlines", text)
        self.assertNotIn("Topic\nwith", text)

    def test_no_trailing_blank_lines(self):
        """No trailing blank lines."""
        pc = _make_presented()
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertFalse(text.endswith("\n\n"))
        self.assertFalse(text.endswith("\n"))

    def test_escape_markdown_text_basic(self):
        """_escape_markdown_text basic behavior."""
        self.assertEqual(_escape_markdown_text("hello"), "hello")
        self.assertEqual(_escape_markdown_text("a|b"), "a\\|b")
        self.assertEqual(_escape_markdown_text("a\nb"), "a b")
        self.assertEqual(_escape_markdown_text("  hello  "), "hello")


# ===========================================================================
# G2. Metadata / field-level escaping (PR9g cleanup)
# ===========================================================================


class TestFieldValueEscaping(unittest.TestCase):
    """G2. Field-level escaping via _format_field_value and metadata output."""

    def test_format_field_value_escapes_strings(self):
        """_format_field_value escapes string values."""
        self.assertEqual(_format_field_value("a|b"), "a\\|b")
        self.assertEqual(_format_field_value("a\nb"), "a b")
        self.assertEqual(_format_field_value("  x  "), "x")

    def test_format_field_value_numeric_passthrough(self):
        """_format_field_value renders numbers with str()."""
        self.assertEqual(_format_field_value(3), "3")
        self.assertEqual(_format_field_value(1), "1")

    def test_format_field_value_bool_passthrough(self):
        """_format_field_value renders bools with str()."""
        self.assertEqual(_format_field_value(True), "True")
        self.assertEqual(_format_field_value(False), "False")

    def test_source_name_pipe_escaped(self):
        """source_name containing '|' is escaped."""
        si = _make_source_item(source_name="weibo|hot")
        pc = _make_presented(source_items=[si])
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("Source Name: weibo\\|hot", text)

    def test_source_name_newline_collapsed(self):
        """source_name containing a newline is collapsed to a space."""
        si = _make_source_item(source_name="weibo\nhot")
        pc = _make_presented(source_items=[si])
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("Source Name: weibo hot", text)
        self.assertNotIn("Source Name: weibo\nhot", text)

    def test_source_id_feed_id_escaped(self):
        """source_id / feed_id string values are escaped."""
        si = _make_source_item(source_id="id|x", feed_id="feed|y")
        pc = _make_presented(source_items=[si])
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("Source ID: id\\|x", text)
        self.assertIn("Feed ID: feed\\|y", text)

    def test_numeric_metadata_renders_normally(self):
        """Numeric metadata values render normally."""
        si = _make_source_item(current_rank=3, normalized_rank=1)
        pc = _make_presented(source_items=[si])
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("Current Rank: 3", text)
        self.assertIn("Normalized Rank: 1", text)

    def test_boolean_metadata_renders_normally(self):
        """Boolean metadata values render normally."""
        si = _make_source_item(is_new=True)
        pc = _make_presented(source_items=[si])
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("Is New: True", text)

    def test_cluster_key_pipe_escaped(self):
        """cluster_key containing '|' is escaped."""
        pc = _make_presented(cluster_key="key|a")
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("Cluster Key: key\\|a", text)

    def test_candidate_id_pipe_escaped(self):
        """candidate_id containing '|' is escaped."""
        pc = _make_presented(candidate_id="c|1")
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("Candidate ID: c\\|1", text)

    def test_run_label_newline_collapsed(self):
        """run_label newline is collapsed to a space."""
        text = render_cr_markdown_audit([], run_label="2026-06-09\n23:30")
        self.assertIn("Run: 2026-06-09 23:30", text)
        self.assertNotIn("Run: 2026-06-09\n23:30", text)

    def test_config_title_pipe_escaped(self):
        """config.title pipe is escaped."""
        config = CRMarkdownRenderConfig(title="Radar | Audit")
        text = render_cr_markdown_audit([], run_label="T", config=config)
        self.assertIn("# Radar \\| Audit", text)


# ===========================================================================
# H. Suppress Audit
# ===========================================================================


class TestSuppressAudit(unittest.TestCase):
    """H. Suppress candidates in audit."""

    def test_suppress_candidates_included(self):
        """Suppress candidates are included in output."""
        pc = _make_presented(
            decision_level=DECISION_SUPPRESS,
            total_score=90.0,
            suppress_labels=["x"],
        )
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("## suppress", text)
        self.assertNotIn("_No candidates._", text.split("## suppress")[1])
        self.assertIn("Decision: suppress", text)

    def test_high_score_suppress_counted_at_80(self):
        """High-score suppress counted when score >= 80."""
        pc = _make_presented(
            decision_level=DECISION_SUPPRESS,
            total_score=80.0,
            suppress_labels=["x"],
        )
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("High-score suppressed candidates: 1", text)

    def test_high_score_suppress_counted_above_80(self):
        """High-score suppress counted when score > 80."""
        pc = _make_presented(
            decision_level=DECISION_SUPPRESS,
            total_score=95.0,
            suppress_labels=["x"],
        )
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("High-score suppressed candidates: 1", text)

    def test_suppress_score_79_9_not_counted(self):
        """Suppress score 79.9 is NOT counted as high-score suppressed."""
        pc = _make_presented(
            decision_level=DECISION_SUPPRESS,
            total_score=79.9,
            suppress_labels=["x"],
        )
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("High-score suppressed candidates: 0", text)

    def test_non_suppress_not_counted(self):
        """Non-suppress candidates are not counted as high-score suppressed."""
        pc = _make_presented(
            decision_level=DECISION_URGENT,
            total_score=90.0,
        )
        text = render_cr_markdown_audit([pc], run_label="T")
        self.assertIn("High-score suppressed candidates: 0", text)


# ===========================================================================
# I. No Forbidden Behavior
# ===========================================================================


class TestStateTransitionPreviewRendering(unittest.TestCase):
    """I. Optional state transition preview rendering."""

    def test_default_does_not_render_state_transition_preview(self):
        text = render_cr_markdown_audit([], run_label="T")
        self.assertNotIn("State Transition Preview", text)

    def test_config_renders_state_transition_preview(self):
        preview = CREventStateTransitionPreview(
            prior_snapshot_available=True,
            prior_snapshot_loaded=True,
            prior_snapshot_error=None,
            update_count=2,
            next_snapshot=CREventStateSnapshot(
                schema_version=CR_EVENT_STATE_SCHEMA_VERSION,
                entries=(
                    CREventStateEntry(event_key="event-a"),
                    CREventStateEntry(event_key="event-b"),
                    CREventStateEntry(event_key="event-c"),
                ),
            ),
            reason="prior snapshot merged with current state updates",
        )
        config = CRMarkdownRenderConfig(
            include_state_transition_preview=True,
            state_transition_preview=preview,
        )

        text = render_cr_markdown_audit([], run_label="T", config=config)

        self.assertIn("#### State Transition Preview", text)
        self.assertIn("- Prior Source: `loaded`", text)
        self.assertIn("- Prior Loaded: `True`", text)
        self.assertIn("- Update Count: `2`", text)
        self.assertIn("- Next Snapshot Preview: `available`", text)
        self.assertIn("- Next Snapshot Entry Count: `3`", text)

    def test_config_renders_suppressed_state_transition_preview(self):
        preview = CREventStateTransitionPreview(
            prior_snapshot_available=False,
            prior_snapshot_loaded=False,
            prior_snapshot_error="invalid event state snapshot",
            update_count=1,
            next_snapshot=None,
            reason="prior snapshot failed to load; next-state preview suppressed",
        )
        config = CRMarkdownRenderConfig(
            include_state_transition_preview=True,
            state_transition_preview=preview,
        )

        text = render_cr_markdown_audit([], run_label="T", config=config)

        self.assertIn("- Prior Source: `error`", text)
        self.assertIn("- Prior Error: `invalid event state snapshot`", text)
        self.assertIn("- Next Snapshot Preview: `suppressed`", text)


# ===========================================================================
# J. No Forbidden Behavior
# ===========================================================================


class TestNoForbiddenBehavior(unittest.TestCase):
    """J. Module does not import forbidden modules or do I/O."""

    def _read_source(self) -> str:
        import trendradar.cr.markdown as mod
        source_file = mod.__file__
        assert source_file is not None
        with open(source_file) as f:
            return f.read()

    def test_no_telegram_import(self):
        """No telegram import."""
        source = self._read_source()
        self.assertNotIn("from trendradar.telegram", source)
        self.assertNotIn("import telegram", source.lower())

    def test_no_report_archive_import(self):
        """No report or archive import."""
        source = self._read_source()
        self.assertNotIn("from trendradar.report", source)
        self.assertNotIn("from trendradar.archive", source)

    def test_no_storage_config_import(self):
        """No storage or config import."""
        source = self._read_source()
        self.assertNotIn("from trendradar.storage", source)
        self.assertNotIn("from trendradar.config", source)

    def test_no_ai_analysis_result(self):
        """No AIAnalysisResult."""
        source = self._read_source()
        self.assertNotIn("AIAnalysisResult", source)

    def test_no_file_writing(self):
        """No file writing operations."""
        source = self._read_source()
        self.assertNotIn("open(", source)
        self.assertNotIn("write(", source)
        self.assertNotIn("pathlib", source)

    def test_no_runtime_import(self):
        """No runtime or __main__ import."""
        source = self._read_source()
        self.assertNotIn("from trendradar.__main__", source)
        self.assertNotIn("from trendradar.runtime", source)
        self.assertNotIn("_run_analysis_pipeline", source)


if __name__ == "__main__":
    unittest.main()
