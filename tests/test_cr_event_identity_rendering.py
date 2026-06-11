# coding=utf-8
"""
Tests that event identity evidence (PR10a) is rendered in CR audit artifacts.

Focused assertions only — does NOT snapshot whole documents.  Verifies that:
  * Markdown / HTML audit artifacts include an Event Identity section.
  * Supporting evidence (candidate_id) is shown; the raw verbose cluster_key
    is NOT embedded (only its fingerprint).
  * HTML identity fields are escaped.
  * The Telegram CR-A text renderer is unchanged (no identity leakage).
"""

import unittest

from trendradar.cr.decision import CRDecision, DECISION_ALERT
from trendradar.cr.html import CRHTMLRenderConfig, render_cr_html_audit
from trendradar.cr.markdown import (
    CRMarkdownRenderConfig,
    render_cr_markdown_audit,
)
from trendradar.cr.models import CRCandidate, CRSourceItem
from trendradar.cr.presentation import (
    CRPresentationRun,
    CRPresentedCandidate,
    render_cr_a_text,
)
from trendradar.cr.scoring import CRScoreResult


_VERBOSE_CLUSTER_KEY = "grp|weibo|zhihu|baidu|UNIQUEVERBOSECLUSTERTOKEN"
_TITLE = "广西兴安发生爆炸已致7死17伤"


def _make_presented(
    *,
    display_title: str = _TITLE,
    candidate_id: str = "6e204d8621b7",
    cluster_key: str = _VERBOSE_CLUSTER_KEY,
    representative_url: str | None = "https://example.com/x",
    source_names: list[str] | None = None,
    source_items: list[CRSourceItem] | None = None,
    decision_level: str = DECISION_ALERT,
) -> CRPresentedCandidate:
    cand = CRCandidate(
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        display_title=display_title,
        representative_url=representative_url,
        source_names=source_names if source_names is not None else ["weibo", "zhihu"],
        source_items=source_items or [CRSourceItem(title="t", url="https://a.com")],
    )
    sr = CRScoreResult(
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        profile_version="cr-score-v0.1",
        total_score=70.0,
        trigger_reasons=[],
        debug={},
    )
    dec = CRDecision(
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        profile_version="cr-score-v0.1",
        policy_version="cr-decision-v0.1",
        level=decision_level,
        total_score=70.0,
        push_eligible=decision_level == DECISION_ALERT,
        suppress_labels=[],
        trigger_reasons=[],
        debug={},
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
        total_score=70.0,
    )


class TestMarkdownEventIdentity(unittest.TestCase):
    def setUp(self):
        self.md = render_cr_markdown_audit([_make_presented()], run_label="T")

    def _identity_block(self) -> str:
        return self.md.split("#### Event Identity")[1].split("####")[0]

    def test_has_event_identity_section(self):
        self.assertIn("#### Event Identity", self.md)

    def test_has_event_key_with_version(self):
        self.assertIn("Event Key:", self.md)
        self.assertIn("cr-event-v1:", self.md)

    def test_has_key_basis(self):
        self.assertIn("Key Basis: normalized_title", self.md)

    def test_has_normalized_title(self):
        self.assertIn("Normalized Title:", self.md)

    def test_has_candidate_id_evidence(self):
        self.assertIn("6e204d8621b7", self._identity_block())

    def test_has_not_enforced_note(self):
        self.assertIn("not enforced here", self.md)

    def test_raw_verbose_cluster_key_not_in_identity_block(self):
        self.assertNotIn("UNIQUEVERBOSECLUSTERTOKEN", self._identity_block())

    def test_can_be_disabled(self):
        cfg = CRMarkdownRenderConfig(include_event_identity=False)
        md = render_cr_markdown_audit([_make_presented()], run_label="T", config=cfg)
        self.assertNotIn("#### Event Identity", md)


class TestHTMLEventIdentity(unittest.TestCase):
    def setUp(self):
        self.html = render_cr_html_audit([_make_presented()], run_label="T")

    def _identity_block(self) -> str:
        return self.html.split('class="event-identity"')[1].split("</section>")[0]

    def test_has_event_identity_section(self):
        self.assertIn('class="event-identity"', self.html)
        self.assertIn("<h4>Event Identity</h4>", self.html)

    def test_has_event_key_and_basis(self):
        block = self._identity_block()
        self.assertIn("Event Key", block)
        self.assertIn("cr-event-v1:", block)
        self.assertIn("normalized_title", block)

    def test_has_candidate_id_evidence(self):
        self.assertIn("6e204d8621b7", self._identity_block())

    def test_raw_verbose_cluster_key_not_in_identity_block(self):
        self.assertNotIn("UNIQUEVERBOSECLUSTERTOKEN", self._identity_block())

    def test_identity_fields_are_escaped(self):
        # A title with HTML metacharacters must be escaped in the identity dl.
        pc = _make_presented(display_title="<script>x</script> & co")
        html = render_cr_html_audit([pc], run_label="T")
        block = html.split('class="event-identity"')[1].split("</section>")[0]
        self.assertNotIn("<script>", block)
        self.assertIn("&lt;script&gt;", block)

    def test_can_be_disabled(self):
        cfg = CRHTMLRenderConfig(include_event_identity=False)
        html = render_cr_html_audit([_make_presented()], run_label="T", config=cfg)
        self.assertNotIn('class="event-identity"', html)


class TestTelegramTextUnchanged(unittest.TestCase):
    def test_cr_a_text_has_no_identity_leakage(self):
        run = CRPresentationRun(run_label="T", candidates=[_make_presented()])
        text = render_cr_a_text(run)
        self.assertNotIn("Event Identity", text)
        self.assertNotIn("cr-event-v1", text)
        self.assertNotIn("Normalized Title", text)


if __name__ == "__main__":
    unittest.main()
