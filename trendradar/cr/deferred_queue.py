# coding=utf-8
"""CR-A deferred dispatch queue.

Filesystem boundary for quiet-hours deferred CR-A messages.  Queue operations
are deterministic, validate stored JSON before use, and never send messages.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from trendradar.cr.decision import CR_DECISION_LEVEL_ORDER


DEFERRED_QUEUE_SCHEMA_VERSION = "cr-deferred-dispatch-queue-v1"
DEFAULT_DEFERRED_QUEUE_PATH = "output/cr/state/cr_deferred_dispatch_queue.json"
DEFAULT_DEFERRED_TTL_SECONDS = 12 * 60 * 60

#: Only alert and urgent are eligible for deferred dispatch.
_DEFERRED_ALLOWED_LEVELS = frozenset({"alert", "urgent"})


@dataclass(frozen=True)
class CRDeferredDispatchEntry:
    entry_id: str
    event_key: str
    candidate_id: str
    title: str
    level: str
    score: float
    deferred_at: str
    deferred_until: str
    reason: str
    message_text: str
    candidate_payload: dict[str, object]
    last_seen_at: str | None = None


@dataclass(frozen=True)
class CRDeferredDispatchQueue:
    queue_schema_version: str
    entries: tuple[CRDeferredDispatchEntry, ...]


@dataclass(frozen=True)
class CRDeferredQueueLoadResult:
    queue: CRDeferredDispatchQueue
    loaded: bool
    error: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class CRDeferredQueueSaveResult:
    saved: bool
    error: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class CRDeferredQueueUpsertResult:
    """Outcome of attempting to add one candidate to the deferred queue."""

    queue: CRDeferredDispatchQueue
    outcome: str
    reason: str
    event_key: str
    candidate_id: str


def _as_utc(value: datetime) -> datetime:
    """Return a timezone-aware UTC datetime for deterministic comparisons."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_deferred_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return _as_utc(parsed)


def expire_deferred_entries(
    queue: CRDeferredDispatchQueue,
    *,
    now: datetime,
    ttl_seconds: int = DEFAULT_DEFERRED_TTL_SECONDS,
) -> tuple[CRDeferredDispatchQueue, tuple[CRDeferredDispatchEntry, ...]]:
    """Remove entries older than the fixed deferred-delivery TTL.

    The first ``deferred_at`` is intentionally used rather than
    ``last_seen_at``.  Queue refreshes therefore cannot keep an old event
    alive indefinitely.  Entries with an unparsable timestamp are retained so
    a malformed timestamp is handled by the existing queue validation/error
    path rather than silently deleting data.
    """
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")
    cutoff = _as_utc(now) - timedelta(seconds=ttl_seconds)
    kept: list[CRDeferredDispatchEntry] = []
    expired: list[CRDeferredDispatchEntry] = []
    for entry in queue.entries:
        try:
            deferred_at = _parse_deferred_at(entry.deferred_at)
        except (TypeError, ValueError, OverflowError):
            kept.append(entry)
            continue
        if deferred_at <= cutoff:
            expired.append(entry)
        else:
            kept.append(entry)
    return (
        CRDeferredDispatchQueue(
            queue_schema_version=queue.queue_schema_version,
            entries=tuple(kept),
        ),
        tuple(expired),
    )


def empty_deferred_dispatch_queue() -> CRDeferredDispatchQueue:
    return CRDeferredDispatchQueue(
        queue_schema_version=DEFERRED_QUEUE_SCHEMA_VERSION,
        entries=(),
    )


def stable_deferred_entry_id(event_key: str) -> str:
    digest = hashlib.sha256(event_key.encode("utf-8")).hexdigest()[:16]
    return f"cr-deferred:{digest}"


def _safe_error(prefix: str, exc: BaseException) -> str:
    return f"{prefix}: {type(exc).__name__}"


def _safe_validation_error(exc: ValueError) -> str:
    message = str(exc).strip() or type(exc).__name__
    if len(message) > 96:
        message = message[:93] + "..."
    return f"invalid deferred queue: {message}"


def _require_str(data: Mapping[str, object], field_name: str) -> str:
    value = data.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"entry requires non-blank {field_name}")
    return value


def _optional_str(data: Mapping[str, object], field_name: str) -> str | None:
    value = data.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"entry {field_name} must be a string")
    return value


