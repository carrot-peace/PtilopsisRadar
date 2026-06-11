# coding=utf-8
"""
Tests that CR-A repeat preview evidence (PR10b) can render in audit artifacts.

The evidence is opt-in, audit-only, and must not leak into the CR-A Telegram
text renderer.
"""

import unittest

from trendradar.cr.decision import CRDecision, DECISION_ALERT, DECISION_URGENT
from trendradar.cr.event_identity import build_cr_event_identity_from_candidate
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
from trendradar.cr.repeat_preview import CRSeenEventState
from trendradar.cr.scoring import CRScoreResult


def _make_presented(
    *,
    display_title: str = "Topic A",
    candidate_id: str = "c1",
    cluster_key: str = "key1",
    decision_level: str = DECISION_ALERT,
    total_score: float = 70.0,
) -> CRPresentedCandidate:
    cand = CRCandidate(
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        display_title=display_title,
        representative_url="https://example.com/topic",
        source_names=["weibo"],
        source_items=[
            CRSourceItem(
                title=display_title,
                url="https://example.com/source",
                source_name="weibo",
            )
        ],
    )
    sr = CRScoreResult(
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        profile_version="cr-score-v0.1",
        total_score=total_score,
        trigger_reasons=[],
        debug={},
    )
    dec = CRDecision(
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        profile_version="cr-score-v0.1",
        policy_version="cr-decision-v0.1",
        level=decision_level,
        total_score=total_score,
        push_eligible=decision_level in (DECISION_ALERT, DECISION_URGENT),
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
        representative_url="https://example.com/topic",
        decision_level=decision_level,
        total_score=total_score,
    )


def _event_key(pc: CRPresentedCandidate) -> str:
    return build_cr_event_identity_from_candidate(pc.candidate).event_key


def _repeat_block_html(html: str) -> str:
    return html.split('class="repeat-preview"')[1].split("</section>")[0]


class TestMarkdownRepeatPreviewRendering(unittest.TestCase):
    def test_can_render_not_evaluated_repeat_preview(self):
        pc = _make_presented()
        cfg = CRMarkdownRenderConfig(
            include_event_identity=False,
            include_repeat_preview=True,
        )
        md = render_cr_markdown_audit([pc], run_label="T", config=cfg)
        self.assertIn("#### Repeat Preview", md)
        self.assertIn("- Status: `not_evaluated`", md)
        self.assertIn("- Reason: no prior event state snapshot provided", md)
        self.assertNotIn("- Current Score:", md)

    def test_can_render_same_level_repeat_with_scores(self):
        pc = _make_presented(decision_level=DECISION_ALERT, total_score=67.0)
        key = _event_key(pc)
        cfg = CRMarkdownRenderConfig(
            include_event_identity=False,
            include_repeat_preview=True,
            seen_event_states={
                key: CRSeenEventState(
                    event_key=key,
                    decision_level=DECISION_ALERT,
                    score=65.0,
                )
            },
        )
        md = render_cr_markdown_audit([pc], run_label="T", config=cfg)
        self.assertIn("- Status: `same_level_repeat`", md)
        self.assertIn("- Previous Level: `alert`", md)
        self.assertIn("- Current Level: `alert`", md)
        self.assertIn("- Previous Score: `65.0`", md)
        self.assertIn("- Current Score: `67.0`", md)

    def test_can_render_meaningful_escalation(self):
        pc = _make_presented(decision_level=DECISION_URGENT, total_score=85.0)
        key = _event_key(pc)
        cfg = CRMarkdownRenderConfig(
            include_event_identity=False,
            include_repeat_preview=True,
            seen_event_states={
                key: CRSeenEventState(
                    event_key=key,
                    decision_level="watch",
                    score=58.0,
                )
            },
        )
        md = render_cr_markdown_audit([pc], run_label="T", config=cfg)
        self.assertIn("- Status: `meaningful_escalation`", md)
        self.assertIn("- Previous Level: `watch`", md)
        self.assertIn("- Current Level: `urgent`", md)
        self.assertIn("- Previous Score: `58.0`", md)
        self.assertIn("- Current Score: `85.0`", md)


