"""Reader preferences shared by CR and every daily-report surface."""

import json
import os
from functools import lru_cache
from pathlib import Path

from trendradar.esports import esports_item


@lru_cache(maxsize=4)
def _read(path: str, modified_ns: int, size: int) -> bool:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("exclude_esports", False), bool):
        raise ValueError("reader preferences require a boolean exclude_esports")
    return data.get("exclude_esports", False)


def exclude_esports() -> bool:
    path = Path(os.environ.get(
        "READER_PREFERENCES_PATH",
        str(Path(__file__).resolve().parents[1] / "config/reader_preferences.json"),
    ))
    try:
        stat = path.stat()
    except FileNotFoundError:
        return False
    return _read(str(path), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=4)
def _topic_groups(path: str, modified_ns: int, size: int) -> frozenset[str]:
    from trendradar.core.frequency import load_frequency_words

    groups, _, _ = load_frequency_words(path)
    return frozenset(str(group.get(key, "")) for group in groups
                     for key in ("group_key", "display_name") if group.get(key))


def is_group_topic(topic: str) -> bool:
    """A configured keyword group can contain several unrelated events."""
    path = Path(os.environ.get(
        "FREQUENCY_WORDS_PATH",
        str(Path(__file__).resolve().parents[1] / "config/frequency_words.txt"),
    ))
    if not path.exists() and not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / "config/custom/keyword" / path
    try:
        stat = path.stat()
    except FileNotFoundError:
        return False
    return str(topic or "").strip() in _topic_groups(str(path), stat.st_mtime_ns, stat.st_size)


def filtered_title_count(group, visible) -> int:
    """Subtract known removals; a capped title list is not the full count."""
    original = group.get("titles") or []
    try:
        count = int(group.get("count", len(original)))
    except (ValueError, TypeError):
        count = len(original)
    return max(len(visible), count - (len(original) - len(visible)))


def filter_reader_stats(stats):
    """Filter event titles without mutating caller data or raw storage."""
    if not stats or not exclude_esports():
        return stats
    groups = []
    for group in stats:
        if "titles" not in group:
            if not esports_item(group.get("title", group.get("word", ""))):
                groups.append(group)
            continue
        original = group.get("titles") or []
        visible = [item for item in original if not esports_item(item.get("title", ""))]
        if not visible:
            continue
        groups.append({**group, "titles": visible,
                       "count": filtered_title_count(group, visible)})
    return groups
