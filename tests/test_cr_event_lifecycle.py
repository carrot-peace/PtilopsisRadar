# coding=utf-8
"""Tests for trendradar/cr/event_lifecycle.py (J1).

J1 is a pure predicate module with zero project imports.  These tests verify
eviction logic, phase labels, and fail-safe behaviour against duck-typed
entry stubs — no filesystem, no clock, no environment.
"""

import inspect
import unittest
from datetime import datetime, timezone, timedelta

from trendradar.cr.event_lifecycle import (
    PHASE_ACTIVE,
    PHASE_EVICTABLE,
    PHASE_FUTURE_SEEN_AT,
    PHASE_INVALID_SEEN_AT,
    PHASE_MISSING_SEEN_AT,
    PHASE_UNKNOWN_LEVEL,
    describe_phase,
    is_evictable,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Entry:
    """Minimal duck-typed entry stub."""

    def __init__(
        self,
        event_key: str = "ek-1",
        decision_level: str | None = "alert",
        seen_at: str | None = None,
    ):
        self.event_key = event_key
        self.decision_level = decision_level
        self.seen_at = seen_at


_TTL = {"alert": 604800, "urgent": 604800, "watch": 604800, "suppress": 604800}
_NOW = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestIsEvictable(unittest.TestCase):
    def test_old_enough_entry_is_evictable(self) -> None:
        seen = _NOW - timedelta(seconds=604801)
        entry = _Entry(seen_at=_iso(seen), decision_level="alert")
        self.assertTrue(is_evictable(entry, now=_NOW, ttl_for_level=_TTL))

    def test_inside_ttl_is_not_evictable(self) -> None:
        seen = _NOW - timedelta(seconds=604799)
        entry = _Entry(seen_at=_iso(seen), decision_level="alert")
        self.assertFalse(is_evictable(entry, now=_NOW, ttl_for_level=_TTL))

    def test_boundary_exactly_at_ttl_is_not_evictable(self) -> None:
        seen = _NOW - timedelta(seconds=604800)
        entry = _Entry(seen_at=_iso(seen), decision_level="alert")
        self.assertFalse(is_evictable(entry, now=_NOW, ttl_for_level=_TTL))

    def test_missing_seen_at_is_kept(self) -> None:
        entry = _Entry(seen_at=None, decision_level="alert")
        self.assertFalse(is_evictable(entry, now=_NOW, ttl_for_level=_TTL))

    def test_blank_seen_at_is_kept(self) -> None:
        entry = _Entry(seen_at="  ", decision_level="alert")
        self.assertFalse(is_evictable(entry, now=_NOW, ttl_for_level=_TTL))

    def test_invalid_seen_at_is_kept(self) -> None:
        entry = _Entry(seen_at="not-a-date", decision_level="alert")
        self.assertFalse(is_evictable(entry, now=_NOW, ttl_for_level=_TTL))

    def test_missing_level_is_kept(self) -> None:
        seen = _NOW - timedelta(seconds=604801)
        entry = _Entry(seen_at=_iso(seen), decision_level=None)
        self.assertFalse(is_evictable(entry, now=_NOW, ttl_for_level=_TTL))

    def test_unknown_level_is_kept(self) -> None:
        seen = _NOW - timedelta(seconds=604801)
        entry = _Entry(seen_at=_iso(seen), decision_level="bogus")
        self.assertFalse(is_evictable(entry, now=_NOW, ttl_for_level=_TTL))

    def test_future_seen_at_is_kept(self) -> None:
        seen = _NOW + timedelta(hours=1)
        entry = _Entry(seen_at=_iso(seen), decision_level="alert")
        self.assertFalse(is_evictable(entry, now=_NOW, ttl_for_level=_TTL))

    def test_timezone_aware_timestamp(self) -> None:
        seen = _NOW - timedelta(seconds=604801)
        entry = _Entry(seen_at=_iso(seen), decision_level="urgent")
        self.assertTrue(is_evictable(entry, now=_NOW, ttl_for_level=_TTL))

    def test_timezone_naive_timestamp_treated_as_utc(self) -> None:
        naive_now = datetime(2026, 6, 22, 12, 0, 0)
        seen_naive = naive_now - timedelta(seconds=604801)
        entry = _Entry(seen_at=seen_naive.isoformat(), decision_level="alert")
        self.assertTrue(is_evictable(entry, now=naive_now, ttl_for_level=_TTL))

    def test_empty_ttl_map_keeps_entry(self) -> None:
        seen = _NOW - timedelta(seconds=999999)
        entry = _Entry(seen_at=_iso(seen), decision_level="alert")
        self.assertFalse(is_evictable(entry, now=_NOW, ttl_for_level={}))

    def test_different_level_ttl(self) -> None:
        short_ttl = {"alert": 100}
        seen = _NOW - timedelta(seconds=200)
        entry = _Entry(seen_at=_iso(seen), decision_level="alert")
        self.assertTrue(is_evictable(entry, now=_NOW, ttl_for_level=short_ttl))

        entry2 = _Entry(seen_at=_iso(seen), decision_level="urgent")
        self.assertFalse(is_evictable(entry2, now=_NOW, ttl_for_level=short_ttl))


class TestDescribePhase(unittest.TestCase):
    def test_active(self) -> None:
        seen = _NOW - timedelta(seconds=100)
        entry = _Entry(seen_at=_iso(seen), decision_level="alert")
        self.assertEqual(describe_phase(entry, now=_NOW, ttl_for_level=_TTL), PHASE_ACTIVE)

    def test_evictable(self) -> None:
        seen = _NOW - timedelta(seconds=604801)
        entry = _Entry(seen_at=_iso(seen), decision_level="alert")
        self.assertEqual(describe_phase(entry, now=_NOW, ttl_for_level=_TTL), PHASE_EVICTABLE)

    def test_missing_seen_at(self) -> None:
        entry = _Entry(seen_at=None)
        self.assertEqual(describe_phase(entry, now=_NOW, ttl_for_level=_TTL), PHASE_MISSING_SEEN_AT)

    def test_blank_seen_at(self) -> None:
        entry = _Entry(seen_at="  ")
        self.assertEqual(describe_phase(entry, now=_NOW, ttl_for_level=_TTL), PHASE_MISSING_SEEN_AT)

    def test_invalid_seen_at(self) -> None:
        entry = _Entry(seen_at="nope")
        self.assertEqual(describe_phase(entry, now=_NOW, ttl_for_level=_TTL), PHASE_INVALID_SEEN_AT)

    def test_unknown_level(self) -> None:
        seen = _NOW - timedelta(seconds=604801)
        entry = _Entry(seen_at=_iso(seen), decision_level="bogus")
        self.assertEqual(describe_phase(entry, now=_NOW, ttl_for_level=_TTL), PHASE_UNKNOWN_LEVEL)

    def test_future_seen_at(self) -> None:
        seen = _NOW + timedelta(hours=1)
        entry = _Entry(seen_at=_iso(seen), decision_level="alert")
        self.assertEqual(describe_phase(entry, now=_NOW, ttl_for_level=_TTL), PHASE_FUTURE_SEEN_AT)


class TestForbiddenImports(unittest.TestCase):
    def test_no_project_imports(self) -> None:
        import trendradar.cr.event_lifecycle as mod

        source = inspect.getsource(mod)
        forbidden = (
            "from trendradar",
            "import trendradar",
            "cooldown_policy",
            "cooldown_enforce",
            "state_store",
            "runtime_dry_run",
            "telegram",
            "dispatch_",
            "os.environ",
            "environ.get",
        )
        for token in forbidden:
            self.assertNotIn(token, source, f"forbidden token {token!r} found in event_lifecycle.py")

    def test_does_not_read_clock(self) -> None:
        import trendradar.cr.event_lifecycle as mod

        source = inspect.getsource(mod)
        self.assertNotIn("datetime.now", source)
        self.assertNotIn("time.time", source)


if __name__ == "__main__":
    unittest.main()
