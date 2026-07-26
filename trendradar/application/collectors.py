"""Collection services with explicit fetch/convert/save outcomes."""

from pathlib import Path

from trendradar.application.run_state import HotlistBatch, RSSBatch
from trendradar.storage.base import convert_crawl_results_to_news_data


def _clock_value(clock, primary: str, fallback: str) -> str:
    method = getattr(clock, primary, None) or getattr(clock, fallback)
    return method()


class HotlistCollector:
    """Collect hotlist data without owning orchestration state."""

    def __init__(self, fetcher, storage, clock, output_dir: str = "output"):
        self.fetcher = fetcher
        self.storage = storage
        self.clock = clock
        self.output_dir = Path(output_dir)

    def collect(self, platforms, request_interval: int) -> HotlistBatch:
        ids = []
        domain_rules = {}
        configured_ids = set()
        for platform in platforms:
            source_id = str(platform["id"])
            configured_ids.add(source_id)
            ids.append(
                (platform["id"], platform["name"])
                if "name" in platform
                else platform["id"]
            )
            expected_domain = platform.get("expected_domain", "")
            if expected_domain:
                domain_rules[platform["id"]] = expected_domain

        self.output_dir.mkdir(parents=True, exist_ok=True)
        results, id_to_name, failed_ids = self.fetcher.crawl_websites(
            ids,
            request_interval,
            domain_rules=domain_rules,
        )
        crawl_time = _clock_value(self.clock, "time", "format_time")
        crawl_date = _clock_value(self.clock, "date", "format_date")
        news_data = convert_crawl_results_to_news_data(
            results,
            id_to_name,
            failed_ids,
            crawl_time,
            crawl_date,
        )
        saved = self.storage.save_news_data(news_data)
        snapshot_path = (
            self.storage.save_txt_snapshot(news_data)
            if saved
            else None
        )
        failed = tuple(str(value) for value in failed_ids)
        successful = frozenset(str(value) for value in results) - set(failed)
        return HotlistBatch(
            raw_results=results,
            id_to_name=id_to_name,
            failed_ids=failed,
            configured_ids=frozenset(configured_ids),
            successful_ids=frozenset(successful),
            news_data=news_data,
            saved=saved,
            snapshot_path=snapshot_path,
        )


class RSSCollector:
    """Collect and persist RSS data without mode-specific analysis."""

    def __init__(self, fetcher, storage):
        self.fetcher = fetcher
        self.storage = storage

    def collect(self, configured_ids) -> RSSBatch:
        rss_data = self.fetcher.fetch_all()
        saved = self.storage.save_rss_data(rss_data)
        failed = tuple(str(value) for value in rss_data.failed_ids)
        successful = (
            frozenset(str(value) for value in rss_data.items)
            - set(failed)
        )
        return RSSBatch(
            rss_data=rss_data,
            configured_ids=frozenset(
                str(value) for value in configured_ids
            ),
            successful_ids=frozenset(successful),
            failed_ids=failed,
            saved=saved,
        )
