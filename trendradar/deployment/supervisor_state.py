# coding=utf-8
"""Safe local state and heartbeat validation for the Apple supervisor."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


DEPLOYMENT_STATE_SCHEMA = "supervisor-deployment-state-v1"


def _parse_aware_datetime(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp is missing")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp is not timezone-aware")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class HeartbeatStatus:
    status: str
    age_seconds: int = -1

    def as_dict(self) -> dict[str, int | str]:
        return {"status": self.status, "age_seconds": self.age_seconds}


def inspect_heartbeat(
    path: str | Path,
    *,
    now_epoch: int,
    started_epoch: int,
    max_age_seconds: int,
    future_skew_seconds: int = 300,
) -> HeartbeatStatus:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return HeartbeatStatus("missing")
    except (OSError, TypeError, ValueError):
        return HeartbeatStatus("invalid")
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "task-heartbeat-v1"
        or set(payload) != {"schema_version", "completed_at"}
    ):
        return HeartbeatStatus("invalid")
    try:
        completed_epoch = int(
            _parse_aware_datetime(payload.get("completed_at")).timestamp()
        )
    except (OverflowError, TypeError, ValueError):
        return HeartbeatStatus("invalid")
    if completed_epoch > now_epoch + future_skew_seconds:
        return HeartbeatStatus("future")
    age = max(0, now_epoch - completed_epoch)
    if completed_epoch < started_epoch:
        return HeartbeatStatus("before_start", age)
    if age > max_age_seconds:
        return HeartbeatStatus("stale", age)
    return HeartbeatStatus("fresh", age)


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_deployment_state(
    state_path: str | Path,
    *,
    env_file: str | Path,
    container_created: str,
    image_digest: str,
    now: datetime | None = None,
) -> str:
    """Return baseline_created/ok/drift/missing/invalid for safe env identity."""
    state = Path(state_path)
    env_path = Path(env_file)
    try:
        created = _parse_aware_datetime(container_created)
    except (TypeError, ValueError):
        return "invalid_container_identity"
    if not image_digest.strip():
        return "invalid_container_identity"
    try:
        env_hash = _sha256_file(env_path)
        env_mtime = env_path.stat().st_mtime
    except OSError:
        return "missing"

    try:
        raw = json.loads(state.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raw = None
    except (OSError, TypeError, ValueError):
        return "invalid"

    identity = {
        "container_created": created.isoformat(),
        "image_digest": image_digest,
    }
    if raw is None:
        if env_mtime > created.timestamp():
            return "drift"
        payload = {
            "schema_version": DEPLOYMENT_STATE_SCHEMA,
            **identity,
            "env_sha256": env_hash,
            "recorded_at": (now or datetime.now(timezone.utc)).isoformat(
                timespec="seconds"
            ),
        }
        try:
            _atomic_write_json(state, payload)
        except OSError:
            return "state_write_failed"
        return "baseline_created"

    if not isinstance(raw, dict) or raw.get("schema_version") != DEPLOYMENT_STATE_SCHEMA:
        return "invalid"
    if not all(
        isinstance(raw.get(key), str)
        for key in ("container_created", "image_digest", "env_sha256")
    ):
        return "invalid"
    if len(str(raw["env_sha256"])) != 64:
        return "invalid"

    if any(raw.get(key) != value for key, value in identity.items()):
        # A new container identity needs the same safety check as the initial
        # baseline.  Otherwise an env edit made after recreation but before the
        # first supervisor pass would be recorded as if the container had
        # consumed it.
        if env_mtime > created.timestamp():
            return "drift"
        payload = {
            "schema_version": DEPLOYMENT_STATE_SCHEMA,
            **identity,
            "env_sha256": env_hash,
            "recorded_at": (now or datetime.now(timezone.utc)).isoformat(
                timespec="seconds"
            ),
        }
        try:
            _atomic_write_json(state, payload)
        except OSError:
            return "state_write_failed"
        return "baseline_created"
    return "ok" if raw.get("env_sha256") == env_hash else "drift"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect safe supervisor state")
    subparsers = parser.add_subparsers(dest="command", required=True)
    heartbeat = subparsers.add_parser("heartbeat")
    heartbeat.add_argument("--path", required=True)
    heartbeat.add_argument("--now-epoch", required=True, type=int)
    heartbeat.add_argument("--started-epoch", required=True, type=int)
    heartbeat.add_argument("--max-age", required=True, type=int)

    deployment = subparsers.add_parser("deployment")
    deployment.add_argument("--state-path", required=True)
    deployment.add_argument("--env-file", required=True)
    deployment.add_argument("--container-created", required=True)
    deployment.add_argument("--image-digest", required=True)
    args = parser.parse_args(argv)

    if args.command == "heartbeat":
        result = inspect_heartbeat(
            args.path,
            now_epoch=args.now_epoch,
            started_epoch=args.started_epoch,
            max_age_seconds=args.max_age,
        )
        print(json.dumps(result.as_dict(), separators=(",", ":")))
        return 0
    result = check_deployment_state(
        args.state_path,
        env_file=args.env_file,
        container_created=args.container_created,
        image_digest=args.image_digest,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
