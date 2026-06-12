# coding=utf-8
"""
Tests that the PR10e cooldown audit context can drive the existing Markdown /
HTML audit renderers (PR10b/d) without any renderer changes.

The assembly is audit-only: it must not leak into the CR-A Telegram text
renderer, must not appear in default render configs, and must not introduce
hrefs/JS.
"""

import unittest

from trendradar.cr.cooldown_audit import build_cr_cooldown_audit_context
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
from trendradar.cr.scoring import CRScoreResult
from trendradar.cr.state_snapshot import (
    CR_EVENT_STATE_SCHEMA_VERSION,
    CREventStateEntry,
    CREventStateSnapshot,
)


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


def _snapshot(*entries: CREventStateEntry) -> CREventStateSnapshot:
    return CREventStateSnapshot(
        schema_version=CR_EVENT_STATE_SCHEMA_VERSION,
        entries=tuple(entries),
    )


def _cooldown_block_html(html: str) -> str:
    return html.split('class="cooldown-decision"')[1].split("</section>")[0]


class TestMarkdownFromAuditContext(unittest.TestCase):
    def test_shows_repeat_and_cooldown_for_same_level_repeat(self):
        pc = _make_presented(decision_level=DECISION_ALERT, total_score=67.0)
        key = _event_key(pc)
        snapshot = _snapshot(
            CREventStateEntry(
                event_key=key, decision_level=DECISION_ALERT, score=65.0
            )
        )
        context = build_cr_cooldown_audit_context(
            (pc,), prior_snapshot=snapshot
        )

        cfg = CRMarkdownRenderConfig(
            include_event_identity=False,
            include_repeat_preview=True,
            include_cooldown_decision=True,
            seen_event_states=context.seen_event_states,
        )
        md = render_cr_markdown_audit([pc], run_label="T", config=cfg)
        self.assertIn("#### Repeat Preview", md)
        self.assertIn("- Status: `same_level_repeat`", md)
        self.assertIn("#### Cooldown Policy Preview", md)
        self.assertIn("- Action: `cooldown`", md)

    def test_shows_allow_escalation_for_meaningful_escalation(self):
        pc = _make_presented(decision_level=DECISION_URGENT, total_score=85.0)
        key = _event_key(pc)
        snapshot = _snapshot(
            CREventStateEntry(
                event_key=key, decision_level="watch", score=58.0
            )
        )
        context = build_cr_cooldown_audit_context(
            (pc,), prior_snapshot=snapshot
        )

        cfg = CRMarkdownRenderConfig(
            include_event_identity=False,
            include_repeat_preview=True,
            include_cooldown_decision=True,
            seen_event_states=context.seen_event_states,
        )
        md = render_cr_markdown_audit([pc], run_label="T", config=cfg)
        self.assertIn("- Status: `meaningful_escalation`", md)
        self.assertIn("- Action: `allow_escalation`", md)

    def test_default_config_does_not_show_cooldown_preview(self):
        pc = _make_presented()
        # Building a context does not change default rendering.
        build_cr_cooldown_audit_context((pc,))
        md = render_cr_markdown_audit([pc], run_label="T")
        self.assertNotIn("Cooldown Policy Preview", md)


class TestHTMLFromAuditContext(unittest.TestCase):
    def test_shows_cooldown_section_safely(self):
        pc = _make_presented(decision_level=DECISION_ALERT, total_score=67.0)
        key = _event_key(pc)
        snapshot = _snapshot(
            CREventStateEntry(
                event_key=key, decision_level=DECISION_ALERT, score=65.0
            )
        )
        context = build_cr_cooldown_audit_context(
            (pc,), prior_snapshot=snapshot
        )

        cfg = CRHTMLRenderConfig(
            include_event_identity=False,
            include_repeat_preview=True,
            include_cooldown_decision=True,
            seen_event_states=context.seen_event_states,
        )
        html = render_cr_html_audit([pc], run_label="T", config=cfg)
        block = _cooldown_block_html(html)
        self.assertIn("<h4>Cooldown Policy Preview</h4>", block)
        self.assertIn("<dt>Action</dt><dd>cooldown</dd>", block)
        self.assertNotIn("href=", block)

    def test_shows_allow_escalation(self):
        pc = _make_presented(decision_level=DECISION_URGENT, total_score=85.0)
        key = _event_key(pc)
        snapshot = _snapshot(
            CREventStateEntry(
                event_key=key, decision_level="watch", score=58.0
            )
        )
        context = build_cr_cooldown_audit_context(
            (pc,), prior_snapshot=snapshot
        )

        cfg = CRHTMLRenderConfig(
            include_event_identity=False,
            include_repeat_preview=True,
            include_cooldown_decision=True,
            seen_event_states=context.seen_event_states,
        )
        html = render_cr_html_audit([pc], run_label="T", config=cfg)
        block = _cooldown_block_html(html)
        self.assertIn("<dt>Action</dt><dd>allow_escalation</dd>", block)

    def test_default_config_does_not_show_cooldown_preview(self):
        pc = _make_presented()
        build_cr_cooldown_audit_context((pc,))
        html = render_cr_html_audit([pc], run_label="T")
        self.assertNotIn("Cooldown Policy Preview", html)


class TestTelegramTextUnchanged(unittest.TestCase):
    def test_cr_a_text_has_no_cooldown_or_repeat_leakage(self):
        pc = _make_presented()
        build_cr_cooldown_audit_context((pc,))
        run = CRPresentationRun(run_label="T", candidates=[pc])
        text = render_cr_a_text(run)
        self.assertNotIn("Cooldown Policy Preview", text)
        self.assertNotIn("Repeat Preview", text)
        self.assertNotIn("allow_escalation", text)


if __name__ == "__main__":
    unittest.main()
