# coding=utf-8
"""Private-command and polling guard tests for the subscription Bot."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from trendradar.telegram.bot import (
    FatalPollingError,
    InstanceLock,
    SubscriptionBotService,
    _assert_no_webhook,
    _raise_for_fatal_status,
)
from trendradar.telegram.subscriptions import SubscriptionStore
from trendradar.telegram.transport import TelegramHTTPResponse


class FakeTransport:
    def __init__(self):
        self.replies = []
        self.webhook_url = ""

    def send_message(self, *, chat_id, text, **kwargs):
        self.replies.append((chat_id, text))
        return TelegramHTTPResponse(200, '{"ok": true}')

    def get_webhook_info(self):
        return TelegramHTTPResponse(
            200,
            '{"ok":true,"result":{"url":"%s"}}' % self.webhook_url,
        )


def _update(update_id, chat_id, text, *, chat_type="private", user_id=None):
    return {
        "update_id": update_id,
        "message": {
            "chat": {"id": chat_id, "type": chat_type},
            "from": {"id": chat_id if user_id is None else user_id},
            "text": text,
        },
    }


class TestSubscriptionBotService(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Path(self.directory.name) / "subscriptions.sqlite3"
        self.now = [1000]
        self.store = SubscriptionStore(self.db, now=lambda: self.now[0])
        self.transport = FakeTransport()
        self.service = SubscriptionBotService(
            transport=self.transport,  # type: ignore[arg-type]
            store=self.store,
            owner_chat_ids=frozenset({"1"}),
        )

    def tearDown(self):
        self.directory.cleanup()

    def test_start_guides_user_and_owner_sees_token_command(self):
        self.service.handle_update(_update(1, 20, "/start"))
        self.service.handle_update(_update(2, 1, "/start"))
        self.assertIn("/subscribe <token>", self.transport.replies[0][1])
        self.assertNotIn("/token -", self.transport.replies[0][1])
        self.assertIn("/token -", self.transport.replies[1][1])

    def test_owner_issues_token_and_user_subscribes(self):
        self.service.handle_update(_update(1, 1, "/token"))
        owner_reply = self.transport.replies[-1][1]
        token = owner_reply.splitlines()[1]
        self.assertGreater(len(token), 20)

        self.service.handle_update(_update(2, 20, f"/subscribe {token}"))
        self.assertEqual(self.store.subscriber_status("20"), "active")
        self.assertIn("订阅成功", self.transport.replies[-1][1])

        self.service.handle_update(_update(3, 30, f"/subscribe {token}"))
        self.assertIn("无效、已过期或已经使用", self.transport.replies[-1][1])

    def test_non_owner_cannot_issue_token(self):
        self.service.handle_update(_update(1, 20, "/token"))
        self.assertIn("可用命令", self.transport.replies[-1][1])
        self.assertNotIn("一次性订阅 Token", self.transport.replies[-1][1])

    def test_missing_expired_and_used_tokens_have_the_same_response(self):
        self.service.handle_update(_update(1, 1, "/token"))
        used_token = self.transport.replies[-1][1].splitlines()[1]
        self.service.handle_update(_update(2, 20, f"/subscribe {used_token}"))
        self.service.handle_update(_update(3, 1, "/token"))
        expired_token = self.transport.replies[-1][1].splitlines()[1]

        self.service.handle_update(_update(4, 30, "/subscribe nonexistent"))
        nonexistent_reply = self.transport.replies[-1][1]
        self.service.handle_update(_update(5, 31, f"/subscribe {used_token}"))
        used_reply = self.transport.replies[-1][1]
        self.now[0] = 1900
        self.service.handle_update(_update(6, 32, f"/subscribe {expired_token}"))
        expired_reply = self.transport.replies[-1][1]
        self.assertEqual(nonexistent_reply, used_reply)
        self.assertEqual(used_reply, expired_reply)

    def test_unsubscribe_and_duplicate_update_are_idempotent(self):
        self.service.handle_update(_update(1, 1, "/token"))
        token = self.transport.replies[-1][1].splitlines()[1]
        self.service.handle_update(_update(2, 20, f"/subscribe {token}"))
        self.service.handle_update(_update(3, 20, "/unsubscribe"))
        reply_count = len(self.transport.replies)
        self.service.handle_update(_update(3, 20, "/unsubscribe"))
        self.assertEqual(len(self.transport.replies), reply_count)
        self.assertEqual(self.store.subscriber_status("20"), "unsubscribed")

    def test_owner_cannot_unsubscribe(self):
        self.service.handle_update(_update(1, 1, "/unsubscribe"))
        self.assertIn("不能取消订阅", self.transport.replies[-1][1])

    def test_group_and_mismatched_private_sender_are_ignored(self):
        self.service.handle_update(_update(1, -100, "/token", chat_type="group"))
        self.service.handle_update(_update(2, 20, "/start", user_id=21))
        self.assertEqual(self.transport.replies, [])
        self.assertEqual(self.store.last_update_id(), 2)

    def test_plain_text_is_ignored_and_unknown_command_gets_help(self):
        self.service.handle_update(_update(1, 20, "hello"))
        self.assertEqual(self.transport.replies, [])
        self.service.handle_update(_update(2, 20, "/unknown"))
        self.assertIn("可用命令", self.transport.replies[-1][1])


class TestPollingGuards(unittest.TestCase):
    def test_webhook_conflict_is_fatal(self):
        transport = FakeTransport()
        transport.webhook_url = "https://example.test/hook"
        with self.assertRaises(FatalPollingError):
            _assert_no_webhook(transport)  # type: ignore[arg-type]

    def test_unauthorized_and_polling_conflict_statuses_are_fatal(self):
        for status in (401, 409):
            with self.subTest(status=status):
                with self.assertRaises(FatalPollingError):
                    _raise_for_fatal_status(
                        TelegramHTTPResponse(status, '{"ok": false}')
                    )

    def test_single_instance_lock_rejects_second_holder(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bot.lock"
            with InstanceLock(path):
                with self.assertRaises(FatalPollingError):
                    with InstanceLock(path):
                        pass


if __name__ == "__main__":
    unittest.main()
