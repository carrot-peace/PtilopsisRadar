# coding=utf-8
"""Private-chat subscription bot using Telegram long polling."""

from __future__ import annotations

import fcntl
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Mapping

from trendradar.telegram.subscriptions import (
    SubscriptionStore,
    TokenIssue,
    resolve_owner_chat_ids,
    subscription_db_path_from_env,
    subscriptions_enabled,
)
from trendradar.telegram.transport import (
    TelegramHTTPResponse,
    TelegramTransport,
    transport_config_from_env,
)


logger = logging.getLogger(__name__)

GUIDE_TEXT = (
    "欢迎使用 Ptilopsis Radar 推送 Bot。\n\n"
    "订阅需要 Owner 提供的一次性 Token。获得 Token 后发送：\n"
    "/subscribe <token>\n\n"
    "订阅成功后你会收到 CR/DR 消息；本 Bot 不接受内容发布。"
)
HELP_TEXT = (
    f"{GUIDE_TEXT}\n\n"
    "可用命令：\n"
    "/start - 查看引导\n"
    "/help - 查看帮助\n"
    "/subscribe <token> - 订阅消息\n"
    "/unsubscribe - 取消订阅"
)
OWNER_HELP_SUFFIX = "\n/token - 生成一个 15 分钟有效的一次性订阅 Token"
INVALID_TOKEN_TEXT = "Token 无效、已过期或已经使用，请向 Owner 获取新的 Token。"


class FatalPollingError(RuntimeError):
    """A polling error that requires operator intervention or process restart."""


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
        handle = self._handle
        self._handle = None
        if handle is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()


@dataclass
class SubscriptionBotService:
    transport: TelegramTransport
    store: SubscriptionStore
    owner_chat_ids: frozenset[str]

    def handle_update(self, update: object) -> None:
        if not isinstance(update, dict):
            return
        raw_update_id = update.get("update_id")
        if not isinstance(raw_update_id, int):
            return
        message = update.get("message")
        if not isinstance(message, dict):
            self.store.advance_update(raw_update_id)
            return
        chat = message.get("chat")
        sender = message.get("from")
        if not isinstance(chat, dict) or not isinstance(sender, dict):
            self.store.advance_update(raw_update_id)
            return
        if chat.get("type") != "private":
            self.store.advance_update(raw_update_id)
            return

        chat_id = str(chat.get("id") or "")
        user_id = str(sender.get("id") or "")
        if not chat_id or not user_id or chat_id != user_id:
            self.store.advance_update(raw_update_id)
            return
        text = message.get("text")
        if not isinstance(text, str):
            self.store.advance_update(raw_update_id)
            return
        stripped = text.strip()
        if not stripped.startswith("/"):
            self.store.advance_update(raw_update_id)
            return

        parts = stripped.split(maxsplit=1)
        command = parts[0].split("@", 1)[0].lower()
        argument = parts[1].strip() if len(parts) == 2 else ""
        is_owner = chat_id in self.owner_chat_ids

        if command == "/start":
            result = self.store.reactivate_blocked(
                update_id=raw_update_id,
                chat_id=chat_id,
                user_id=user_id,
            )
            if result.applied:
                suffix = OWNER_HELP_SUFFIX if is_owner else ""
                self._reply(chat_id, GUIDE_TEXT + suffix)
            return

        if command == "/help":
            if self.store.advance_update(raw_update_id):
                suffix = OWNER_HELP_SUFFIX if is_owner else ""
                self._reply(chat_id, HELP_TEXT + suffix)
            return

        if command == "/token":
            if not is_owner:
                if self.store.advance_update(raw_update_id):
                    self._reply(chat_id, HELP_TEXT)
                return
            result = self.store.issue_token(
                update_id=raw_update_id,
                owner_chat_id=chat_id,
            )
            if result.applied and isinstance(result.value, TokenIssue):
                self._reply(
                    chat_id,
                    "一次性订阅 Token（15 分钟内有效）：\n"
                    f"{result.value.token}\n\n"
                    "使用方式：/subscribe <token>",
                )
            return

        if command == "/subscribe":
            if not argument:
                if self.store.advance_update(raw_update_id):
                    self._reply(chat_id, "请使用：/subscribe <token>")
                return
            result = self.store.redeem_token(
                update_id=raw_update_id,
                token=argument,
                chat_id=chat_id,
                user_id=user_id,
            )
            if not result.applied:
                return
            if result.value == "subscribed":
                self._reply(chat_id, "订阅成功。你现在会收到 CR/DR 推送。")
            elif result.value == "already_active":
                self._reply(chat_id, "你已经处于订阅状态。")
            else:
                self._reply(chat_id, INVALID_TOKEN_TEXT)
            return

        if command == "/unsubscribe":
            if is_owner:
                if self.store.advance_update(raw_update_id):
                    self._reply(chat_id, "Owner 是固定接收者，不能取消订阅。")
                return
            result = self.store.unsubscribe(
                update_id=raw_update_id,
                chat_id=chat_id,
            )
            if result.applied:
                if result.value == "unsubscribed":
                    self._reply(chat_id, "已取消订阅。再次订阅需要新的 Token。")
                else:
                    self._reply(chat_id, "你当前没有有效订阅。")
            return

        if self.store.advance_update(raw_update_id):
            suffix = OWNER_HELP_SUFFIX if is_owner else ""
            self._reply(chat_id, HELP_TEXT + suffix)

    def _reply(self, chat_id: str, text: str) -> None:
        response = self.transport.send_message(chat_id=chat_id, text=text)
        if not response.ok:
            raise ConnectionError(
                f"Telegram command reply rejected with HTTP {response.status_code}"
            )


