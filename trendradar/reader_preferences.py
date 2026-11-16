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
                       "count": max(len(visible), group.get("count", len(original))
                                    - (len(original) - len(visible)))})
    return groups
