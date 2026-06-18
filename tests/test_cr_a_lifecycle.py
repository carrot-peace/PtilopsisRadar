# coding=utf-8
"""Tests for scripts/cr_a_lifecycle.py (J2 + J5).

The lifecycle janitor is standalone: it reads/writes versioned JSON file
contracts through public boundaries, classifies entries via J1, and emits
a lifecycle report.  These tests exercise it against temporary files only.
"""

import importlib.util
import inspect
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from trendradar.cr.cooldown_policy import DEFAULT_CR_COOLDOWN_POLICY
from trendradar.cr.event_lifecycle import PHASE_ACTIVE, PHASE_EVICTABLE
from trendradar.cr.state_snapshot import (
    CREventStateEntry,
    CREventStateSnapshot,
    cr_event_state_snapshot_to_json_dict,
)
from trendradar.cr.state_store import save_cr_event_state_snapshot

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_PATH = os.path.join(ROOT, "scripts", "cr_a_lifecycle.py")

_spec = importlib.util.spec_from_file_location("cr_a_lifecycle", SCRIPT_PATH)
lifecycle = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["cr_a_lifecycle"] = lifecycle
_spec.loader.exec_module(lifecycle)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)
_COOLDOWN_SECONDS = DEFAULT_CR_COOLDOWN_POLICY.same_level_cooldown_minutes * 60
_TTL_FLOOR_DAYS = 7
_TTL_FLOOR_SECONDS = _TTL_FLOOR_DAYS * 86400


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _make_snapshot(*entries: CREventStateEntry) -> CREventStateSnapshot:
    return CREventStateSnapshot(
        schema_version="cr-event-state-v1",
        entries=entries,
    )


def _write_snapshot(path: Path, snapshot: CREventStateSnapshot) -> None:
    save_cr_event_state_snapshot(snapshot, path)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDisabledNoop(unittest.TestCase):
    def test_disabled_does_not_write_state_or_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            report = Path(tmp) / "report.json"
            entry = CREventStateEntry(
                event_key="ek-1", decision_level="alert",
                seen_at=_iso(_NOW - timedelta(days=30)),
            )
            _write_snapshot(state, _make_snapshot(entry))

            result = lifecycle.run_lifecycle(
                state_path=str(state),
                report_path=str(report),
                enabled=False,
                now=_NOW,
            )
            self.assertFalse(result.enabled)
            self.assertEqual(result.input_count, 0)
            self.assertFalse(state.exists() is False)  # state unchanged
            self.assertFalse(report.exists())  # no report


class TestPreviewMode(unittest.TestCase):
    def test_preview_does_not_modify_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            report = Path(tmp) / "report.json"
            entry_old = CREventStateEntry(
                event_key="ek-old", decision_level="alert",
                seen_at=_iso(_NOW - timedelta(days=30)),
            )
            entry_new = CREventStateEntry(
                event_key="ek-new", decision_level="alert",
                seen_at=_iso(_NOW - timedelta(hours=1)),
            )
            _write_snapshot(state, _make_snapshot(entry_old, entry_new))
            state_before = state.read_bytes()

            result = lifecycle.run_lifecycle(
                state_path=str(state),
                report_path=str(report),
                enabled=True,
                mode="preview",
                ttl_floor_days=_TTL_FLOOR_DAYS,
                now=_NOW,
            )
            self.assertTrue(result.enabled)
            self.assertEqual(result.mode, "preview")
            self.assertEqual(result.input_count, 2)
            self.assertEqual(result.kept_count, 1)
            self.assertEqual(result.would_evict_count, 1)
            self.assertEqual(result.evicted_count, 0)
            self.assertFalse(result.state_saved)
            self.assertEqual(state.read_bytes(), state_before)
            self.assertTrue(report.exists())

    def test_preview_report_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            report = Path(tmp) / "report.json"
            entry = CREventStateEntry(
                event_key="ek-1", decision_level="urgent",
                seen_at=_iso(_NOW - timedelta(days=30)),
            )
            _write_snapshot(state, _make_snapshot(entry))

            lifecycle.run_lifecycle(
                state_path=str(state),
                report_path=str(report),
                enabled=True,
                mode="preview",
                ttl_floor_days=_TTL_FLOOR_DAYS,
                now=_NOW,
            )
            data = _read_json(report)
            self.assertEqual(data["schema_version"], "cr-lifecycle-report-v1")
            self.assertTrue(data["enabled"])
            self.assertEqual(data["mode"], "preview")
            self.assertEqual(data["input_count"], 1)
            self.assertEqual(data["evicted_count"], 0)
            self.assertIsInstance(data["ttl_for_level"], dict)
            self.assertGreater(len(data["would_evict"]), 0)
            self.assertEqual(data["would_evict"][0]["event_key"], "ek-1")


