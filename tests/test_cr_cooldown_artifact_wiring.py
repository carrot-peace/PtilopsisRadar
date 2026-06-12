# coding=utf-8
"""
PR10f: CR-A cooldown audit artifact-only wiring tests.

Covers the opt-in ``include_cooldown_audit`` flag on the CR runtime dry-run
bridge.  The flag affects audit artifact rendering only — it must not change
CR-A text, dispatch behavior, or read/write any event state.

No network, no real crawlers, no Telegram, no real output directories.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trendradar.cr.cooldown_audit import (
    CRCooldownAuditContext,
    build_cr_cooldown_audit_context,
)
from trendradar.cr.cooldown_policy import CRCooldownPolicy
from trendradar.cr.artifacts import CRArtifactConfig
from trendradar.cr.decision import CRDecision, DECISION_ALERT, DECISION_URGENT
from trendradar.cr.event_identity import build_cr_event_identity_from_candidate
from trendradar.cr.markdown import (
    CRMarkdownRenderConfig,
    render_cr_markdown_audit,
)
from trendradar.cr.html import CRHTMLRenderConfig, render_cr_html_audit
from trendradar.cr.models import CRCandidate, CRSourceItem
from trendradar.cr.presentation import CRPresentedCandidate
from trendradar.cr.runtime_dry_run import build_and_write_cr_runtime_dry_run
from trendradar.cr.scoring import CRScoreResult
from trendradar.cr.state_snapshot import (
    CR_EVENT_STATE_SCHEMA_VERSION,
    CREventStateEntry,
    CREventStateSnapshot,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_hotlist_item(title, ranks=None, url="https://example.com"):
    return {
        "title": title,
        "source_name": "weibo",
        "source_id": "weibo",
        "ranks": ranks or [3],
        "count": 3,
        "first_time": "09:30",
        "last_time": "12:00",
        "url": url,
        "mobileUrl": "",
        "is_new": False,
        "rank_timeline": [],
    }


def _hotlist_stats():
    return [
        {
            "word": "AI",
            "titles": [
                _make_hotlist_item("AI Title One", ranks=[3]),
                _make_hotlist_item("AI Title Two", ranks=[8]),
            ],
            "count": 2,
            "position": 0,
        },
    ]


def _artifact_config(root: str) -> CRArtifactConfig:
    return CRArtifactConfig(root_dir=Path(root))


def _read_markdown(result) -> str:
    return result.artifact_paths.latest_markdown_path.read_text(encoding="utf-8")


def _read_html(result) -> str:
    return result.artifact_paths.latest_html_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Synthetic presented candidate (for the render-config consumption check)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Group A — Default behavior unchanged
# ---------------------------------------------------------------------------


class TestDefaultBehaviorUnchanged(unittest.TestCase):
    def test_default_has_no_cooldown_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="run-default",
                artifact_config=_artifact_config(tmp),
            )
            md = _read_markdown(result)
            html = _read_html(result)
            self.assertNotIn("Cooldown Policy Preview", md)
            self.assertNotIn("Cooldown Policy Preview", html)
            self.assertIsNone(result.cooldown_audit)

    def test_default_artifacts_byte_for_byte_match_disabled(self):
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
            r_default = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="run-x",
                artifact_config=_artifact_config(t1),
            )
            r_explicit_off = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="run-x",
                artifact_config=_artifact_config(t2),
                include_cooldown_audit=False,
            )
            self.assertEqual(
                r_default.pipeline.markdown_audit_text,
                r_explicit_off.pipeline.markdown_audit_text,
            )
            self.assertEqual(
                r_default.pipeline.html_audit_text,
                r_explicit_off.pipeline.html_audit_text,
            )


# ---------------------------------------------------------------------------
# Group B — Artifact-only cooldown audit enabled
# ---------------------------------------------------------------------------


class TestCooldownAuditEnabled(unittest.TestCase):
    def _run(self, tmp):
        return build_and_write_cr_runtime_dry_run(
            hotlist_stats=_hotlist_stats(),
            run_label="run-audit",
            artifact_config=_artifact_config(tmp),
            include_cooldown_audit=True,
        )

    def test_markdown_shows_repeat_and_cooldown_not_evaluated(self):
        with tempfile.TemporaryDirectory() as tmp:
            md = _read_markdown(self._run(tmp))
            self.assertIn("#### Repeat Preview", md)
            self.assertIn("#### Cooldown Policy Preview", md)
            self.assertIn("- Action: `not_evaluated`", md)

    def test_html_shows_repeat_and_cooldown_not_evaluated(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = _read_html(self._run(tmp))
            self.assertIn("Repeat Preview", html)
            self.assertIn("Cooldown Policy Preview", html)
            self.assertIn("<dt>Action</dt><dd>not_evaluated</dd>", html)

    def test_context_is_populated_and_inert(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp)
            self.assertIsInstance(result.cooldown_audit, CRCooldownAuditContext)
            # Empty prior snapshot → empty seen states, all not_evaluated.
            self.assertEqual(result.cooldown_audit.seen_event_states, {})
            self.assertGreater(len(result.cooldown_audit.candidates), 0)
            for ac in result.cooldown_audit.candidates:
                self.assertEqual(ac.repeat_preview.status, "not_evaluated")
                self.assertEqual(ac.cooldown_decision.action, "not_evaluated")
            # Proposed state updates exist in memory, one per candidate.
            self.assertEqual(
                len(result.cooldown_audit.state_updates),
                len(result.cooldown_audit.candidates),
            )

    def test_written_artifacts_match_pipeline_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp)
            self.assertEqual(_read_markdown(result), result.pipeline.markdown_audit_text)
            self.assertEqual(_read_html(result), result.pipeline.html_audit_text)


# ---------------------------------------------------------------------------
# Group C — Existing render configs can consume an audit context
# ---------------------------------------------------------------------------


class TestRenderConfigConsumesContext(unittest.TestCase):
    def test_synthetic_same_level_repeat_renders_cooldown(self):
        pc = _make_presented(decision_level=DECISION_ALERT, total_score=67.0)
        key = build_cr_event_identity_from_candidate(pc.candidate).event_key
        snapshot = CREventStateSnapshot(
            schema_version=CR_EVENT_STATE_SCHEMA_VERSION,
            entries=(
                CREventStateEntry(
                    event_key=key, decision_level=DECISION_ALERT, score=65.0
                ),
            ),
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
        self.assertIn("- Status: `same_level_repeat`", md)
        self.assertIn("- Action: `cooldown`", md)

        html_cfg = CRHTMLRenderConfig(
            include_event_identity=False,
            include_repeat_preview=True,
            include_cooldown_decision=True,
            seen_event_states=context.seen_event_states,
        )
        html = render_cr_html_audit([pc], run_label="T", config=html_cfg)
        self.assertIn("<dt>Action</dt><dd>cooldown</dd>", html)


# ---------------------------------------------------------------------------
# Group D — Telegram / CR-A text and dispatch unchanged
# ---------------------------------------------------------------------------


class TestTelegramAndDispatchUnchanged(unittest.TestCase):
    def test_cr_a_text_has_no_cooldown_or_repeat_leakage(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="run-tg",
                artifact_config=_artifact_config(tmp),
                include_cooldown_audit=True,
            )
            text = result.pipeline.cr_a_text
            self.assertNotIn("Cooldown Policy Preview", text)
            self.assertNotIn("Repeat Preview", text)
            self.assertNotIn("allow_escalation", text)

    def test_cr_a_text_and_dispatch_plan_identical_with_flag(self):
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
            off = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="run-eq",
                artifact_config=_artifact_config(t1),
            )
            on = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="run-eq",
                artifact_config=_artifact_config(t2),
                include_cooldown_audit=True,
            )
            # The flag must not affect CR-A text or the dispatch plan.
            self.assertEqual(off.pipeline.cr_a_text, on.pipeline.cr_a_text)
            self.assertEqual(
                off.dispatch_plan.run_label, on.dispatch_plan.run_label
            )
            self.assertEqual(
                len(off.dispatch_plan.messages), len(on.dispatch_plan.messages)
            )


# ---------------------------------------------------------------------------
# Group E — No state file I/O / no Telegram send in the dry-run module
# ---------------------------------------------------------------------------


class TestNoStateIOSourceGuard(unittest.TestCase):
    def _module_source(self) -> str:
        import trendradar.cr.runtime_dry_run as mod

        return Path(mod.__file__).read_text(encoding="utf-8")

    def test_dry_run_has_no_state_io_or_telegram_send(self):
        source = self._module_source()
        forbidden = (
            "state_store",
            "load_cr_event_state_snapshot",
            "save_cr_event_state_snapshot",
            "PTILOPSIS_CR_TELEGRAM_SEND",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_CHAT_ID",
            "telegram_sink",
            "telegram_env",
            "os.environ",
            "open(",
        )
        for token in forbidden:
            self.assertNotIn(token, source, f"forbidden token {token!r}")


if __name__ == "__main__":
    unittest.main()
