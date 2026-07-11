# coding=utf-8
"""
CR-A event state snapshot boundary (PR10c).

Pure helpers for representing, serializing, and merging prior event state.
This module intentionally does not perform filesystem I/O, read environment
variables, import runtime/dispatch/Telegram code, generate timestamps, or make
policy decisions about suppression.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

from trendradar.cr.decision import CRDecisionLevel
from trendradar.cr.event_identity import (
    CR_EVENT_IDENTITY_KEY_VERSION,
    build_cr_event_identity_from_candidate,
)
from trendradar.cr.presentation import CRPresentedCandidate
from trendradar.cr.repeat_preview import (
    CRSeenEventState,
    normalize_cr_decision_level,
)


CR_EVENT_STATE_SCHEMA_VERSION = "cr-event-state-v1"

_CR_DECISION_LEVEL_ORDER: dict[str, int] = {
    "suppress": 0,
    "watch": 1,
    "alert": 2,
    "urgent": 3,
}


@dataclass(frozen=True)
class CREventStateEntry:
    event_key: str
    decision_level: CRDecisionLevel | None = None
    score: float | None = None
    seen_at: str | None = None
    title: str | None = None
    candidate_id: str | None = None
    event_key_version: str | None = None


@dataclass(frozen=True)
class CREventStateSnapshot:
    schema_version: str
    entries: tuple[CREventStateEntry, ...]


def empty_cr_event_state_snapshot() -> CREventStateSnapshot:
    return CREventStateSnapshot(
        schema_version=CR_EVENT_STATE_SCHEMA_VERSION,
        entries=(),
    )


def _require_event_key(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("event state entry requires a non-blank event_key")
    return value.strip()


def _optional_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"event state entry {field_name} must be a string")
    return value


def _optional_score(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("event state entry score must be a number")
    return float(value)


def _entry_from_mapping(data: Mapping[str, object]) -> CREventStateEntry:
    return CREventStateEntry(
        event_key=_require_event_key(data.get("event_key")),
        decision_level=normalize_cr_decision_level(
            _optional_str(data.get("decision_level"), "decision_level")
        ),
        score=_optional_score(data.get("score")),
        seen_at=_optional_str(data.get("seen_at"), "seen_at"),
        title=_optional_str(data.get("title"), "title"),
        candidate_id=_optional_str(data.get("candidate_id"), "candidate_id"),
        event_key_version=_optional_str(
            data.get("event_key_version"),
            "event_key_version",
        ),
    )


def _entry_to_json_dict(entry: CREventStateEntry) -> dict[str, object]:
    event_key = _require_event_key(entry.event_key)
    data: dict[str, object] = {"event_key": event_key}
    if entry.decision_level is not None:
        data["decision_level"] = entry.decision_level
    if entry.score is not None:
        data["score"] = float(entry.score)
    if entry.seen_at is not None:
        data["seen_at"] = entry.seen_at
    if entry.title is not None:
        data["title"] = entry.title
    if entry.candidate_id is not None:
        data["candidate_id"] = entry.candidate_id
    if entry.event_key_version is not None:
        data["event_key_version"] = entry.event_key_version
    return data


def _canonical_entries(
    entries: tuple[CREventStateEntry, ...],
) -> tuple[CREventStateEntry, ...]:
    by_key: dict[str, CREventStateEntry] = {}
    for entry in entries:
        event_key = _require_event_key(entry.event_key)
        by_key[event_key] = CREventStateEntry(
            event_key=event_key,
            decision_level=entry.decision_level,
            score=entry.score,
            seen_at=entry.seen_at,
            title=entry.title,
            candidate_id=entry.candidate_id,
            event_key_version=entry.event_key_version,
        )
    return tuple(by_key[key] for key in sorted(by_key))


def _dedupe_state_update_entries_keep_highest(
    entries: tuple[CREventStateEntry, ...],
) -> tuple[CREventStateEntry, ...]:
    """Dedupe one batch of state updates by event_key.

    For duplicate event keys:
      - keep the entry with the higher decision level;
      - on the same level, keep the later seen_at;
      - on a further tie, keep the later entry.

    This helper is only for updates produced in one runtime execution. It must
    not be applied across the previous snapshot, because a newer successful
    dispatch must be allowed to replace an older, higher decision level.
    """
    by_key: dict[str, CREventStateEntry] = {}

    for entry in entries:
        event_key = _require_event_key(entry.event_key)
        normalized_entry = CREventStateEntry(
            event_key=event_key,
            decision_level=entry.decision_level,
            score=entry.score,
            seen_at=entry.seen_at,
            title=entry.title,
            candidate_id=entry.candidate_id,
            event_key_version=entry.event_key_version,
        )

        existing = by_key.get(event_key)
        if existing is None:
            by_key[event_key] = normalized_entry
            continue

        existing_rank = _CR_DECISION_LEVEL_ORDER.get(
            existing.decision_level or "",
            -1,
        )
        new_rank = _CR_DECISION_LEVEL_ORDER.get(
            normalized_entry.decision_level or "",
            -1,
        )

        if new_rank > existing_rank:
            by_key[event_key] = normalized_entry
            continue

        if new_rank == existing_rank:
            existing_seen_at = _parse_seen_at(existing.seen_at)
            new_seen_at = _parse_seen_at(normalized_entry.seen_at)

            if (
                existing_seen_at is None
                and new_seen_at is None
            ) or (
                new_seen_at is not None
                and (
                    existing_seen_at is None
                    or new_seen_at >= existing_seen_at
                )
            ):
                by_key[event_key] = normalized_entry

    return tuple(by_key[key] for key in sorted(by_key))


def _parse_seen_at(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def cr_event_state_snapshot_to_seen_states(
    snapshot: CREventStateSnapshot,
) -> dict[str, CRSeenEventState]:
    if snapshot.schema_version != CR_EVENT_STATE_SCHEMA_VERSION:
        raise ValueError("event state snapshot schema_version mismatch")

    seen_states: dict[str, CRSeenEventState] = {}
    for entry in _canonical_entries(snapshot.entries):
        seen_states[entry.event_key] = CRSeenEventState(
            event_key=entry.event_key,
            decision_level=entry.decision_level,
            score=entry.score,
            seen_at=entry.seen_at,
            title=entry.title,
            candidate_id=entry.candidate_id,
        )
    return seen_states


def cr_event_state_snapshot_to_json_dict(
    snapshot: CREventStateSnapshot,
) -> dict[str, object]:
    if snapshot.schema_version != CR_EVENT_STATE_SCHEMA_VERSION:
        raise ValueError("event state snapshot schema_version mismatch")
    return {
        "schema_version": CR_EVENT_STATE_SCHEMA_VERSION,
        "entries": [
            _entry_to_json_dict(entry)
            for entry in _canonical_entries(snapshot.entries)
        ],
    }


def cr_event_state_snapshot_from_json_dict(
    data: Mapping[str, object],
) -> CREventStateSnapshot:
    if data.get("schema_version") != CR_EVENT_STATE_SCHEMA_VERSION:
        raise ValueError("event state snapshot schema_version mismatch")

    raw_entries = data.get("entries")
    if raw_entries is None:
        raw_entries = []
    if not isinstance(raw_entries, list):
        raise ValueError("event state snapshot entries must be a list")

    entries: list[CREventStateEntry] = []
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, Mapping):
            raise ValueError("event state snapshot entry must be an object")
        entries.append(_entry_from_mapping(raw_entry))

    return CREventStateSnapshot(
        schema_version=CR_EVENT_STATE_SCHEMA_VERSION,
        entries=_canonical_entries(tuple(entries)),
    )


def merge_cr_event_state_entries(
    previous: CREventStateSnapshot,
    updates: tuple[CREventStateEntry, ...],
) -> CREventStateSnapshot:
    if previous.schema_version != CR_EVENT_STATE_SCHEMA_VERSION:
        raise ValueError("event state snapshot schema_version mismatch")

    deduped_updates = _dedupe_state_update_entries_keep_highest(updates)

    return CREventStateSnapshot(
        schema_version=CR_EVENT_STATE_SCHEMA_VERSION,
        # Keep the existing last-writer-wins behavior between the historical
        # snapshot and this run's resolved updates.
        entries=_canonical_entries(previous.entries + deduped_updates),
    )


def build_cr_event_state_entry_from_presented_candidate(
    pc: CRPresentedCandidate,
    *,
    seen_at: str | None = None,
) -> CREventStateEntry:
    identity = build_cr_event_identity_from_candidate(pc.candidate)
    return CREventStateEntry(
        event_key=identity.event_key,
        decision_level=pc.decision_level,
        score=pc.total_score,
        seen_at=seen_at,
        title=pc.display_title,
        candidate_id=pc.candidate_id,
        event_key_version=CR_EVENT_IDENTITY_KEY_VERSION,
    )


def build_cr_event_state_entries_from_presented_candidates(
    candidates: tuple[CRPresentedCandidate, ...],
    *,
    seen_at: str | None = None,
) -> tuple[CREventStateEntry, ...]:
    return tuple(
        build_cr_event_state_entry_from_presented_candidate(
            pc,
            seen_at=seen_at,
        )
        for pc in candidates
    )