class TestHTMLRepeatPreviewRendering(unittest.TestCase):
    def test_can_render_not_evaluated_repeat_preview(self):
        pc = _make_presented()
        cfg = CRHTMLRenderConfig(
            include_event_identity=False,
            include_repeat_preview=True,
        )
        html = render_cr_html_audit([pc], run_label="T", config=cfg)
        block = _repeat_block_html(html)
        self.assertIn("<h4>Repeat Preview</h4>", block)
        self.assertIn("<dt>Status</dt><dd>not_evaluated</dd>", block)
        self.assertIn(
            "<dt>Reason</dt><dd>no prior event state snapshot provided</dd>",
            block,
        )

    def test_can_render_same_level_repeat_and_scores(self):
        pc = _make_presented(decision_level=DECISION_ALERT, total_score=67.0)
        key = _event_key(pc)
        cfg = CRHTMLRenderConfig(
            include_event_identity=False,
            include_repeat_preview=True,
            seen_event_states={
                key: CRSeenEventState(
                    event_key=key,
                    decision_level=DECISION_ALERT,
                    score=65.0,
                )
            },
        )
        html = render_cr_html_audit([pc], run_label="T", config=cfg)
        block = _repeat_block_html(html)
        self.assertIn("<dt>Status</dt><dd>same_level_repeat</dd>", block)
        self.assertIn("<dt>Previous Level</dt><dd>alert</dd>", block)
        self.assertIn("<dt>Current Level</dt><dd>alert</dd>", block)
        self.assertIn("<dt>Previous Score</dt><dd>65.0</dd>", block)
        self.assertIn("<dt>Current Score</dt><dd>67.0</dd>", block)

    def test_can_render_meaningful_escalation(self):
        pc = _make_presented(decision_level=DECISION_URGENT, total_score=85.0)
        key = _event_key(pc)
        cfg = CRHTMLRenderConfig(
            include_event_identity=False,
            include_repeat_preview=True,
            seen_event_states={
                key: CRSeenEventState(
                    event_key=key,
                    decision_level="watch",
                    score=58.0,
                )
            },
        )
        html = render_cr_html_audit([pc], run_label="T", config=cfg)
        block = _repeat_block_html(html)
        self.assertIn("<dt>Status</dt><dd>meaningful_escalation</dd>", block)
        self.assertIn("<dt>Previous Level</dt><dd>watch</dd>", block)
        self.assertIn("<dt>Current Level</dt><dd>urgent</dd>", block)

    def test_html_escapes_values(self):
        pc = _make_presented()
        key = _event_key(pc)
        cfg = CRHTMLRenderConfig(
            include_event_identity=False,
            include_repeat_preview=True,
            seen_event_states={
                key: CRSeenEventState(
                    event_key=key,
                    decision_level=DECISION_ALERT,
                    seen_at="<script>alert(1)</script>",
                )
            },
        )
        html = render_cr_html_audit([pc], run_label="T", config=cfg)
        block = _repeat_block_html(html)
        self.assertNotIn("<script>", block)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", block)

    def test_repeat_preview_section_adds_no_hrefs(self):
        pc = _make_presented()
        cfg = CRHTMLRenderConfig(
            include_event_identity=False,
            include_repeat_preview=True,
        )
        html = render_cr_html_audit([pc], run_label="T", config=cfg)
        self.assertNotIn("href=", _repeat_block_html(html))


class TestTelegramTextUnchanged(unittest.TestCase):
    def test_cr_a_text_has_no_repeat_preview_leakage(self):
        run = CRPresentationRun(run_label="T", candidates=[_make_presented()])
        text = render_cr_a_text(run)
        self.assertNotIn("Repeat Preview", text)
        self.assertNotIn("same_level_repeat", text)
        self.assertNotIn("meaningful_escalation", text)
        self.assertNotIn("not_evaluated", text)


if __name__ == "__main__":
    unittest.main()
