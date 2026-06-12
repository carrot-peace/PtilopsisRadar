# coding=utf-8
"""
Tests for the explicit CR-A event state filesystem boundary (PR10c).
"""

import inspect
import tempfile
import unittest
from pathlib import Path

from trendradar.cr.state_snapshot import (
    CR_EVENT_STATE_SCHEMA_VERSION,
    CREventStateEntry,
    CREventStateSnapshot,
    empty_cr_event_state_snapshot,
)
from trendradar.cr.state_store import (
    load_cr_event_state_snapshot,
    save_cr_event_state_snapshot,
)
import trendradar.cr.state_store as state_store_module


class TestMissingFile(unittest.TestCase):
    def test_missing_file_returns_empty_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.json"
            result = load_cr_event_state_snapshot(path)

        self.assertEqual(result.snapshot, empty_cr_event_state_snapshot())
        self.assertFalse(result.loaded)
        self.assertIsNone(result.error)


class TestSaveAndLoad(unittest.TestCase):
    def test_save_and_load_round_trip(self):
        snapshot = CREventStateSnapshot(
            schema_version=CR_EVENT_STATE_SCHEMA_VERSION,
            entries=(
                CREventStateEntry(
                    event_key="event-1",
                    decision_level="alert",
                    score=72.0,
                    seen_at="2026-06-12T08:00:00+08:00",
                    title="Topic",
                    candidate_id="candidate-1",
                    event_key_version="cr-event-v1",
                ),
            ),
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            save_result = save_cr_event_state_snapshot(snapshot, path)
            load_result = load_cr_event_state_snapshot(path)

        self.assertTrue(save_result.saved)
        self.assertIsNone(save_result.error)
        self.assertEqual(save_result.path, str(path))
        self.assertTrue(load_result.loaded)
        self.assertIsNone(load_result.error)
        self.assertEqual(load_result.path, str(path))
        self.assertEqual(load_result.snapshot, snapshot)

    def test_saving_to_nested_path_creates_parents(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "state" / "snapshot.json"
            result = save_cr_event_state_snapshot(
                empty_cr_event_state_snapshot(),
                path,
            )
            exists = path.exists()

        self.assertTrue(result.saved)
        self.assertTrue(exists)


class TestMalformedAndInvalidState(unittest.TestCase):
    def test_malformed_json_returns_empty_snapshot_and_sanitized_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text("{not-json", encoding="utf-8")

            result = load_cr_event_state_snapshot(path)

        self.assertEqual(result.snapshot, empty_cr_event_state_snapshot())
        self.assertFalse(result.loaded)
        self.assertIsNotNone(result.error)
        self.assertLess(len(result.error or ""), 120)
        self.assertIn("JSONDecodeError", result.error or "")
        self.assertNotIn("{not-json", result.error or "")
        self.assertEqual(result.path, str(path))

    def test_schema_mismatch_returns_empty_snapshot_and_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(
                '{"schema_version":"wrong","entries":[]}',
                encoding="utf-8",
            )

            result = load_cr_event_state_snapshot(path)

        self.assertEqual(result.snapshot, empty_cr_event_state_snapshot())
        self.assertFalse(result.loaded)
        self.assertIsNotNone(result.error)
        self.assertIn("schema_version mismatch", result.error or "")
        self.assertEqual(result.path, str(path))


class TestAtomicishBehavior(unittest.TestCase):
    def test_save_writes_final_path_and_leaves_no_temp_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            path = base / "state.json"
            result = save_cr_event_state_snapshot(
                empty_cr_event_state_snapshot(),
                path,
            )
            final_path_exists = path.exists()
            leftovers = list(base.glob("*.tmp")) + list(base.glob(".*.tmp"))

        self.assertTrue(result.saved)
        self.assertTrue(final_path_exists)
        self.assertEqual(leftovers, [])


class TestForbiddenImportsAndBehavior(unittest.TestCase):
    def test_module_source_has_no_forbidden_imports_or_defaults(self):
        source = inspect.getsource(state_store_module)
        forbidden_fragments = (
            "requests",
            "httpx",
            "aiohttp",
            "urllib.request",
            "urlopen",
            "telegram_sink",
            "telegram_env",
            "dispatch_executor",
            "dispatch_plan",
            "runtime_dry_run",
            "os.environ",
            "output/",
            "config/",
            "config.yaml",
        )
        for fragment in forbidden_fragments:
            self.assertNotIn(fragment, source)


if __name__ == "__main__":
    unittest.main()
