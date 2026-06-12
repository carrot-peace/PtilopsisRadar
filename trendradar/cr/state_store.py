# coding=utf-8
"""
Explicit filesystem store boundary for CR-A event state snapshots (PR10c).

This module performs filesystem I/O only for a caller-provided path. It does
not read environment variables, choose default paths, import runtime/dispatch
or Telegram code, use network access, or make suppression decisions.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from trendradar.cr.state_snapshot import (
    CREventStateSnapshot,
    cr_event_state_snapshot_from_json_dict,
    cr_event_state_snapshot_to_json_dict,
    empty_cr_event_state_snapshot,
)


@dataclass(frozen=True)
class CREventStateLoadResult:
    snapshot: CREventStateSnapshot
    loaded: bool
    error: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class CREventStateSaveResult:
    saved: bool
    error: str | None = None
    path: str | None = None


def _safe_error(prefix: str, exc: BaseException) -> str:
    return f"{prefix}: {type(exc).__name__}"


def _safe_validation_error(exc: ValueError) -> str:
    message = str(exc).strip()
    if not message:
        message = type(exc).__name__
    if len(message) > 96:
        message = message[:93] + "..."
    return f"invalid event state snapshot: {message}"


def load_cr_event_state_snapshot(path: str | Path) -> CREventStateLoadResult:
    state_path = Path(path)
    result_path = str(state_path)
    empty = empty_cr_event_state_snapshot()

    if not state_path.exists():
        return CREventStateLoadResult(
            snapshot=empty,
            loaded=False,
            error=None,
            path=result_path,
        )

    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("event state snapshot root must be an object")
        snapshot = cr_event_state_snapshot_from_json_dict(raw)
    except json.JSONDecodeError as exc:
        return CREventStateLoadResult(
            snapshot=empty,
            loaded=False,
            error=_safe_error("malformed event state JSON", exc),
            path=result_path,
        )
    except ValueError as exc:
        return CREventStateLoadResult(
            snapshot=empty,
            loaded=False,
            error=_safe_validation_error(exc),
            path=result_path,
        )
    except OSError as exc:
        return CREventStateLoadResult(
            snapshot=empty,
            loaded=False,
            error=_safe_error("unable to read event state snapshot", exc),
            path=result_path,
        )

    return CREventStateLoadResult(
        snapshot=snapshot,
        loaded=True,
        error=None,
        path=result_path,
    )


def save_cr_event_state_snapshot(
    snapshot: CREventStateSnapshot,
    path: str | Path,
) -> CREventStateSaveResult:
    state_path = Path(path)
    result_path = str(state_path)
    tmp_name: str | None = None

    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        data = cr_event_state_snapshot_to_json_dict(snapshot)
        text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
        text += "\n"

        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{state_path.name}.",
            suffix=".tmp",
            dir=str(state_path.parent),
            text=True,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_name, state_path)
        tmp_name = None
    except (OSError, ValueError, TypeError) as exc:
        if tmp_name is not None:
            try:
                Path(tmp_name).unlink(missing_ok=True)
            except OSError:
                pass
        return CREventStateSaveResult(
            saved=False,
            error=_safe_error("unable to save event state snapshot", exc),
            path=result_path,
        )

    return CREventStateSaveResult(
        saved=True,
        error=None,
        path=result_path,
    )
