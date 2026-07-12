# coding=utf-8
"""One-time, owner-only deployment notification with isolated local state."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Protocol

from trendradar.telegram_bot.access import build_telegram_access_config


logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = Path("output/meta/deployment_notification.json")
DEFAULT_API_BASE_URL = "https://api.telegram.org"


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
class TelegramSendResult:
    ok: bool
    detail: str


class DeploymentTelegramSender(Protocol):
    def send(
        self,
        *,
        bot_token: str,
        chat_id: str,
        text: str,
        api_base_url: str,
        timeout_seconds: float,
    ) -> TelegramSendResult:
        ...


@dataclass
class UrllibDeploymentTelegramSender:
    def send(
        self,
        *,
        bot_token: str,
        chat_id: str,
        text: str,
        api_base_url: str,
        timeout_seconds: float,
    ) -> TelegramSendResult:
        url = f"{api_base_url.rstrip('/')}/bot{bot_token}/sendMessage"
        payload = json.dumps(
            {
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=timeout_seconds
            ) as response:
                status = int(
                    getattr(response, "status", None) or response.getcode()
                )
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            body = exc.read().decode("utf-8", errors="replace")

        try:
            decoded = json.loads(body)
        except (TypeError, ValueError):
            decoded = {}
        accepted = 200 <= status < 300 and decoded.get("ok") is True
        return TelegramSendResult(
            ok=accepted,
            detail="telegram_ok" if accepted else f"telegram_http_{status}",
        )


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


def _load_state(path: Path, identity_key: str) -> set[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return set()
    if not isinstance(data, dict) or data.get("identity_key") != identity_key:
        return set()
    values = data.get("delivered_owner_hashes") or []
    return {str(value) for value in values if str(value)}


def _write_state(
    path: Path,
    *,
    identity_key: str,
    delivered_owner_hashes: set[str],
    updated_at: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "deployment-notification-v1",
        "identity_key": identity_key,
        "delivered_owner_hashes": sorted(delivered_owner_hashes),
        "updated_at": updated_at,
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


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
    state_path: str | Path = DEFAULT_STATE_PATH,
    sender: DeploymentTelegramSender | None = None,
    now: datetime | None = None,
) -> DeploymentNotificationResult:
    """Notify each configured owner once for the current deployment identity."""
    identity = identity_from_env(env)
    if not identity.stable:
        logger.warning(
            "Deployment notification skipped: no stable image/build/commit identity"
        )
        return DeploymentNotificationResult(status="skipped_no_identity")

    access = build_telegram_access_config(dict(env))
    owners = list(access.get("owner_chat_ids") or [])
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

    state = Path(state_path)
    delivered = _load_state(state, identity.key)
    pending = [owner for owner in owners if _owner_hash(owner) not in delivered]
    if not pending:
        return DeploymentNotificationResult(
            status="already_notified",
            identity_key=identity.key,
            delivered_owner_count=len(owners),
        )

    effective_now = now or datetime.now(timezone.utc)
    if effective_now.tzinfo is None:
        effective_now = effective_now.replace(tzinfo=timezone.utc)
    started_at = effective_now.isoformat(timespec="seconds")
    message = render_deployment_message(
        identity,
        started_at=started_at,
        health=_clean(
            env.get("PTILOPSIS_DEPLOYMENT_HEALTH"),
            "startup checks passed",
        ),
    )
    transport = sender or UrllibDeploymentTelegramSender()
    api_base_url = _clean(
        env.get("TELEGRAM_API_BASE_URL"), DEFAULT_API_BASE_URL
    )
    try:
        timeout = float(env.get("TELEGRAM_TIMEOUT_SECONDS", "10"))
        if timeout <= 0:
            raise ValueError
    except (TypeError, ValueError):
        timeout = 10.0

    succeeded = 0
    failed = 0
    details: list[str] = []
    for owner in pending:
        try:
            result = transport.send(
                bot_token=bot_token,
                chat_id=owner,
                text=message,
                api_base_url=api_base_url,
                timeout_seconds=timeout,
            )
        except Exception as exc:  # noqa: BLE001 - deployment notification is non-fatal
            logger.error(
                "Deployment notification transport failed for owner hash %s: %s",
                _owner_hash(owner)[:12],
                type(exc).__name__,
            )
            failed += 1
            details.append(f"transport_error:{type(exc).__name__}")
            continue

        details.append(result.detail)
        if not result.ok:
            failed += 1
            logger.error(
                "Deployment notification rejected for owner hash %s: %s",
                _owner_hash(owner)[:12],
                result.detail,
            )
            continue

        succeeded += 1
        delivered.add(_owner_hash(owner))
        _write_state(
            state,
            identity_key=identity.key,
            delivered_owner_hashes=delivered,
            updated_at=effective_now.isoformat(),
        )

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
    result = notify_deployment(os.environ)
    logger.info(
        "Deployment notification result: status=%s attempted=%d delivered=%d failed=%d",
        result.status,
        result.attempted_owner_count,
        result.delivered_owner_count,
        result.failed_owner_count,
    )
    return 1 if result.failed_owner_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