def _require_score(data: Mapping[str, object]) -> float:
    value = data.get("score")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("entry score must be a number")
    return float(value)


def _entry_from_mapping(data: Mapping[str, object]) -> CRDeferredDispatchEntry:
    level = _require_str(data, "level")
    if level not in _DEFERRED_ALLOWED_LEVELS:
        raise ValueError("entry level must be alert or urgent")
    payload = data.get("candidate_payload")
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("entry candidate_payload must be an object")
    return CRDeferredDispatchEntry(
        entry_id=_require_str(data, "entry_id"),
        event_key=_require_str(data, "event_key"),
        candidate_id=_require_str(data, "candidate_id"),
        title=_require_str(data, "title"),
        level=level,
        score=_require_score(data),
        deferred_at=_require_str(data, "deferred_at"),
        deferred_until=_require_str(data, "deferred_until"),
        reason=_require_str(data, "reason"),
        message_text=_require_str(data, "message_text"),
        candidate_payload=dict(payload),
        last_seen_at=_optional_str(data, "last_seen_at"),
    )


def _entry_to_json_dict(entry: CRDeferredDispatchEntry) -> dict[str, object]:
    data: dict[str, object] = {
        "entry_id": entry.entry_id,
        "event_key": entry.event_key,
        "candidate_id": entry.candidate_id,
        "title": entry.title,
        "level": entry.level,
        "score": float(entry.score),
        "deferred_at": entry.deferred_at,
        "deferred_until": entry.deferred_until,
        "reason": entry.reason,
        "message_text": entry.message_text,
        "candidate_payload": dict(entry.candidate_payload),
    }
    if entry.last_seen_at is not None:
        data["last_seen_at"] = entry.last_seen_at
    return data


def _queue_from_mapping(data: Mapping[str, object]) -> CRDeferredDispatchQueue:
    if data.get("queue_schema_version") != DEFERRED_QUEUE_SCHEMA_VERSION:
        raise ValueError("deferred queue schema_version mismatch")
    raw_entries = data.get("entries")
    if raw_entries is None:
        raw_entries = []
    if not isinstance(raw_entries, list):
        raise ValueError("deferred queue entries must be a list")
    entries: list[CRDeferredDispatchEntry] = []
    for raw in raw_entries:
        if not isinstance(raw, Mapping):
            raise ValueError("deferred queue entry must be an object")
        entries.append(_entry_from_mapping(raw))
    return CRDeferredDispatchQueue(
        queue_schema_version=DEFERRED_QUEUE_SCHEMA_VERSION,
        entries=tuple(entries),
    )


def deferred_dispatch_queue_to_json_dict(
    queue: CRDeferredDispatchQueue,
) -> dict[str, object]:
    if queue.queue_schema_version != DEFERRED_QUEUE_SCHEMA_VERSION:
        raise ValueError("deferred queue schema_version mismatch")
    return {
        "queue_schema_version": DEFERRED_QUEUE_SCHEMA_VERSION,
        "entries": [_entry_to_json_dict(entry) for entry in queue.entries],
    }


