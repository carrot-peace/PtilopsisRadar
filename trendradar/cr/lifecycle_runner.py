# coding=utf-8
"""Installable CR-A lifecycle janitor (J2).

Reads the CR event-state snapshot, classifies each entry via the J1
predicate, and either previews (report-only) or enforces (prunes the
snapshot and saves).

The package module is the lifecycle composition root used by both the runtime
and the compatibility script.  It talks only to versioned file contracts
through public boundaries and is runnable with
``python -m trendradar.cr.lifecycle_runner``.

Environment variables:

    PTILOPSIS_CR_LIFECYCLE_ENABLED  = 1  to enable (default: off)
    PTILOPSIS_CR_LIFECYCLE_MODE     = preview | enforce (default: preview)
    PTILOPSIS_CR_LIFECYCLE_TTL_FLOOR_DAYS = positive number (default: 7)

Design reference: docs/cr-a-event-lifecycle-design.md §5 (J2 + J5).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Project imports — public boundaries only
# ---------------------------------------------------------------------------
from trendradar.cr.cooldown_policy import DEFAULT_CR_COOLDOWN_POLICY
from trendradar.cr.event_lifecycle import (
    PHASE_EVICTABLE,
    describe_phase,
    is_evictable,
)
from trendradar.cr.state_snapshot import (
    CREventStateEntry,
    CREventStateSnapshot,
)
from trendradar.cr.state_store import (
    load_cr_event_state_snapshot,
    save_cr_event_state_snapshot,
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_STATE_PATH = "output/cr/state/cr_dispatch_state.json"
DEFAULT_REPORT_PATH = "output/cr/latest/lifecycle_report.json"

REPORT_SCHEMA_VERSION = "cr-lifecycle-report-v1"

_DEFAULT_TTL_FLOOR_DAYS = 7
_DEFAULT_COOLDOWN_MINUTES = DEFAULT_CR_COOLDOWN_POLICY.same_level_cooldown_minutes

# Map every known decision level to its cooldown seconds.
_KNOWN_LEVELS = ("alert", "urgent", "watch", "suppress")


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CRLifecycleRunResult:
    """Result of a single lifecycle janitor run."""

    enabled: bool
    mode: str
    state_path: str
    report_path: str
    input_count: int
    kept_count: int
    would_evict_count: int
    evicted_count: int
    phase_counts: dict[str, int]
    errors: list[str]
    state_loaded: bool
    state_error: str | None
    state_saved: bool
    report_written: bool


# ---------------------------------------------------------------------------
# TTL construction
# ---------------------------------------------------------------------------


def build_ttl_for_level(ttl_floor_seconds: int | float) -> dict[str, int]:
    """Build the ``level → ttl_seconds`` map.

    ``ttl = max(cooldown_seconds, ttl_floor_seconds)`` for every level.
    This is the G5 guard: eviction can never outpace cooldown.
    """
    cooldown_seconds = _DEFAULT_COOLDOWN_MINUTES * 60
    effective = max(cooldown_seconds, int(ttl_floor_seconds))
    return {level: effective for level in _KNOWN_LEVELS}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _build_report(
    *,
    enabled: bool,
    mode: str,
    state_path: str,
    generated_at: str,
    ttl_floor_seconds: int,
    ttl_for_level: dict[str, int],
    input_count: int,
    kept_count: int,
    would_evict_count: int,
    evicted_count: int,
    phase_counts: dict[str, int],
    would_evict: list[dict[str, object]],
    errors: list[str],
) -> dict[str, object]:
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "enabled": enabled,
        "mode": mode,
        "state_path": state_path,
        "generated_at": generated_at,
        "ttl_floor_seconds": ttl_floor_seconds,
        "ttl_for_level": ttl_for_level,
        "input_count": input_count,
        "kept_count": kept_count,
        "would_evict_count": would_evict_count,
        "evicted_count": evicted_count,
        "phase_counts": phase_counts,
        "would_evict": would_evict,
        "errors": errors,
    }


def _write_report(report: dict[str, object], path: str) -> bool:
    """Write *report* as JSON to *path*.  Returns True on success."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        return True
    except (OSError, ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def run_lifecycle(
    *,
    state_path: str = DEFAULT_STATE_PATH,
    report_path: str = DEFAULT_REPORT_PATH,
    enabled: bool = False,
    mode: str = "preview",
    ttl_floor_days: float = _DEFAULT_TTL_FLOOR_DAYS,
    now: datetime | None = None,
) -> CRLifecycleRunResult:
    """Run the lifecycle janitor.  Returns a :class:`CRLifecycleRunResult`.

    Never raises — errors are captured in the result.
    """
    errors: list[str] = []

    if not enabled:
        return CRLifecycleRunResult(
            enabled=False,
            mode=mode,
            state_path=state_path,
            report_path=report_path,
            input_count=0,
            kept_count=0,
            would_evict_count=0,
            evicted_count=0,
            phase_counts={},
            errors=[],
            state_loaded=False,
            state_error=None,
            state_saved=False,
            report_written=False,
        )

    if mode not in ("preview", "enforce"):
        errors.append(f"invalid mode: {mode!r}")
        mode = "preview"

    if ttl_floor_days <= 0:
        errors.append(f"invalid ttl_floor_days: {ttl_floor_days}")
        ttl_floor_days = _DEFAULT_TTL_FLOOR_DAYS

    ttl_floor_seconds = int(ttl_floor_days * 86400)
    ttl_for_level = build_ttl_for_level(ttl_floor_seconds)

    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    generated_at = now.isoformat()

    # Load state
    load_result = load_cr_event_state_snapshot(state_path)
    if load_result.error is not None:
        errors.append(f"state load error: {load_result.error}")
        report = _build_report(
            enabled=True, mode=mode, state_path=state_path,
            generated_at=generated_at, ttl_floor_seconds=ttl_floor_seconds,
            ttl_for_level=ttl_for_level, input_count=0, kept_count=0,
            would_evict_count=0, evicted_count=0, phase_counts={},
            would_evict=[], errors=errors,
        )
        report_written = _write_report(report, report_path)
        return CRLifecycleRunResult(
            enabled=True, mode=mode, state_path=state_path,
            report_path=report_path, input_count=0, kept_count=0,
            would_evict_count=0, evicted_count=0, phase_counts={},
            errors=errors, state_loaded=load_result.loaded,
            state_error=load_result.error, state_saved=False,
            report_written=report_written,
        )

    snapshot = load_result.snapshot
    entries = snapshot.entries
    input_count = len(entries)

    # Classify
    kept: list[CREventStateEntry] = []
    would_evict_entries: list[CREventStateEntry] = []
    phase_counts: dict[str, int] = {}
    would_evict_details: list[dict[str, object]] = []

    for entry in entries:
        phase = describe_phase(entry, now=now, ttl_for_level=ttl_for_level)
        phase_counts[phase] = phase_counts.get(phase, 0) + 1

        if is_evictable(entry, now=now, ttl_for_level=ttl_for_level):
            would_evict_entries.append(entry)
            age_seconds = 0.0
            try:
                seen_dt = datetime.fromisoformat(entry.seen_at)
                if seen_dt.tzinfo is None:
                    seen_dt = seen_dt.replace(tzinfo=timezone.utc)
                age_seconds = (now - seen_dt).total_seconds()
            except (ValueError, TypeError, AttributeError):
                pass
            would_evict_details.append({
                "event_key": entry.event_key,
                "decision_level": entry.decision_level,
                "seen_at": entry.seen_at,
                "age_seconds": int(age_seconds),
                "ttl_seconds": ttl_for_level.get(entry.decision_level, 0),
            })
        else:
            kept.append(entry)

    kept_count = len(kept)
    would_evict_count = len(would_evict_entries)
    evicted_count = 0
    state_saved = False

    # Enforce: write pruned snapshot
    if mode == "enforce" and would_evict_count > 0:
        pruned = CREventStateSnapshot(
            schema_version=snapshot.schema_version,
            entries=tuple(kept),
        )
        save_result = save_cr_event_state_snapshot(pruned, state_path)
        if not save_result.saved:
            errors.append(f"state save error: {save_result.error}")
        else:
            state_saved = True
            evicted_count = would_evict_count

    # Write report
    report = _build_report(
        enabled=True, mode=mode, state_path=state_path,
        generated_at=generated_at, ttl_floor_seconds=ttl_floor_seconds,
        ttl_for_level=ttl_for_level, input_count=input_count,
        kept_count=kept_count, would_evict_count=would_evict_count,
        evicted_count=evicted_count, phase_counts=phase_counts,
        would_evict=would_evict_details, errors=errors,
    )
    report_written = _write_report(report, report_path)

    return CRLifecycleRunResult(
        enabled=True, mode=mode, state_path=state_path,
        report_path=report_path, input_count=input_count,
        kept_count=kept_count, would_evict_count=would_evict_count,
        evicted_count=evicted_count, phase_counts=phase_counts,
        errors=errors, state_loaded=True, state_error=None,
        state_saved=state_saved, report_written=report_written,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_now(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CR-A lifecycle janitor (J2)")
    parser.add_argument("--state-path", default=DEFAULT_STATE_PATH)
    parser.add_argument("--report-path", default=DEFAULT_REPORT_PATH)
    parser.add_argument("--mode", choices=("preview", "enforce"), default=None)
    parser.add_argument("--enabled", action="store_true", default=False)
    parser.add_argument("--ttl-floor-days", type=float, default=None)
    parser.add_argument("--now", default=None, help="ISO timestamp override (testing)")
    args = parser.parse_args(argv)

    # Env config with CLI override
    env_enabled = os.environ.get("PTILOPSIS_CR_LIFECYCLE_ENABLED") == "1"
    enabled = args.enabled or env_enabled

    mode = args.mode or os.environ.get("PTILOPSIS_CR_LIFECYCLE_MODE", "preview")
    if mode not in ("preview", "enforce"):
        print(f"[lifecycle] invalid mode {mode!r}, defaulting to preview", file=sys.stderr)
        mode = "preview"

    ttl_floor_days = args.ttl_floor_days
    if ttl_floor_days is None:
        env_val = os.environ.get("PTILOPSIS_CR_LIFECYCLE_TTL_FLOOR_DAYS")
        if env_val is not None:
            try:
                ttl_floor_days = float(env_val)
            except (ValueError, TypeError):
                print(f"[lifecycle] invalid TTL_FLOOR_DAYS {env_val!r}, using default", file=sys.stderr)
                ttl_floor_days = _DEFAULT_TTL_FLOOR_DAYS
        else:
            ttl_floor_days = _DEFAULT_TTL_FLOOR_DAYS

    now = _parse_now(args.now)

    result = run_lifecycle(
        state_path=args.state_path,
        report_path=args.report_path,
        enabled=enabled,
        mode=mode,
        ttl_floor_days=ttl_floor_days,
        now=now,
    )

    if not result.enabled:
        print("[lifecycle] disabled — no-op")
        return 0

    print(f"[lifecycle] mode={result.mode} state={result.state_path}")
    print(f"[lifecycle] input={result.input_count} kept={result.kept_count} "
          f"would_evict={result.would_evict_count} evicted={result.evicted_count}")
    if result.errors:
        for err in result.errors:
            print(f"[lifecycle] error: {err}", file=sys.stderr)
    if result.report_written:
        print(f"[lifecycle] report: {result.report_path}")
    if result.state_saved:
        print(f"[lifecycle] state saved: {result.state_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
