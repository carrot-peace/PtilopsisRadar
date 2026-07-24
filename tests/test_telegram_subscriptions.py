# coding=utf-8
"""Token, subscriber, offset, and reader-recipient persistence tests."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from trendradar.telegram.subscriptions import (
    ReaderRecipientProvider,
    SubscriptionStore,
    TokenIssue,
)


class MutableClock:
    def __init__(self, value=1000):
        self.value = value

    def __call__(self):
        return self.value


class TestSubscriptionStore(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "subscriptions.sqlite3"
        self.clock = MutableClock()
        self.store = SubscriptionStore(self.path, now=self.clock)

    def tearDown(self):
        self.directory.cleanup()

    def _issue(self, update_id=1):
        result = self.store.issue_token(update_id=update_id, owner_chat_id="1")
        self.assertTrue(result.applied)
        self.assertIsInstance(result.value, TokenIssue)
        return result.value.token

    def test_database_file_is_owner_only(self):
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_raw_token_is_not_stored_and_token_is_single_use(self):
        token = self._issue()
        connection = sqlite3.connect(self.path)
        row = connection.execute(
            "SELECT token_hash FROM invite_tokens"
        ).fetchone()
        connection.close()
        self.assertEqual(row[0], hashlib.sha256(token.encode()).hexdigest())
        self.assertNotEqual(row[0], token)

        first = self.store.redeem_token(
            update_id=2,
            token=token,
            chat_id="20",
            user_id="20",
        )
        second = self.store.redeem_token(
            update_id=3,
            token=token,
            chat_id="30",
            user_id="30",
        )
        self.assertEqual(first.value, "subscribed")
        self.assertEqual(second.value, "invalid")
        self.assertEqual(self.store.active_chat_ids(), ["20"])

    def test_token_is_valid_before_but_not_at_900_second_boundary(self):
        token = self._issue()
        self.clock.value = 1899
        valid = self.store.redeem_token(
            update_id=2, token=token, chat_id="20", user_id="20"
        )
        self.assertEqual(valid.value, "subscribed")

        token2 = self._issue(update_id=3)
        self.clock.value = 2799
        expired = self.store.redeem_token(
            update_id=4, token=token2, chat_id="30", user_id="30"
        )
        self.assertEqual(expired.value, "invalid")

    def test_concurrent_redemption_never_activates_two_subscribers(self):
        token = self._issue()

        def redeem(values):
            update_id, chat_id = values
            return self.store.redeem_token(
                update_id=update_id,
                token=token,
                chat_id=chat_id,
                user_id=chat_id,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(redeem, ((2, "20"), (3, "30"))))
        self.assertEqual(len(self.store.active_chat_ids()), 1)

    def test_state_mutation_and_update_offset_are_committed_together(self):
        token = self._issue()
        result = self.store.redeem_token(
            update_id=7, token=token, chat_id="20", user_id="20"
        )
        self.assertTrue(result.applied)
        self.assertEqual(self.store.last_update_id(), 7)
        duplicate = self.store.unsubscribe(update_id=7, chat_id="20")
        self.assertFalse(duplicate.applied)
        self.assertEqual(self.store.subscriber_status("20"), "active")

    def test_unsubscribe_requires_a_new_token(self):
        token = self._issue()
        self.store.redeem_token(
            update_id=2, token=token, chat_id="20", user_id="20"
        )
        result = self.store.unsubscribe(update_id=3, chat_id="20")
        self.assertEqual(result.value, "unsubscribed")
        start = self.store.reactivate_blocked(
            update_id=4, chat_id="20", user_id="20"
        )
        self.assertEqual(start.value, "unchanged")
        self.assertEqual(self.store.subscriber_status("20"), "unsubscribed")

    def test_blocked_subscriber_can_be_reactivated_by_start(self):
        token = self._issue()
        self.store.redeem_token(
            update_id=2, token=token, chat_id="20", user_id="20"
        )
        self.store.mark_blocked("20")
        self.assertEqual(self.store.subscriber_status("20"), "blocked")
        result = self.store.reactivate_blocked(
            update_id=3, chat_id="20", user_id="20"
        )
        self.assertEqual(result.value, "reactivated")
        self.assertEqual(self.store.subscriber_status("20"), "active")

    def test_reader_provider_merges_owners_and_active_subscribers(self):
        token = self._issue()
        self.store.redeem_token(
            update_id=2, token=token, chat_id="20", user_id="20"
        )
        provider = ReaderRecipientProvider(("1",), self.store)
        self.assertEqual(provider.get_chat_ids(), ("1", "20"))
        provider.mark_blocked("1")
        self.assertIsNone(self.store.subscriber_status("1"))
        provider.mark_blocked("20")
        self.assertEqual(self.store.subscriber_status("20"), "blocked")


if __name__ == "__main__":
    unittest.main()
