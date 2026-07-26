# coding=utf-8
"""Subscriber state and inbound update ledger tests."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from trendradar.telegram.subscriptions import (
    SCHEMA_VERSION,
    SubscriberDeliveryTarget,
    SubscriptionStore,
    TOKEN_TTL_SECONDS,
    TokenIssue,
    UpdateMutationResult,
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

    def _issue(self, update_id: int = 1) -> TokenIssue:
        result = self.store.issue_token(
            update_id=update_id,
            owner_chat_id="1",
        )
        self.assertTrue(result.applied)
        self.assertIsInstance(result.value, TokenIssue)
        return result.value

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
        self.assertEqual(
            self.store.active_delivery_targets(),
            [
                SubscriberDeliveryTarget("20", 1),
                SubscriberDeliveryTarget("30", 1),
            ],
        )

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
        target = self.store.active_delivery_targets()[0]
        self.assertTrue(
            self.store.mark_blocked(
                "20",
                expected_lifecycle_version=target.lifecycle_version,
            )
        )
        self.assertFalse(
            self.store.mark_blocked(
                "20",
                expected_lifecycle_version=target.lifecycle_version,
            )
        )
        self.assertFalse(
            self.store.mark_blocked(
                "30",
                expected_lifecycle_version=1,
            )
        )
        self.assertEqual(self.store.subscriber_status("20"), "blocked")

    def test_stale_delivery_cannot_overwrite_reactivation(self) -> None:
        self._seed("20", "active")
        stale = self.store.active_delivery_targets()[0]
        self.assertTrue(
            self.store.mark_blocked(
                stale.chat_id,
                expected_lifecycle_version=stale.lifecycle_version,
            )
        )
        reactivated = self.store.reactivate_blocked(
            update_id=1,
            chat_id="20",
            user_id="20",
        )
        self.assertEqual(reactivated.value, "reactivated")
        self.assertFalse(
            self.store.mark_blocked(
                stale.chat_id,
                expected_lifecycle_version=stale.lifecycle_version,
            )
        )
        self.assertEqual(self.store.subscriber_status("20"), "active")
        self.assertGreater(
            self.store.active_delivery_targets()[0].lifecycle_version,
            stale.lifecycle_version,
        )

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

    def test_v1_database_is_migrated_without_losing_state(self) -> None:
        self._seed("20", "active")
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("DROP TABLE invite_tokens")
            connection.execute("PRAGMA user_version = 1")
            connection.commit()
        finally:
            connection.close()

        migrated = SubscriptionStore(self.path, now=self.clock)
        self.assertEqual(migrated.active_chat_ids(), ["20"])
        connection = sqlite3.connect(self.path)
        try:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            token_table = connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name = 'invite_tokens'
                """
            ).fetchone()
            lifecycle_column = next(
                row
                for row in connection.execute(
                    "PRAGMA table_info(subscribers)"
                ).fetchall()
                if row[1] == "lifecycle_version"
            )
        finally:
            connection.close()
        self.assertEqual(version, SCHEMA_VERSION)
        self.assertIsNotNone(token_table)
        self.assertEqual(lifecycle_column[4], "1")

    def test_v2_database_adds_delivery_lifecycle_version(self) -> None:
        path = Path(self.directory.name) / "subscriptions-v2.sqlite3"
        connection = sqlite3.connect(path)
        try:
            connection.executescript(
                """
                CREATE TABLE subscribers (
                    chat_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    subscribed_at_epoch INTEGER NOT NULL,
                    updated_at_epoch INTEGER NOT NULL
                );
                CREATE TABLE bot_state (
                    singleton INTEGER PRIMARY KEY,
                    last_update_id INTEGER NOT NULL
                );
                INSERT INTO bot_state VALUES (1, -1);
                CREATE TABLE invite_tokens (
                    token_hash TEXT PRIMARY KEY,
                    issued_by_chat_id TEXT NOT NULL,
                    created_at_epoch INTEGER NOT NULL,
                    expires_at_epoch INTEGER NOT NULL,
                    used_at_epoch INTEGER
                );
                INSERT INTO subscribers VALUES (
                    '20', '20', 'active', 100, 100
                );
                PRAGMA user_version = 2;
                """
            )
        finally:
            connection.close()

        migrated = SubscriptionStore(path, now=self.clock)
        self.assertEqual(
            migrated.active_delivery_targets(),
            [SubscriberDeliveryTarget("20", 1)],
        )
        connection = sqlite3.connect(path)
        try:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        finally:
            connection.close()
        self.assertEqual(version, SCHEMA_VERSION)

    def test_concurrent_v2_initialization_serializes_migration(self) -> None:
        path = Path(self.directory.name) / "subscriptions-concurrent-v2.sqlite3"
        connection = sqlite3.connect(path)
        try:
            connection.executescript(
                """
                CREATE TABLE subscribers (
                    chat_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    subscribed_at_epoch INTEGER NOT NULL,
                    updated_at_epoch INTEGER NOT NULL
                );
                CREATE TABLE bot_state (
                    singleton INTEGER PRIMARY KEY,
                    last_update_id INTEGER NOT NULL
                );
                INSERT INTO bot_state VALUES (1, -1);
                CREATE TABLE invite_tokens (
                    token_hash TEXT PRIMARY KEY,
                    issued_by_chat_id TEXT NOT NULL,
                    created_at_epoch INTEGER NOT NULL,
                    expires_at_epoch INTEGER NOT NULL,
                    used_at_epoch INTEGER
                );
                PRAGMA user_version = 2;
                """
            )
        finally:
            connection.close()

        barrier = threading.Barrier(8)

        class CoordinatedStore(SubscriptionStore):
            def _connect(self) -> sqlite3.Connection:
                opened = super()._connect()
                barrier.wait()
                return opened

        for _attempt in range(10):
            barrier.reset()
            with ThreadPoolExecutor(max_workers=8) as executor:
                stores = list(
                    executor.map(
                        lambda _index: CoordinatedStore(path),
                        range(8),
                    )
                )

            self.assertEqual(len(stores), 8)
        connection = sqlite3.connect(path)
        try:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(subscribers)"
                ).fetchall()
            }
        finally:
            connection.close()
        self.assertEqual(version, SCHEMA_VERSION)
        self.assertIn("lifecycle_version", columns)

    def test_token_is_secret_hashed_and_expires_in_fifteen_minutes(self) -> None:
        issue = self._issue()
        self.assertNotIn(issue.token, repr(issue))
        self.assertEqual(
            issue.expires_at_epoch,
            self.clock.value + TOKEN_TTL_SECONDS,
        )
        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute(
                """
                SELECT token_hash, issued_by_chat_id,
                       created_at_epoch, expires_at_epoch
                FROM invite_tokens
                """
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(
            row[0],
            hashlib.sha256(issue.token.encode("utf-8")).hexdigest(),
        )
        self.assertNotEqual(row[0], issue.token)
        self.assertEqual(row[1:], ("1", 1000, 1900))

    def test_token_is_valid_before_but_not_at_ttl_boundary(self) -> None:
        first = self._issue()
        self.clock.value = 1899
        valid = self.store.redeem_token(
            update_id=2,
            token=first.token,
            chat_id="20",
            user_id="20",
        )
        self.assertEqual(valid.value, "subscribed")

        second = self._issue(update_id=3)
        self.clock.value = 2799
        expired = self.store.redeem_token(
            update_id=4,
            token=second.token,
            chat_id="30",
            user_id="30",
        )
        self.assertEqual(expired.value, "invalid")

    def test_token_is_single_use_and_invalid_reasons_are_uniform(self) -> None:
        issue = self._issue()
        first = self.store.redeem_token(
            update_id=2,
            token=issue.token,
            chat_id="20",
            user_id="20",
        )
        used = self.store.redeem_token(
            update_id=3,
            token=issue.token,
            chat_id="30",
            user_id="30",
        )
        missing = self.store.redeem_token(
            update_id=4,
            token="not-a-token",
            chat_id="40",
            user_id="40",
        )
        self.assertEqual(first.value, "subscribed")
        self.assertEqual(used.value, "invalid")
        self.assertEqual(missing.value, "invalid")
        self.assertEqual(self.store.active_chat_ids(), ["20"])

    def test_concurrent_redemption_activates_only_one_subscriber(self) -> None:
        issue = self._issue()

        def redeem(values: tuple[int, str]) -> UpdateMutationResult:
            update_id, chat_id = values
            return self.store.redeem_token(
                update_id=update_id,
                token=issue.token,
                chat_id=chat_id,
                user_id=chat_id,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(redeem, ((2, "20"), (3, "30"))))
        self.assertEqual(len(self.store.active_chat_ids()), 1)

    def test_active_subscriber_does_not_consume_another_token(self) -> None:
        first = self._issue()
        self.store.redeem_token(
            update_id=2,
            token=first.token,
            chat_id="20",
            user_id="20",
        )
        second = self._issue(update_id=3)
        active = self.store.redeem_token(
            update_id=4,
            token=second.token,
            chat_id="20",
            user_id="20",
        )
        other = self.store.redeem_token(
            update_id=5,
            token=second.token,
            chat_id="30",
            user_id="30",
        )
        self.assertEqual(active.value, "already_active")
        self.assertEqual(other.value, "subscribed")

    def test_unsubscribed_user_requires_a_new_token(self) -> None:
        first = self._issue()
        self.store.redeem_token(
            update_id=2,
            token=first.token,
            chat_id="20",
            user_id="20",
        )
        self.store.unsubscribe(update_id=3, chat_id="20")
        old = self.store.redeem_token(
            update_id=4,
            token=first.token,
            chat_id="20",
            user_id="20",
        )
        second = self._issue(update_id=5)
        renewed = self.store.redeem_token(
            update_id=6,
            token=second.token,
            chat_id="20",
            user_id="20",
        )
        self.assertEqual(old.value, "invalid")
        self.assertEqual(renewed.value, "subscribed")

    def test_failed_subscriber_insert_rolls_back_token_and_offset(self) -> None:
        issue = self._issue()
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                """
                CREATE TRIGGER reject_new_subscriber
                BEFORE INSERT ON subscribers
                BEGIN
                    SELECT RAISE(ABORT, 'subscriber insert rejected');
                END
                """
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaises(sqlite3.IntegrityError):
            self.store.redeem_token(
                update_id=2,
                token=issue.token,
                chat_id="20",
                user_id="20",
            )
        self.assertEqual(self.store.last_update_id(), 1)

        connection = sqlite3.connect(self.path)
        try:
            used_at = connection.execute(
                "SELECT used_at_epoch FROM invite_tokens"
            ).fetchone()[0]
            connection.execute("DROP TRIGGER reject_new_subscriber")
            connection.commit()
        finally:
            connection.close()
        self.assertIsNone(used_at)

        retry = self.store.redeem_token(
            update_id=2,
            token=issue.token,
            chat_id="20",
            user_id="20",
        )
        self.assertEqual(retry.value, "subscribed")


if __name__ == "__main__":
    unittest.main()