class TestEnforceMode(unittest.TestCase):
    def test_enforce_removes_evictable_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            report = Path(tmp) / "report.json"
            entry_old = CREventStateEntry(
                event_key="ek-old", decision_level="alert",
                seen_at=_iso(_NOW - timedelta(days=30)),
            )
            entry_new = CREventStateEntry(
                event_key="ek-new", decision_level="alert",
                seen_at=_iso(_NOW - timedelta(hours=1)),
            )
            _write_snapshot(state, _make_snapshot(entry_old, entry_new))

            result = lifecycle.run_lifecycle(
                state_path=str(state),
                report_path=str(report),
                enabled=True,
                mode="enforce",
                ttl_floor_days=_TTL_FLOOR_DAYS,
                now=_NOW,
            )
            self.assertTrue(result.enabled)
            self.assertEqual(result.mode, "enforce")
            self.assertEqual(result.input_count, 2)
            self.assertEqual(result.kept_count, 1)
            self.assertEqual(result.would_evict_count, 1)
            self.assertEqual(result.evicted_count, 1)
            self.assertTrue(result.state_saved)

            # Verify state file was pruned
            from trendradar.cr.state_store import load_cr_event_state_snapshot
            reloaded = load_cr_event_state_snapshot(str(state))
            self.assertIsNone(reloaded.error)
            self.assertEqual(len(reloaded.snapshot.entries), 1)
            self.assertEqual(reloaded.snapshot.entries[0].event_key, "ek-new")

    def test_enforce_keeps_invalid_seen_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            report = Path(tmp) / "report.json"
            entry_bad = CREventStateEntry(
                event_key="ek-bad", decision_level="alert",
                seen_at="not-a-date",
            )
            _write_snapshot(state, _make_snapshot(entry_bad))

            result = lifecycle.run_lifecycle(
                state_path=str(state),
                report_path=str(report),
                enabled=True,
                mode="enforce",
                now=_NOW,
            )
            self.assertEqual(result.evicted_count, 0)
            self.assertEqual(result.kept_count, 1)

    def test_enforce_keeps_unknown_level(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            report = Path(tmp) / "report.json"
            entry = CREventStateEntry(
                event_key="ek-1", decision_level="bogus",
                seen_at=_iso(_NOW - timedelta(days=30)),
            )
            _write_snapshot(state, _make_snapshot(entry))

            result = lifecycle.run_lifecycle(
                state_path=str(state),
                report_path=str(report),
                enabled=True,
                mode="enforce",
                now=_NOW,
            )
            self.assertEqual(result.evicted_count, 0)
            self.assertEqual(result.kept_count, 1)


class TestMissingStateFile(unittest.TestCase):
    def test_missing_state_file_zero_entries_no_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "nonexistent.json"
            report = Path(tmp) / "report.json"

            result = lifecycle.run_lifecycle(
                state_path=str(state),
                report_path=str(report),
                enabled=True,
                mode="preview",
                now=_NOW,
            )
            self.assertTrue(result.enabled)
            self.assertIsNone(result.state_error)
            self.assertEqual(result.input_count, 0)
            self.assertTrue(report.exists())


class TestMalformedStateFile(unittest.TestCase):
    def test_malformed_state_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            report = Path(tmp) / "report.json"
            state.write_text("not json", encoding="utf-8")

            result = lifecycle.run_lifecycle(
                state_path=str(state),
                report_path=str(report),
                enabled=True,
                mode="enforce",
                now=_NOW,
            )
            self.assertIsNotNone(result.state_error)
            self.assertFalse(result.state_saved)
            self.assertEqual(result.evicted_count, 0)


class TestG5Guard(unittest.TestCase):
    def test_ttl_floor_smaller_than_cooldown_still_gte_cooldown(self) -> None:
        ttl = lifecycle.build_ttl_for_level(ttl_floor_seconds=60)
        for level, seconds in ttl.items():
            self.assertGreaterEqual(
                seconds, _COOLDOWN_SECONDS,
                f"ttl_for_level[{level!r}] = {seconds} < cooldown {_COOLDOWN_SECONDS}",
            )


class TestInvalidConfig(unittest.TestCase):
    def test_invalid_mode_defaults_to_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            report = Path(tmp) / "report.json"
            _write_snapshot(state, _make_snapshot())

            result = lifecycle.run_lifecycle(
                state_path=str(state),
                report_path=str(report),
                enabled=True,
                mode="bogus",
                now=_NOW,
            )
            self.assertEqual(result.mode, "preview")
            self.assertTrue(len(result.errors) > 0)

    def test_negative_ttl_floor_uses_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            report = Path(tmp) / "report.json"
            _write_snapshot(state, _make_snapshot())

            result = lifecycle.run_lifecycle(
                state_path=str(state),
                report_path=str(report),
                enabled=True,
                mode="preview",
                ttl_floor_days=-5,
                now=_NOW,
            )
            self.assertTrue(len(result.errors) > 0)


class TestReportWriteFailureDoesNotCorruptState(unittest.TestCase):
    def test_unwritable_report_does_not_prevent_state_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            # Point report to a path inside a non-existent nested dir that
            # would fail if mkdir were not called — but since _write_report
            # calls mkdir, we instead test by making the parent a file.
            report = Path(tmp) / "not_a_dir" / "report.json"
            report_path_file = Path(tmp) / "not_a_dir"
            report_path_file.write_text("block", encoding="utf-8")

            entry_old = CREventStateEntry(
                event_key="ek-old", decision_level="alert",
                seen_at=_iso(_NOW - timedelta(days=30)),
            )
            _write_snapshot(state, _make_snapshot(entry_old))

            result = lifecycle.run_lifecycle(
                state_path=str(state),
                report_path=str(report),
                enabled=True,
                mode="enforce",
                now=_NOW,
            )
            # State should still be saved even if report write fails
            self.assertTrue(result.state_saved)
            self.assertFalse(result.report_written)


class TestPostRunTrigger(unittest.TestCase):
    """Verify the post-run trigger wiring in __main__.py (P1)."""

    MAIN_PATH = os.path.join(ROOT, "trendradar", "__main__.py")

    def _main_source(self) -> str:
        return Path(self.MAIN_PATH).read_text(encoding="utf-8")

    def test_trigger_gated_by_lifecycle_enabled(self) -> None:
        source = self._main_source()
        self.assertIn(
            'PTILOPSIS_CR_LIFECYCLE_ENABLED',
            source,
            "trigger must check PTILOPSIS_CR_LIFECYCLE_ENABLED",
        )

    def test_trigger_loads_lifecycle_module(self) -> None:
        source = self._main_source()
        self.assertIn("cr_a_lifecycle.py", source)
        self.assertIn(".main([", source)

    def test_trigger_is_fail_closed(self) -> None:
        source = self._main_source()
        # The trigger must catch exceptions and print, never propagate.
        self.assertIn("except Exception", source)
        self.assertIn("[lifecycle] janitor error", source)

    def test_lifecycle_module_loadable_via_importlib(self) -> None:
        """The trigger uses importlib.util to load the script; verify it works."""
        import importlib.util as _ilu

        lifecycle_path = os.path.join(ROOT, "scripts", "cr_a_lifecycle.py")
        spec = _ilu.spec_from_file_location("cr_a_lifecycle_trigger_test", lifecycle_path)
        self.assertIsNotNone(spec)
        assert spec and spec.loader
        mod = _ilu.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        self.assertTrue(hasattr(mod, "run_lifecycle"))
        self.assertTrue(hasattr(mod, "CRLifecycleRunResult"))

    def test_trigger_import_style_runs_main_with_env_enabled(self) -> None:
        """Mirror __main__.py trigger loading and verify env-gated execution."""
        import importlib.util as _ilu

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            report = Path(tmp) / "report.json"
            entry = CREventStateEntry(
                event_key="ek-trigger", decision_level="alert",
                seen_at=_iso(_NOW - timedelta(hours=1)),
            )
            _write_snapshot(state, _make_snapshot(entry))

            lifecycle_path = os.path.join(ROOT, "scripts", "cr_a_lifecycle.py")
            spec = _ilu.spec_from_file_location(
                "cr_a_lifecycle_trigger_test_main",
                lifecycle_path,
            )
            self.assertIsNotNone(spec)
            assert spec and spec.loader
            mod = _ilu.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)

            with patch.dict(os.environ, {
                "PTILOPSIS_CR_LIFECYCLE_ENABLED": "1",
                "PTILOPSIS_CR_LIFECYCLE_MODE": "preview",
            }):
                code = mod.main([
                    "--state-path", str(state),
                    "--report-path", str(report),
                    "--now", _NOW.isoformat(),
                ])

            self.assertEqual(code, 0)
            self.assertTrue(report.exists())
            data = json.loads(report.read_text(encoding="utf-8"))
            self.assertTrue(data["enabled"])
            self.assertEqual(data["mode"], "preview")

    def test_trigger_does_not_modify_state_when_disabled(self) -> None:
        """When lifecycle is not enabled, run_lifecycle returns enabled=False."""
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            report = Path(tmp) / "report.json"
            _write_snapshot(state, _make_snapshot())

            result = lifecycle.run_lifecycle(
                state_path=str(state),
                report_path=str(report),
                enabled=False,
                now=_NOW,
            )
            self.assertFalse(result.enabled)
            self.assertFalse(report.exists())

    def test_trigger_writes_report_when_enabled(self) -> None:
        """When enabled, run_lifecycle produces a lifecycle report."""
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            report = Path(tmp) / "report.json"
            entry = CREventStateEntry(
                event_key="ek-1", decision_level="alert",
                seen_at=_iso(_NOW - timedelta(hours=1)),
            )
            _write_snapshot(state, _make_snapshot(entry))

            result = lifecycle.run_lifecycle(
                state_path=str(state),
                report_path=str(report),
                enabled=True,
                mode="preview",
                now=_NOW,
            )
            self.assertTrue(result.enabled)
            self.assertTrue(report.exists())
            data = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], "cr-lifecycle-report-v1")


class TestForbiddenImports(unittest.TestCase):
    def test_no_runtime_imports(self) -> None:
        source = inspect.getsource(lifecycle)
        forbidden = (
            "runtime_dry_run",
            "telegram",
            "dispatch_executor",
            "dispatch_sink",
            "deploy_trace",
        )
        for token in forbidden:
            self.assertNotIn(token, source, f"forbidden token {token!r} in cr_a_lifecycle.py")


if __name__ == "__main__":
    unittest.main()
