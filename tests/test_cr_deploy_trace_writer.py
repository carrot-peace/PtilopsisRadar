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
            self.assertEqual(result.cr_dispatch["decision_source"], "missing_artifacts")
            self.assertEqual(result.cr_dispatch["confidence"], "low")


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


if __name__ == "__main__":
    unittest.main()
