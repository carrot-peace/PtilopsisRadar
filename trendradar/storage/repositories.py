"""Partitioned repository contracts over a storage backend."""

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

from trendradar.storage.base import NewsData, RSSData


@runtime_checkable
class NewsRepository(Protocol):
    def save_news_data(self, data: NewsData) -> bool: ...
    def get_today_all_data(
        self,
        date: Optional[str] = None,
    ) -> Optional[NewsData]: ...
    def get_latest_crawl_data(
        self,
        date: Optional[str] = None,
    ) -> Optional[NewsData]: ...
    def detect_new_titles(self, current_data: NewsData) -> dict: ...


@runtime_checkable
class RSSRepository(Protocol):
    def save_rss_data(self, data: RSSData) -> bool: ...
    def get_rss_data(
        self,
        date: Optional[str] = None,
    ) -> Optional[RSSData]: ...
    def get_latest_rss_data(
        self,
        date: Optional[str] = None,
    ) -> Optional[RSSData]: ...
    def detect_new_rss_items(self, current_data: RSSData) -> dict: ...


@runtime_checkable
class ScheduleRepository(Protocol):
    def has_period_executed(
        self,
        date_str: str,
        period_key: str,
        action: str,
    ) -> bool: ...
    def record_period_execution(
        self,
        date_str: str,
        period_key: str,
        action: str,
    ) -> bool: ...


@runtime_checkable
class AIFilterRepository(Protocol):
    def get_active_ai_filter_tags(
        self,
        date=None,
        interests_file: str = "ai_interests.txt",
    ): ...
    def save_ai_filter_tags(
        self,
        tags,
        version,
        prompt_hash,
        date=None,
        interests_file: str = "ai_interests.txt",
    ): ...
    def save_ai_filter_results(self, results, date=None): ...


@dataclass(frozen=True, slots=True)
class StorageRepositories:
    news: NewsRepository
    rss: RSSRepository
    schedule: ScheduleRepository
    ai_filter: AIFilterRepository

    @classmethod
    def from_backend(cls, backend) -> "StorageRepositories":
        return cls(
            news=backend,
            rss=backend,
            schedule=backend,
            ai_filter=backend,
        )
