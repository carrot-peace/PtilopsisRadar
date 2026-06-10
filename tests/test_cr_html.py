# coding=utf-8
"""
Tests for the canonical CR HTML audit renderer (PR9i).

Covers: basic structure, candidate rendering, ordering, score components,
source items, debug, collapse behavior, HTML safety, suppress audit, and
no-forbidden-behavior / no-I/O guarantees.
"""

import unittest

from trendradar.cr.decision import (
    CRDecision,
    DECISION_ALERT,
    DECISION_SUPPRESS,
    DECISION_URGENT,
    DECISION_WATCH,
)
from trendradar.cr.html import (
    CRHTMLRenderConfig,
    render_cr_html_audit,
)
from trendradar.cr.models import CRCandidate, CRSourceItem
from trendradar.cr.presentation import CRPresentedCandidate
from trendradar.cr.scoring import CRScoreResult


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_source_item(
    title: str = "Source A",
    url: str | None = "https://source.example.com",
    source_type: str = "hotlist",
    source_name: str = "weibo",
    source_id: str = "weibo",
    feed_id: str | None = None,
    current_rank: int | None = 3,
    normalized_rank: int | None = 1,
    is_new: bool | None = True,
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
    )


def _make_presented(
    candidate_id: str = "c1",
    cluster_key: str = "key1",
    display_title: str = "Topic A",
    representative_url: str | None = "https://example.com",
    decision_level: str = DECISION_ALERT,
    total_score: float = 70.0,
    trigger_reasons: list | None = None,
    suppress_labels: list | None = None,
    source_items: list | None = None,
    score_debug: dict | None = None,
    decision_debug: dict | None = None,
) -> CRPresentedCandidate:
    cand = CRCandidate(
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        display_title=display_title,
        representative_url=representative_url,
        source_items=source_items or [],
    )
    sr = CRScoreResult(
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        profile_version="cr-score-v0.1",
        total_score=total_score,
        trigger_reasons=trigger_reasons or [],
        debug=score_debug
        if score_debug is not None
        else {"profile_version": "cr-score-v0.1", "total_raw": total_score},
    )
    dec = CRDecision(
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        profile_version="cr-score-v0.1",
        policy_version="cr-decision-v0.1",
        level=decision_level,
        total_score=total_score,
        push_eligible=decision_level in (DECISION_ALERT, DECISION_URGENT),
        suppress_labels=suppress_labels or [],
        trigger_reasons=trigger_reasons or [],
        debug=decision_debug
        if decision_debug is not None
        else {"policy_version": "cr-decision-v0.1"},
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


def _suppress_portion(html: str) -> str:
    """Return everything after the suppress section heading."""
    return html.split("<h2>suppress</h2>")[1]


def _watch_portion(html: str) -> str:
    """Return only the watch section (between watch and suppress headings)."""
    return html.split("<h2>watch</h2>")[1].split("<h2>suppress</h2>")[0]


# ===========================================================================
# A. Basic Rendering
# ===========================================================================


class TestBasicRendering(unittest.TestCase):
    """A. Basic document structure."""

    def test_doctype_exists(self):
        html = render_cr_html_audit([], run_label="T")
        self.assertIn("<!doctype html>", html)

    def test_html_head_body_exist(self):
        html = render_cr_html_audit([], run_label="T")
        self.assertIn("<html lang=\"en\">", html)
        self.assertIn("<head>", html)
        self.assertIn("<body>", html)
        self.assertIn("</html>", html)

    def test_meta_charset_exists(self):
        html = render_cr_html_audit([], run_label="T")
        self.assertIn('<meta charset="utf-8">', html)

    def test_title_exists(self):
        html = render_cr_html_audit([], run_label="T")
        self.assertIn("<title>Ptilopsis Radar｜CR HTML Audit</title>", html)

    def test_custom_title(self):
        cfg = CRHTMLRenderConfig(title="Custom HTML Title")
        html = render_cr_html_audit([], run_label="T", config=cfg)
        self.assertIn("<title>Custom HTML Title</title>", html)
        self.assertIn("<h1>Custom HTML Title</h1>", html)

    def test_h1_exists(self):
        html = render_cr_html_audit([], run_label="T")
        self.assertIn("<h1>Ptilopsis Radar｜CR HTML Audit</h1>", html)

    def test_run_label_exists(self):
        html = render_cr_html_audit([], run_label="2026-06-09 23:30")
        self.assertIn(
            "<strong>Run:</strong> 2026-06-09 23:30", html
        )

    def test_candidate_count_exists(self):
        pc = _make_presented()
        html = render_cr_html_audit([pc], run_label="T")
        self.assertIn("<strong>Candidates:</strong> 1", html)

    def test_high_score_suppressed_count_exists(self):
        html = render_cr_html_audit([], run_label="T")
        self.assertIn(
            "<strong>High-score suppressed candidates:</strong> 0", html
        )

    def test_all_four_sections_exist(self):
        html = render_cr_html_audit([], run_label="T")
        self.assertIn("<h2>urgent</h2>", html)
        self.assertIn("<h2>alert</h2>", html)
        self.assertIn("<h2>watch</h2>", html)
        self.assertIn("<h2>suppress</h2>", html)
        self.assertIn('class="decision-section decision-urgent"', html)

    def test_empty_section_shows_no_candidates(self):
        html = render_cr_html_audit([], run_label="T")
        self.assertEqual(html.count("<p><em>No candidates.</em></p>"), 4)

    def test_no_emoji(self):
        pc = _make_presented()
        html = render_cr_html_audit([pc], run_label="T")
        # Common decoration emoji must not appear.
        for emoji in ("🔥", "⚠️", "✅", "🚨", "📊"):
            self.assertNotIn(emoji, html)


# ===========================================================================
# B. Candidate Rendering
# ===========================================================================


class TestCandidateRendering(unittest.TestCase):
    """B. Candidate card fields."""

    def test_candidate_title_shown(self):
        pc = _make_presented(display_title="My HTML Topic")
        html = render_cr_html_audit([pc], run_label="T")
        self.assertIn("<h3>My HTML Topic</h3>", html)

    def test_candidate_id_shown(self):
        pc = _make_presented(candidate_id="abc123")
        html = render_cr_html_audit([pc], run_label="T")
        self.assertIn("<dt>Candidate ID</dt><dd>abc123</dd>", html)
        self.assertIn('id="candidate-abc123"', html)

    def test_cluster_key_shown(self):
        pc = _make_presented(cluster_key="my_cluster")
        html = render_cr_html_audit([pc], run_label="T")
        self.assertIn("<dt>Cluster Key</dt><dd>my_cluster</dd>", html)

    def test_decision_shown(self):
        pc = _make_presented(decision_level=DECISION_URGENT, total_score=90.0)
        html = render_cr_html_audit([pc], run_label="T")
        self.assertIn("<dt>Decision</dt><dd>urgent</dd>", html)

    def test_total_score_shown(self):
        pc = _make_presented(total_score=83.5)
        html = render_cr_html_audit([pc], run_label="T")
        self.assertIn("<dt>Total Score</dt><dd>83.5</dd>", html)

    def test_triggers_joined(self):
        pc = _make_presented(trigger_reasons=["high heat", "rapid growth"])
        html = render_cr_html_audit([pc], run_label="T")
        self.assertIn(
            "<dt>Triggers</dt><dd>high heat; rapid growth</dd>", html
        )

    def test_fallback_trigger_score_threshold(self):
        pc = _make_presented(trigger_reasons=[])
        html = render_cr_html_audit([pc], run_label="T")
        self.assertIn("<dt>Triggers</dt><dd>score threshold</dd>", html)

    def test_link_rendered_as_anchor(self):
        pc = _make_presented(representative_url="https://example.com")
        html = render_cr_html_audit([pc], run_label="T")
        self.assertIn(
            '<dt>Link</dt><dd><a href="https://example.com">'
            "https://example.com</a></dd>",
            html,
        )

    def test_link_omitted_when_absent(self):
        pc = _make_presented(representative_url=None)
        html = render_cr_html_audit([pc], run_label="T")
        self.assertNotIn("<dt>Link</dt>", html)

    def test_suppress_labels_shown_when_present(self):
        pc = _make_presented(
            decision_level=DECISION_SUPPRESS,
            total_score=50.0,
            suppress_labels=["low_quality", "off_topic"],
        )
        html = render_cr_html_audit([pc], run_label="T")
        self.assertIn(
            "<dt>Suppress Labels</dt><dd>low_quality; off_topic</dd>", html
        )

    def test_suppress_labels_omitted_when_empty(self):
        pc = _make_presented(decision_level=DECISION_ALERT, total_score=70.0)
        html = render_cr_html_audit([pc], run_label="T")
        self.assertNotIn("<dt>Suppress Labels</dt>", html)


# ===========================================================================
# C. Ordering
# ===========================================================================


class TestOrdering(unittest.TestCase):
    """C. Section / candidate ordering."""

    def test_section_order(self):
        html = render_cr_html_audit([], run_label="T")
        u = html.index("<h2>urgent</h2>")
        a = html.index("<h2>alert</h2>")
        w = html.index("<h2>watch</h2>")
        s = html.index("<h2>suppress</h2>")
        self.assertTrue(u < a < w < s)

    def test_same_level_score_desc(self):
        p_low = _make_presented(
            "c_low", "k", "Low Score", decision_level=DECISION_ALERT,
            total_score=60.0,
        )
        p_high = _make_presented(
            "c_high", "k", "High Score", decision_level=DECISION_ALERT,
            total_score=90.0,
        )
        html = render_cr_html_audit([p_low, p_high], run_label="T")
        self.assertLess(html.index("High Score"), html.index("Low Score"))

    def test_input_list_not_mutated(self):
        p1 = _make_presented("c1", "k1", "A", decision_level=DECISION_ALERT, total_score=70.0)
        p2 = _make_presented("c2", "k2", "B", decision_level=DECISION_URGENT, total_score=90.0)
        original = [p1, p2]
        original_ids = [pc.candidate_id for pc in original]
        render_cr_html_audit(original, run_label="T")
        self.assertEqual([pc.candidate_id for pc in original], original_ids)


# ===========================================================================
# D. Score Components
# ===========================================================================


class TestScoreComponents(unittest.TestCase):
    """D. Score components table."""

    def test_score_table_included_by_default(self):
        pc = _make_presented()
        html = render_cr_html_audit([pc], run_label="T")
        self.assertIn('<table class="score-components">', html)
        self.assertIn(
            "<th>Component</th><th>Raw</th><th>Capped</th><th>Cap</th>", html
        )

    def test_all_six_components_included(self):
        pc = _make_presented()
        html = render_cr_html_audit([pc], run_label="T")
        for name in (
            "Growth Raw",
            "Current Heat Raw",
            "Heat",
            "Cross Layer Raw",
            "Background Support Raw",
            "Cross Evidence",
        ):
            self.assertIn(f"<td>{name}</td>", html)

    def test_score_table_hidden_when_disabled(self):
        cfg = CRHTMLRenderConfig(include_score_components=False)
        pc = _make_presented()
        html = render_cr_html_audit([pc], run_label="T", config=cfg)
        # The CSS rule for the table lives in <style>; assert the table element
        # itself is absent.
        self.assertNotIn('<table class="score-components">', html)


# ===========================================================================
# E. Source Items
# ===========================================================================


class TestSourceItems(unittest.TestCase):
    """E. Source items rendering."""

    def test_source_items_included_by_default(self):
        pc = _make_presented(source_items=[_make_source_item()])
        html = render_cr_html_audit([pc], run_label="T")
        self.assertIn('<section class="source-items">', html)
        self.assertIn("<h4>Source Items</h4>", html)

    def test_source_title_link_shown(self):
        si = _make_source_item(title="Src Title", url="https://s.example.com")
        pc = _make_presented(source_items=[si])
        html = render_cr_html_audit([pc], run_label="T")
        self.assertIn(
            '<a href="https://s.example.com">Src Title</a>', html
        )

    def test_source_title_without_url_plain(self):
        si = _make_source_item(title="Plain Src", url=None)
        pc = _make_presented(source_items=[si])
        html = render_cr_html_audit([pc], run_label="T")
        self.assertIn("Plain Src", html)

    def test_metadata_shown(self):
        si = _make_source_item(source_name="weibo", source_id="weibo")
        pc = _make_presented(source_items=[si])
        html = render_cr_html_audit([pc], run_label="T")
        self.assertIn("<dt>Source Name</dt><dd>weibo</dd>", html)
        self.assertIn("<dt>Source Type</dt><dd>hotlist</dd>", html)

    def test_none_empty_fields_skipped(self):
        si = _make_source_item(feed_id=None, current_rank=None, normalized_rank=None)
        pc = _make_presented(source_items=[si])
        html = render_cr_html_audit([pc], run_label="T")
        self.assertNotIn("<dt>Feed ID</dt>", html)
        self.assertNotIn("<dt>Current Rank</dt>", html)
        self.assertNotIn("<dt>Normalized Rank</dt>", html)

    def test_source_items_hidden_when_disabled(self):
        cfg = CRHTMLRenderConfig(include_source_items=False)
        pc = _make_presented(source_items=[_make_source_item()])
        html = render_cr_html_audit([pc], run_label="T", config=cfg)
        # The CSS rule for the list lives in <style>; assert the section
        # element and its heading are absent.
        self.assertNotIn('<section class="source-items">', html)
        self.assertNotIn("<h4>Source Items</h4>", html)

    def test_source_items_order_preserved(self):
        si1 = _make_source_item(title="First Src", url=None)
        si2 = _make_source_item(title="Second Src", url=None)
        pc = _make_presented(source_items=[si1, si2])
        html = render_cr_html_audit([pc], run_label="T")
        self.assertLess(html.index("First Src"), html.index("Second Src"))


# ===========================================================================
# F. Debug
# ===========================================================================


class TestDebug(unittest.TestCase):
    """F. Debug block."""

    def test_debug_included_by_default(self):
        pc = _make_presented()
        html = render_cr_html_audit([pc], run_label="T")
        self.assertIn('<details class="debug">', html)
        self.assertIn("<summary>Debug</summary>", html)
        self.assertIn("<pre>", html)
        self.assertIn("score.profile_version: cr-score-v0.1", html)

    def test_debug_hidden_when_disabled(self):
        cfg = CRHTMLRenderConfig(include_debug=False)
        pc = _make_presented()
        html = render_cr_html_audit([pc], run_label="T", config=cfg)
        self.assertNotIn('<details class="debug">', html)
        self.assertNotIn("<summary>Debug</summary>", html)

    def test_debug_does_not_dump_full_object_repr(self):
        pc = _make_presented()
        html = render_cr_html_audit([pc], run_label="T")
        self.assertNotIn("CRScoreResult(", html)
        self.assertNotIn("CRDecision(", html)
        self.assertNotIn("CRComponentScore(", html)
        self.assertNotIn("CRSourceItem(", html)


# ===========================================================================
# G. Collapse Behavior
# ===========================================================================


class TestCollapseBehavior(unittest.TestCase):
    """G. Suppress / watch section collapsing."""

    def test_collapse_suppress_true_collapsed(self):
        cfg = CRHTMLRenderConfig(collapse_suppress=True)
        pc = _make_presented(
            decision_level=DECISION_SUPPRESS, total_score=90.0,
            suppress_labels=["x"],
        )
        html = render_cr_html_audit([pc], run_label="T", config=cfg)
        self.assertIn('<details class="section-collapse">', _suppress_portion(html))

    def test_collapse_suppress_false_expanded(self):
        cfg = CRHTMLRenderConfig(collapse_suppress=False)
        pc = _make_presented(
            decision_level=DECISION_SUPPRESS, total_score=90.0,
            suppress_labels=["x"],
        )
        html = render_cr_html_audit([pc], run_label="T", config=cfg)
        self.assertNotIn("section-collapse", _suppress_portion(html))

    def test_collapse_watch_true_collapsed(self):
        cfg = CRHTMLRenderConfig(collapse_watch=True)
        pc = _make_presented(decision_level=DECISION_WATCH, total_score=50.0)
        html = render_cr_html_audit([pc], run_label="T", config=cfg)
        self.assertIn('<details class="section-collapse">', _watch_portion(html))

    def test_collapse_watch_false_expanded(self):
        cfg = CRHTMLRenderConfig(collapse_watch=False)
        pc = _make_presented(decision_level=DECISION_WATCH, total_score=50.0)
        html = render_cr_html_audit([pc], run_label="T", config=cfg)
        self.assertNotIn("section-collapse", _watch_portion(html))

    def test_collapse_uses_no_open_attribute(self):
        cfg = CRHTMLRenderConfig(collapse_suppress=True)
        pc = _make_presented(
            decision_level=DECISION_SUPPRESS, total_score=90.0,
            suppress_labels=["x"],
        )
        html = render_cr_html_audit([pc], run_label="T", config=cfg)
        self.assertNotIn("<details open", html)


# ===========================================================================
# H. HTML Safety
# ===========================================================================


class TestHTMLSafety(unittest.TestCase):
    """H. HTML escaping / injection safety."""

    def test_title_script_escaped(self):
        cfg = CRHTMLRenderConfig(title="<script>alert(1)</script>")
        html = render_cr_html_audit([], run_label="T", config=cfg)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_run_label_escaped(self):
        html = render_cr_html_audit([], run_label="<b>R</b>")
        self.assertNotIn("<b>R</b>", html)
        self.assertIn("&lt;b&gt;R&lt;/b&gt;", html)

    def test_source_name_escaped(self):
        si = _make_source_item(source_name="<b>weibo</b>")
        pc = _make_presented(source_items=[si])
        html = render_cr_html_audit([pc], run_label="T")
        self.assertNotIn("<b>weibo</b>", html)
        self.assertIn("&lt;b&gt;weibo&lt;/b&gt;", html)

    def test_cluster_key_angle_brackets_escaped(self):
        pc = _make_presented(cluster_key="<key>")
        html = render_cr_html_audit([pc], run_label="T")
        self.assertNotIn("<dd><key></dd>", html)
        self.assertIn("&lt;key&gt;", html)

    def test_title_field_escaped(self):
        pc = _make_presented(display_title="<i>Topic</i>")
        html = render_cr_html_audit([pc], run_label="T")
        self.assertNotIn("<h3><i>Topic</i></h3>", html)
        self.assertIn("&lt;i&gt;Topic&lt;/i&gt;", html)

    def test_url_attribute_escaped(self):
        pc = _make_presented(representative_url='https://e.com/?a="x"&b=1')
        html = render_cr_html_audit([pc], run_label="T")
        self.assertIn("&quot;", html)
        self.assertIn("&amp;", html)
        self.assertNotIn('href="https://e.com/?a="x"&b=1"', html)

    def test_debug_text_escaped(self):
        pc = _make_presented(score_debug={"profile_version": "<script>x</script>"})
        html = render_cr_html_audit([pc], run_label="T")
        self.assertNotIn("<script>x</script>", html)
        self.assertIn("&lt;script&gt;x&lt;/script&gt;", html)

    def test_no_raw_script_tag_appears(self):
        cfg = CRHTMLRenderConfig(title="<script>evil()</script>")
        si = _make_source_item(source_name="<script>evil2()</script>")
        pc = _make_presented(
            display_title="<script>evil3()</script>",
            source_items=[si],
        )
        html = render_cr_html_audit([pc], run_label="<script>evil4()</script>", config=cfg)
        self.assertNotIn("<script>", html)


# ===========================================================================
# H2. Href Scheme Safety
# ===========================================================================


class TestHrefSchemeSafety(unittest.TestCase):
    """H2. Only http/https URLs become anchors; other schemes stay text."""

    def test_javascript_representative_url_no_href(self):
        """representative_url='javascript:...' does not produce an href."""
        pc = _make_presented(representative_url="javascript:alert(1)")
        html = render_cr_html_audit([pc], run_label="T")
        self.assertNotIn('href="javascript:alert(1)"', html)
        self.assertNotIn("href=\"javascript:", html)
        # Text itself is preserved (escaped) for audit tracking.
        self.assertIn("javascript:alert(1)", html)

    def test_data_source_item_url_no_href(self):
        """Source item url='data:...' does not produce an href."""
        si = _make_source_item(url="data:text/html,<script>x</script>")
        pc = _make_presented(source_items=[si])
        html = render_cr_html_audit([pc], run_label="T")
        self.assertNotIn('href="data:', html)
        self.assertNotIn("<script>", html)
        # Title is still rendered.
        self.assertIn("Source A", html)

    def test_https_representative_url_still_anchor(self):
        """https URL still produces an anchor."""
        pc = _make_presented(representative_url="https://example.com/x")
        html = render_cr_html_audit([pc], run_label="T")
        self.assertIn('<a href="https://example.com/x">', html)

    def test_http_representative_url_still_anchor(self):
        """http URL still produces an anchor."""
        pc = _make_presented(representative_url="http://example.com/x")
        html = render_cr_html_audit([pc], run_label="T")
        self.assertIn('<a href="http://example.com/x">', html)

    def test_https_source_item_url_still_anchor(self):
        """https source item URL still produces an anchor."""
        si = _make_source_item(url="https://source.example.com/a")
        pc = _make_presented(source_items=[si])
        html = render_cr_html_audit([pc], run_label="T")
        self.assertIn('<a href="https://source.example.com/a">', html)

    def test_https_url_with_quotes_and_amp_attribute_escaped(self):
        """https URL containing quotes and & is still attribute-escaped."""
        pc = _make_presented(representative_url='https://e.com/?a="x"&b=1')
        html = render_cr_html_audit([pc], run_label="T")
        # Still an anchor (safe scheme) ...
        self.assertIn('<a href="https://e.com/?a=&quot;x&quot;&amp;b=1">', html)
        # ... and never the raw unescaped attribute.
        self.assertNotIn('href="https://e.com/?a="x"&b=1"', html)

    def test_scheme_case_and_whitespace_normalized(self):
        """Scheme check is case-insensitive and ignores surrounding spaces."""
        pc = _make_presented(representative_url="  HTTPS://example.com/x  ")
        html = render_cr_html_audit([pc], run_label="T")
        self.assertIn("<a href=", html)

    def test_javascript_scheme_uppercase_blocked(self):
        """Uppercase JavaScript: scheme is also blocked."""
        pc = _make_presented(representative_url="JavaScript:alert(1)")
        html = render_cr_html_audit([pc], run_label="T")
        self.assertNotIn("href=\"JavaScript:", html)
        self.assertNotIn("href=\"javascript:", html)


# ===========================================================================
# I. Suppress Audit
# ===========================================================================


class TestSuppressAudit(unittest.TestCase):
    """I. Suppress candidates and high-score suppress counting."""

    def test_suppress_candidates_included(self):
        pc = _make_presented(
            decision_level=DECISION_SUPPRESS, total_score=90.0,
            suppress_labels=["x"], display_title="Suppressed Topic",
        )
        html = render_cr_html_audit([pc], run_label="T")
        self.assertIn("Suppressed Topic", html)
        self.assertIn("<dt>Decision</dt><dd>suppress</dd>", html)

    def test_high_score_suppress_counted_at_80(self):
        pc = _make_presented(
            decision_level=DECISION_SUPPRESS, total_score=80.0,
            suppress_labels=["x"],
        )
        html = render_cr_html_audit([pc], run_label="T")
        self.assertIn(
            "<strong>High-score suppressed candidates:</strong> 1", html
        )

    def test_suppress_score_79_9_not_counted(self):
        pc = _make_presented(
            decision_level=DECISION_SUPPRESS, total_score=79.9,
            suppress_labels=["x"],
        )
        html = render_cr_html_audit([pc], run_label="T")
        self.assertIn(
            "<strong>High-score suppressed candidates:</strong> 0", html
        )

    def test_non_suppress_not_counted(self):
        pc = _make_presented(decision_level=DECISION_URGENT, total_score=90.0)
        html = render_cr_html_audit([pc], run_label="T")
        self.assertIn(
            "<strong>High-score suppressed candidates:</strong> 0", html
        )


# ===========================================================================
# J. No Forbidden Behavior
# ===========================================================================


class TestNoForbiddenBehavior(unittest.TestCase):
    """J. html.py does not import forbidden modules or do I/O."""

    def _read_source(self) -> str:
        import trendradar.cr.html as mod

        source_file = mod.__file__
        assert source_file is not None
        with open(source_file) as f:
            return f.read()

    def test_no_telegram_import(self):
        source = self._read_source()
        self.assertNotIn("telegram", source.lower())

    def test_no_report_archive_import(self):
        source = self._read_source()
        self.assertNotIn("from trendradar.report", source)
        self.assertNotIn("from trendradar.archive", source)

    def test_no_storage_config_import(self):
        source = self._read_source()
        self.assertNotIn("from trendradar.storage", source)
        self.assertNotIn("from trendradar.config", source)

    def test_no_ai_analysis_result(self):
        source = self._read_source()
        self.assertNotIn("AIAnalysisResult", source)

    def test_no_file_writing(self):
        source = self._read_source()
        self.assertNotIn("open(", source)
        self.assertNotIn(".write(", source)
        self.assertNotIn("pathlib", source)
        self.assertNotIn("from pathlib", source)

    def test_no_runtime_import(self):
        source = self._read_source()
        self.assertNotIn("from trendradar.__main__", source)
        self.assertNotIn("_run_analysis_pipeline", source)


if __name__ == "__main__":
    unittest.main()
