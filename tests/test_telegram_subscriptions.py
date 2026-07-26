# coding=utf-8
"""Subscriber state and inbound update ledger tests."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from trendradar.telegram.subscriptions import (
    SCHEMA_VERSION,
    SubscriptionStore,
)


class MutableClock:
    def __init__(self, value: int = 1000) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


class TestSubscriptionStore(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "subscriptions.sqlite3"
        self.clock = MutableClock()
        self.store = SubscriptionStore(self.path, now=self.clock)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _seed(
        self,
        chat_id: str,
        status: str,
        *,
        user_id: str | None = None,
        subscribed_at: int = 100,
        updated_at: int = 100,
    ) -> None:
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                """
                INSERT INTO subscribers(
                    chat_id, user_id, status,
                    subscribed_at_epoch, updated_at_epoch
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    user_id or chat_id,
                    status,
                    subscribed_at,
                    updated_at,
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def test_initialization_is_idempotent_owner_only_and_versioned(self) -> None:
        SubscriptionStore(self.path, now=self.clock)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        connection = sqlite3.connect(self.path)
        try:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            offset = int(
                connection.execute(
                    "SELECT last_update_id FROM bot_state WHERE singleton = 1"
                ).fetchone()[0]
            )
        finally:
            connection.close()
        self.assertEqual(version, SCHEMA_VERSION)
        self.assertEqual(offset, -1)

    def test_schema_rejects_unknown_subscriber_status(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self._seed("20", "unknown")

    def test_active_ids_are_filtered_and_stably_ordered(self) -> None:
        self._seed("30", "active", subscribed_at=200, updated_at=200)
        self._seed("20", "active", subscribed_at=100, updated_at=100)
        self._seed("10", "blocked")
        self._seed("40", "unsubscribed")
        self.assertEqual(self.store.active_chat_ids(), ["20", "30"])

    def test_unsubscribe_and_offset_commit_together(self) -> None:
        self._seed("20", "active")
        result = self.store.unsubscribe(update_id=7, chat_id="20")
        self.assertTrue(result.applied)
        self.assertEqual(result.value, "unsubscribed")
        self.assertEqual(self.store.subscriber_status("20"), "unsubscribed")
        self.assertEqual(self.store.last_update_id(), 7)

    def test_duplicate_or_older_update_does_not_mutate_state(self) -> None:
        self._seed("20", "active")
        self.assertTrue(self.store.advance_update(7))
        duplicate = self.store.unsubscribe(update_id=7, chat_id="20")
        older = self.store.unsubscribe(update_id=6, chat_id="20")
        self.assertFalse(duplicate.applied)
        self.assertFalse(older.applied)
        self.assertEqual(self.store.subscriber_status("20"), "active")

    def test_non_active_unsubscribe_still_consumes_update(self) -> None:
        result = self.store.unsubscribe(update_id=3, chat_id="20")
        self.assertTrue(result.applied)
        self.assertEqual(result.value, "not_active")
        self.assertEqual(self.store.last_update_id(), 3)

    def test_only_blocked_subscriber_can_be_reactivated(self) -> None:
        self._seed("20", "blocked")
        self._seed("30", "unsubscribed")
        blocked = self.store.reactivate_blocked(
            update_id=1,
            chat_id="20",
            user_id="new-user",
        )
        unsubscribed = self.store.reactivate_blocked(
            update_id=2,
            chat_id="30",
            user_id="30",
        )
        self.assertEqual(blocked.value, "reactivated")
        self.assertEqual(unsubscribed.value, "unchanged")
        self.assertEqual(self.store.subscriber_status("20"), "active")
        self.assertEqual(self.store.subscriber_status("30"), "unsubscribed")

    def test_mark_blocked_only_changes_active_once(self) -> None:
        self._seed("20", "active")
        self._seed("30", "unsubscribed")
        self.assertTrue(self.store.mark_blocked("20"))
        self.assertFalse(self.store.mark_blocked("20"))
        self.assertFalse(self.store.mark_blocked("30"))
        self.assertEqual(self.store.subscriber_status("20"), "blocked")

    def test_mutation_exception_rolls_back_state_and_offset(self) -> None:
        self._seed("20", "active")

        def fail(connection: sqlite3.Connection, now_epoch: int) -> None:
            connection.execute(
                """
                UPDATE subscribers
                SET status = 'blocked', updated_at_epoch = ?
                WHERE chat_id = '20'
                """,
                (now_epoch,),
            )
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            self.store._mutate_update(8, fail)
        self.assertEqual(self.store.subscriber_status("20"), "active")
        self.assertEqual(self.store.last_update_id(), -1)


if __name__ == "__main__":
    unittest.main()
