# coding=utf-8
"""Tests for scripts/cr_a_smoke_check.py (PR-CR-A8).

The smoke check is read-only: it parses CR-A artifacts and enforces the
no-false-success invariant (accepted == true requires status == "accepted").
These tests exercise it against temporary artifact files only; they never run
CR, never send Telegram, and never touch real output paths.
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

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self):
        return smoke.run_smoke_check(
            plan_path=str(self.plan),
            receipts_path=str(self.receipts),
            deploy_trace_path=str(self.trace),
            deferred_queue_path=str(self.queue),
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
            ]
        )
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
