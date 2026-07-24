# coding=utf-8
"""SQLite-backed Telegram invitation and subscriber state."""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


DEFAULT_SUBSCRIPTION_DB_PATH = Path(
    "output/meta/telegram-subscriptions.sqlite3"
)
TOKEN_TTL_SECONDS = 15 * 60
SUBSCRIBER_ACTIVE = "active"
SUBSCRIBER_UNSUBSCRIBED = "unsubscribed"
SUBSCRIBER_BLOCKED = "blocked"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO schema_metadata(key, value)
VALUES ('schema_version', 'telegram-subscriptions-v1');

CREATE TABLE IF NOT EXISTS invite_tokens (
    token_hash TEXT PRIMARY KEY,
    issued_by_chat_id TEXT NOT NULL,
    created_at_epoch INTEGER NOT NULL,
    expires_at_epoch INTEGER NOT NULL,
    used_at_epoch INTEGER
);

CREATE TABLE IF NOT EXISTS subscribers (
    chat_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('active', 'unsubscribed', 'blocked')
    ),
    subscribed_at_epoch INTEGER NOT NULL,
    updated_at_epoch INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    last_update_id INTEGER NOT NULL
);
INSERT OR IGNORE INTO bot_state(singleton, last_update_id) VALUES (1, -1);
"""

@dataclass(frozen=True)
class UpdateMutationResult:
    applied: bool
    value: object = None


@dataclass(frozen=True)
class TokenIssue:
    token: str
    expires_at_epoch: int


class SubscriptionStore:
    def __init__(
        self,
        path: str | Path = DEFAULT_SUBSCRIPTION_DB_PATH,
        *,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.path = Path(path)
        self.now = now
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=5.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(_SCHEMA)
        finally:
            connection.close()
        os.chmod(self.path, 0o600)

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _mutate_update(
        self,
        update_id: int,
        operation: Callable[[sqlite3.Connection, int], object],
    ) -> UpdateMutationResult:
        now_epoch = int(self.now())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT last_update_id FROM bot_state WHERE singleton = 1"
            ).fetchone()
            last_update_id = int(row["last_update_id"])
            if update_id <= last_update_id:
                connection.rollback()
                return UpdateMutationResult(applied=False)
            value = operation(connection, now_epoch)
            connection.execute(
                "UPDATE bot_state SET last_update_id = ? WHERE singleton = 1",
                (update_id,),
            )
            connection.commit()
            return UpdateMutationResult(applied=True, value=value)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def advance_update(self, update_id: int) -> bool:
        result = self._mutate_update(update_id, lambda _connection, _now: None)
        return result.applied

    def issue_token(
        self,
        *,
        update_id: int,
        owner_chat_id: str,
    ) -> UpdateMutationResult:
        raw_token = secrets.token_urlsafe(24)
        token_hash = self._token_hash(raw_token)

        def operation(connection: sqlite3.Connection, now_epoch: int) -> TokenIssue:
            expires_at = now_epoch + TOKEN_TTL_SECONDS
            connection.execute(
                """
                INSERT INTO invite_tokens(
                    token_hash, issued_by_chat_id, created_at_epoch,
                    expires_at_epoch, used_at_epoch
                ) VALUES (?, ?, ?, ?, NULL)
                """,
                (token_hash, owner_chat_id, now_epoch, expires_at),
            )
            return TokenIssue(raw_token, expires_at)

        return self._mutate_update(update_id, operation)

    def redeem_token(
        self,
        *,
        update_id: int,
        token: str,
        chat_id: str,
        user_id: str,
    ) -> UpdateMutationResult:
        token_hash = self._token_hash(token)

        def operation(connection: sqlite3.Connection, now_epoch: int) -> str:
            existing = connection.execute(
                "SELECT status FROM subscribers WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
            if existing is not None and existing["status"] == SUBSCRIBER_ACTIVE:
                return "already_active"

            token_row = connection.execute(
                """
                SELECT expires_at_epoch, used_at_epoch
                FROM invite_tokens
                WHERE token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
            valid = (
                token_row is not None
                and token_row["used_at_epoch"] is None
                and int(token_row["expires_at_epoch"]) > now_epoch
            )
            if not valid:
                return "invalid"

            updated = connection.execute(
                """
                UPDATE invite_tokens
                SET used_at_epoch = ?
                WHERE token_hash = ?
                  AND used_at_epoch IS NULL
                  AND expires_at_epoch > ?
                """,
                (now_epoch, token_hash, now_epoch),
            )
            if updated.rowcount != 1:
                return "invalid"

            connection.execute(
                """
                INSERT INTO subscribers(
                    chat_id, user_id, status, subscribed_at_epoch,
                    updated_at_epoch
                ) VALUES (?, ?, 'active', ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    status = 'active',
                    subscribed_at_epoch = excluded.subscribed_at_epoch,
                    updated_at_epoch = excluded.updated_at_epoch
                """,
                (chat_id, user_id, now_epoch, now_epoch),
            )
            return "subscribed"

        return self._mutate_update(update_id, operation)

    def unsubscribe(
        self,
        *,
        update_id: int,
        chat_id: str,
    ) -> UpdateMutationResult:
        def operation(connection: sqlite3.Connection, now_epoch: int) -> str:
            row = connection.execute(
                "SELECT status FROM subscribers WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
            if row is None or row["status"] != SUBSCRIBER_ACTIVE:
                return "not_active"
            connection.execute(
                """
                UPDATE subscribers
                SET status = 'unsubscribed', updated_at_epoch = ?
                WHERE chat_id = ?
                """,
                (now_epoch, chat_id),
            )
            return "unsubscribed"

        return self._mutate_update(update_id, operation)

    def reactivate_blocked(
        self,
        *,
        update_id: int,
        chat_id: str,
        user_id: str,
    ) -> UpdateMutationResult:
        def operation(connection: sqlite3.Connection, now_epoch: int) -> str:
            row = connection.execute(
                "SELECT status FROM subscribers WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
            if row is not None and row["status"] == SUBSCRIBER_BLOCKED:
                connection.execute(
                    """
                    UPDATE subscribers
                    SET user_id = ?, status = 'active', updated_at_epoch = ?
                    WHERE chat_id = ?
                    """,
                    (user_id, now_epoch, chat_id),
                )
                return "reactivated"
            return "unchanged"

        return self._mutate_update(update_id, operation)

    def mark_blocked(self, chat_id: str) -> None:
        now_epoch = int(self.now())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE subscribers
                SET status = 'blocked', updated_at_epoch = ?
                WHERE chat_id = ? AND status = 'active'
                """,
                (now_epoch, chat_id),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def active_chat_ids(self) -> list[str]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT chat_id
                FROM subscribers
                WHERE status = 'active'
                ORDER BY subscribed_at_epoch, chat_id
                """
            ).fetchall()
        finally:
            connection.close()
        return [str(row["chat_id"]) for row in rows]

    def subscriber_status(self, chat_id: str) -> str | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT status FROM subscribers WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        finally:
            connection.close()
        return str(row["status"]) if row is not None else None

    def last_update_id(self) -> int:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT last_update_id FROM bot_state WHERE singleton = 1"
            ).fetchone()
        finally:
            connection.close()
        return int(row["last_update_id"])


