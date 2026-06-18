# coding=utf-8
"""CR-A quiet-hours evaluation.

Pure helpers for explicit quiet-hours runtime policy.  This module reads only
the environment mapping supplied by its caller and performs no delivery,
filesystem writes, state mutation, or scheduling.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_CR_TIMEZONE = "Asia/Shanghai"
DEFAULT_QUIET_HOURS_START = "23:00"
DEFAULT_QUIET_HOURS_END = "08:00"


@dataclass(frozen=True)
class CRQuietHoursEvaluation:
    enabled: bool
    timezone: str | None
    local_time: datetime | None
    start: str | None
    end: str | None
    in_quiet_hours: bool
    allow_urgent_bypass: bool
    deferred_until: datetime | None
    decision: str
    reason: str | None = None
    config_error: str | None = None
    window_enabled: bool = True


_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _parse_hhmm(raw: str, field_name: str) -> time:
    value = raw.strip()
    match = _HHMM_RE.match(value)
    if match is None:
        raise ValueError(f"{field_name} must be HH:MM")
    return time(hour=int(match.group(1)), minute=int(match.group(2)))


def _safe_config_error(exc: BaseException) -> str:
    message = str(exc).strip() or type(exc).__name__
    if len(message) > 96:
        message = message[:93] + "..."
    return message


def _is_in_window(local_time: time, start: time, end: time) -> bool:
    if start == end:
        return False
    if start < end:
        return start <= local_time < end
    return local_time >= start or local_time < end


def _next_window_end(local_dt: datetime, start: time, end: time) -> datetime | None:
    if start == end:
        return None
    end_dt = local_dt.replace(
        hour=end.hour, minute=end.minute, second=0, microsecond=0
    )
    if start < end:
        if local_dt.time() < end:
            return end_dt
        return None
    if local_dt.time() >= start:
        return end_dt + timedelta(days=1)
    if local_dt.time() < end:
        return end_dt
    return None


def evaluate_cr_quiet_hours(
    env: Mapping[str, str] | None,
    *,
    now: datetime | None = None,
) -> CRQuietHoursEvaluation:
    """Evaluate quiet-hours policy from an explicit environment mapping."""
    env = env or {}
    enabled = env.get("PTILOPSIS_CR_QUIET_HOURS_ENABLED") == "1"
    if not enabled:
        return CRQuietHoursEvaluation(
            enabled=False,
            timezone=None,
            local_time=None,
            start=None,
            end=None,
            in_quiet_hours=False,
            allow_urgent_bypass=False,
            deferred_until=None,
            decision="not_evaluated",
            reason="quiet_hours_disabled",
            window_enabled=False,
        )

    tz_name = env.get("PTILOPSIS_CR_TIMEZONE", DEFAULT_CR_TIMEZONE).strip()
    start_raw = env.get(
        "PTILOPSIS_CR_QUIET_HOURS_START", DEFAULT_QUIET_HOURS_START
    ).strip()
    end_raw = env.get(
        "PTILOPSIS_CR_QUIET_HOURS_END", DEFAULT_QUIET_HOURS_END
    ).strip()
    allow_urgent = env.get("PTILOPSIS_CR_QUIET_HOURS_ALLOW_URGENT") == "1"

    try:
        tz = ZoneInfo(tz_name)
        start = _parse_hhmm(
            start_raw, "PTILOPSIS_CR_QUIET_HOURS_START"
        )
        end = _parse_hhmm(end_raw, "PTILOPSIS_CR_QUIET_HOURS_END")
    except (ZoneInfoNotFoundError, ValueError) as exc:
        return CRQuietHoursEvaluation(
            enabled=True,
            timezone=tz_name,
            local_time=None,
            start=start_raw,
            end=end_raw,
            in_quiet_hours=False,
            allow_urgent_bypass=allow_urgent,
            deferred_until=None,
            decision="quiet_hours_config_error",
            reason="quiet_hours_config_error",
            config_error=_safe_config_error(exc),
            window_enabled=False,
        )

    effective_now = now if now is not None else datetime.now(timezone.utc)
    if effective_now.tzinfo is None:
        effective_now = effective_now.replace(tzinfo=timezone.utc)
    local_dt = effective_now.astimezone(tz)

    if start == end:
        return CRQuietHoursEvaluation(
            enabled=True,
            timezone=tz_name,
            local_time=local_dt,
            start=start_raw,
            end=end_raw,
            in_quiet_hours=False,
            allow_urgent_bypass=allow_urgent,
            deferred_until=None,
            decision="outside_quiet_hours",
            reason="quiet_hours_window_disabled",
            window_enabled=False,
        )

    in_quiet = _is_in_window(local_dt.time(), start, end)
    deferred_until = _next_window_end(local_dt, start, end) if in_quiet else None
    return CRQuietHoursEvaluation(
        enabled=True,
        timezone=tz_name,
        local_time=local_dt,
        start=start_raw,
        end=end_raw,
        in_quiet_hours=in_quiet,
        allow_urgent_bypass=allow_urgent,
        deferred_until=deferred_until,
        decision="in_quiet_hours" if in_quiet else "outside_quiet_hours",
        reason="quiet_hours_active" if in_quiet else "outside_quiet_hours",
        window_enabled=True,
    )


def quiet_hours_evaluation_to_plan_dict(
    evaluation: CRQuietHoursEvaluation,
    *,
    decision: str | None = None,
    reason: str | None = None,
    bypass_applied: bool = False,
    deferred_count: int = 0,
    entries: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Serialize quiet-hours evaluation for dispatch_plan.json."""
    if not evaluation.enabled:
        return {"enabled": False, "decision": "not_evaluated"}

    if evaluation.decision == "quiet_hours_config_error":
        return {
            "enabled": True,
            "decision": "quiet_hours_config_error",
            "config_error": evaluation.config_error,
        }

    result: dict[str, object] = {
        "enabled": True,
        "timezone": evaluation.timezone,
        "local_time": (
            evaluation.local_time.isoformat()
            if evaluation.local_time is not None
            else None
        ),
        "start": evaluation.start,
        "end": evaluation.end,
        "in_quiet_hours": evaluation.in_quiet_hours,
        "allow_urgent_bypass": evaluation.allow_urgent_bypass,
        "bypass_applied": bypass_applied,
        "deferred_until": (
            evaluation.deferred_until.isoformat()
            if evaluation.deferred_until is not None
            else None
        ),
        "decision": decision or evaluation.decision,
        "reason": reason or evaluation.reason,
        "deferred_count": deferred_count,
        "entries": entries or [],
    }
    if not evaluation.window_enabled:
        result["window_enabled"] = False
    return result
