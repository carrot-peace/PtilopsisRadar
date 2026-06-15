# coding=utf-8
"""Fail-closed stub for the removed Legacy Push dispatcher."""

from __future__ import annotations

from .removed import LegacyNotificationRemovedError, raise_legacy_notification_removed


class NotificationDispatcher:
    """Legacy notification dispatcher stub.

    The old dispatcher is intentionally importable during PR-C1 so stale imports
    fail with an explicit removal error instead of silently succeeding.
    """

    def __init__(self, *args, **kwargs):
        raise_legacy_notification_removed()

    def translate_content(self, *args, **kwargs):
        raise_legacy_notification_removed()

    def dispatch_all(self, *args, **kwargs):
        raise_legacy_notification_removed()

    def _send_telegram(self, *args, **kwargs):
        raise_legacy_notification_removed()

    def _send_telegram_attachments(self, *args, **kwargs):
        raise_legacy_notification_removed()


__all__ = ["LegacyNotificationRemovedError", "NotificationDispatcher"]
