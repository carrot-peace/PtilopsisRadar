# coding=utf-8
"""
Tests for the CR-A cooldown audit assembly (PR10e).

The module under test is pure: it assembles event identity, repeat preview,
cooldown policy preview, and a *proposed* next-state entry into one audit-only
context. It performs no I/O, reads no clock, enforces no policy, and writes no
state.
"""

import inspect
import unittest

from trendradar.cr.cooldown_audit import (
    CRCooldownAuditCandidate,
    CRCooldownAuditContext,
    build_cr_cooldown_audit_context,
)
import trendradar.cr.cooldown_audit as cooldown_audit_module
from trendradar.cr.cooldown_policy import CRCooldownPolicy
from trendradar.cr.decision import CRDecision, DECISION_ALERT, DECISION_URGENT
from trendradar.cr.event_identity import build_cr_event_identity_from_candidate
from trendradar.cr.models import CRCandidate, CRSourceItem
from trendradar.cr.presentation import CRPresentedCandidate
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


class TestNoPriorSnapshot(unittest.TestCase):
    def test_builds_one_audit_candidate_per_input(self):
        pcs = (
            _make_presented(candidate_id="c1", display_title="Topic A"),
            _make_presented(candidate_id="c2", display_title="Topic B"),
        )
        context = build_cr_cooldown_audit_context(pcs)
        self.assertIsInstance(context, CRCooldownAuditContext)
        self.assertEqual(len(context.candidates), 2)
        for ac in context.candidates:
            self.assertIsInstance(ac, CRCooldownAuditCandidate)

    def test_repeat_preview_and_cooldown_are_not_evaluated(self):
        context = build_cr_cooldown_audit_context((_make_presented(),))
        ac = context.candidates[0]
        self.assertEqual(ac.repeat_preview.status, "not_evaluated")
        self.assertEqual(ac.cooldown_decision.action, "not_evaluated")

    def test_seen_event_states_is_empty(self):
        context = build_cr_cooldown_audit_context((_make_presented(),))
        self.assertEqual(context.seen_event_states, {})

    def test_state_updates_has_one_entry_per_candidate(self):
        pcs = (
            _make_presented(candidate_id="c1", display_title="Topic A"),
            _make_presented(candidate_id="c2", display_title="Topic B"),
        )
        context = build_cr_cooldown_audit_context(pcs)
        self.assertEqual(len(context.state_updates), 2)

    def test_input_order_preserved(self):
        pcs = (
            _make_presented(candidate_id="c2", display_title="Topic B"),
            _make_presented(candidate_id="c1", display_title="Topic A"),
        )
        context = build_cr_cooldown_audit_context(pcs)
        self.assertEqual(
            [ac.candidate_id for ac in context.candidates], ["c2", "c1"]
        )

    def test_empty_candidates_yields_empty_context(self):
        context = build_cr_cooldown_audit_context(())
        self.assertEqual(context.candidates, ())
        self.assertEqual(context.state_updates, ())
        self.assertEqual(context.seen_event_states, {})


class TestExistingPriorSnapshot(unittest.TestCase):
    def test_same_level_repeat_yields_cooldown(self):
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
        ac = context.candidates[0]
        self.assertEqual(ac.repeat_preview.status, "same_level_repeat")
        self.assertEqual(ac.cooldown_decision.action, "cooldown")

    def test_lower_prior_level_yields_meaningful_escalation_allow(self):
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
        ac = context.candidates[0]
        self.assertEqual(ac.repeat_preview.status, "meaningful_escalation")
        self.assertEqual(ac.cooldown_decision.action, "allow_escalation")

    def test_absent_prior_event_yields_new_allow_new(self):
        pc = _make_presented()
        # A non-empty snapshot that does not contain this candidate's key.
        snapshot = _snapshot(
            CREventStateEntry(
                event_key="cr-event-v1:other", decision_level=DECISION_ALERT
            )
        )
        context = build_cr_cooldown_audit_context(
            (pc,), prior_snapshot=snapshot
        )
        ac = context.candidates[0]
        self.assertEqual(ac.repeat_preview.status, "new")
        self.assertEqual(ac.cooldown_decision.action, "allow_new")

    def test_seen_event_states_reflects_snapshot(self):
        pc = _make_presented()
        key = _event_key(pc)
        snapshot = _snapshot(
            CREventStateEntry(
                event_key=key, decision_level=DECISION_ALERT, score=65.0
            )
        )
        context = build_cr_cooldown_audit_context(
            (pc,), prior_snapshot=snapshot
        )
        self.assertIn(key, context.seen_event_states)
        self.assertEqual(
            context.seen_event_states[key].decision_level, DECISION_ALERT
        )


