# coding=utf-8
"""
CR-A event lifecycle predicate (J1).

Pure, zero-project-import module that answers one question:
  "Is this event-state entry old enough to evict?"

This module intentionally does NOT import any project modules.  It operates
on duck-typed entry-like objects with ``event_key``, ``decision_level``, and
``seen_at`` attributes.  All time is injected via the ``now`` parameter;
the module never reads the clock.

Design reference: docs/cr-a-event-lifecycle-design.md §5 (J1).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping


# ---------------------------------------------------------------------------
# Phase labels (observability only — not a state machine)
# ---------------------------------------------------------------------------

PHASE_ACTIVE = "active"
PHASE_EVICTABLE = "evictable"
PHASE_MISSING_SEEN_AT = "missing_seen_at"
PHASE_INVALID_SEEN_AT = "invalid_seen_at"
PHASE_UNKNOWN_LEVEL = "unknown_level"
PHASE_FUTURE_SEEN_AT = "future_seen_at"


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------


def _parse_seen_at(raw: object) -> datetime | None:
    """Attempt to parse *raw* as an ISO-8601 datetime.

    Returns a timezone-aware UTC datetime on success, or ``None`` if *raw*
    is not a string, is blank, or cannot be parsed.
    """
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_evictable(
    entry: object,
    *,
    now: datetime,
    ttl_for_level: Mapping[str, int | float],
) -> bool:
    """Return ``True`` when *entry* is old enough to evict.

    Eviction requires **all** of:
    - ``seen_at`` is a parseable, non-future timestamp;
    - ``decision_level`` is present in *ttl_for_level*;
    - ``age_seconds > ttl_for_level[level]`` (strict ``>``).

    If any precondition fails the entry is **kept** (fail-safe).
    The entry is never mutated.
    """
    phase = _classify_phase(entry, now=now, ttl_for_level=ttl_for_level)
    return phase == PHASE_EVICTABLE


def describe_phase(
    entry: object,
    *,
    now: datetime,
    ttl_for_level: Mapping[str, int | float],
) -> str:
    """Return a descriptive phase label for *entry*.

    Observability only — does **not** affect eviction semantics.
    """
    return _classify_phase(entry, now=now, ttl_for_level=ttl_for_level)


# ---------------------------------------------------------------------------
# Internal classification
# ---------------------------------------------------------------------------


def _classify_phase(
    entry: object,
    *,
    now: datetime,
    ttl_for_level: Mapping[str, int | float],
) -> str:
    # Normalise now to timezone-aware UTC for consistent comparison.
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    seen_at_raw = getattr(entry, "seen_at", None)
    if seen_at_raw is None or (isinstance(seen_at_raw, str) and not seen_at_raw.strip()):
        return PHASE_MISSING_SEEN_AT

    seen_at = _parse_seen_at(seen_at_raw)
    if seen_at is None:
        return PHASE_INVALID_SEEN_AT

    if seen_at > now:
        return PHASE_FUTURE_SEEN_AT

    level = getattr(entry, "decision_level", None)
    if level is None or level not in ttl_for_level:
        return PHASE_UNKNOWN_LEVEL

    age_seconds = (now - seen_at).total_seconds()
    ttl_seconds = ttl_for_level[level]

    if age_seconds > ttl_seconds:
        return PHASE_EVICTABLE
    return PHASE_ACTIVE
