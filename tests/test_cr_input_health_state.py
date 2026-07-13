# coding=utf-8

import json
import tempfile
import unittest
from pathlib import Path

from trendradar.cr.input_health_state import (
    CRInputHealthState,
    load_cr_input_health_state,
    quarantine_invalid_cr_input_health_state,
    recovered_source_ids,
    save_cr_input_health_state,
)


class TestCRInputHealthState(unittest.TestCase):
    def test_round_trip_and_recovery_intersection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            saved = save_cr_input_health_state(
                CRInputHealthState(
                    recorded_at="2026-07-13T00:00:00+00:00",
                    hotlist_successful_ids=("a",),
                    hotlist_failed_ids=("b", "c"),
                    rss_failed_ids=("feed-a",),
                ),
                path,
            )
            self.assertTrue(saved.saved, saved.error)
            loaded = load_cr_input_health_state(path)
            self.assertTrue(loaded.loaded, loaded.error)
            self.assertEqual(loaded.state.hotlist_failed_ids, ("b", "c"))
            self.assertEqual(
                recovered_source_ids(
                    loaded.state.hotlist_failed_ids,
                    ("b", "new-source"),
                ),
                ("b",),
            )

    def test_missing_state_is_clean_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded = load_cr_input_health_state(Path(tmp) / "missing.json")
            self.assertFalse(loaded.loaded)
            self.assertIsNone(loaded.state)
            self.assertIsNone(loaded.error)

    def test_invalid_state_can_be_quarantined_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text("{broken", encoding="utf-8")
            loaded = load_cr_input_health_state(path)
            self.assertIsNotNone(loaded.error)
            self.assertTrue(
                quarantine_invalid_cr_input_health_state(
                    path,
                    suffix="test",
                )
            )
            self.assertFalse(path.exists())
            corrupt = Path(tmp) / "state.json.corrupt.test"
            self.assertEqual(corrupt.read_text(encoding="utf-8"), "{broken")

    def test_incomplete_but_valid_json_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(
                '{"schema_version":"cr-input-health-state-v1"}',
                encoding="utf-8",
            )
            loaded = load_cr_input_health_state(path)
            self.assertFalse(loaded.loaded)
            self.assertIsNotNone(loaded.error)

    def test_non_string_source_ids_are_not_trusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "cr-input-health-state-v1",
                        "recorded_at": "2026-07-13T00:00:00+00:00",
                        "hotlist": {
                            "successful_ids": [],
                            "failed_ids": [{"bad": "id"}],
                        },
                        "rss": {"successful_ids": [], "failed_ids": []},
                    }
                ),
                encoding="utf-8",
            )
            loaded = load_cr_input_health_state(path)
            self.assertFalse(loaded.loaded)
            self.assertIsNotNone(loaded.error)

    def test_directory_path_is_never_quarantined(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state-dir"
            path.mkdir()
            self.assertFalse(
                quarantine_invalid_cr_input_health_state(
                    path,
                    suffix="test",
                )
            )
            self.assertTrue(path.is_dir())

    def test_state_contains_no_item_payload_or_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            save_cr_input_health_state(
                CRInputHealthState(
                    recorded_at="2026-07-13T00:00:00+00:00",
                    hotlist_failed_ids=("weibo",),
                    rss_successful_ids=("feed",),
                ),
                path,
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "cr-input-health-state-v1")
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("TELEGRAM", text)
            self.assertNotIn("title", text)
            self.assertNotIn("url", text)


if __name__ == "__main__":
    unittest.main()
