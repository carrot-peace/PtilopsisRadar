import unittest
from types import SimpleNamespace
from unittest.mock import Mock


def _plan(mode):
    return SimpleNamespace(report_mode=mode)


class AnalysisInputBuilderTests(unittest.TestCase):
    def _builder(self, history):
        from trendradar.application.analysis_input import AnalysisInputBuilder

        self.load_history = Mock(return_value=history)
        self.prepare_current = Mock(
            return_value={"source": {"current": {"count": 1}}}
        )
        self.detect_new = Mock(return_value={"source": ["new"]})
        self.load_words = Mock(return_value=([{"word": "x"}], ["skip"], ["global"]))
        return AnalysisInputBuilder(
            load_history=self.load_history,
            prepare_current_title_info=self.prepare_current,
            detect_new_titles=self.detect_new,
            load_frequency_words=self.load_words,
            format_time=Mock(return_value="09-30"),
        )

    def _build(self, builder, mode):
        return builder.build(
            plan=_plan(mode),
            results={"source": {"current": {"ranks": [1]}}},
            id_to_name={"source": "Current"},
            failed_ids=["failed"],
            rss_items=[{"title": "rss"}],
            rss_new_items=[{"title": "new rss"}],
            rss_new_urls={"https://example.com/new"},
        )

    def test_current_uses_history_and_loads_frequency_once(self):
        history = (
            {"source": {"historical": {}}},
            {"source": "Historical"},
            {"source": {"historical": {"count": 2}}},
            {"source": ["historical"]},
        )
        builder = self._builder(history)

        request = self._build(builder, "current")

        self.assertEqual(request.mode, "current")
        self.assertEqual(request.results, history[0])
        self.assertEqual(request.id_to_name, history[1])
        self.assertEqual(request.title_info, history[2])
        self.assertEqual(request.new_titles, history[3])
        self.assertTrue(request.historical_data_reused)
        self.load_history.assert_called_once_with()
        self.prepare_current.assert_not_called()
        self.detect_new.assert_not_called()
        self.load_words.assert_called_once_with()

    def test_current_without_history_is_an_explicit_error(self):
        from trendradar.application.analysis_input import AnalysisInputUnavailable

        builder = self._builder(None)

        with self.assertRaises(AnalysisInputUnavailable):
            self._build(builder, "current")

        self.load_words.assert_called_once_with()

    def test_daily_falls_back_to_current_batch(self):
        builder = self._builder(None)

        request = self._build(builder, "daily")

        self.assertEqual(request.results, {"source": {"current": {"ranks": [1]}}})
        self.assertEqual(request.id_to_name, {"source": "Current"})
        self.assertFalse(request.historical_data_reused)
        self.load_history.assert_called_once_with()
        self.prepare_current.assert_called_once_with(
            {"source": {"current": {"ranks": [1]}}},
            "09-30",
        )
        self.detect_new.assert_called_once_with()
        self.load_words.assert_called_once_with()

    def test_incremental_never_loads_history(self):
        builder = self._builder(
            (
                {"ignored": {}},
                {"ignored": "Ignored"},
                {},
                {},
            )
        )

        request = self._build(builder, "incremental")

        self.assertEqual(request.mode, "incremental")
        self.assertEqual(request.results, {"source": {"current": {"ranks": [1]}}})
        self.assertFalse(request.historical_data_reused)
        self.load_history.assert_not_called()
        self.prepare_current.assert_called_once()
        self.detect_new.assert_called_once_with()
        self.load_words.assert_called_once_with()

    def test_rss_and_failure_metadata_are_preserved(self):
        builder = self._builder(None)

        request = self._build(builder, "incremental")

        self.assertEqual(request.failed_ids, ("failed",))
        self.assertEqual(request.rss_items, [{"title": "rss"}])
        self.assertEqual(request.rss_new_items, [{"title": "new rss"}])
        self.assertEqual(
            request.rss_new_urls,
            frozenset({"https://example.com/new"}),
        )


if __name__ == "__main__":
    unittest.main()
