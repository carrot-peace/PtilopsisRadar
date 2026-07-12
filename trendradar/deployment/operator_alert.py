# coding=utf-8
"""Owner-only operator alerts shared by deployment and supervisor paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from trendradar.telegram_bot.access import build_telegram_access_config


logger = logging.getLogger(__name__)
DEFAULT_API_BASE_URL = "https://api.telegram.org"


@dataclass(frozen=True)
class TelegramSendResult:
    ok: bool
    detail: str


class OperatorTelegramSender(Protocol):
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
class UrllibOperatorTelegramSender:
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
class OwnerDelivery:
    chat_id: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class OwnerAlertResult:
    status: str
    deliveries: tuple[OwnerDelivery, ...] = field(default_factory=tuple)

    @property
    def failed_count(self) -> int:
        return sum(not delivery.ok for delivery in self.deliveries)


def _clean(value: object, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _owner_hash(chat_id: str) -> str:
    return hashlib.sha256(chat_id.encode("utf-8")).hexdigest()[:12]


def send_owner_alert(
    env: Mapping[str, str],
    text: str,
    *,
    sender: OperatorTelegramSender | None = None,
    owner_chat_ids: Sequence[str] | None = None,
) -> OwnerAlertResult:
    """Send text only to configured owners, optionally narrowed to a subset."""
    access = build_telegram_access_config(dict(env))
    configured = list(access.get("owner_chat_ids") or [])
    if owner_chat_ids is None:
        owners = configured
    else:
        requested = set(owner_chat_ids)
        owners = [owner for owner in configured if owner in requested]
    if not owners:
        logger.warning("Operator alert skipped: no eligible owner chat ids")
        return OwnerAlertResult(status="skipped_no_owner")

    bot_token = _clean(env.get("TELEGRAM_BOT_TOKEN"))
    if not bot_token:
        logger.error("Operator alert failed: TELEGRAM_BOT_TOKEN is not configured")
        return OwnerAlertResult(
            status="failed_missing_token",
            deliveries=tuple(
                OwnerDelivery(owner, False, "missing_token") for owner in owners
            ),
        )

    try:
        timeout = float(env.get("TELEGRAM_TIMEOUT_SECONDS", "10"))
        if timeout <= 0:
            raise ValueError
    except (TypeError, ValueError):
        timeout = 10.0

    transport = sender or UrllibOperatorTelegramSender()
    api_base_url = _clean(
        env.get("TELEGRAM_API_BASE_URL"), DEFAULT_API_BASE_URL
    )
    deliveries: list[OwnerDelivery] = []
    for owner in owners:
        try:
            result = transport.send(
                bot_token=bot_token,
                chat_id=owner,
                text=text,
                api_base_url=api_base_url,
                timeout_seconds=timeout,
            )
        except Exception as exc:  # noqa: BLE001 - alert failures stay diagnostic
            detail = f"transport_error:{type(exc).__name__}"
            logger.error(
                "Operator alert transport failed for owner hash %s: %s",
                _owner_hash(owner),
                type(exc).__name__,
            )
            deliveries.append(OwnerDelivery(owner, False, detail))
            continue
        if not result.ok:
            logger.error(
                "Operator alert rejected for owner hash %s: %s",
                _owner_hash(owner),
                result.detail,
            )
        deliveries.append(
            OwnerDelivery(owner, result.ok, result.detail)
        )

    status = "sent" if all(item.ok for item in deliveries) else "partial_failure"
    return OwnerAlertResult(status=status, deliveries=tuple(deliveries))


def load_env_file(path: str | Path) -> dict[str, str]:
    """Load the small KEY=VALUE subset needed by the operator alert CLI."""
    values: dict[str, str] = {}
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key in {
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_OWNER_CHAT_IDS",
            "TELEGRAM_CHAT_ID",
            "TELEGRAM_API_BASE_URL",
            "TELEGRAM_TIMEOUT_SECONDS",
        }:
            values[key] = value
    return values


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send an owner-only operator alert")
    parser.add_argument("--message", required=True)
    parser.add_argument("--env-file")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    env = dict(os.environ)
    if args.env_file:
        try:
            env.update(load_env_file(args.env_file))
        except OSError as exc:
            logger.error("Operator alert env file unavailable: %s", type(exc).__name__)
            return 1
    result = send_owner_alert(env, args.message)
    logger.info(
        "Operator alert result: status=%s delivered=%d failed=%d",
        result.status,
        sum(item.ok for item in result.deliveries),
        result.failed_count,
    )
    return 0 if result.status == "sent" else 1


if __name__ == "__main__":
    raise SystemExit(main())
