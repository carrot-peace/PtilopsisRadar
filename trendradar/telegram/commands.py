# coding=utf-8
"""Pure private-chat commands for the Telegram subscription Bot."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from trendradar.telegram.subscriptions import (
    TokenIssue,
    UpdateMutationResult,
)


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


class SubscriptionCommandStore(Protocol):
    def advance_update(self, update_id: int) -> bool:
        ...

    def reactivate_blocked(
        self,
        *,
        update_id: int,
        chat_id: str,
        user_id: str,
    ) -> UpdateMutationResult:
        ...

    def issue_token(
        self,
        *,
        update_id: int,
        owner_chat_id: str,
    ) -> UpdateMutationResult:
        ...

    def redeem_token(
        self,
        *,
        update_id: int,
        token: str,
        chat_id: str,
        user_id: str,
    ) -> UpdateMutationResult:
        ...

    def unsubscribe(
        self,
        *,
        update_id: int,
        chat_id: str,
    ) -> UpdateMutationResult:
        ...


@dataclass(frozen=True)
class BotReply:
    chat_id: str
    text: str = field(repr=False)


@dataclass
class SubscriptionCommandHandler:
    """Consume one update before returning its at-most-once reply."""

    store: SubscriptionCommandStore
    owner_chat_ids: frozenset[str]

    def handle_update(self, update: object) -> BotReply | None:
        if not isinstance(update, dict):
            return None
        update_id = update.get("update_id")
        if type(update_id) is not int:
            return None

        message = update.get("message")
        if not isinstance(message, dict):
            return self._ignore(update_id)
        chat = message.get("chat")
        sender = message.get("from")
        if not isinstance(chat, dict) or not isinstance(sender, dict):
            return self._ignore(update_id)
        if chat.get("type") != "private" or sender.get("is_bot") is True:
            return self._ignore(update_id)

        raw_chat_id = chat.get("id")
        raw_user_id = sender.get("id")
        if (
            type(raw_chat_id) is not int
            or type(raw_user_id) is not int
            or raw_chat_id <= 0
            or raw_chat_id != raw_user_id
        ):
            return self._ignore(update_id)
        chat_id = str(raw_chat_id)
        user_id = str(raw_user_id)

        text = message.get("text")
        if not isinstance(text, str):
            return self._ignore(update_id)
        stripped = text.strip()
        if not stripped.startswith("/"):
            return self._ignore(update_id)

        parts = stripped.split(maxsplit=1)
        command = parts[0].split("@", 1)[0].lower()
        argument = parts[1].strip() if len(parts) == 2 else ""
        is_owner = chat_id in self.owner_chat_ids

        if command == "/start":
            result = self.store.reactivate_blocked(
                update_id=update_id,
                chat_id=chat_id,
                user_id=user_id,
            )
            return self._when_applied(
                result,
                chat_id,
                GUIDE_TEXT + (OWNER_HELP_SUFFIX if is_owner else ""),
            )

        if command == "/help":
            return self._advance_and_reply(
                update_id,
                chat_id,
                HELP_TEXT + (OWNER_HELP_SUFFIX if is_owner else ""),
            )

        if command == "/token":
            if not is_owner:
                return self._advance_and_reply(update_id, chat_id, HELP_TEXT)
            result = self.store.issue_token(
                update_id=update_id,
                owner_chat_id=chat_id,
            )
            if not result.applied or not isinstance(result.value, TokenIssue):
                return None
            return BotReply(
                chat_id,
                "一次性订阅 Token（15 分钟内有效）：\n"
                f"{result.value.token}\n\n"
                "使用方式：/subscribe <token>",
            )

        if command == "/subscribe":
            if not argument:
                return self._advance_and_reply(
                    update_id,
                    chat_id,
                    "请使用：/subscribe <token>",
                )
            result = self.store.redeem_token(
                update_id=update_id,
                token=argument,
                chat_id=chat_id,
                user_id=user_id,
            )
            if not result.applied:
                return None
            if result.value == "subscribed":
                text = "订阅成功。你现在会收到 CR/DR 推送。"
            elif result.value == "already_active":
                text = "你已经处于订阅状态。"
            else:
                text = INVALID_TOKEN_TEXT
            return BotReply(chat_id, text)

        if command == "/unsubscribe":
            if is_owner:
                return self._advance_and_reply(
                    update_id,
                    chat_id,
                    "Owner 是固定接收者，不能取消订阅。",
                )
            result = self.store.unsubscribe(
                update_id=update_id,
                chat_id=chat_id,
            )
            if not result.applied:
                return None
            text = (
                "已取消订阅。再次订阅需要新的 Token。"
                if result.value == "unsubscribed"
                else "你当前没有有效订阅。"
            )
            return BotReply(chat_id, text)

        return self._advance_and_reply(
            update_id,
            chat_id,
            HELP_TEXT + (OWNER_HELP_SUFFIX if is_owner else ""),
        )

    def _ignore(self, update_id: int) -> None:
        self.store.advance_update(update_id)
        return None

    def _advance_and_reply(
        self,
        update_id: int,
        chat_id: str,
        text: str,
    ) -> BotReply | None:
        return BotReply(chat_id, text) if self.store.advance_update(update_id) else None

    @staticmethod
    def _when_applied(
        result: UpdateMutationResult,
        chat_id: str,
        text: str,
    ) -> BotReply | None:
        return BotReply(chat_id, text) if result.applied else None
