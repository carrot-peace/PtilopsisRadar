# coding=utf-8
"""CR input-health evaluation and fresh-item identity helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping

DEFAULT_STALE_AFTER_MINUTES = 120.0
DEFAULT_DEGRADED_SUCCESS_RATIO = 0.67

STATUS_HEALTHY = "healthy"
STATUS_DEGRADED = "degraded"
STATUS_FAIL_CLOSED = "fail_closed"

REASON_HOTLIST_ALL_FAILED = "hotlist_all_failed"
REASON_HOTLIST_SUCCESS_RATIO_LOW = "hotlist_success_ratio_low"
REASON_RSS_ALL_FAILED = "rss_all_failed"
REASON_STALE_INPUT = "stale_input"


@dataclass(frozen=True)
class CRInputHealthPolicy:
    stale_after_minutes: float = DEFAULT_STALE_AFTER_MINUTES
    degraded_success_ratio: float = DEFAULT_DEGRADED_SUCCESS_RATIO


@dataclass(frozen=True)
class CRInputSourceHealth:
    configured_ids: tuple[str, ...] = ()
    successful_ids: tuple[str, ...] = ()
    failed_ids: tuple[str, ...] = ()

    @property
    def success_ratio(self) -> float | None:
        if not self.configured_ids:
            return None
        return len(self.successful_ids) / len(self.configured_ids)


@dataclass(frozen=True)
class CRInputHealth:
    status: str = STATUS_HEALTHY
    reasons: tuple[str, ...] = ()
    hotlist: CRInputSourceHealth = field(default_factory=CRInputSourceHealth)
    rss: CRInputSourceHealth = field(default_factory=CRInputSourceHealth)
    observed_item_identities: frozenset[str] = field(default_factory=frozenset)
    snapshot_generated_at: str | None = None
    snapshot_age_minutes: float | None = None
    historical_data_reused: bool = False
    policy: CRInputHealthPolicy = field(default_factory=CRInputHealthPolicy)
    warnings: tuple[str, ...] = ()

    @property
    def fail_closed(self) -> bool:
        return self.status == STATUS_FAIL_CLOSED

    @property
    def dispatch_block_reason(self) -> str:
        if REASON_STALE_INPUT in self.reasons:
            return "stale_input"
        return "insufficient_fresh_sources"


def _clean_ids(values: object) -> tuple[str, ...]:
    if isinstance(values, str):
        values = (values,)
    return tuple(sorted({str(v).strip() for v in (values or ()) if str(v).strip()}))


def input_item_identity(
    *, source_type: str, source_id: str | None = None,
    feed_id: str | None = None, title: str = "", url: str | None = None,
) -> str:
    """Return a stable identity for one observed hotlist or RSS item."""
    kind = (source_type or "unknown").strip().lower()
    owner = (source_id if kind == "hotlist" else feed_id) or ""
    value = (url if kind == "rss" and url else title) or ""
    return "\x1f".join((kind, owner.strip(), value.strip()))


def source_item_identity(item: object) -> str:
    return input_item_identity(
        source_type=str(getattr(item, "source_type", "unknown")),
        source_id=getattr(item, "source_id", None),
        feed_id=getattr(item, "feed_id", None),
        title=str(getattr(item, "title", "") or ""),
        url=getattr(item, "url", None),
    )


def candidate_has_fresh_input(candidate: object) -> bool:
    source = getattr(candidate, "candidate", candidate)
    return any(
        bool(getattr(item, "observed_in_current_run", False))
        for item in (getattr(source, "source_items", None) or ())
    )


def policy_from_env(
    env: Mapping[str, str] | None,
) -> tuple[CRInputHealthPolicy, tuple[str, ...]]:
    values = env or {}
    warnings: list[str] = []

    def parse(name: str, default: float, *, ratio: bool = False) -> float:
        raw = values.get(name)
        if raw is None:
            return default
        try:
            value = float(raw)
            valid = math.isfinite(value) and value > 0
            if ratio:
                valid = valid and value <= 1
            if not valid:
                raise ValueError
            return value
        except (TypeError, ValueError):
            warnings.append(f"invalid_env:{name}:using_default={default}")
            return default

    return (
        CRInputHealthPolicy(
            stale_after_minutes=parse(
                "PTILOPSIS_CR_INPUT_STALE_AFTER_MINUTES",
                DEFAULT_STALE_AFTER_MINUTES,
            ),
            degraded_success_ratio=parse(
                "PTILOPSIS_CR_INPUT_DEGRADED_SUCCESS_RATIO",
                DEFAULT_DEGRADED_SUCCESS_RATIO,
                ratio=True,
            ),
        ),
        tuple(warnings),
    )


def evaluate_cr_input_health(
    *,
    hotlist_configured_ids: object = (), hotlist_successful_ids: object = (),
    hotlist_failed_ids: object = (), rss_configured_ids: object = (),
    rss_successful_ids: object = (), rss_failed_ids: object = (),
    observed_item_identities: object = (), snapshot_generated_at: str | None = None,
    now: datetime | None = None, historical_data_reused: bool = False,
    policy: CRInputHealthPolicy | None = None, warnings: object = (),
) -> CRInputHealth:
    """Evaluate source success and snapshot staleness without side effects."""
    effective_policy = policy or CRInputHealthPolicy()
    hotlist = CRInputSourceHealth(
        _clean_ids(hotlist_configured_ids), _clean_ids(hotlist_successful_ids),
        _clean_ids(hotlist_failed_ids),
    )
    rss = CRInputSourceHealth(
        _clean_ids(rss_configured_ids), _clean_ids(rss_successful_ids),
        _clean_ids(rss_failed_ids),
    )

    age_minutes: float | None = None
    if snapshot_generated_at:
        try:
            generated = datetime.fromisoformat(snapshot_generated_at)
            if generated.tzinfo is None:
                generated = generated.replace(tzinfo=timezone.utc)
            effective_now = now or datetime.now(timezone.utc)
            if effective_now.tzinfo is None:
                effective_now = effective_now.replace(tzinfo=timezone.utc)
            age_minutes = max(0.0, (effective_now - generated).total_seconds() / 60)
        except (TypeError, ValueError):
            warnings = tuple(warnings or ()) + ("invalid_snapshot_generated_at",)

    reasons: list[str] = []
    fail_closed = False
    if hotlist.configured_ids and not hotlist.successful_ids:
        reasons.append(REASON_HOTLIST_ALL_FAILED)
        fail_closed = True
    if age_minutes is not None and age_minutes > effective_policy.stale_after_minutes:
        reasons.append(REASON_STALE_INPUT)
        fail_closed = True

    hotlist_ratio = hotlist.success_ratio
    if (
        hotlist_ratio is not None and hotlist.successful_ids
        and hotlist_ratio < effective_policy.degraded_success_ratio
    ):
        reasons.append(REASON_HOTLIST_SUCCESS_RATIO_LOW)
    if rss.configured_ids and not rss.successful_ids:
        reasons.append(REASON_RSS_ALL_FAILED)

    status = STATUS_FAIL_CLOSED if fail_closed else (
        STATUS_DEGRADED if reasons else STATUS_HEALTHY
    )
    return CRInputHealth(
        status=status,
        reasons=tuple(reasons),
        hotlist=hotlist,
        rss=rss,
        observed_item_identities=frozenset(str(v) for v in (observed_item_identities or ())),
        snapshot_generated_at=snapshot_generated_at,
        snapshot_age_minutes=age_minutes,
        historical_data_reused=historical_data_reused,
        policy=effective_policy,
        warnings=tuple(str(v) for v in (warnings or ())),
    )


def input_health_to_json_dict(health: CRInputHealth) -> dict[str, object]:
    def source(value: CRInputSourceHealth) -> dict[str, object]:
        return {
            "configured_ids": list(value.configured_ids),
            "successful_ids": list(value.successful_ids),
            "failed_ids": list(value.failed_ids),
            "success_ratio": value.success_ratio,
        }

    return {
        "status": health.status,
        "reasons": list(health.reasons),
        "hotlist": source(health.hotlist),
        "rss": source(health.rss),
        "snapshot": {
            "generated_at": health.snapshot_generated_at,
            "age_minutes": health.snapshot_age_minutes,
            "historical_data_reused": health.historical_data_reused,
        },
        "policy": {
            "stale_after_minutes": health.policy.stale_after_minutes,
            "degraded_success_ratio": health.policy.degraded_success_ratio,
        },
        "warnings": list(health.warnings),
    }