class TestProposedStateUpdates(unittest.TestCase):
    def test_state_update_event_key_matches_identity(self):
        pc = _make_presented()
        context = build_cr_cooldown_audit_context((pc,))
        ac = context.candidates[0]
        self.assertEqual(ac.state_update.event_key, ac.event_identity.event_key)

    def test_state_update_preserves_decision_score_title_candidate(self):
        pc = _make_presented(
            candidate_id="c9",
            display_title="Topic Z",
            decision_level=DECISION_URGENT,
            total_score=88.0,
        )
        context = build_cr_cooldown_audit_context((pc,))
        entry = context.candidates[0].state_update
        self.assertEqual(entry.decision_level, DECISION_URGENT)
        self.assertEqual(entry.score, 88.0)
        self.assertEqual(entry.title, "Topic Z")
        self.assertEqual(entry.candidate_id, "c9")

    def test_seen_at_is_copied_from_explicit_input(self):
        pc = _make_presented()
        stamp = "2026-06-12T10:00:00+08:00"
        context = build_cr_cooldown_audit_context((pc,), seen_at=stamp)
        self.assertEqual(context.candidates[0].state_update.seen_at, stamp)
        self.assertEqual(context.state_updates[0].seen_at, stamp)

    def test_no_seen_at_leaves_none(self):
        pc = _make_presented()
        context = build_cr_cooldown_audit_context((pc,))
        self.assertIsNone(context.candidates[0].state_update.seen_at)

    def test_state_updates_match_per_candidate_entries(self):
        pcs = (
            _make_presented(candidate_id="c1", display_title="Topic A"),
            _make_presented(candidate_id="c2", display_title="Topic B"),
        )
        context = build_cr_cooldown_audit_context(pcs)
        self.assertEqual(
            context.state_updates,
            tuple(ac.state_update for ac in context.candidates),
        )


class TestCustomPolicy(unittest.TestCase):
    def test_custom_cooldown_minutes_appear_in_decision(self):
        pc = _make_presented(decision_level=DECISION_ALERT, total_score=67.0)
        key = _event_key(pc)
        snapshot = _snapshot(
            CREventStateEntry(
                event_key=key, decision_level=DECISION_ALERT, score=65.0
            )
        )
        context = build_cr_cooldown_audit_context(
            (pc,),
            prior_snapshot=snapshot,
            policy=CRCooldownPolicy(same_level_cooldown_minutes=120),
        )
        ac = context.candidates[0]
        self.assertEqual(ac.cooldown_decision.action, "cooldown")
        self.assertEqual(ac.cooldown_decision.cooldown_minutes, 120)

    def test_disabling_escalation_changes_to_cooldown(self):
        pc = _make_presented(decision_level=DECISION_URGENT, total_score=85.0)
        key = _event_key(pc)
        snapshot = _snapshot(
            CREventStateEntry(
                event_key=key, decision_level="watch", score=58.0
            )
        )
        context = build_cr_cooldown_audit_context(
            (pc,),
            prior_snapshot=snapshot,
            policy=CRCooldownPolicy(allow_meaningful_escalation=False),
        )
        self.assertEqual(
            context.candidates[0].cooldown_decision.action, "cooldown"
        )

    def test_allow_deescalation_changes_to_allow(self):
        pc = _make_presented(decision_level=DECISION_ALERT, total_score=62.0)
        key = _event_key(pc)
        snapshot = _snapshot(
            CREventStateEntry(
                event_key=key, decision_level=DECISION_URGENT, score=85.0
            )
        )
        context = build_cr_cooldown_audit_context(
            (pc,),
            prior_snapshot=snapshot,
            policy=CRCooldownPolicy(allow_deescalation=True),
        )
        ac = context.candidates[0]
        self.assertEqual(ac.repeat_preview.status, "deescalation")
        self.assertEqual(ac.cooldown_decision.action, "allow")


class TestPurityForbiddenBehavior(unittest.TestCase):
    def test_module_source_has_no_forbidden_io_network_env_clock_or_transport(
        self,
    ):
        source = inspect.getsource(cooldown_audit_module)
        forbidden_fragments = (
            "open(",
            "Path(",
            "os.environ",
            "datetime.now",
            "time.time",
            "requests",
            "httpx",
            "aiohttp",
            "urllib.request",
            "urlopen",
            # Runtime / transport / state / config imports must be absent.
            # Checked as import paths so module docstring prose (which may say
            # "config", "Telegram", "state files", ...) does not trip this.
            "telegram_sink",
            "telegram_env",
            "dispatch_executor",
            "dispatch_plan",
            "runtime_dry_run",
            "state_store",
            "import config",
            "from config",
            "trendradar.config",
        )
        for fragment in forbidden_fragments:
            self.assertNotIn(fragment, source)


if __name__ == "__main__":
    unittest.main()
