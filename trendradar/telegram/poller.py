# coding=utf-8
"""Manual long-polling runtime for Telegram subscription commands."""

from __future__ import annotations

import fcntl
import logging
import os
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from trendradar.telegram.commands import SubscriptionCommandHandler
from trendradar.telegram.subscriptions import (
    DEFAULT_SUBSCRIPTION_DB_PATH,
    SubscriptionStore,
)
from trendradar.telegram.transport import (
    TelegramHTTPClient,
    TelegramHTTPResponse,
    TelegramTransport,
    transport_config_from_env,
)


logger = logging.getLogger(__name__)
_TRANSIENT_ERRORS = (ConnectionError, OSError, TimeoutError)


class FatalPollingError(RuntimeError):
    """A polling failure that cannot be repaired by retrying."""


def subscriptions_enabled(env: Mapping[str, str]) -> bool:
    return env.get("PTILOPSIS_TELEGRAM_SUBSCRIPTIONS_ENABLED") == "1"


def subscription_db_path_from_env(env: Mapping[str, str]) -> Path:
    raw = str(env.get("PTILOPSIS_TELEGRAM_SUBSCRIPTION_DB_PATH") or "").strip()
    return Path(raw) if raw else DEFAULT_SUBSCRIPTION_DB_PATH


def resolve_owner_chat_ids(env: Mapping[str, str]) -> frozenset[str]:
    values = str(env.get("TELEGRAM_OWNER_CHAT_IDS") or "").split(",")
    return frozenset(value.strip() for value in values if value.strip())


def _raise_for_fatal_status(response: TelegramHTTPResponse) -> None:
    if response.status_code in {401, 409}:
        raise FatalPollingError(
            f"Telegram polling failed with HTTP {response.status_code}"
        )


@dataclass
class InstanceLock:
    path: Path
    _handle: object | None = None

    def __enter__(self) -> "InstanceLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        os.chmod(self.path, 0o600)
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise FatalPollingError("another Telegram poller holds the lock") from exc
        self._handle = handle
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        handle = self._handle
        self._handle = None
        if handle is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()


@dataclass
class TelegramPollingRunner:
    transport: TelegramTransport
    handler: SubscriptionCommandHandler
    store: SubscriptionStore
    sleep: Callable[[float], None] = time.sleep

    def assert_no_webhook(self) -> None:
        response = self.transport.get_webhook_info()
        _raise_for_fatal_status(response)
        if not response.ok:
            raise ConnectionError(
                f"webhook inspection failed with HTTP {response.status_code}"
            )
        result = response.result
        if isinstance(result, dict) and str(result.get("url") or "").strip():
            raise FatalPollingError(
                "Telegram webhook is configured; polling cannot start"
            )

    def poll_once(self) -> None:
        response = self.transport.get_updates(
            offset=self.store.last_update_id() + 1,
            timeout_seconds=50,
        )
        _raise_for_fatal_status(response)
        if not response.ok:
            raise ConnectionError(
                f"polling request failed with HTTP {response.status_code}"
            )
        updates = response.result
        if not isinstance(updates, list):
            raise ConnectionError("polling request returned an invalid result")
        for update in updates:
            reply = self.handler.handle_update(update)
            if reply is None:
                continue
            # State and offset are already committed: replies are at-most-once.
            sent = self.transport.send_message(
                chat_id=reply.chat_id,
                text=reply.text,
            )
            _raise_for_fatal_status(sent)
            if not sent.ok:
                raise ConnectionError(
                    f"command reply rejected with HTTP {sent.status_code}"
                )

    def run_forever(self) -> None:
        self.assert_no_webhook()
        backoff_seconds = 1.0
        while True:
            try:
                self.poll_once()
                backoff_seconds = 1.0
            except FatalPollingError:
                raise
            except _TRANSIENT_ERRORS as exc:
                logger.warning(
                    "Telegram poller transient error: %s; retrying in %.0fs",
                    type(exc).__name__,
                    backoff_seconds,
                )
                self.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, 30.0)


def build_runner(
    env: Mapping[str, str],
    *,
    http_client: TelegramHTTPClient | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[TelegramPollingRunner, Path]:
    owners = resolve_owner_chat_ids(env)
    if not owners:
        raise ValueError("TELEGRAM_OWNER_CHAT_IDS is required")
    db_path = subscription_db_path_from_env(env)
    store = SubscriptionStore(db_path)
    transport = TelegramTransport(
        transport_config_from_env(env),
        http_client=http_client,
    )
    handler = SubscriptionCommandHandler(store=store, owner_chat_ids=owners)
    runner = TelegramPollingRunner(transport, handler, store, sleep=sleep)
    return runner, db_path.with_suffix(db_path.suffix + ".lock")


def run_poller(env: Mapping[str, str]) -> None:
    if not subscriptions_enabled(env):
        logger.info("Telegram subscriptions are disabled")
        return
    runner, lock_path = build_runner(env)
    with InstanceLock(lock_path):
        logger.info("Telegram subscription poller started")
        runner.run_forever()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        run_poller(os.environ)
    except (FatalPollingError, ValueError) as exc:
        logger.error("Telegram poller stopped: %s", exc)
        return 1
    except _TRANSIENT_ERRORS as exc:
        logger.error(
            "Telegram poller startup transport error: %s",
            type(exc).__name__,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
