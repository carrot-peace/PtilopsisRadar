"""Build one canonical analysis request from mode-specific inputs."""

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Optional

from trendradar.application.run_state import AnalysisRequest


class AnalysisInputUnavailable(RuntimeError):
    """Raised when a mode's required persisted input cannot be loaded."""


class AnalysisInputBuilder:
    """Collapse daily/current/incremental input branching into one boundary."""

    def __init__(
        self,
        *,
        load_history: Callable[[], Optional[tuple]],
        prepare_current_title_info: Callable[[Mapping, str], Mapping],
        detect_new_titles: Callable[[], Mapping],
        load_frequency_words: Callable[[], tuple],
        format_time: Callable[[], str],
    ):
        self._load_history = load_history
        self._prepare_current_title_info = prepare_current_title_info
        self._detect_new_titles = detect_new_titles
        self._load_frequency_words = load_frequency_words
        self._format_time = format_time

    def build(
        self,
        *,
        plan,
        results: Mapping[str, Any],
        id_to_name: Mapping[str, str],
        failed_ids: Sequence[str],
        rss_items: Optional[list[dict]] = None,
        rss_new_items: Optional[list[dict]] = None,
        rss_new_urls=None,
    ) -> AnalysisRequest:
        word_groups, filter_words, global_filters = self._load_frequency_words()
        mode = plan.report_mode
        selected_results = results
        selected_names = id_to_name
        historical_data_reused = False

        history = None
        if mode in {"current", "daily"}:
            history = self._load_history()

        if history:
            (
                selected_results,
                selected_names,
                title_info,
                new_titles,
            ) = history
            historical_data_reused = True
        elif mode == "current":
            raise AnalysisInputUnavailable(
                "current mode requires persisted data from the current day"
            )
        else:
            title_info = self._prepare_current_title_info(
                results,
                self._format_time(),
            )
            new_titles = self._detect_new_titles()

        return AnalysisRequest(
            mode=mode,
            results=selected_results,
            id_to_name=selected_names,
            failed_ids=tuple(str(value) for value in failed_ids),
            title_info=title_info,
            new_titles=new_titles,
            word_groups=tuple(word_groups),
            filter_words=tuple(filter_words),
            global_filters=tuple(global_filters),
            rss_items=rss_items,
            rss_new_items=rss_new_items,
            rss_new_urls=frozenset(rss_new_urls or ()),
            historical_data_reused=historical_data_reused,
        )
