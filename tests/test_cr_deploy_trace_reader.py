# coding=utf-8
"""
PR-CR-A6a: CR deploy trace reader tests.

Covers:
  - Both plan and receipt present → authoritative_plan_receipt, high confidence
  - Plan present, receipt missing → authoritative_plan_only, medium confidence
  - Receipt present, plan missing → authoritative_receipt_only, medium confidence
  - Neither present → missing_artifacts, low confidence
  - Malformed plan JSON → artifact_parse_error, no crash
  - Malformed receipt JSON → artifact_parse_error, no crash
  - Read-only: deploy_trace does not modify CR artifacts

Pure tests only — no network, no Telegram, no real output directories.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trendradar.cr.deploy_trace_reader import read_cr_deploy_trace


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_plan(path: Path, **overrides) -> None:
    """Write a minimal dispatch_plan.json fixture."""
    plan = {
        "schema_version": "cr-dispatch-plan-v1",
        "run_id": "test-run-001",
        "created_at": "2026-06-17T09:00:00+00:00",
        "dispatch_mode": "live",
        "should_dispatch": True,
        "decision": "dispatch",
        "reason": "ready",
        "selected_event_key": "ev-A",
        "selected_candidate_id": "c-A",
        "selected_title": "Topic A",
        "selected_level": "urgent",
        "selected_score": 90.0,
        "candidate_counts": {
            "urgent": 1, "alert": 0, "watch": 0, "suppress": 0, "push_eligible": 1,
        },
        "candidate_summary": [],
        "message_preview": "Alert body",
        "missing_fields": [],
        "cooldown": {
            "state_available": True,
            "state_error": None,
            "policy_version": "cr-cooldown-v1",
            "entries": [
                {
                    "candidate_id": "c-A",
                    "event_key": "ev-A",
                    "current_level": "urgent",
                    "last_level": "alert",
                    "is_escalation": True,
                    "allowed_by_escalation": True,
                    "suppressed_by_cooldown": False,
                    "decision": "eligible_escalation_bypass",
                },
                {
                    "candidate_id": "c-B",
                    "event_key": "ev-B",
                    "current_level": "alert",
                    "last_level": "alert",
                    "is_escalation": False,
                    "allowed_by_escalation": False,
                    "suppressed_by_cooldown": True,
                    "decision": "skipped_cooldown",
                },
            ],
        },
    }
    plan.update(overrides)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_receipt(path: Path, **overrides) -> None:
    """Write a minimal dispatch_receipts.json fixture."""
    receipt = {
        "schema_version": "cr-dispatch-receipts-v1",
        "run_id": "test-run-001",
        "created_at": "2026-06-17T09:00:01+00:00",
        "dispatch_mode": "live",
        "plan_decision": "dispatch",
        "plan_should_dispatch": True,
        "receipts": [
            {
                "message_index": 0,
                "attempted": True,
                "accepted": True,
                "status": "accepted",
                "detail": "telegram_ok",
                "transport": None,
                "http_status": None,
                "sink_ok": None,
                "exception_type": None,
                "exception_message": None,
            },
        ],
        "candidate_outcomes": [
            {
                "candidate_id": "c-A",
                "event_key": "ev-A",
                "is_escalation": True,
                "allowed_by_escalation": True,
                "suppressed_by_cooldown": False,
                "decision": "eligible_escalation_bypass",
            },
            {
                "candidate_id": "c-B",
                "event_key": "ev-B",
                "is_escalation": False,
                "allowed_by_escalation": False,
                "suppressed_by_cooldown": True,
                "decision": "skipped_cooldown",
            },
        ],
    }
    receipt.update(overrides)
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Test Group A — Both plan and receipt present
# ---------------------------------------------------------------------------


class TestBothPresent(unittest.TestCase):
    def test_decision_source_authoritative(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "dispatch_plan.json"
            receipt_path = Path(tmp) / "dispatch_receipts.json"
            _write_plan(plan_path)
            _write_receipt(receipt_path)

            result = read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
            cr = result["cr_dispatch"]

            self.assertEqual(cr["decision_source"], "authoritative_plan_receipt")
            self.assertEqual(cr["confidence"], "high")
            self.assertTrue(cr["plan_available"])
            self.assertTrue(cr["receipt_available"])
            self.assertIsNone(cr["plan_parse_error"])
            self.assertIsNone(cr["receipt_parse_error"])

    def test_plan_fields_mapped(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "dispatch_plan.json"
            receipt_path = Path(tmp) / "dispatch_receipts.json"
            _write_plan(plan_path)
            _write_receipt(receipt_path)

            result = read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
            cr = result["cr_dispatch"]

            self.assertEqual(cr["run_id"], "test-run-001")
            self.assertEqual(cr["dispatch_mode"], "live")
            self.assertEqual(cr["plan_decision"], "dispatch")
            self.assertTrue(cr["plan_should_dispatch"])
            self.assertEqual(cr["selected_candidate"]["event_key"], "ev-A")
            self.assertEqual(cr["selected_candidate"]["candidate_id"], "c-A")
            self.assertEqual(cr["selected_candidate"]["level"], "urgent")

    def test_receipt_summary_mapped(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "dispatch_plan.json"
            receipt_path = Path(tmp) / "dispatch_receipts.json"
            _write_plan(plan_path)
            _write_receipt(receipt_path)

            result = read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
            cr = result["cr_dispatch"]
            summary = cr["receipt_summary"]

            self.assertTrue(summary["attempted"])
            self.assertTrue(summary["accepted"])
            self.assertEqual(summary["status"], "accepted")

    def test_cooldown_entries_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "dispatch_plan.json"
            receipt_path = Path(tmp) / "dispatch_receipts.json"
            _write_plan(plan_path)
            _write_receipt(receipt_path)

            result = read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
            cr = result["cr_dispatch"]

            self.assertIsNotNone(cr["cooldown"])
            entries = cr["cooldown"]["entries"]
            self.assertEqual(len(entries), 2)

    def test_candidate_outcomes_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "dispatch_plan.json"
            receipt_path = Path(tmp) / "dispatch_receipts.json"
            _write_plan(plan_path)
            _write_receipt(receipt_path)

            result = read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
            cr = result["cr_dispatch"]

            outcomes = cr["candidate_outcomes"]
            self.assertEqual(len(outcomes), 2)
            a_outcome = [o for o in outcomes if o["candidate_id"] == "c-A"][0]
            self.assertTrue(a_outcome["allowed_by_escalation"])
            b_outcome = [o for o in outcomes if o["candidate_id"] == "c-B"][0]
            self.assertTrue(b_outcome["suppressed_by_cooldown"])

    def test_schema_versions_mapped(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "dispatch_plan.json"
            receipt_path = Path(tmp) / "dispatch_receipts.json"
            _write_plan(plan_path)
            _write_receipt(receipt_path)

            result = read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
            cr = result["cr_dispatch"]

            self.assertEqual(cr["schema_version"]["plan"], "cr-dispatch-plan-v1")
            self.assertEqual(cr["schema_version"]["receipt"], "cr-dispatch-receipts-v1")


# ---------------------------------------------------------------------------
# Test Group B — Plan present, receipt missing
# ---------------------------------------------------------------------------


class TestPlanOnly(unittest.TestCase):
    def test_decision_source_plan_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "dispatch_plan.json"
            receipt_path = Path(tmp) / "dispatch_receipts.json"
            _write_plan(plan_path)
            # receipt does not exist

            result = read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
            cr = result["cr_dispatch"]

            self.assertEqual(cr["decision_source"], "authoritative_plan_only")
            self.assertEqual(cr["confidence"], "medium")
            self.assertTrue(cr["plan_available"])
            self.assertFalse(cr["receipt_available"])

    def test_plan_fields_still_mapped(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "dispatch_plan.json"
            receipt_path = Path(tmp) / "dispatch_receipts.json"
            _write_plan(plan_path)

            result = read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
            cr = result["cr_dispatch"]

            self.assertEqual(cr["dispatch_mode"], "live")
            self.assertEqual(cr["plan_decision"], "dispatch")
            self.assertEqual(cr["selected_candidate"]["candidate_id"], "c-A")


# ---------------------------------------------------------------------------
# Test Group C — Receipt present, plan missing
# ---------------------------------------------------------------------------


class TestReceiptOnly(unittest.TestCase):
    def test_decision_source_receipt_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "dispatch_plan.json"
            receipt_path = Path(tmp) / "dispatch_receipts.json"
            _write_receipt(receipt_path)
            # plan does not exist

            result = read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
            cr = result["cr_dispatch"]

            self.assertEqual(cr["decision_source"], "authoritative_receipt_only")
            self.assertEqual(cr["confidence"], "medium")
            self.assertFalse(cr["plan_available"])
            self.assertTrue(cr["receipt_available"])

    def test_receipt_fields_mapped(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "dispatch_plan.json"
            receipt_path = Path(tmp) / "dispatch_receipts.json"
            _write_receipt(receipt_path)

            result = read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
            cr = result["cr_dispatch"]

            self.assertEqual(cr["dispatch_mode"], "live")
            self.assertTrue(cr["receipt_summary"]["accepted"])


# ---------------------------------------------------------------------------
# Test Group D — Neither artifact exists
# ---------------------------------------------------------------------------


class TestNeitherPresent(unittest.TestCase):
    def test_decision_source_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "dispatch_plan.json"
            receipt_path = Path(tmp) / "dispatch_receipts.json"

            result = read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
            cr = result["cr_dispatch"]

            self.assertEqual(cr["decision_source"], "missing_artifacts")
            self.assertEqual(cr["confidence"], "low")
            self.assertFalse(cr["plan_available"])
            self.assertFalse(cr["receipt_available"])


# ---------------------------------------------------------------------------
# Test Group E — Malformed plan JSON
# ---------------------------------------------------------------------------


class TestMalformedPlan(unittest.TestCase):
    def test_no_crash_on_malformed_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "dispatch_plan.json"
            receipt_path = Path(tmp) / "dispatch_receipts.json"
            plan_path.write_text("{bad json", encoding="utf-8")
            _write_receipt(receipt_path)

            result = read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
            cr = result["cr_dispatch"]

            self.assertEqual(cr["decision_source"], "artifact_parse_error")
            self.assertEqual(cr["confidence"], "low")
            self.assertTrue(cr["plan_available"])
            self.assertIsNotNone(cr["plan_parse_error"])

    def test_receipt_still_read_when_plan_malformed(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "dispatch_plan.json"
            receipt_path = Path(tmp) / "dispatch_receipts.json"
            plan_path.write_text("not json", encoding="utf-8")
            _write_receipt(receipt_path)

            result = read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
            cr = result["cr_dispatch"]

            self.assertTrue(cr["receipt_available"])
            self.assertIsNone(cr["receipt_parse_error"])


# ---------------------------------------------------------------------------
# Test Group F — Malformed receipt JSON
# ---------------------------------------------------------------------------


class TestMalformedReceipt(unittest.TestCase):
    def test_no_crash_on_malformed_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "dispatch_plan.json"
            receipt_path = Path(tmp) / "dispatch_receipts.json"
            _write_plan(plan_path)
            receipt_path.write_text("{bad json", encoding="utf-8")

            result = read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
            cr = result["cr_dispatch"]

            self.assertEqual(cr["decision_source"], "artifact_parse_error")
            self.assertEqual(cr["confidence"], "low")
            self.assertTrue(cr["receipt_available"])
            self.assertIsNotNone(cr["receipt_parse_error"])


# ---------------------------------------------------------------------------
# Test Group G — Read-only behavior
# ---------------------------------------------------------------------------


class TestReadOnly(unittest.TestCase):
    def test_plan_file_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "dispatch_plan.json"
            receipt_path = Path(tmp) / "dispatch_receipts.json"
            _write_plan(plan_path)
            _write_receipt(receipt_path)

            original_content = plan_path.read_text(encoding="utf-8")
            read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
            self.assertEqual(plan_path.read_text(encoding="utf-8"), original_content)

    def test_receipt_file_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "dispatch_plan.json"
            receipt_path = Path(tmp) / "dispatch_receipts.json"
            _write_plan(plan_path)
            _write_receipt(receipt_path)

            original_content = receipt_path.read_text(encoding="utf-8")
            read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
            self.assertEqual(receipt_path.read_text(encoding="utf-8"), original_content)

    def test_malformed_file_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "dispatch_plan.json"
            receipt_path = Path(tmp) / "dispatch_receipts.json"
            plan_path.write_text("{malformed", encoding="utf-8")
            _write_receipt(receipt_path)

            original_content = plan_path.read_text(encoding="utf-8")
            read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
            self.assertEqual(plan_path.read_text(encoding="utf-8"), original_content)


# ---------------------------------------------------------------------------
# Test Group H — Not-configured / skipped receipt statuses
# ---------------------------------------------------------------------------


class TestNotConfiguredReceipt(unittest.TestCase):
    def test_not_configured_status_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "dispatch_plan.json"
            receipt_path = Path(tmp) / "dispatch_receipts.json"
            _write_plan(plan_path, should_dispatch=False, decision="no_candidate", reason="no_selected_candidates")
            _write_receipt(receipt_path, plan_should_dispatch=False, plan_decision="no_candidate", receipts=[
                {
                    "message_index": 0,
                    "attempted": False,
                    "accepted": False,
                    "status": "skipped_no_candidate",
                    "detail": "no_selected_candidates",
                    "transport": None, "http_status": None, "sink_ok": None,
                    "exception_type": None, "exception_message": None,
                },
            ])

            result = read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
            cr = result["cr_dispatch"]

            self.assertFalse(cr["plan_should_dispatch"])
            self.assertEqual(cr["receipt_summary"]["status"], "skipped_no_candidate")
            self.assertFalse(cr["receipt_summary"]["accepted"])


# ---------------------------------------------------------------------------
# Test Group I — Fix 1: empty candidate_outcomes preserved
# ---------------------------------------------------------------------------


class TestEmptyCandidateOutcomes(unittest.TestCase):
    def test_empty_outcomes_not_overridden_by_plan_cooldown(self):
        """candidate_outcomes: [] must be preserved, not fall back to cooldown entries."""
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "dispatch_plan.json"
            receipt_path = Path(tmp) / "dispatch_receipts.json"
            _write_plan(plan_path)
            _write_receipt(receipt_path, candidate_outcomes=[])

            result = read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
            cr = result["cr_dispatch"]

            self.assertEqual(cr["candidate_outcomes"], [])


# ---------------------------------------------------------------------------
# Test Group J — Fix 2: receipt-only plan_should_dispatch fallback
# ---------------------------------------------------------------------------


class TestReceiptOnlyPlanShouldDispatch(unittest.TestCase):
    def test_receipt_plan_should_dispatch_used(self):
        """Receipt-only: plan_should_dispatch comes from receipt."""
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "dispatch_plan.json"
            receipt_path = Path(tmp) / "dispatch_receipts.json"
            _write_receipt(receipt_path, plan_should_dispatch=True)

            result = read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
            cr = result["cr_dispatch"]

            self.assertTrue(cr["plan_should_dispatch"])


# ---------------------------------------------------------------------------
# Test Group K — Fix 3: receipt transport/detail fields preserved
# ---------------------------------------------------------------------------


class TestReceiptTransportFields(unittest.TestCase):
    def test_transport_fields_preserved(self):
        """Receipt summary preserves transport/http_status/exception fields."""
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "dispatch_plan.json"
            receipt_path = Path(tmp) / "dispatch_receipts.json"
            _write_plan(plan_path)
            _write_receipt(receipt_path, receipts=[
                {
                    "message_index": 0,
                    "attempted": True,
                    "accepted": False,
                    "status": "failed_transport",
                    "detail": "TimeoutError",
                    "transport": "telegram",
                    "http_status": None,
                    "sink_ok": None,
                    "exception_type": "TimeoutError",
                    "exception_message": "connection timed out",
                },
            ])

            result = read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
            cr = result["cr_dispatch"]
            summary = cr["receipt_summary"]

            self.assertEqual(summary["transport"], "telegram")
            self.assertIsNone(summary["http_status"])
            self.assertEqual(summary["exception_type"], "TimeoutError")
            self.assertEqual(summary["exception_message"], "connection timed out")


# ---------------------------------------------------------------------------
# Test Group L — Fix 4: plan fields preserved
# ---------------------------------------------------------------------------


class TestPlanFieldsPreserved(unittest.TestCase):
    def test_created_at_from_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "dispatch_plan.json"
            receipt_path = Path(tmp) / "dispatch_receipts.json"
            _write_plan(plan_path, created_at="2026-06-17T09:00:00+00:00")
            _write_receipt(receipt_path)

            result = read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
            cr = result["cr_dispatch"]

            self.assertEqual(cr["created_at"], "2026-06-17T09:00:00+00:00")

    def test_candidate_counts_from_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "dispatch_plan.json"
            receipt_path = Path(tmp) / "dispatch_receipts.json"
            _write_plan(plan_path)
            _write_receipt(receipt_path)

            result = read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
            cr = result["cr_dispatch"]

            self.assertIsNotNone(cr["candidate_counts"])
            self.assertEqual(cr["candidate_counts"]["urgent"], 1)

    def test_message_preview_from_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "dispatch_plan.json"
            receipt_path = Path(tmp) / "dispatch_receipts.json"
            _write_plan(plan_path, message_preview="Alert body text")
            _write_receipt(receipt_path)

            result = read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
            cr = result["cr_dispatch"]

            self.assertEqual(cr["message_preview"], "Alert body text")

    def test_created_at_from_receipt_when_plan_missing(self):
        """Receipt-only: created_at comes from receipt."""
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "dispatch_plan.json"
            receipt_path = Path(tmp) / "dispatch_receipts.json"
            _write_receipt(receipt_path, created_at="2026-06-17T10:00:00+00:00")

            result = read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
            cr = result["cr_dispatch"]

            self.assertEqual(cr["created_at"], "2026-06-17T10:00:00+00:00")


# ---------------------------------------------------------------------------
# Test Group M — Fix 5: no-send boundary
# ---------------------------------------------------------------------------


class TestNoSendBoundary(unittest.TestCase):
    """deploy_trace_reader must not reference send/transport modules."""

    FORBIDDEN = (
        "CRTelegramSink",
        "build_cr_telegram_sink_from_env",
        "execute_cr_dispatch_plan",
        "urllib",
    )

    def test_no_forbidden_tokens(self):
        import trendradar.cr.deploy_trace_reader as mod
        source = Path(mod.__file__).read_text(encoding="utf-8")
        for token in self.FORBIDDEN:
            self.assertNotIn(token, source, f"forbidden token {token!r} present")


if __name__ == "__main__":
    unittest.main()
