# coding=utf-8
"""Fail-closed facade for the removed Legacy Push package."""

from trendradar.notification.formatters import (
    strip_markdown,
)
from trendradar.notification.removed import (
    LegacyNotificationRemovedError,
)
from trendradar.notification.senders import (
    send_telegram_document,
    send_to_telegram,
)
from trendradar.notification.dispatcher import NotificationDispatcher

__all__ = [
    "LegacyNotificationRemovedError",
    "strip_markdown",
    "send_telegram_document",
    "send_to_telegram",
    "NotificationDispatcher",
]