def load_deferred_dispatch_queue(
    path: str | Path,
) -> CRDeferredQueueLoadResult:
    queue_path = Path(path)
    result_path = str(queue_path)
    empty = empty_deferred_dispatch_queue()
    if not queue_path.exists():
        return CRDeferredQueueLoadResult(
            queue=empty, loaded=False, error=None, path=result_path
        )
    try:
        raw = json.loads(queue_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("deferred queue root must be an object")
        queue = _queue_from_mapping(raw)
    except json.JSONDecodeError as exc:
        return CRDeferredQueueLoadResult(
            queue=empty,
            loaded=False,
            error=_safe_error("malformed deferred queue JSON", exc),
            path=result_path,
        )
    except ValueError as exc:
        return CRDeferredQueueLoadResult(
            queue=empty,
            loaded=False,
            error=_safe_validation_error(exc),
            path=result_path,
        )
    except OSError as exc:
        return CRDeferredQueueLoadResult(
            queue=empty,
            loaded=False,
            error=_safe_error("unable to read deferred queue", exc),
            path=result_path,
        )
    return CRDeferredQueueLoadResult(
        queue=queue, loaded=True, error=None, path=result_path
    )


def save_deferred_dispatch_queue(
    queue: CRDeferredDispatchQueue,
    path: str | Path,
) -> CRDeferredQueueSaveResult:
    queue_path = Path(path)
    result_path = str(queue_path)
    tmp_name: str | None = None
    try:
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(
            deferred_dispatch_queue_to_json_dict(queue),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        text += "\n"
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{queue_path.name}.",
            suffix=".tmp",
            dir=str(queue_path.parent),
            text=True,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_name, queue_path)
        tmp_name = None
    except (OSError, ValueError, TypeError) as exc:
        if tmp_name is not None:
            try:
                Path(tmp_name).unlink(missing_ok=True)
            except OSError:
                pass
        return CRDeferredQueueSaveResult(
            saved=False,
            error=_safe_error("unable to save deferred queue", exc),
            path=result_path,
        )
    return CRDeferredQueueSaveResult(saved=True, error=None, path=result_path)


def _rank(level: str | None) -> int:
    return CR_DECISION_LEVEL_ORDER.get(level or "", -1)


def upsert_deferred_entry(
    queue: CRDeferredDispatchQueue,
    entry: CRDeferredDispatchEntry,
) -> CRDeferredQueueUpsertResult:
    """Insert or refresh one deferred entry while deduping by event key.

    Dispatch-state cooldown eligibility is deliberately resolved before this
    queue boundary. Reapplying a level-only historical-state check here would
    reject same-level candidates even after their cooldown has expired.
    """

    output: list[CRDeferredDispatchEntry] = []
    replaced = False
    outcome_reason = "new_entry"
    for existing in queue.entries:
        if existing.event_key != entry.event_key:
            output.append(existing)
            continue

        replaced = True
        if _rank(entry.level) > _rank(existing.level):
            outcome_reason = "higher_level_refresh"
            output.append(
                CRDeferredDispatchEntry(
                    entry_id=existing.entry_id,
                    event_key=entry.event_key,
                    candidate_id=entry.candidate_id,
                    title=entry.title,
                    level=entry.level,
                    score=entry.score,
                    deferred_at=existing.deferred_at,
                    deferred_until=entry.deferred_until,
                    reason=entry.reason,
                    message_text=entry.message_text,
                    candidate_payload=dict(entry.candidate_payload),
                    last_seen_at=entry.last_seen_at,
                )
            )
        elif _rank(entry.level) == _rank(existing.level):
            outcome_reason = "same_level_refresh"
            output.append(
                CRDeferredDispatchEntry(
                    entry_id=existing.entry_id,
                    event_key=entry.event_key,
                    candidate_id=entry.candidate_id,
                    title=entry.title,
                    level=entry.level,
                    score=entry.score,
                    deferred_at=existing.deferred_at,
                    deferred_until=entry.deferred_until,
                    reason=entry.reason,
                    message_text=entry.message_text,
                    candidate_payload=dict(entry.candidate_payload),
                    last_seen_at=entry.last_seen_at,
                )
            )
        else:
            return CRDeferredQueueUpsertResult(
                queue=queue,
                outcome="skipped",
                reason="existing_higher_level",
                event_key=entry.event_key,
                candidate_id=entry.candidate_id,
            )

    if not replaced:
        output.append(entry)

    updated_queue = CRDeferredDispatchQueue(
        queue_schema_version=DEFERRED_QUEUE_SCHEMA_VERSION, entries=tuple(output)
    )
    return CRDeferredQueueUpsertResult(
        queue=updated_queue,
        outcome="refreshed" if replaced else "inserted",
        reason=outcome_reason,
        event_key=entry.event_key,
        candidate_id=entry.candidate_id,
    )


def remove_deferred_entries(
    queue: CRDeferredDispatchQueue,
    event_keys: set[str],
) -> CRDeferredDispatchQueue:
    return CRDeferredDispatchQueue(
        queue_schema_version=DEFERRED_QUEUE_SCHEMA_VERSION,
        entries=tuple(
            entry for entry in queue.entries if entry.event_key not in event_keys
        ),
    )


def ordered_entries_for_flush(
    queue: CRDeferredDispatchQueue,
) -> tuple[CRDeferredDispatchEntry, ...]:
    return tuple(
        sorted(
            queue.entries,
            key=lambda entry: (
                0 if entry.level == "urgent" else 1,
                entry.deferred_at,
                entry.event_key,
            ),
        )
    )
