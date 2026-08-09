# coding=utf-8
"""
Tests that the CR-A cooldown policy preview (PR10d) can render in audit
artifacts.

The cooldown preview is opt-in, audit-only, and must not leak into the CR-A
Telegram text renderer or change dispatch behavior.
"""

import unittest

from trendradar.cr.cooldown_policy import CRCooldownPolicy
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


def _cooldown_block_html(html: str) -> str:
    return html.split('class="cooldown-decision"')[1].split("</section>")[0]


class TestMarkdownCooldownRendering(unittest.TestCase):
    def test_renders_cooldown_action_when_enabled(self):
        pc = _make_presented(decision_level=DECISION_ALERT, total_score=67.0)
        key = _event_key(pc)
        cfg = CRMarkdownRenderConfig(
            include_event_identity=False,
            include_repeat_preview=True,
            include_cooldown_decision=True,
            seen_event_states={
                key: CRSeenEventState(
                    event_key=key,
                    decision_level=DECISION_ALERT,
                    score=65.0,
                )
            },
        )
        md = render_cr_markdown_audit([pc], run_label="T", config=cfg)
        self.assertIn("#### Cooldown Policy Preview", md)
        self.assertIn("- Action: `cooldown`", md)
        self.assertIn("- Repeat Status: `same_level_repeat`", md)
        self.assertIn("- Cooldown Minutes: `240`", md)

    def test_renders_allow_escalation_for_meaningful_escalation(self):
        pc = _make_presented(decision_level=DECISION_URGENT, total_score=85.0)
        key = _event_key(pc)
        cfg = CRMarkdownRenderConfig(
            include_event_identity=False,
            include_repeat_preview=True,
            include_cooldown_decision=True,
            seen_event_states={
                key: CRSeenEventState(
                    event_key=key,
                    decision_level="watch",
                    score=58.0,
                )
            },
        )
        md = render_cr_markdown_audit([pc], run_label="T", config=cfg)
        self.assertIn("- Action: `allow_escalation`", md)
        self.assertIn("- Repeat Status: `meaningful_escalation`", md)
        self.assertNotIn("- Cooldown Minutes:", md)

    def test_default_config_does_not_render_cooldown_preview(self):
        pc = _make_presented()
        md = render_cr_markdown_audit([pc], run_label="T")
        self.assertNotIn("Cooldown Policy Preview", md)

    def test_repeat_preview_enabled_but_cooldown_disabled_is_absent(self):
        pc = _make_presented()
        cfg = CRMarkdownRenderConfig(
            include_event_identity=False,
            include_repeat_preview=True,
            include_cooldown_decision=False,
        )
        md = render_cr_markdown_audit([pc], run_label="T", config=cfg)
        self.assertIn("#### Repeat Preview", md)
        self.assertNotIn("Cooldown Policy Preview", md)

    def test_custom_cooldown_minutes_are_rendered(self):
        pc = _make_presented(decision_level=DECISION_ALERT, total_score=67.0)
        key = _event_key(pc)
        cfg = CRMarkdownRenderConfig(
            include_event_identity=False,
            include_repeat_preview=True,
            include_cooldown_decision=True,
            cooldown_policy=CRCooldownPolicy(same_level_cooldown_minutes=120),
            seen_event_states={
                key: CRSeenEventState(
                    event_key=key,
                    decision_level=DECISION_ALERT,
                    score=65.0,
                )
            },
        )
        md = render_cr_markdown_audit([pc], run_label="T", config=cfg)
        self.assertIn("- Cooldown Minutes: `120`", md)


class TestHTMLCooldownRendering(unittest.TestCase):
    def test_renders_cooldown_decision_safely(self):
        pc = _make_presented(decision_level=DECISION_ALERT, total_score=67.0)
        key = _event_key(pc)
        cfg = CRHTMLRenderConfig(
            include_event_identity=False,
            include_repeat_preview=True,
            include_cooldown_decision=True,
            seen_event_states={
                key: CRSeenEventState(
                    event_key=key,
                    decision_level=DECISION_ALERT,
                    score=65.0,
                )
            },
        )
        html = render_cr_html_audit([pc], run_label="T", config=cfg)
        block = _cooldown_block_html(html)
        self.assertIn("<h4>Cooldown Policy Preview</h4>", block)
        self.assertIn("<dt>Action</dt><dd>cooldown</dd>", block)
        self.assertIn(
            "<dt>Repeat Status</dt><dd>same_level_repeat</dd>", block
        )
        self.assertIn("<dt>Cooldown Minutes</dt><dd>240</dd>", block)

    def test_renders_allow_escalation(self):
        pc = _make_presented(decision_level=DECISION_URGENT, total_score=85.0)
        key = _event_key(pc)
        cfg = CRHTMLRenderConfig(
            include_event_identity=False,
            include_repeat_preview=True,
            include_cooldown_decision=True,
            seen_event_states={
                key: CRSeenEventState(
                    event_key=key,
                    decision_level="watch",
                    score=58.0,
                )
            },
        )
        html = render_cr_html_audit([pc], run_label="T", config=cfg)
        block = _cooldown_block_html(html)
        self.assertIn("<dt>Action</dt><dd>allow_escalation</dd>", block)
        self.assertIn(
            "<dt>Repeat Status</dt><dd>meaningful_escalation</dd>", block
        )

    def test_html_escapes_values(self):
        # The reason text is policy-derived, but ensure the section escapes
        # any value injected via event evidence (defense in depth).
        pc = _make_presented(
            display_title="<script>alert(1)</script>",
        )
        key = _event_key(pc)
        cfg = CRHTMLRenderConfig(
            include_event_identity=False,
            include_repeat_preview=True,
            include_cooldown_decision=True,
            seen_event_states={
                key: CRSeenEventState(
                    event_key=key,
                    decision_level=DECISION_ALERT,
                    score=65.0,
                )
            },
        )
        html = render_cr_html_audit([pc], run_label="T", config=cfg)
        block = _cooldown_block_html(html)
        self.assertNotIn("<script>", block)

    def test_cooldown_section_adds_no_hrefs(self):
        pc = _make_presented(decision_level=DECISION_ALERT, total_score=67.0)
        key = _event_key(pc)
        cfg = CRHTMLRenderConfig(
            include_event_identity=False,
            include_repeat_preview=True,
            include_cooldown_decision=True,
            seen_event_states={
                key: CRSeenEventState(
                    event_key=key, decision_level=DECISION_ALERT, score=65.0
                )
            },
        )
        html = render_cr_html_audit([pc], run_label="T", config=cfg)
        self.assertNotIn("href=", _cooldown_block_html(html))

    def test_default_config_does_not_render_cooldown_preview(self):
        pc = _make_presented()
        html = render_cr_html_audit([pc], run_label="T")
        self.assertNotIn("Cooldown Policy Preview", html)


class TestTelegramTextUnchanged(unittest.TestCase):
    def test_cr_a_text_has_no_cooldown_preview_leakage(self):
        run = CRPresentationRun(run_label="T", candidates=[_make_presented()])
        text = render_cr_a_text(run)
        self.assertNotIn("Cooldown Policy Preview", text)
        self.assertNotIn("allow_escalation", text)
        self.assertNotIn("cooldown", text)


if __name__ == "__main__":
    unittest.main()
