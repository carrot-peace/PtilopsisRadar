# coding=utf-8
"""One-time, owner-only deployment notification with isolated local state."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Mapping

from trendradar.deployment.operator_alert import (
    OperatorTelegramSender as DeploymentTelegramSender,
    TelegramSendResult,
    send_owner_alert,
)
from trendradar.deployment.telegram_owner import resolve_telegram_owner_chat_ids


logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = Path("output/meta/deployment_notification.json")
STATE_SCHEMA_V1 = "deployment-notification-v1"
STATE_SCHEMA_V2 = "deployment-notification-v2"


@dataclass(frozen=True)
class DeploymentIdentity:
    image_name: str = "unknown"
    image_id: str = "unknown"
    build_id: str = "unknown"
    commit: str = "unknown"

    @property
    def stable(self) -> bool:
        return any(
            value and value != "unknown"
            for value in (self.image_id, self.build_id, self.commit)
        )

    @property
    def key(self) -> str:
        payload = json.dumps(
            {
                "image_name": self.image_name,
                "image_id": self.image_id,
                "build_id": self.build_id,
                "commit": self.commit,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DeploymentNotificationResult:
    status: str
    identity_key: str | None = None
    attempted_owner_count: int = 0
    delivered_owner_count: int = 0
    failed_owner_count: int = 0
    details: tuple[str, ...] = field(default_factory=tuple)


def _clean(value: object, default: str = "unknown") -> str:
    text = str(value or "").strip()
    return text or default


def identity_from_env(env: Mapping[str, str]) -> DeploymentIdentity:
    return DeploymentIdentity(
        image_name=_clean(
            env.get("PTILOPSIS_DEPLOYMENT_IMAGE_NAME"),
            "ptilopsis-radar",
        ),
        image_id=_clean(env.get("PTILOPSIS_DEPLOYMENT_IMAGE_ID")),
        build_id=_clean(env.get("PTILOPSIS_BUILD_ID")),
        commit=_clean(env.get("PTILOPSIS_BUILD_COMMIT")),
    )


def _owner_hash(chat_id: str) -> str:
    return hashlib.sha256(chat_id.encode("utf-8")).hexdigest()


class InvalidDeploymentState(ValueError):
    """Raised when persisted notification state cannot be trusted."""


def _is_sha256_hex(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _hashes(values: object) -> set[str]:
    if not isinstance(values, list) or not all(
        _is_sha256_hex(value) for value in values
    ):
        raise InvalidDeploymentState("invalid delivered owner hashes")
    return set(values)


def _load_state(path: Path) -> tuple[dict[str, set[str]], bool]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, False
    except (OSError, ValueError, TypeError) as exc:
        raise InvalidDeploymentState(type(exc).__name__) from exc

    if not isinstance(data, dict):
        raise InvalidDeploymentState("state root is not an object")

    schema = data.get("schema_version")
    if schema == STATE_SCHEMA_V1:
        identity_key = data.get("identity_key")
        if not _is_sha256_hex(identity_key):
            raise InvalidDeploymentState("v1 identity key is missing")
        return {
            identity_key: _hashes(data.get("delivered_owner_hashes"))
        }, True

    if schema != STATE_SCHEMA_V2:
        raise InvalidDeploymentState("unsupported state schema")
    raw_identities = data.get("identities")
    if not isinstance(raw_identities, dict):
        raise InvalidDeploymentState("v2 identities are missing")

    identities: dict[str, set[str]] = {}
    for identity_key, entry in raw_identities.items():
        if not _is_sha256_hex(identity_key):
            raise InvalidDeploymentState("invalid identity key")
        if not isinstance(entry, dict):
            raise InvalidDeploymentState("invalid identity entry")
        identities[identity_key] = _hashes(
            entry.get("delivered_owner_hashes")
        )
    return identities, False


def _write_state(
    path: Path,
    *,
    identities: Mapping[str, set[str]],
    updated_at: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": STATE_SCHEMA_V2,
        "identities": {
            identity_key: {
                "delivered_owner_hashes": sorted(delivered_owner_hashes),
                "updated_at": updated_at,
            }
            for identity_key, delivered_owner_hashes in sorted(
                identities.items()
            )
        },
        "updated_at": updated_at,
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _lock_state(path: Path) -> IO[str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_file = lock_path.open("a+", encoding="utf-8")
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
    return lock_file


def render_deployment_message(
    identity: DeploymentIdentity,
    *,
    started_at: str,
    health: str,
) -> str:
    display_image_id = (
        identity.image_id
        if identity.image_id != "unknown"
        else identity.build_id
    )
    return "\n".join(
        (
            "Ptilopsis Radar deployment updated",
            "",
            f"Image: {identity.image_name}",
            f"Image ID: {display_image_id}",
            f"Commit: {identity.commit}",
            f"Started: {started_at}",
            f"Health: {health}",
        )
    )


def notify_deployment(
    env: Mapping[str, str],
    *,
    health: str,
    state_path: str | Path = DEFAULT_STATE_PATH,
    sender: DeploymentTelegramSender | None = None,
    now: datetime | None = None,
) -> DeploymentNotificationResult:
    """Notify each configured owner once for the current deployment identity."""
    health_text = str(health or "").strip()
    if not health_text:
        logger.error("Deployment notification failed: explicit health is required")
        return DeploymentNotificationResult(status="failed_missing_health")

    identity = identity_from_env(env)
    if not identity.stable:
        logger.warning(
            "Deployment notification skipped: no stable image/build/commit identity"
        )
        return DeploymentNotificationResult(status="skipped_no_identity")

    owners = resolve_telegram_owner_chat_ids(env)
    if not owners:
        logger.warning(
            "Deployment notification skipped: no Telegram owner chat ids configured"
        )
        return DeploymentNotificationResult(
            status="skipped_no_owner",
            identity_key=identity.key,
        )

    bot_token = _clean(env.get("TELEGRAM_BOT_TOKEN"), "")
    if not bot_token:
        logger.error(
            "Deployment notification failed: TELEGRAM_BOT_TOKEN is not configured"
        )
        return DeploymentNotificationResult(
            status="failed_missing_token",
            identity_key=identity.key,
            failed_owner_count=len(owners),
        )

    effective_now = now or datetime.now(timezone.utc)
    if effective_now.tzinfo is None:
        effective_now = effective_now.replace(tzinfo=timezone.utc)
    started_at = effective_now.isoformat(timespec="seconds")
    message = render_deployment_message(
        identity,
        started_at=started_at,
        health=health_text,
    )
    state = Path(state_path)
    try:
        lock_file = _lock_state(state)
    except OSError as exc:
        logger.error(
            "Deployment notification state lock failed: %s", type(exc).__name__
        )
        return DeploymentNotificationResult(
            status="failed_state_access",
            identity_key=identity.key,
            failed_owner_count=len(owners),
        )

    succeeded = 0
    failed = 0
    details: list[str] = []
    with lock_file:
        try:
            identities, migrated = _load_state(state)
        except InvalidDeploymentState as exc:
            logger.error(
                "Deployment notification state is invalid; refusing to send: %s",
                str(exc),
            )
            return DeploymentNotificationResult(
                status="failed_invalid_state",
                identity_key=identity.key,
                failed_owner_count=len(owners),
                details=("invalid_state",),
            )

        delivered = identities.setdefault(identity.key, set())
        pending = [
            owner for owner in owners if _owner_hash(owner) not in delivered
        ]
        if not pending:
            if migrated:
                try:
                    _write_state(
                        state,
                        identities=identities,
                        updated_at=effective_now.isoformat(),
                    )
                except OSError as exc:
                    logger.error(
                        "Deployment notification state migration failed: %s",
                        type(exc).__name__,
                    )
                    return DeploymentNotificationResult(
                        status="failed_state_write",
                        identity_key=identity.key,
                        failed_owner_count=len(owners),
                    )
            return DeploymentNotificationResult(
                status="already_notified",
                identity_key=identity.key,
                delivered_owner_count=len(owners),
            )

        alert_result = send_owner_alert(
            env,
            message,
            sender=sender,
            owner_chat_ids=pending,
        )
        if not alert_result.deliveries:
            failed = len(pending)
            details.append(alert_result.status)

        for delivery in alert_result.deliveries:
            details.append(delivery.detail)
            if not delivery.ok:
                failed += 1
                continue

            delivered.add(_owner_hash(delivery.chat_id))
            try:
                _write_state(
                    state,
                    identities=identities,
                    updated_at=effective_now.isoformat(),
                )
            except OSError as exc:
                logger.error(
                    "Deployment notification state write failed after delivery to "
                    "owner hash %s: %s",
                    _owner_hash(delivery.chat_id)[:12],
                    type(exc).__name__,
                )
                failed += 1
                details.append(f"state_write_error:{type(exc).__name__}")
                break
            succeeded += 1

    status = "sent" if failed == 0 else "partial_failure"
    return DeploymentNotificationResult(
        status=status,
        identity_key=identity.key,
        attempted_owner_count=len(pending),
        delivered_owner_count=succeeded,
        failed_owner_count=failed,
        details=tuple(details),
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="Notify configured owners after verified deployment startup"
    )
    parser.add_argument(
        "--health",
        required=True,
        help="Explicit summary of startup checks that have already passed",
    )
    args = parser.parse_args()
    result = notify_deployment(os.environ, health=args.health)
    logger.info(
        "Deployment notification result: status=%s attempted=%d delivered=%d failed=%d",
        result.status,
        result.attempted_owner_count,
        result.delivered_owner_count,
        result.failed_owner_count,
    )
    failed = bool(
        result.failed_owner_count or result.status.startswith("failed_")
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
