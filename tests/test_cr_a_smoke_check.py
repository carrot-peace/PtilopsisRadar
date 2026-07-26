# coding=utf-8
"""Tests for scripts/cr_a_smoke_check.py (PR-CR-A8).

The smoke check is read-only: it parses CR-A artifacts and enforces the
no-false-success invariant (accepted == true requires a full or partial
acceptance status). These tests exercise it against temporary artifact files
only; they never run CR, never send Telegram, and never touch real output
paths.
"""

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_PATH = os.path.join(ROOT, "scripts", "cr_a_smoke_check.py")

_spec = importlib.util.spec_from_file_location("cr_a_smoke_check", SCRIPT_PATH)
smoke = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(smoke)


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class CRSmokeCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.plan = self.base / "dispatch_plan.json"
        self.receipts = self.base / "dispatch_receipts.json"
        self.trace = self.base / "latest.json"
        self.queue = self.base / "cr_deferred_dispatch_queue.json"
        self.lifecycle = self.base / "lifecycle_report.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self):
        return smoke.run_smoke_check(
            plan_path=str(self.plan),
            receipts_path=str(self.receipts),
            deploy_trace_path=str(self.trace),
            deferred_queue_path=str(self.queue),
            lifecycle_report_path=str(self.lifecycle),
        )

    def test_all_missing_files_are_tolerated(self) -> None:
        # Fresh checkout: nothing has run yet. Should not raise.
        lines = self._run()
        self.assertTrue(any("SKIP" in line for line in lines))

    def test_accepted_receipt_passes(self) -> None:
        _write(self.plan, {"schema_version": "x"})
        _write(
            self.receipts,
            {"receipts": [{"message_index": 0, "accepted": True, "status": "accepted"}]},
        )
        lines = self._run()
        self.assertTrue(any("no false success" in line for line in lines))

    def test_partially_accepted_receipt_passes(self) -> None:
        _write(
            self.receipts,
            {
                "receipts": [
                    {
                        "message_index": 0,
                        "accepted": True,
                        "status": "accepted_partial",
                    }
                ]
            },
        )
        lines = self._run()
        self.assertTrue(any("no false success" in line for line in lines))

    def test_no_send_states_pass(self) -> None:
        _write(
            self.receipts,
            {
                "receipts": [
                    {"message_index": 0, "accepted": False, "status": "not_configured"},
                    {"message_index": 1, "accepted": False, "status": "failed_transport"},
                    {"message_index": 2, "accepted": False, "status": "deferred_quiet_hours"},
                ]
            },
        )
        # No accepted==true entries; invariant holds.
        self._run()

    def test_false_success_is_rejected(self) -> None:
        _write(
            self.receipts,
            {
                "receipts": [
                    {"message_index": 0, "accepted": True, "status": "failed_transport"}
                ]
            },
        )
        with self.assertRaises(smoke.SmokeCheckError):
            self._run()

    def test_malformed_json_is_rejected(self) -> None:
        self.plan.parent.mkdir(parents=True, exist_ok=True)
        self.plan.write_text("{not valid json", encoding="utf-8")
        with self.assertRaises(smoke.SmokeCheckError):
            self._run()

    def test_receipts_root_must_be_object(self) -> None:
        _write(self.receipts, ["not", "an", "object"])
        with self.assertRaises(smoke.SmokeCheckError):
            self._run()

    def test_main_returns_zero_on_clean_artifacts(self) -> None:
        _write(
            self.receipts,
            {"receipts": [{"message_index": 0, "accepted": True, "status": "accepted"}]},
        )
        code = smoke.main(
            [
                "--plan-path", str(self.plan),
                "--receipts-path", str(self.receipts),
                "--deploy-trace-path", str(self.trace),
                "--deferred-queue-path", str(self.queue),
                "--lifecycle-report-path", str(self.lifecycle),
            ]
        )
        self.assertEqual(code, 0)

    def test_main_returns_one_on_false_success(self) -> None:
        _write(
            self.receipts,
            {"receipts": [{"message_index": 0, "accepted": True, "status": "rejected"}]},
        )
        code = smoke.main(
            [
                "--plan-path", str(self.plan),
                "--receipts-path", str(self.receipts),
                "--deploy-trace-path", str(self.trace),
                "--deferred-queue-path", str(self.queue),
                "--lifecycle-report-path", str(self.lifecycle),
            ]
        )
        self.assertEqual(code, 1)


