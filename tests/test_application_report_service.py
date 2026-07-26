import unittest
from types import SimpleNamespace
from unittest.mock import Mock


class ReportServiceTests(unittest.TestCase):
    def _request(self, mode="daily"):
        from trendradar.application.services.report import (
            ReportCounters,
            ReportRequest,
        )

        return ReportRequest(
            mode=mode,
            stats=[{"word": "topic", "count": 1}],
            total_titles=4,
            failed_ids=("failed",),
            new_titles={"source": ["new"]},
            id_to_name={"source": "Source"},
            rss_items=[{"word": "rss", "count": 2}],
            rss_new_items=[{"title": "new rss"}],
            ai_analysis=object(),
            update_info={"remote_version": "2.0.0"},
            frequency_file="frequency.txt",
            counters=ReportCounters(
                platform_total=3,
                rss_total_count=5,
                rss_source_total=2,
                rss_source_failed=1,
            ),
        )

    def test_daily_translates_before_render_and_returns_metadata(self):
        from trendradar.application.services.report import ReportService

        events = []
        translated_rss = [{"word": "translated", "count": 3}]
        translated_new = [{"title": "translated new"}]

        def translate(**kwargs):
            events.append(("translate", kwargs))
            return [], translated_rss, translated_new

        gateway = SimpleNamespace(
            html_enabled=True,
            translation_enabled=True,
            debug=False,
            show_version_update=True,
            create_translator=Mock(return_value="translator"),
            generate_html=Mock(
                side_effect=lambda *args, **kwargs: events.append(
                    ("html", args, kwargs)
                )
                or "report.html"
            ),
            generate_dashboard=Mock(),
        )
        service = ReportService(gateway, translate_content=translate)

        result = service.render(self._request())

        self.assertEqual([event[0] for event in events], ["translate", "html"])
        self.assertEqual(result.html_file, "report.html")
        self.assertEqual(result.rss_items, translated_rss)
        self.assertEqual(result.rss_new_items, translated_new)
        self.assertEqual(result.rss_matched_count, 3)
        html_kwargs = gateway.generate_html.call_args.kwargs
        self.assertEqual(html_kwargs["rss_items"], translated_rss)
        self.assertEqual(
            html_kwargs["report_metadata"],
            {
                "hotlist_total": 4,
                "platform_total": 3,
                "rss_matched_count": 3,
                "rss_total_count": 5,
                "rss_source_total": 2,
                "rss_source_failed": 1,
            },
        )

    def test_current_routes_only_to_dashboard(self):
        from trendradar.application.services.report import ReportService

        gateway = SimpleNamespace(
            html_enabled=True,
            translation_enabled=False,
            debug=False,
            show_version_update=False,
            create_translator=Mock(),
            generate_html=Mock(),
            generate_dashboard=Mock(),
        )
        service = ReportService(gateway)

        result = service.render(self._request(mode="current"))

        self.assertIsNone(result.html_file)
        gateway.generate_html.assert_not_called()
        gateway.generate_dashboard.assert_called_once()
        self.assertEqual(
            gateway.generate_dashboard.call_args.kwargs["mode"],
            "current",
        )

    def test_disabled_html_has_no_render_side_effect(self):
        from trendradar.application.services.report import ReportService

        gateway = SimpleNamespace(
            html_enabled=False,
            translation_enabled=False,
            debug=False,
            show_version_update=False,
            create_translator=Mock(),
            generate_html=Mock(),
            generate_dashboard=Mock(),
        )
        service = ReportService(gateway)

        result = service.render(self._request())

        self.assertIsNone(result.html_file)
        self.assertEqual(result.rss_matched_count, 2)
        gateway.generate_html.assert_not_called()
        gateway.generate_dashboard.assert_not_called()


if __name__ == "__main__":
    unittest.main()
