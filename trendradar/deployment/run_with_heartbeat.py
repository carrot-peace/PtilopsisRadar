# coding=utf-8
"""Run the scheduled application and atomically record task completion."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


DEFAULT_HEARTBEAT_PATH = Path("output/meta/last_task_completed.json")


def write_heartbeat(path: str | Path = DEFAULT_HEARTBEAT_PATH) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "task-heartbeat-v1",
        "completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def main(application: Callable[[], None] | None = None) -> None:
    if application is None:
        from trendradar.__main__ import main as application_main

        application = application_main
    application()
    write_heartbeat()


if __name__ == "__main__":
    main()