def subscriptions_enabled(env: Mapping[str, str]) -> bool:
    return env.get("PTILOPSIS_TELEGRAM_SUBSCRIPTIONS_ENABLED") == "1"


def subscription_db_path_from_env(env: Mapping[str, str]) -> Path:
    raw = str(env.get("PTILOPSIS_TELEGRAM_SUBSCRIPTION_DB_PATH") or "").strip()
    return Path(raw) if raw else DEFAULT_SUBSCRIPTION_DB_PATH


def resolve_owner_chat_ids(env: Mapping[str, str]) -> list[str]:
    """Resolve only explicitly configured command-authority owners."""
    raw_values = str(env.get("TELEGRAM_OWNER_CHAT_IDS") or "").split(",")
    return list(dict.fromkeys(value.strip() for value in raw_values if value.strip()))


@dataclass
class ReaderRecipientProvider:
    owner_chat_ids: tuple[str, ...]
    store: SubscriptionStore | None = None

    def get_chat_ids(self) -> Sequence[str]:
        subscribers = self.store.active_chat_ids() if self.store is not None else []
        return tuple(dict.fromkeys((*self.owner_chat_ids, *subscribers)))

    def mark_blocked(self, chat_id: str) -> None:
        if chat_id in self.owner_chat_ids or self.store is None:
            return
        self.store.mark_blocked(chat_id)


def build_reader_recipient_provider(
    env: Mapping[str, str],
) -> ReaderRecipientProvider:
    owners = tuple(resolve_owner_chat_ids(env))
    if not owners:
        raise ValueError("TELEGRAM_OWNER_CHAT_IDS is required")
    store = (
        SubscriptionStore(subscription_db_path_from_env(env))
        if subscriptions_enabled(env)
        else None
    )
    return ReaderRecipientProvider(owner_chat_ids=owners, store=store)
