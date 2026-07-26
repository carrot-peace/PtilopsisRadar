# coding=utf-8
"""Behavior contracts for resolving a run before acquisition side effects."""

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


for _stale in [
    _name
    for _name in list(sys.modules)
    if _name == "trendradar" or _name.startswith("trendradar.")
]:
    del sys.modules[_stale]

import trendradar.__main__ as application
from trendradar.application.run_plan import RunPlanBuilder
from trendradar.core.scheduler import ResolvedSchedule


def _schedule(
    *,
    collect=True,
    report_mode="daily",
    frequency_file="scheduled.txt",
    filter_method="ai",
    interests_file="scheduled-interests.txt",
):
    return ResolvedSchedule(
        period_key="active",
        period_name="Active",
        day_plan="weekday",
        collect=collect,
        analyze=True,
        report_mode=report_mode,
        ai_mode="follow_report",
        once_analyze=False,
        frequency_file=frequency_file,
        filter_method=filter_method,
        interests_file=interests_file,
    )


def _bare_analyzer(schedule):
    analyzer = object.__new__(application.NewsAnalyzer)
    scheduler = SimpleNamespace(resolve=Mock(return_value=schedule))
    analyzer.ctx = SimpleNamespace(
        config={"FILTER": {"METHOD": "keyword"}},
        filter_method="keyword",
        create_scheduler=Mock(return_value=scheduler),
        run_retention_maintenance=Mock(),
        close=Mock(),
        cleanup=Mock(),
    )
    analyzer.report_mode = "current"
    analyzer.frequency_file = "stale.txt"
    analyzer.filter_method = "keyword"
    analyzer.interests_file = None
    analyzer._initialize_and_check_config = Mock(return_value=True)
    analyzer._cr_hotlist_successful_ids = set()
    analyzer._cr_hotlist_failed_ids = set()
    analyzer._cr_rss_successful_ids = set()
    analyzer._cr_rss_failed_ids = set()
    analyzer._cr_observed_item_identities = set()
    analyzer._cr_input_snapshot_generated_at = None
    analyzer._cr_historical_data_reused = False
    analyzer._cr_rss_historical_data_reused = False
    return analyzer, scheduler


class TestRunOrder(unittest.TestCase):
    def test_each_run_replaces_the_complete_run_state(self):
        analyzer, _ = _bare_analyzer(_schedule())
        previous_state = analyzer.run_state
        previous_state.observed_item_identities.add("stale")
        states_seen_by_collection = []

        def crawl_hotlist():
            states_seen_by_collection.append(analyzer.run_state)
            return {}, {}, []

        analyzer._crawl_data = Mock(side_effect=crawl_hotlist)
        analyzer._crawl_rss_data = Mock(return_value=(None, None, None, set()))
        analyzer._execute_mode_strategy = Mock()

        analyzer.run()

        self.assertEqual(len(states_seen_by_collection), 1)
        current_state = states_seen_by_collection[0]
        self.assertIsNot(current_state, previous_state)
        self.assertEqual(current_state.observed_item_identities, set())

    def test_collect_false_prevents_all_acquisition_and_pipeline_effects(self):
        analyzer, scheduler = _bare_analyzer(_schedule(collect=False))
        analyzer._crawl_data = Mock()
        analyzer._crawl_rss_data = Mock()
        analyzer._execute_mode_strategy = Mock()

        analyzer.run()

        scheduler.resolve.assert_called_once_with()
        analyzer._crawl_data.assert_not_called()
        analyzer._crawl_rss_data.assert_not_called()
        analyzer._execute_mode_strategy.assert_not_called()
        analyzer.ctx.run_retention_maintenance.assert_not_called()
        analyzer.ctx.close.assert_called_once_with()
        analyzer.ctx.cleanup.assert_not_called()

    def test_resolved_plan_is_applied_before_hotlist_and_rss_collection(self):
        analyzer, scheduler = _bare_analyzer(_schedule())
        events = []

        def crawl_hotlist():
            events.append(("hotlist", analyzer.report_mode, analyzer.frequency_file))
            return {}, {}, []

        def crawl_rss(plan):
            events.append(("rss", plan.report_mode, plan.frequency_file))
            return None, None, None, set()

        def execute(plan, *args, **kwargs):
            events.append(("pipeline", plan.report_mode, plan.frequency_file))

        analyzer._crawl_data = Mock(side_effect=crawl_hotlist)
        analyzer._crawl_rss_data = Mock(side_effect=crawl_rss)
        analyzer._execute_mode_strategy = Mock(side_effect=execute)

        analyzer.run()

        self.assertEqual(
            events,
            [
                ("hotlist", "daily", "scheduled.txt"),
                ("rss", "daily", "scheduled.txt"),
                ("pipeline", "daily", "scheduled.txt"),
            ],
        )
        scheduler.resolve.assert_called_once_with()
        plan = analyzer._crawl_rss_data.call_args.args[0]
        self.assertEqual(plan.filter_method, "ai")
        self.assertEqual(plan.interests_file, "scheduled-interests.txt")
        self.assertIs(analyzer._execute_mode_strategy.call_args.args[0], plan)
        analyzer.ctx.run_retention_maintenance.assert_called_once_with()
        analyzer.ctx.close.assert_called_once_with()
        analyzer.ctx.cleanup.assert_not_called()


class TestRSSRunPlanUsage(unittest.TestCase):
    def test_rss_processing_uses_plan_instead_of_stale_analyzer_fields(self):
        plan = RunPlanBuilder.build(_schedule(report_mode="daily"), {})
        daily_data = SimpleNamespace(
            items={"feed": [object()]},
            id_to_name={"feed": "Feed"},
        )
        storage = SimpleNamespace(
            get_rss_data=Mock(return_value=daily_data),
            get_latest_rss_data=Mock(),
            detect_new_rss_items=Mock(return_value={}),
        )
        ctx = SimpleNamespace(
            load_frequency_words=Mock(return_value=([], [], [])),
            timezone="Asia/Shanghai",
            config={
                "MAX_NEWS_PER_KEYWORD": 0,
                "SORT_BY_POSITION_FIRST": False,
            },
        )
        analyzer = SimpleNamespace(
            ctx=ctx,
            storage_manager=storage,
            report_mode="current",
            frequency_file="stale.txt",
            rank_threshold=50,
            _cr_rss_historical_data_reused=False,
            _rss_total_count=0,
            _convert_rss_items_to_list=Mock(
                return_value=[{"title": "item", "url": "https://example.com"}]
            ),
        )
        rss_data = SimpleNamespace(
            date="2026-07-24",
            items={"feed": [object()]},
            id_to_name={"feed": "Feed"},
        )

        with patch(
            "trendradar.core.analyzer.count_rss_frequency",
            return_value=([{"word": "item", "count": 1, "titles": []}], 1),
        ):
            result = application.NewsAnalyzer._process_rss_data_by_mode(
                analyzer, rss_data, plan
            )

        ctx.load_frequency_words.assert_called_once_with("scheduled.txt")
        storage.get_rss_data.assert_called_once_with("2026-07-24")
        storage.get_latest_rss_data.assert_not_called()
        self.assertEqual(result[0][0]["word"], "item")


if __name__ == "__main__":
    unittest.main()
