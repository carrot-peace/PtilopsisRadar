# coding=utf-8
"""Canonical Telegram reader recipient provider tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from trendradar.telegram.fanout import RecipientTarget
from trendradar.telegram.recipients import (
    ReaderRecipientProvider,
    build_reader_recipient_provider,
)
from trendradar.telegram.subscriptions import SubscriptionStore


class TestReaderRecipientProvider(unittest.TestCase):
    def test_owners_are_first_and_duplicate_subscriber_is_not_blockable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SubscriptionStore(Path(directory) / "subscriptions.sqlite3")
            owner_token = store.issue_token(update_id=1, owner_chat_id="1").value
            subscriber_token = store.issue_token(update_id=2, owner_chat_id="1").value
            store.redeem_token(
                update_id=3,
                token=owner_token.token,
                chat_id="1",
                user_id="1",
            )
            store.redeem_token(
                update_id=4,
                token=subscriber_token.token,
                chat_id="20",
                user_id="20",
            )
            provider = ReaderRecipientProvider(("1", "2"), store)

            targets = provider.get_targets()

            self.assertEqual(
                targets,
                (
                    RecipientTarget("1"),
                    RecipientTarget("2"),
                    RecipientTarget("20", 1),
                ),
            )
            self.assertFalse(provider.mark_blocked(targets[0]))
            self.assertEqual(store.subscriber_status("1"), "active")

    def test_versioned_subscriber_can_be_marked_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SubscriptionStore(Path(directory) / "subscriptions.sqlite3")
            issue = store.issue_token(update_id=1, owner_chat_id="1").value
            store.redeem_token(
                update_id=2,
                token=issue.token,
                chat_id="20",
                user_id="20",
            )
            provider = ReaderRecipientProvider(("1",), store)
            subscriber = provider.get_targets()[1]

            self.assertTrue(provider.mark_blocked(subscriber))
            self.assertEqual(store.subscriber_status("20"), "blocked")

    def test_disabled_subscriptions_do_not_create_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "disabled.sqlite3"
            provider = build_reader_recipient_provider(
                {
                    "TELEGRAM_OWNER_CHAT_IDS": "1, 2,1",
                    "TELEGRAM_CHAT_ID": "legacy",
                    "PTILOPSIS_TELEGRAM_SUBSCRIPTION_DB_PATH": str(path),
                }
            )

            self.assertEqual(provider.get_targets(), (
                RecipientTarget("1"),
                RecipientTarget("2"),
            ))
            self.assertFalse(path.exists())

    def test_enabled_subscriptions_require_explicit_owners(self) -> None:
        with self.assertRaisesRegex(ValueError, "TELEGRAM_OWNER_CHAT_IDS"):
            build_reader_recipient_provider(
                {"PTILOPSIS_TELEGRAM_SUBSCRIPTIONS_ENABLED": "1"}
            )


if __name__ == "__main__":
    unittest.main()
