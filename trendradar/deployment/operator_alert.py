# coding=utf-8
"""Owner-only operator alerts shared by deployment and supervisor paths."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Mapping, Protocol, Sequence

from trendradar.telegram_bot.access import build_telegram_access_config


logger = logging.getLogger(__name__)
DEFAULT_API_BASE_URL = "https://api.telegram.org"
DEFAULT_ALERT_STATE_PATH = Path("output/meta/supervisor-alerts.json")
ALERT_STATE_SCHEMA = "supervisor-alerts-v1"


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
    return hashlib.sha256(chat_id.encode("utf-8")).hexdigest()


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
                _owner_hash(owner)[:12],
                type(exc).__name__,
            )
            deliveries.append(OwnerDelivery(owner, False, detail))
            continue
        if not result.ok:
            logger.error(
                "Operator alert rejected for owner hash %s: %s",
                _owner_hash(owner)[:12],
                result.detail,
            )
        deliveries.append(
            OwnerDelivery(owner, result.ok, result.detail)
        )

    status = "sent" if all(item.ok for item in deliveries) else "partial_failure"
    return OwnerAlertResult(status=status, deliveries=tuple(deliveries))


class InvalidOperatorAlertState(ValueError):
    """Raised when supervisor alert state is malformed or unsupported."""


@dataclass(frozen=True)
class StatefulOwnerAlertResult:
    status: str
    deliveries: tuple[OwnerDelivery, ...] = field(default_factory=tuple)
    suppressed_owner_count: int = 0

    @property
    def failed_count(self) -> int:
        return sum(not delivery.ok for delivery in self.deliveries)


def _load_alert_state(path: Path) -> dict[str, dict[str, int]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, TypeError, ValueError) as exc:
        raise InvalidOperatorAlertState(type(exc).__name__) from exc
    if not isinstance(data, dict) or data.get("schema_version") != ALERT_STATE_SCHEMA:
        raise InvalidOperatorAlertState("unsupported state schema")
    raw_incidents = data.get("incidents")
    if not isinstance(raw_incidents, dict):
        raise InvalidOperatorAlertState("incidents are missing")
    incidents: dict[str, dict[str, int]] = {}
    for code, entry in raw_incidents.items():
        if not isinstance(code, str) or not code or not isinstance(entry, dict):
            raise InvalidOperatorAlertState("invalid incident")
        raw_owners = entry.get("delivered_owner_epochs")
        if not isinstance(raw_owners, dict):
            raise InvalidOperatorAlertState("owner delivery epochs are missing")
        owners: dict[str, int] = {}
        for owner_hash, epoch in raw_owners.items():
            if (
                not isinstance(owner_hash, str)
                or len(owner_hash) != 64
                or not isinstance(epoch, int)
                or epoch < 0
            ):
                raise InvalidOperatorAlertState("invalid owner delivery epoch")
            try:
                int(owner_hash, 16)
            except ValueError as exc:
                raise InvalidOperatorAlertState("invalid owner hash") from exc
            owners[owner_hash] = epoch
        incidents[code] = owners
    return incidents


def _write_alert_state(
    path: Path,
    incidents: Mapping[str, Mapping[str, int]],
    *,
    updated_at: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": ALERT_STATE_SCHEMA,
        "incidents": {
            code: {
                "delivered_owner_epochs": dict(sorted(owners.items())),
            }
            for code, owners in sorted(incidents.items())
        },
        "updated_at": updated_at,
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _lock_alert_state(path: Path) -> IO[str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = path.with_suffix(path.suffix + ".lock").open(
        "a+", encoding="utf-8"
    )
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
    return lock_file


def _rotate_invalid_alert_state(path: Path, *, now_epoch: int) -> None:
    if not path.exists():
        return
    corrupt = path.with_name(f"{path.name}.corrupt.{now_epoch}")
    suffix = 1
    while corrupt.exists():
        corrupt = path.with_name(f"{path.name}.corrupt.{now_epoch}.{suffix}")
        suffix += 1
    path.replace(corrupt)


def send_stateful_owner_alert(
    env: Mapping[str, str],
    text: str,
    *,
    code: str,
    state_path: str | Path = DEFAULT_ALERT_STATE_PATH,
    repeat_seconds: int = 3600,
    sender: OperatorTelegramSender | None = None,
    now: datetime | None = None,
) -> StatefulOwnerAlertResult:
    """Send one active incident to owners with per-owner repeat suppression."""
    diagnostic_code = str(code or "").strip()
    if not diagnostic_code or repeat_seconds <= 0:
        return StatefulOwnerAlertResult(status="failed_invalid_arguments")

    access = build_telegram_access_config(dict(env))
    owners = list(access.get("owner_chat_ids") or [])
    if not owners:
        return StatefulOwnerAlertResult(status="skipped_no_owner")

    effective_now = now or datetime.now(timezone.utc)
    if effective_now.tzinfo is None:
        effective_now = effective_now.replace(tzinfo=timezone.utc)
    now_epoch = int(effective_now.timestamp())
    state = Path(state_path)
    try:
        lock_file = _lock_alert_state(state)
    except OSError:
        return StatefulOwnerAlertResult(status="failed_state_access")

    with lock_file:
        try:
            incidents = _load_alert_state(state)
        except InvalidOperatorAlertState as exc:
            logger.error(
                "Operator alert state is invalid; rotating it: %s", str(exc)
            )
            try:
                _rotate_invalid_alert_state(state, now_epoch=now_epoch)
            except OSError:
                return StatefulOwnerAlertResult(status="failed_state_access")
            incidents = {}

        delivered_epochs = incidents.setdefault(diagnostic_code, {})
        pending: list[str] = []
        for owner in owners:
            last_delivered = delivered_epochs.get(_owner_hash(owner))
            # A future timestamp is not trustworthy suppression evidence.  Send
            # fail-open and replace it with the current successful delivery.
            if (
                last_delivered is None
                or last_delivered > now_epoch
                or now_epoch - last_delivered >= repeat_seconds
            ):
                pending.append(owner)
        if not pending:
            return StatefulOwnerAlertResult(
                status="already_notified",
                suppressed_owner_count=len(owners),
            )

        result = send_owner_alert(
            env,
            text,
            sender=sender,
            owner_chat_ids=pending,
        )
        for delivery in result.deliveries:
            if not delivery.ok:
                continue
            delivered_epochs[_owner_hash(delivery.chat_id)] = now_epoch
            try:
                _write_alert_state(
                    state,
                    incidents,
                    updated_at=effective_now.isoformat(timespec="seconds"),
                )
            except OSError:
                return StatefulOwnerAlertResult(
                    status="failed_state_write",
                    deliveries=result.deliveries,
                    suppressed_owner_count=len(owners) - len(pending),
                )

        status = "sent" if result.status == "sent" else "partial_failure"
        return StatefulOwnerAlertResult(
            status=status,
            deliveries=result.deliveries,
            suppressed_owner_count=len(owners) - len(pending),
        )


def clear_operator_alert_state(
    state_path: str | Path = DEFAULT_ALERT_STATE_PATH,
    *,
    now: datetime | None = None,
) -> bool:
    """Clear active incidents after a fully healthy supervisor cycle."""
    effective_now = now or datetime.now(timezone.utc)
    if effective_now.tzinfo is None:
        effective_now = effective_now.replace(tzinfo=timezone.utc)
    state = Path(state_path)
    try:
        lock_file = _lock_alert_state(state)
    except OSError:
        return False
    with lock_file:
        if not state.exists():
            return True
        try:
            incidents = _load_alert_state(state)
        except InvalidOperatorAlertState:
            try:
                _rotate_invalid_alert_state(
                    state, now_epoch=int(effective_now.timestamp())
                )
            except OSError:
                return False
            incidents = {"invalid_state": {}}
        if not incidents:
            return True
        try:
            _write_alert_state(
                state,
                {},
                updated_at=effective_now.isoformat(timespec="seconds"),
            )
        except OSError:
            return False
    return True


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
    parser.add_argument("--message")
    parser.add_argument("--code")
    parser.add_argument("--env-file")
    parser.add_argument("--state-path", default=str(DEFAULT_ALERT_STATE_PATH))
    parser.add_argument("--repeat-seconds", type=int, default=3600)
    parser.add_argument("--clear-state", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.clear_state:
        return 0 if clear_operator_alert_state(args.state_path) else 1
    if not args.message or not args.code or args.repeat_seconds <= 0:
        parser.error("--message, --code, and a positive --repeat-seconds are required")
    env = dict(os.environ)
    if args.env_file:
        try:
            env.update(load_env_file(args.env_file))
        except OSError as exc:
            logger.error("Operator alert env file unavailable: %s", type(exc).__name__)
            return 1
    result = send_stateful_owner_alert(
        env,
        args.message,
        code=args.code,
        state_path=args.state_path,
        repeat_seconds=args.repeat_seconds,
    )
    logger.info(
        "Operator alert result: status=%s delivered=%d failed=%d",
        result.status,
        sum(item.ok for item in result.deliveries),
        result.failed_count,
    )
    return 0 if result.status in {"sent", "already_notified"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
