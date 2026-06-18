# coding=utf-8
"""
PR-CR-A6b: CR deploy trace writer tests.

Covers:
  - Writer uses reader output and writes latest + archive JSON
  - Missing CR artifacts still writes low-confidence trace
  - Malformed CR artifacts still writes parse-error trace
  - Read-only: writer does not modify CR plan/receipt/state files
  - No-send: writer cannot call Telegram / executor
  - Archive/latest parity

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
from trendradar.cr.deploy_trace_writer import (
    DEPLOY_TRACE_SCHEMA_VERSION,
    DeployTraceConfig,
    write_deploy_trace,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_plan(path: Path, **overrides) -> None:
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
        "candidate_counts": {"urgent": 1, "alert": 0, "watch": 0, "suppress": 0, "push_eligible": 1},
        "candidate_summary": [],
        "message_preview": "Alert body",
        "missing_fields": [],
        "cooldown": {
            "state_available": True,
            "state_error": None,
            "policy_version": "cr-cooldown-v1",
            "entries": [],
        },
        "quiet_hours": {
            "enabled": True,
            "timezone": "Asia/Shanghai",
            "in_quiet_hours": True,
            "allow_urgent_bypass": False,
            "bypass_applied": False,
            "decision": "deferred_quiet_hours",
            "deferred_count": 1,
            "entries": [],
        },
    }
    plan.update(overrides)
    path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")


def _write_receipt(path: Path, **overrides) -> None:
    receipt = {
        "schema_version": "cr-dispatch-receipts-v1",
        "run_id": "test-run-001",
        "created_at": "2026-06-17T09:00:01+00:00",
        "dispatch_mode": "live",
        "plan_decision": "dispatch",
        "plan_should_dispatch": True,
        "receipts": [{
            "message_index": 0,
            "attempted": True,
            "accepted": True,
            "status": "accepted",
            "detail": "telegram_ok",
            "transport": "telegram",
            "http_status": 200,
            "sink_ok": True,
            "exception_type": None,
            "exception_message": None,
        }],
        "candidate_outcomes": [],
    }
    receipt.update(overrides)
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Test Group A — Writer uses reader output
# ---------------------------------------------------------------------------


class TestWriterUsesReader(unittest.TestCase):
    def test_writes_latest_and_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            cr_dir = Path(tmp) / "cr" / "latest"
            cr_dir.mkdir(parents=True)
            plan_path = cr_dir / "dispatch_plan.json"
            receipt_path = cr_dir / "dispatch_receipts.json"
            _write_plan(plan_path)
            _write_receipt(receipt_path)

            trace_dir = Path(tmp) / "trace"
            config = DeployTraceConfig(root_dir=trace_dir)
            result = write_deploy_trace(
                run_label="run-001",
                plan_path=plan_path,
                receipt_path=receipt_path,
                config=config,
            )

            self.assertTrue(result.latest_path.exists())
            self.assertTrue(result.archive_path.exists())

    def test_output_contains_cr_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            cr_dir = Path(tmp) / "cr" / "latest"
            cr_dir.mkdir(parents=True)
            plan_path = cr_dir / "dispatch_plan.json"
            receipt_path = cr_dir / "dispatch_receipts.json"
            _write_plan(plan_path)
            _write_receipt(receipt_path)

            trace_dir = Path(tmp) / "trace"
            config = DeployTraceConfig(root_dir=trace_dir)
            result = write_deploy_trace(
                run_label="run-001",
                plan_path=plan_path,
                receipt_path=receipt_path,
                config=config,
            )

            self.assertEqual(result.cr_dispatch["decision_source"], "authoritative_plan_receipt")
            self.assertEqual(result.cr_dispatch["confidence"], "high")

    def test_output_json_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            cr_dir = Path(tmp) / "cr" / "latest"
            cr_dir.mkdir(parents=True)
            plan_path = cr_dir / "dispatch_plan.json"
            receipt_path = cr_dir / "dispatch_receipts.json"
            _write_plan(plan_path)
            _write_receipt(receipt_path)

            trace_dir = Path(tmp) / "trace"
            config = DeployTraceConfig(root_dir=trace_dir)
            result = write_deploy_trace(
                run_label="run-001",
                plan_path=plan_path,
                receipt_path=receipt_path,
                config=config,
            )

            data = json.loads(result.latest_path.read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], DEPLOY_TRACE_SCHEMA_VERSION)
            self.assertIn("cr_dispatch", data)
            self.assertEqual(data["cr_dispatch"]["decision_source"], "authoritative_plan_receipt")

    def test_output_contains_quiet_hours(self):
        with tempfile.TemporaryDirectory() as tmp:
            cr_dir = Path(tmp) / "cr" / "latest"
            cr_dir.mkdir(parents=True)
            plan_path = cr_dir / "dispatch_plan.json"
            receipt_path = cr_dir / "dispatch_receipts.json"
            _write_plan(plan_path)
            _write_receipt(receipt_path)

            trace_dir = Path(tmp) / "trace"
            config = DeployTraceConfig(root_dir=trace_dir)
            result = write_deploy_trace(
                run_label="run-001",
                plan_path=plan_path,
                receipt_path=receipt_path,
                config=config,
            )

            self.assertEqual(
                result.cr_dispatch["quiet_hours"]["decision"],
                "deferred_quiet_hours",
            )
            latest = json.loads(result.latest_path.read_text(encoding="utf-8"))
            archive = json.loads(result.archive_path.read_text(encoding="utf-8"))
            self.assertEqual(
                latest["cr_dispatch"]["quiet_hours"],
                archive["cr_dispatch"]["quiet_hours"],
            )


# ---------------------------------------------------------------------------
# Test Group B — Missing CR artifacts
# ---------------------------------------------------------------------------


class TestMissingArtifacts(unittest.TestCase):
    def test_missing_artifacts_still_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace_dir = Path(tmp) / "trace"
            config = DeployTraceConfig(root_dir=trace_dir)
            result = write_deploy_trace(
                run_label="run-missing",
                plan_path=Path(tmp) / "nonexistent_plan.json",
                receipt_path=Path(tmp) / "nonexistent_receipt.json",
                config=config,
            )

            self.assertTrue(result.latest_path.exists())
            self.assertTrue(result.archive_path.exists())
            self.assertEqual(result.cr_dispatch["decision_source"], "missing_artifacts")
            self.assertEqual(result.cr_dispatch["confidence"], "low")


# ---------------------------------------------------------------------------
# Test Group B2 — Plan-only / receipt-only writer
# ---------------------------------------------------------------------------


class TestWriterPartialArtifacts(unittest.TestCase):
    def test_plan_only_writer(self):
        """Only plan exists → writer produces authoritative_plan_only."""
        with tempfile.TemporaryDirectory() as tmp:
            cr_dir = Path(tmp) / "cr" / "latest"
            cr_dir.mkdir(parents=True)
            plan_path = cr_dir / "dispatch_plan.json"
            _write_plan(plan_path)
            # receipt does not exist

            trace_dir = Path(tmp) / "trace"
            config = DeployTraceConfig(root_dir=trace_dir)
            result = write_deploy_trace(
                run_label="plan-only",
                plan_path=plan_path,
                receipt_path=Path(tmp) / "nonexistent_receipt.json",
                config=config,
            )

            self.assertTrue(result.latest_path.exists())
            self.assertTrue(result.archive_path.exists())
            self.assertEqual(result.cr_dispatch["decision_source"], "authoritative_plan_only")
            self.assertEqual(result.cr_dispatch["confidence"], "medium")

    def test_receipt_only_writer(self):
        """Only receipt exists → writer produces authoritative_receipt_only."""
        with tempfile.TemporaryDirectory() as tmp:
            cr_dir = Path(tmp) / "cr" / "latest"
            cr_dir.mkdir(parents=True)
            receipt_path = cr_dir / "dispatch_receipts.json"
            _write_receipt(receipt_path)
            # plan does not exist

            trace_dir = Path(tmp) / "trace"
            config = DeployTraceConfig(root_dir=trace_dir)
            result = write_deploy_trace(
                run_label="receipt-only",
                plan_path=Path(tmp) / "nonexistent_plan.json",
                receipt_path=receipt_path,
                config=config,
            )

            self.assertTrue(result.latest_path.exists())
            self.assertTrue(result.archive_path.exists())
            self.assertEqual(result.cr_dispatch["decision_source"], "authoritative_receipt_only")
            self.assertEqual(result.cr_dispatch["confidence"], "medium")


# ---------------------------------------------------------------------------
# Test Group C — Malformed CR artifacts
# ---------------------------------------------------------------------------


class TestMalformedArtifacts(unittest.TestCase):
    def test_malformed_plan_writes_parse_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            cr_dir = Path(tmp) / "cr" / "latest"
            cr_dir.mkdir(parents=True)
            plan_path = cr_dir / "dispatch_plan.json"
            receipt_path = cr_dir / "dispatch_receipts.json"
            plan_path.write_text("{bad json", encoding="utf-8")
            _write_receipt(receipt_path)

            trace_dir = Path(tmp) / "trace"
            config = DeployTraceConfig(root_dir=trace_dir)
            result = write_deploy_trace(
                run_label="run-bad-plan",
                plan_path=plan_path,
                receipt_path=receipt_path,
                config=config,
            )

            self.assertEqual(result.cr_dispatch["decision_source"], "artifact_parse_error")
            self.assertEqual(result.cr_dispatch["confidence"], "low")
            self.assertIsNotNone(result.cr_dispatch["plan_parse_error"])


# ---------------------------------------------------------------------------
# Test Group D — Read-only CR boundary
# ---------------------------------------------------------------------------


class TestReadOnlyBoundary(unittest.TestCase):
    def test_plan_file_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            cr_dir = Path(tmp) / "cr" / "latest"
            cr_dir.mkdir(parents=True)
            plan_path = cr_dir / "dispatch_plan.json"
            receipt_path = cr_dir / "dispatch_receipts.json"
            _write_plan(plan_path)
            _write_receipt(receipt_path)

            original = plan_path.read_text(encoding="utf-8")
            trace_dir = Path(tmp) / "trace"
            write_deploy_trace(
                run_label="ro-test",
                plan_path=plan_path,
                receipt_path=receipt_path,
                config=DeployTraceConfig(root_dir=trace_dir),
            )
            self.assertEqual(plan_path.read_text(encoding="utf-8"), original)

    def test_receipt_file_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            cr_dir = Path(tmp) / "cr" / "latest"
            cr_dir.mkdir(parents=True)
            plan_path = cr_dir / "dispatch_plan.json"
            receipt_path = cr_dir / "dispatch_receipts.json"
            _write_plan(plan_path)
            _write_receipt(receipt_path)

            original = receipt_path.read_text(encoding="utf-8")
            trace_dir = Path(tmp) / "trace"
            write_deploy_trace(
                run_label="ro-test",
                plan_path=plan_path,
                receipt_path=receipt_path,
                config=DeployTraceConfig(root_dir=trace_dir),
            )
            self.assertEqual(receipt_path.read_text(encoding="utf-8"), original)


# ---------------------------------------------------------------------------
# Test Group E — No-send boundary
# ---------------------------------------------------------------------------


class TestNoSendBoundary(unittest.TestCase):
    FORBIDDEN = (
        "CRTelegramSink",
        "build_cr_telegram_sink_from_env",
        "execute_cr_dispatch_plan",
        "urllib",
    )

    def test_no_forbidden_tokens_in_writer(self):
        import trendradar.cr.deploy_trace_writer as mod
        source = Path(mod.__file__).read_text(encoding="utf-8")
        for token in self.FORBIDDEN:
            self.assertNotIn(token, source, f"forbidden token {token!r} present")


# ---------------------------------------------------------------------------
# Test Group F — Archive/latest parity
# ---------------------------------------------------------------------------


class TestArchiveLatestParity(unittest.TestCase):
    def test_latest_and_archive_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            cr_dir = Path(tmp) / "cr" / "latest"
            cr_dir.mkdir(parents=True)
            plan_path = cr_dir / "dispatch_plan.json"
            receipt_path = cr_dir / "dispatch_receipts.json"
            _write_plan(plan_path)
            _write_receipt(receipt_path)

            trace_dir = Path(tmp) / "trace"
            config = DeployTraceConfig(root_dir=trace_dir)
            result = write_deploy_trace(
                run_label="parity-test",
                plan_path=plan_path,
                receipt_path=receipt_path,
                config=config,
            )

            latest = json.loads(result.latest_path.read_text(encoding="utf-8"))
            archive = json.loads(result.archive_path.read_text(encoding="utf-8"))
            self.assertEqual(latest["cr_dispatch"], archive["cr_dispatch"])
            self.assertEqual(latest["schema_version"], archive["schema_version"])


# ---------------------------------------------------------------------------
# Test Group G — A6a reader tests still pass
# ---------------------------------------------------------------------------


class TestReaderStillWorks(unittest.TestCase):
    def test_reader_returns_cr_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "dispatch_plan.json"
            receipt_path = Path(tmp) / "dispatch_receipts.json"
            _write_plan(plan_path)
            _write_receipt(receipt_path)

            result = read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
            self.assertIn("cr_dispatch", result)
            self.assertEqual(result["cr_dispatch"]["decision_source"], "authoritative_plan_receipt")


# ---------------------------------------------------------------------------
# Test Group H — Multi-receipt visibility survives latest/archive
# ---------------------------------------------------------------------------


def _write_multi_receipt(path: Path) -> None:
    receipt = {
        "schema_version": "cr-dispatch-receipts-v1",
        "run_id": "test-run-multi",
        "created_at": "2026-06-18T08:01:00+00:00",
        "dispatch_mode": "live",
        "plan_decision": "dispatch",
        "plan_should_dispatch": True,
        "receipts": [
            {
                "message_index": 0, "attempted": True, "accepted": True,
                "status": "accepted", "detail": "flushed_deferred",
                "transport": None, "http_status": None, "sink_ok": None,
                "exception_type": None, "exception_message": None,
                "source": "deferred_queue", "event_key": "ev-B",
                "candidate_id": "c-B", "title": "Urgent B",
            },
            {
                "message_index": 1, "attempted": True, "accepted": True,
                "status": "accepted", "detail": "flushed_deferred",
                "transport": None, "http_status": None, "sink_ok": None,
                "exception_type": None, "exception_message": None,
                "source": "deferred_queue", "event_key": "ev-A",
                "candidate_id": "c-A", "title": "Alert A",
            },
            {
                "message_index": 0, "attempted": True, "accepted": True,
                "status": "accepted", "detail": "telegram_ok",
                "transport": "telegram", "http_status": 200, "sink_ok": True,
                "exception_type": None, "exception_message": None,
                "event_key": "ev-C", "candidate_id": "c-C", "title": "Current C",
            },
        ],
        "candidate_outcomes": [],
    }
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


class TestMultiReceiptInTrace(unittest.TestCase):
    def test_latest_and_archive_contain_multi_receipt_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            cr_dir = Path(tmp) / "cr" / "latest"
            cr_dir.mkdir(parents=True)
            plan_path = cr_dir / "dispatch_plan.json"
            receipt_path = cr_dir / "dispatch_receipts.json"
            _write_plan(plan_path)
            _write_multi_receipt(receipt_path)

            trace_dir = Path(tmp) / "trace"
            result = write_deploy_trace(
                run_label="multi-run",
                plan_path=plan_path,
                receipt_path=receipt_path,
                config=DeployTraceConfig(root_dir=trace_dir),
            )

            latest = json.loads(result.latest_path.read_text(encoding="utf-8"))
            archive = json.loads(result.archive_path.read_text(encoding="utf-8"))
            latest_cr = latest["cr_dispatch"]
            archive_cr = archive["cr_dispatch"]

            for cr in (latest_cr, archive_cr):
                self.assertEqual(cr["receipts_count"], 3)
                self.assertEqual(len(cr["receipt_summaries"]), 3)
                self.assertEqual(len(cr["deferred_flush_summaries"]), 2)
                self.assertEqual(cr["current_receipt_summary"]["event_key"], "ev-C")

            # latest and archive multi-receipt fields match.
            self.assertEqual(
                latest_cr["receipt_summaries"], archive_cr["receipt_summaries"]
            )
            self.assertEqual(
                latest_cr["deferred_flush_summaries"],
                archive_cr["deferred_flush_summaries"],
            )
            self.assertEqual(
                latest_cr["current_receipt_summary"],
                archive_cr["current_receipt_summary"],
            )
            self.assertEqual(latest_cr["receipts_count"], archive_cr["receipts_count"])

    def test_quiet_hours_still_present_with_multi_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            cr_dir = Path(tmp) / "cr" / "latest"
            cr_dir.mkdir(parents=True)
            plan_path = cr_dir / "dispatch_plan.json"
            receipt_path = cr_dir / "dispatch_receipts.json"
            _write_plan(plan_path)
            _write_multi_receipt(receipt_path)

            trace_dir = Path(tmp) / "trace"
            result = write_deploy_trace(
                run_label="multi-run-qh",
                plan_path=plan_path,
                receipt_path=receipt_path,
                config=DeployTraceConfig(root_dir=trace_dir),
            )

            self.assertIsNotNone(result.cr_dispatch["quiet_hours"])
            self.assertEqual(
                result.cr_dispatch["quiet_hours"]["decision"],
                "deferred_quiet_hours",
            )


if __name__ == "__main__":
    unittest.main()