def _assert_no_webhook(transport: TelegramTransport) -> None:
    response = transport.get_webhook_info()
    _raise_for_fatal_status(response)
    if not response.ok:
        raise ConnectionError(
            f"getWebhookInfo failed with HTTP {response.status_code}"
        )
    result = response.result
    if isinstance(result, dict) and str(result.get("url") or "").strip():
        raise FatalPollingError(
            "Telegram webhook is configured; getUpdates cannot be used"
        )


def _raise_for_fatal_status(response: TelegramHTTPResponse) -> None:
    if response.status_code in {401, 409}:
        raise FatalPollingError(
            f"Telegram polling failed with HTTP {response.status_code}"
        )


def run_poller(env: Mapping[str, str]) -> None:
    if not subscriptions_enabled(env):
        logger.info("Telegram subscriptions are disabled")
        return
    owners = frozenset(resolve_owner_chat_ids(env))
    if not owners:
        raise FatalPollingError("TELEGRAM_OWNER_CHAT_IDS is required")

    db_path = subscription_db_path_from_env(env)
    store = SubscriptionStore(db_path)
    transport = TelegramTransport(transport_config_from_env(env))
    service = SubscriptionBotService(
        transport=transport,
        store=store,
        owner_chat_ids=owners,
    )
    lock_path = db_path.with_suffix(db_path.suffix + ".lock")

    with InstanceLock(lock_path):
        _assert_no_webhook(transport)
        logger.info("Telegram subscription poller started")
        backoff_seconds = 1.0
        while True:
            try:
                response = transport.get_updates(
                    offset=store.last_update_id() + 1,
                    timeout_seconds=50,
                )
                _raise_for_fatal_status(response)
                if not response.ok:
                    raise ConnectionError(
                        f"getUpdates failed with HTTP {response.status_code}"
                    )
                updates = response.result
                if not isinstance(updates, list):
                    raise ConnectionError("getUpdates returned an invalid result")
                for update in updates:
                    service.handle_update(update)
                backoff_seconds = 1.0
            except FatalPollingError:
                raise
            except (ConnectionError, OSError, TimeoutError) as exc:
                logger.warning(
                    "Telegram poller transient error: %s; retrying in %.0fs",
                    type(exc).__name__,
                    backoff_seconds,
                )
                time.sleep(backoff_seconds)
                backoff_seconds = min(backoff_seconds * 2, 30.0)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        run_poller(os.environ)
    except FatalPollingError as exc:
        logger.error("Telegram poller stopped: %s", exc)
        return 1
    except ValueError as exc:
        logger.error("Telegram poller configuration error: %s", exc)
        return 1
    except (ConnectionError, OSError, TimeoutError) as exc:
        logger.error(
            "Telegram poller startup transport error: %s",
            type(exc).__name__,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
