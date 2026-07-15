# coding=utf-8
"""Schedule-aware deduplication for live DR delivery."""

from __future__ import annotations

from typing import Any


DR_DISPATCH_SCHEDULE_ACTION = "dr_dispatch"


def should_run_scheduled_live_dispatch(
    *,
    schedule: Any,
    scheduler: Any,
    date_str: str,
    has_analysis_result: bool,
) -> bool:
    """Return whether this run may send the live daily brief.

    A timeline period configured with ``once.analyze`` may execute the crawler
    more than once.  A later run where analysis was already skipped must not
    send a no-AI replacement, and an accepted fallback must not be sent again
    on every failed-analysis retry.
    """
    if not (
        schedule is not None
        and bool(getattr(schedule, "once_analyze", False))
        and getattr(schedule, "period_key", None)
    ):
        return True
    if not has_analysis_result:
        return False
    return not scheduler.already_executed(
        schedule.period_key,
        DR_DISPATCH_SCHEDULE_ACTION,
        date_str,
    )


def record_scheduled_live_dispatch(
    *, schedule: Any, scheduler: Any, date_str: str
) -> None:
    """Record one accepted live delivery for the active once-only period."""
    if not (
        schedule is not None
        and bool(getattr(schedule, "once_analyze", False))
        and getattr(schedule, "period_key", None)
    ):
        return
    scheduler.record_execution(
        schedule.period_key,
        DR_DISPATCH_SCHEDULE_ACTION,
        date_str,
    )
