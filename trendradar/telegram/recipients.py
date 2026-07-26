# coding=utf-8
"""Canonical reader recipient configuration and subscription provider."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from trendradar.telegram.fanout import RecipientTarget
from trendradar.telegram.subscriptions import (
    DEFAULT_SUBSCRIPTION_DB_PATH,
    SubscriptionStore,
)


def subscriptions_enabled(env: Mapping[str, str]) -> bool:
    return env.get("PTILOPSIS_TELEGRAM_SUBSCRIPTIONS_ENABLED") == "1"


def subscription_db_path_from_env(env: Mapping[str, str]) -> Path:
    raw = str(env.get("PTILOPSIS_TELEGRAM_SUBSCRIPTION_DB_PATH") or "").strip()
    return Path(raw) if raw else DEFAULT_SUBSCRIPTION_DB_PATH


def resolve_owner_chat_ids(env: Mapping[str, str]) -> tuple[str, ...]:
    values = str(env.get("TELEGRAM_OWNER_CHAT_IDS") or "").split(",")
    return tuple(
        dict.fromkeys(value.strip() for value in values if value.strip())
    )


@dataclass
class ReaderRecipientProvider:
    owner_chat_ids: tuple[str, ...]
    store: SubscriptionStore | None = None

    def get_targets(self) -> Sequence[RecipientTarget]:
        targets = {
            chat_id: RecipientTarget(chat_id)
            for chat_id in self.owner_chat_ids
        }
        if self.store is not None:
            for subscriber in self.store.active_delivery_targets():
                targets.setdefault(
                    subscriber.chat_id,
                    RecipientTarget(
                        subscriber.chat_id,
                        subscriber.lifecycle_version,
                    ),
                )
        return tuple(targets.values())

    def mark_blocked(self, target: RecipientTarget) -> bool:
        if (
            self.store is None
            or target.lifecycle_version is None
            or target.chat_id in self.owner_chat_ids
        ):
            return False
        return self.store.mark_blocked(
            target.chat_id,
            expected_lifecycle_version=target.lifecycle_version,
        )


def build_reader_recipient_provider(
    env: Mapping[str, str],
) -> ReaderRecipientProvider:
    owners = resolve_owner_chat_ids(env)
    if not owners:
        raise ValueError("TELEGRAM_OWNER_CHAT_IDS is required")
    store = (
        SubscriptionStore(subscription_db_path_from_env(env))
        if subscriptions_enabled(env)
        else None
    )
    return ReaderRecipientProvider(owner_chat_ids=owners, store=store)
