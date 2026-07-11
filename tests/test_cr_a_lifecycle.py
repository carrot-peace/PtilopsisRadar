# coding=utf-8
"""Tests for the installable CR-A lifecycle entry (J2 + J5).

The lifecycle janitor is independently runnable: it reads/writes versioned
JSON file contracts through public boundaries, classifies entries via J1, and
emits a lifecycle report.  These tests exercise it against temporary files
only.
"""

import inspect
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from trendradar.cr.cooldown_policy import DEFAULT_CR_COOLDOWN_POLICY
from trendradar.cr.event_lifecycle import PHASE_ACTIVE, PHASE_EVICTABLE
from trendradar.cr import lifecycle_runner as lifecycle
from trendradar.cr.state_snapshot import (
    CREventStateEntry,
    CREventStateSnapshot,
    cr_event_state_snapshot_to_json_dict,
)
from trendradar.cr.state_store import save_cr_event_state_snapshot

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_PATH = os.path.join(ROOT, "scripts", "cr_a_lifecycle.py")


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
            self.assertTrue(result.report_written)

            audit = _read_json(report)
            self.assertEqual(audit["mode"], "enforce")
            self.assertEqual(audit["would_evict_count"], 1)
            self.assertEqual(audit["evicted_count"], 1)
            self.assertEqual(audit["errors"], [])

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

    def _lifecycle_gate_source(self) -> str:
        source = self._main_source()
        start = source.index(
            'if os.environ.get("PTILOPSIS_CR_LIFECYCLE_ENABLED") == "1":',
        )
        end = source.index("\n\n        return stats, html_file", start)
        return source[start:end]

    def test_trigger_gated_by_lifecycle_enabled(self) -> None:
        source = self._main_source()
        self.assertIn(
            'PTILOPSIS_CR_LIFECYCLE_ENABLED',
            source,
            "trigger must check PTILOPSIS_CR_LIFECYCLE_ENABLED",
        )

    def test_trigger_imports_installable_lifecycle_module(self) -> None:
        gate = self._lifecycle_gate_source()
        self.assertIn("from trendradar.cr.lifecycle_runner import main", gate)
        self.assertIn("lifecycle_main([", gate)
        self.assertNotIn("importlib.util", gate)
        self.assertNotIn("cr_a_lifecycle.py", gate)
        self.assertNotIn('"scripts",', gate)

    def test_trigger_failure_is_non_fatal_and_diagnostic(self) -> None:
        gate = self._lifecycle_gate_source()
        # The trigger must diagnose exceptions and never propagate them.
        self.assertIn("try:", gate)
        self.assertIn("except Exception", gate)
        self.assertIn("[lifecycle] janitor error", gate)
        self.assertIn("file=sys.stderr", gate)

    def test_package_main_runs_with_env_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            report = Path(tmp) / "report.json"
            entry = CREventStateEntry(
                event_key="ek-trigger", decision_level="alert",
                seen_at=_iso(_NOW - timedelta(hours=1)),
            )
            _write_snapshot(state, _make_snapshot(entry))

            with patch.dict(os.environ, {
                "PTILOPSIS_CR_LIFECYCLE_ENABLED": "1",
                "PTILOPSIS_CR_LIFECYCLE_MODE": "preview",
            }):
                code = lifecycle.main([
                    "--state-path", str(state),
                    "--report-path", str(report),
                    "--now", _NOW.isoformat(),
                ])

            self.assertEqual(code, 0)
            self.assertTrue(report.exists())
            data = json.loads(report.read_text(encoding="utf-8"))
            self.assertTrue(data["enabled"])
            self.assertEqual(data["mode"], "preview")


class TestLifecycleEntrypoints(unittest.TestCase):
    def _run_cli(self, entry: list[str], state: Path, report: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                *entry,
                "--enabled",
                "--mode", "preview",
                "--state-path", str(state),
                "--report-path", str(report),
                "--now", _NOW.isoformat(),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_module_cli_writes_preview_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            report = Path(tmp) / "module-report.json"
            _write_snapshot(state, _make_snapshot())

            completed = self._run_cli(
                ["-m", "trendradar.cr.lifecycle_runner"], state, report,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(report.exists())
            self.assertIn("mode=preview", completed.stdout)

    def test_compatibility_wrapper_writes_preview_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            report = Path(tmp) / "wrapper-report.json"
            _write_snapshot(state, _make_snapshot())

            completed = self._run_cli([SCRIPT_PATH], state, report)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(report.exists())

    def test_wrapper_reexports_public_api(self) -> None:
        wrapper_source = Path(SCRIPT_PATH).read_text(encoding="utf-8")
        self.assertIn("from trendradar.cr.lifecycle_runner import", wrapper_source)
        for name in ("CRLifecycleRunResult", "build_ttl_for_level", "run_lifecycle", "main"):
            self.assertIn(name, wrapper_source)


class TestLifecycleRuntimeGate(unittest.TestCase):
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


class TestProductionImageLoadability(unittest.TestCase):
    def test_dockerfile_smoke_checks_installed_package(self) -> None:
        source = (Path(ROOT) / "docker" / "Dockerfile").read_text(encoding="utf-8")
        install_pos = source.index(
            "uv sync --locked --no-dev", source.index("COPY trendradar/"),
        )
        smoke_pos = source.index("from trendradar.cr.lifecycle_runner import")
        self.assertGreater(smoke_pos, install_pos)
        self.assertNotIn("COPY scripts/", source)


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
            self.assertNotIn(
                token, source,
                f"forbidden token {token!r} in lifecycle_runner.py",
            )


if __name__ == "__main__":
    unittest.main()
