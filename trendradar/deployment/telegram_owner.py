# coding=utf-8
"""Resolve the owner chat ids used by deployment-only Telegram transports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping


def _normalize_chat_id(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _dedupe(values: Iterable[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        chat_id = _normalize_chat_id(value)
        if chat_id is None or chat_id in seen:
            continue
        seen.add(chat_id)
        result.append(chat_id)
    return result


def resolve_telegram_owner_chat_ids(env: Mapping[str, str]) -> list[str]:
    """Return explicit owners plus the supported ``TELEGRAM_CHAT_ID`` alias."""
    compatible = str(env.get("TELEGRAM_CHAT_ID") or "").split(";")
    explicit = str(env.get("TELEGRAM_OWNER_CHAT_IDS") or "").split(",")
    return _dedupe([*compatible, *explicit])
