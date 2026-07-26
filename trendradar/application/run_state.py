"""Per-run state and boundary DTOs for application orchestration."""

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

from trendradar.storage.base import NewsData, RSSData


@dataclass(slots=True)
class SourceRunState:
    """Configured, successful, and failed sources for one input family."""

    configured_ids: frozenset[str] = frozenset()
    successful_ids: set[str] = field(default_factory=set)
    failed_ids: set[str] = field(default_factory=set)


@dataclass(slots=True)
class RunState:
    """Mutable state owned by exactly one coordinator run."""

    hotlist: SourceRunState
    rss: SourceRunState
    observed_item_identities: set[str] = field(default_factory=set)
    input_snapshot_generated_at: Optional[str] = None
    historical_data_reused: bool = False
    rss_historical_data_reused: bool = False
    raw_rss_items: Optional[list[dict]] = None
    hotlist_total_count: int = 0
    rss_source_total: int = 0
    rss_source_failed: int = 0
    rss_total_count: int = 0
    rss_matched_count: int = 0

    @classmethod
    def create(
        cls,
        *,
        hotlist_configured_ids,
        rss_configured_ids,
    ) -> "RunState":
        return cls(
            hotlist=SourceRunState(
                configured_ids=frozenset(
                    str(value) for value in hotlist_configured_ids
                )
            ),
            rss=SourceRunState(
                configured_ids=frozenset(
                    str(value) for value in rss_configured_ids
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class HotlistBatch:
    """Result of one hotlist fetch → convert → save operation."""

    raw_results: Mapping[str, Any]
    id_to_name: Mapping[str, str]
    failed_ids: tuple[str, ...]
    configured_ids: frozenset[str]
    successful_ids: frozenset[str]
    news_data: NewsData
    saved: bool
    snapshot_path: Optional[str] = None


@dataclass(frozen=True, slots=True)
class RSSBatch:
    """Result of one RSS fetch → save operation."""

    rss_data: RSSData
    configured_ids: frozenset[str]
    successful_ids: frozenset[str]
    failed_ids: tuple[str, ...]
    saved: bool


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    """Canonical typed input for analysis regardless of report mode."""

    mode: str
    results: Mapping[str, Any]
    id_to_name: Mapping[str, str]
    failed_ids: tuple[str, ...]
    title_info: Mapping[str, Any]
    new_titles: Mapping[str, Any]
    word_groups: tuple[Any, ...]
    filter_words: tuple[Any, ...]
    global_filters: tuple[Any, ...]
    rss_items: Optional[list[dict]] = None
    rss_new_items: Optional[list[dict]] = None
    rss_new_urls: frozenset[str] = frozenset()
    historical_data_reused: bool = False


@dataclass(frozen=True, slots=True)
class AnalysisOutcome:
    """Typed result of the complete analysis and reporting pipeline."""

    stats: list[dict]
    total_titles: int
    html_file: Optional[str]
    ai_result: Any
    rss_items: Optional[list[dict]]
    rss_matched_count: int
