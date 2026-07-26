# coding=utf-8
"""Immutable, side-effect-free schedule snapshot for one application run."""

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from trendradar.core.scheduler import ResolvedSchedule


@dataclass(frozen=True, slots=True)
class RunPlan:
    """Effective runtime choices resolved before any acquisition side effect."""

    period_key: Optional[str]
    period_name: Optional[str]
    day_plan: str
    collect: bool
    analyze: bool
    report_mode: str
    ai_mode: str
    once_analyze: bool
    frequency_file: Optional[str] = None
    filter_method: str = "keyword"
    interests_file: Optional[str] = None


class RunPlanBuilder:
    """Build a complete :class:`RunPlan` without mutating its inputs."""

    @staticmethod
    def build(
        schedule: ResolvedSchedule,
        config: Mapping[str, Any],
    ) -> RunPlan:
        filter_config = config.get("FILTER", {})
        configured_filter_method = (
            filter_config.get("METHOD", "keyword")
            if isinstance(filter_config, Mapping)
            else "keyword"
        )
        filter_method = schedule.filter_method or configured_filter_method or "keyword"

        return RunPlan(
            period_key=schedule.period_key,
            period_name=schedule.period_name,
            day_plan=schedule.day_plan,
            collect=schedule.collect,
            analyze=schedule.analyze,
            report_mode=schedule.report_mode,
            ai_mode=schedule.ai_mode,
            once_analyze=schedule.once_analyze,
            frequency_file=schedule.frequency_file,
            filter_method=str(filter_method),
            interests_file=schedule.interests_file,
        )