def _valid_lifecycle_report(**overrides: object) -> dict:
    """Return a valid lifecycle report dict, with optional overrides."""
    report = {
        "schema_version": "cr-lifecycle-report-v1",
        "enabled": True,
        "mode": "preview",
        "state_path": "output/cr/state/cr_dispatch_state.json",
        "generated_at": "2026-06-22T12:00:00+00:00",
        "ttl_floor_seconds": 604800,
        "ttl_for_level": {
            "alert": 604800,
            "urgent": 604800,
            "watch": 604800,
            "suppress": 604800,
        },
        "input_count": 10,
        "kept_count": 8,
        "would_evict_count": 2,
        "evicted_count": 0,
        "phase_counts": {"active": 8, "evictable": 2},
        "would_evict": [],
        "errors": [],
    }
    report.update(overrides)
    return report


class CRLifecycleReportSmokeCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.lifecycle = self.base / "lifecycle_report.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self):
        return smoke.run_smoke_check(
            plan_path=str(self.base / "no_plan.json"),
            receipts_path=str(self.base / "no_receipts.json"),
            deploy_trace_path=str(self.base / "no_trace.json"),
            deferred_queue_path=str(self.base / "no_queue.json"),
            lifecycle_report_path=str(self.lifecycle),
        )

    def test_absent_report_is_skip(self) -> None:
        lines = self._run()
        self.assertTrue(any("SKIP" in line and "lifecycle" in line.lower() for line in lines))

    def test_valid_preview_report_passes(self) -> None:
        _write(self.lifecycle, _valid_lifecycle_report())
        lines = self._run()
        self.assertTrue(any("lifecycle report invariants" in line for line in lines))

    def test_valid_enforce_report_passes(self) -> None:
        _write(self.lifecycle, _valid_lifecycle_report(
            mode="enforce",
            would_evict_count=2,
            evicted_count=2,
            kept_count=8,
        ))
        lines = self._run()
        self.assertTrue(any("lifecycle report invariants" in line for line in lines))

    def test_wrong_schema_version_fails(self) -> None:
        _write(self.lifecycle, _valid_lifecycle_report(schema_version="wrong"))
        with self.assertRaises(smoke.SmokeCheckError):
            self._run()

    def test_invalid_mode_fails(self) -> None:
        _write(self.lifecycle, _valid_lifecycle_report(mode="bogus"))
        with self.assertRaises(smoke.SmokeCheckError):
            self._run()

    def test_negative_count_fails(self) -> None:
        _write(self.lifecycle, _valid_lifecycle_report(input_count=-1))
        with self.assertRaises(smoke.SmokeCheckError):
            self._run()

    def test_preview_count_mismatch_fails(self) -> None:
        _write(self.lifecycle, _valid_lifecycle_report(
            input_count=10, kept_count=5, would_evict_count=2,
        ))
        with self.assertRaises(smoke.SmokeCheckError):
            self._run()

    def test_preview_nonzero_evicted_fails(self) -> None:
        _write(self.lifecycle, _valid_lifecycle_report(evicted_count=1))
        with self.assertRaises(smoke.SmokeCheckError):
            self._run()

    def test_enforce_count_mismatch_fails(self) -> None:
        _write(self.lifecycle, _valid_lifecycle_report(
            mode="enforce",
            input_count=10, kept_count=5, evicted_count=2,
            would_evict_count=2,
        ))
        with self.assertRaises(smoke.SmokeCheckError):
            self._run()

    def test_enforce_would_evict_mismatch_fails(self) -> None:
        _write(self.lifecycle, _valid_lifecycle_report(
            mode="enforce",
            would_evict_count=3,
            evicted_count=2,
            kept_count=8,
        ))
        with self.assertRaises(smoke.SmokeCheckError):
            self._run()

    def test_nonempty_errors_fails(self) -> None:
        _write(self.lifecycle, _valid_lifecycle_report(
            errors=["state load error: malformed"],
        ))
        with self.assertRaises(smoke.SmokeCheckError):
            self._run()

    def test_negative_ttl_fails(self) -> None:
        _write(self.lifecycle, _valid_lifecycle_report(
            ttl_for_level={"alert": -1, "urgent": 604800, "watch": 604800, "suppress": 604800},
        ))
        with self.assertRaises(smoke.SmokeCheckError):
            self._run()

    def test_malformed_json_fails(self) -> None:
        self.lifecycle.parent.mkdir(parents=True, exist_ok=True)
        self.lifecycle.write_text("{bad json", encoding="utf-8")
        with self.assertRaises(smoke.SmokeCheckError):
            self._run()


if __name__ == "__main__":
    unittest.main()
