# coding=utf-8
"""Run the scheduled application and atomically record task completion."""

from __future__ import annotations

import json
import os
import tempfile
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
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def main(application: Callable[[], int] | None = None) -> int:
    if application is None:
        from trendradar.__main__ import main as application_main

        application = application_main
    exit_code = application()
    if exit_code != 0:
        return exit_code if isinstance(exit_code, int) else 1
    write_heartbeat()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
