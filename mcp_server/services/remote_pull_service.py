"""Bounded, query-compatible pulls from remote object storage."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from ..utils.errors import InvalidParameterError


MAX_PULL_DAYS = 365


def validate_pull_days(days: int) -> int:
    """Validate a bounded lookback without accepting booleans as integers."""
    if isinstance(days, bool) or not isinstance(days, int):
        raise InvalidParameterError("days 必须是整数")
    if days < 0 or days > MAX_PULL_DAYS:
        raise InvalidParameterError(
            f"days 必须在 0 到 {MAX_PULL_DAYS} 之间",
            suggestion=f"请提供 0 到 {MAX_PULL_DAYS} 之间的整数",
        )
    return days


@dataclass(slots=True)
class RemotePullResult:
    """Stable counters and per-date outcomes for one pull."""

    synced_dates: list[str] = field(default_factory=list)
    skipped_dates: list[str] = field(default_factory=list)
    failed_dates: list[dict[str, str]] = field(default_factory=list)


class RemotePullService:
    """Pull news databases into the canonical local query layout."""

    def __init__(self, remote_backend, local_data_dir: Path):
        self.remote_backend = remote_backend
        self.local_data_dir = Path(local_data_dir)

    def pull_recent_news(
        self,
        *,
        days: int,
        now: datetime,
        remote_dates: Iterable[str],
        local_dates: Iterable[str],
    ) -> RemotePullResult:
        days = validate_pull_days(days)
        result = RemotePullResult()
        if days == 0:
            return result

        available = set(remote_dates)
        existing = set(local_dates)
        targets = [
            (now - timedelta(days=offset)).strftime("%Y-%m-%d")
            for offset in range(days)
        ]

        for date_str in targets:
            if date_str not in available:
                continue

            local_path = (
                self.local_data_dir / "news" / f"{date_str}.db"
            )
            if date_str in existing or local_path.exists():
                result.skipped_dates.append(date_str)
                continue

            try:
                downloaded = self.remote_backend.download_database(
                    date=date_str,
                    db_type="news",
                    local_path=local_path,
                )
                if downloaded is None:
                    raise FileNotFoundError(
                        "远端对象在同步过程中消失"
                    )
                result.synced_dates.append(date_str)
            except Exception as error:
                result.failed_dates.append({
                    "date": date_str,
                    "error": str(error),
                })

        return result
