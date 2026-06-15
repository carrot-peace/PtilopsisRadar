# coding=utf-8
"""Fail-closed stubs for the removed Legacy Push sender layer."""

from __future__ import annotations

from .removed import LegacyNotificationRemovedError, raise_legacy_notification_removed


def send_to_telegram(*args, **kwargs):
    """Legacy Telegram sending is removed and must fail closed."""
    raise_legacy_notification_removed()


def send_telegram_document(*args, **kwargs):
    """Legacy Telegram document sending is removed and must fail closed."""
    raise_legacy_notification_removed()


def should_apply_realtime_alert_gate(*args, **kwargs):
    """Legacy realtime alert gate is removed with the old sender path."""
    raise_legacy_notification_removed()


def resolve_attachment_kind_for_event(*args, **kwargs):
    """Legacy attachment routing is removed with the old sender path."""
    raise_legacy_notification_removed()


def resolve_report_attachment_path(*args, **kwargs):
    """Legacy attachment routing is removed with the old sender path."""
    raise_legacy_notification_removed()


__all__ = [
    "LegacyNotificationRemovedError",
    "send_to_telegram",
    "send_telegram_document",
    "should_apply_realtime_alert_gate",
    "resolve_attachment_kind_for_event",
    "resolve_report_attachment_path",
]
