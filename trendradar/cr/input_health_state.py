# coding=utf-8
"""Persistent source-health state used to identify ingest recovery runs."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping


CR_INPUT_HEALTH_STATE_SCHEMA_VERSION = "cr-input-health-state-v1"
DEFAULT_CR_INPUT_HEALTH_STATE_PATH = Path(
    "output/meta/cr-input-health-state.json"
)


def _clean_ids(values: Iterable[object] | None) -> tuple[str, ...]:
    return tuple(
        sorted({str(value).strip() for value in (values or ()) if str(value).strip()})
    )


@dataclass(frozen=True)
class CRInputHealthState:
    recorded_at: str | None = None
    hotlist_successful_ids: tuple[str, ...] = ()
    hotlist_failed_ids: tuple[str, ...] = ()
    rss_successful_ids: tuple[str, ...] = ()
    rss_failed_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CRInputHealthStateLoadResult:
    state: CRInputHealthState | None
    loaded: bool
    error: str | None = None


@dataclass(frozen=True)
class CRInputHealthStateSaveResult:
    saved: bool
    error: str | None = None


def _source_mapping(data: Mapping[str, object], key: str) -> Mapping[str, object]:
    if key not in data:
        raise ValueError(f"{key} is required")
    value = data[key]
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be an object")
    return value


def _state_ids(data: Mapping[str, object], key: str) -> tuple[str, ...]:
    if key not in data:
        raise ValueError(f"{key} is required")
    value = data[key]
    if not isinstance(value, list):
        raise ValueError(f"{key} must be an array")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{key} must contain non-empty strings")
    return _clean_ids(value)


def load_cr_input_health_state(
    path: str | Path = DEFAULT_CR_INPUT_HEALTH_STATE_PATH,
) -> CRInputHealthStateLoadResult:
    state_path = Path(path)
    if not state_path.exists():
        return CRInputHealthStateLoadResult(state=None, loaded=False)
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise ValueError("state root must be an object")
        if raw.get("schema_version") != CR_INPUT_HEALTH_STATE_SCHEMA_VERSION:
            raise ValueError("schema_version mismatch")
        recorded_at = raw.get("recorded_at")
        if not isinstance(recorded_at, str) or not recorded_at.strip():
            raise ValueError("recorded_at must be a non-empty string")
        parsed_recorded_at = datetime.fromisoformat(
            recorded_at.replace("Z", "+00:00")
        )
        if parsed_recorded_at.tzinfo is None:
            raise ValueError("recorded_at must include a timezone")
        hotlist = _source_mapping(raw, "hotlist")
        rss = _source_mapping(raw, "rss")
        state = CRInputHealthState(
            recorded_at=recorded_at,
            hotlist_successful_ids=_state_ids(hotlist, "successful_ids"),
            hotlist_failed_ids=_state_ids(hotlist, "failed_ids"),
            rss_successful_ids=_state_ids(rss, "successful_ids"),
            rss_failed_ids=_state_ids(rss, "failed_ids"),
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return CRInputHealthStateLoadResult(
            state=None,
            loaded=False,
            error=f"invalid input health state: {type(exc).__name__}",
        )
    return CRInputHealthStateLoadResult(state=state, loaded=True)


def recovered_source_ids(
    previous_failed_ids: Iterable[object],
    current_successful_ids: Iterable[object],
) -> tuple[str, ...]:
    return tuple(
        sorted(set(_clean_ids(previous_failed_ids)) & set(_clean_ids(current_successful_ids)))
    )


def save_cr_input_health_state(
    state: CRInputHealthState,
    path: str | Path = DEFAULT_CR_INPUT_HEALTH_STATE_PATH,
) -> CRInputHealthStateSaveResult:
    state_path = Path(path)
    temporary_name: str | None = None
    payload = {
        "schema_version": CR_INPUT_HEALTH_STATE_SCHEMA_VERSION,
        "recorded_at": state.recorded_at,
        "hotlist": {
            "successful_ids": list(_clean_ids(state.hotlist_successful_ids)),
            "failed_ids": list(_clean_ids(state.hotlist_failed_ids)),
        },
        "rss": {
            "successful_ids": list(_clean_ids(state.rss_successful_ids)),
            "failed_ids": list(_clean_ids(state.rss_failed_ids)),
        },
    }
    try:
        if not isinstance(state.recorded_at, str) or not state.recorded_at.strip():
            raise ValueError("recorded_at must be a non-empty string")
        recorded_at = datetime.fromisoformat(
            state.recorded_at.replace("Z", "+00:00")
        )
        if recorded_at.tzinfo is None:
            raise ValueError("recorded_at must include a timezone")
        state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{state_path.name}.",
            suffix=".tmp",
            dir=state_path.parent,
            text=True,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary_name, state_path)
        temporary_name = None
    except (OSError, TypeError, ValueError) as exc:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
        return CRInputHealthStateSaveResult(
            saved=False,
            error=f"unable to save input health state: {type(exc).__name__}",
        )
    return CRInputHealthStateSaveResult(saved=True)


def quarantine_invalid_cr_input_health_state(
    path: str | Path,
    *,
    suffix: str,
) -> bool:
    state_path = Path(path)
    if not state_path.exists():
        return True
    try:
        if state_path.is_dir():
            return False
        destination = state_path.with_name(
            f"{state_path.name}.corrupt.{suffix}"
        )
        state_path.replace(destination)
    except (OSError, ValueError):
        return False
    return True
