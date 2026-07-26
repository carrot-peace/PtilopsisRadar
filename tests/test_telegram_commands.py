# coding=utf-8
"""Pure Telegram subscription command tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from trendradar.telegram.commands import (
    HELP_TEXT,
    INVALID_TOKEN_TEXT,
    BotReply,
    SubscriptionCommandHandler,
)
from trendradar.telegram.subscriptions import SubscriptionStore


class MutableClock:
    def __init__(self, value: int = 1000) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


def _update(
    update_id: int,
    chat_id: int,
    text: object,
    *,
    chat_type: str = "private",
    user_id: object | None = None,
    is_bot: bool = False,
) -> dict[str, object]:
    return {
        "update_id": update_id,
        "message": {
            "chat": {"id": chat_id, "type": chat_type},
            "from": {
                "id": chat_id if user_id is None else user_id,
                "is_bot": is_bot,
            },
            "text": text,
        },
    }


class TestSubscriptionCommandHandler(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.clock = MutableClock()
        self.store = SubscriptionStore(
            Path(self.directory.name) / "subscriptions.sqlite3",
            now=self.clock,
        )
        self.handler = SubscriptionCommandHandler(
            store=self.store,
            owner_chat_ids=frozenset({"1"}),
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _handle(self, update_id: int, chat_id: int, text: str) -> BotReply | None:
        return self.handler.handle_update(_update(update_id, chat_id, text))

    def _issue(self, update_id: int = 1) -> tuple[str, BotReply]:
        reply = self._handle(update_id, 1, "/token")
        assert reply is not None
        return reply.text.splitlines()[1], reply

    def test_start_guides_user_and_owner_sees_token_command(self) -> None:
        user = self._handle(1, 20, "/start")
        owner = self._handle(2, 1, "/start")
        assert user is not None and owner is not None
        self.assertIn("/subscribe <token>", user.text)
        self.assertNotIn("/token -", user.text)
        self.assertIn("/token -", owner.text)

    def test_owner_issues_token_and_user_subscribes(self) -> None:
        token, owner_reply = self._issue()
        self.assertNotIn(token, repr(owner_reply))
        subscribed = self._handle(2, 20, f"/subscribe {token}")
        assert subscribed is not None
        self.assertIn("订阅成功", subscribed.text)
        self.assertEqual(self.store.subscriber_status("20"), "active")

    def test_active_user_gets_idempotent_subscription_reply(self) -> None:
        first, _ = self._issue()
        self._handle(2, 20, f"/subscribe {first}")
        second, _ = self._issue(update_id=3)
        reply = self._handle(4, 20, f"/subscribe {second}")
        assert reply is not None
        self.assertIn("已经处于订阅状态", reply.text)

    def test_non_owner_cannot_issue_token(self) -> None:
        reply = self._handle(1, 20, "/token")
        assert reply is not None
        self.assertEqual(reply.text, HELP_TEXT)
        self.assertNotIn("一次性订阅 Token", reply.text)

    def test_missing_expired_and_used_tokens_have_same_response(self) -> None:
        used_token, _ = self._issue()
        self._handle(2, 20, f"/subscribe {used_token}")
        expired_token, _ = self._issue(update_id=3)

        missing = self._handle(4, 30, "/subscribe nonexistent")
        used = self._handle(5, 31, f"/subscribe {used_token}")
        self.clock.value = 1900
        expired = self._handle(6, 32, f"/subscribe {expired_token}")
        assert missing is not None and used is not None and expired is not None
        self.assertEqual(missing.text, INVALID_TOKEN_TEXT)
        self.assertEqual(used.text, INVALID_TOKEN_TEXT)
        self.assertEqual(expired.text, INVALID_TOKEN_TEXT)

    def test_missing_token_argument_gets_usage(self) -> None:
        reply = self._handle(1, 20, "/subscribe")
        assert reply is not None
        self.assertEqual(reply.text, "请使用：/subscribe <token>")

    def test_unsubscribe_and_duplicate_update_are_idempotent(self) -> None:
        token, _ = self._issue()
        self._handle(2, 20, f"/subscribe {token}")
        reply = self._handle(3, 20, "/unsubscribe")
        duplicate = self._handle(3, 20, "/unsubscribe")
        assert reply is not None
        self.assertIn("已取消订阅", reply.text)
        self.assertIsNone(duplicate)
        self.assertEqual(self.store.subscriber_status("20"), "unsubscribed")

    def test_owner_cannot_unsubscribe(self) -> None:
        reply = self._handle(1, 1, "/unsubscribe")
        assert reply is not None
        self.assertIn("不能取消订阅", reply.text)

    def test_start_reactivates_blocked_but_not_unsubscribed(self) -> None:
        first, _ = self._issue()
        self._handle(2, 20, f"/subscribe {first}")
        target = self.store.active_delivery_targets()[0]
        self.store.mark_blocked(
            "20",
            expected_lifecycle_version=target.lifecycle_version,
        )
        self._handle(3, 20, "/start")
        self.assertEqual(self.store.subscriber_status("20"), "active")

        self._handle(4, 20, "/unsubscribe")
        self._handle(5, 20, "/start")
        self.assertEqual(self.store.subscriber_status("20"), "unsubscribed")

    def test_group_mismatch_bot_and_malformed_ids_are_ignored(self) -> None:
        updates = (
            _update(1, -100, "/token", chat_type="group"),
            _update(2, 20, "/start", user_id=21),
            _update(3, 20, "/start", is_bot=True),
            _update(4, 20, "/start", user_id=True),
        )
        self.assertEqual(
            [self.handler.handle_update(update) for update in updates],
            [None, None, None, None],
        )
        self.assertEqual(self.store.last_update_id(), 4)

    def test_plain_text_is_ignored_and_unknown_command_gets_help(self) -> None:
        plain = self._handle(1, 20, "hello")
        unknown = self._handle(2, 20, "/unknown")
        self.assertIsNone(plain)
        assert unknown is not None
        self.assertEqual(unknown.text, HELP_TEXT)

    def test_command_suffix_and_case_are_accepted(self) -> None:
        reply = self._handle(1, 1, "/ToKeN@PtilopsisRadarBot")
        assert reply is not None
        self.assertIn("一次性订阅 Token", reply.text)

    def test_invalid_update_id_is_rejected_without_consuming_offset(self) -> None:
        malformed = _update(1, 20, "/start")
        malformed["update_id"] = True
        self.assertIsNone(self.handler.handle_update(malformed))
        self.assertEqual(self.store.last_update_id(), -1)


if __name__ == "__main__":
    unittest.main()
