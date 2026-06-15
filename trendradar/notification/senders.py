# coding=utf-8
"""Fail-closed stubs for the removed Legacy Push sender layer."""

from __future__ import annotations

from typing import Any, Callable, Dict, NoReturn, Optional

from .removed import LegacyNotificationRemovedError, raise_legacy_notification_removed


def send_to_telegram(
    bot_token: str,
    chat_id: str,
    report_data: Dict,
    report_type: str,
    update_info: Optional[Dict] = None,
    proxy_url: Optional[str] = None,
    mode: str = "daily",
    account_label: str = "",
    *,
    batch_size: int = 4000,
    batch_interval: float = 1.0,
    rss_items: Optional[list] = None,
    rss_new_items: Optional[list] = None,
    ai_analysis: Any = None,
    display_regions: Optional[Dict] = None,
    html_file_path: Optional[str] = None,
    get_time_func: Optional[Callable] = None,
    alert_state_store: Any = None,
    alert_config: Optional[Dict] = None,
    manual_trigger: bool = False,
) -> NoReturn:
    """Legacy Telegram sending is removed and must fail closed."""
    raise_legacy_notification_removed()


def send_telegram_document(
    bot_token: str,
    chat_id: str,
    document_path: str,
    *,
    filename: Optional[str] = None,
    caption: Optional[str] = None,
    proxy_url: Optional[str] = None,
    max_file_mb: float = 8,
    timeout: int = 60,
    log_prefix: str = "Telegram",
) -> NoReturn:
    """Legacy Telegram document sending is removed and must fail closed."""
    raise_legacy_notification_removed()


def should_apply_realtime_alert_gate(
    report_style: str,
    mode: str,
    manual_trigger: bool = False,
) -> NoReturn:
    """Legacy realtime alert gate is removed with the old sender path."""
    raise_legacy_notification_removed()


def resolve_attachment_kind_for_event(cfg: Dict[str, Any], event_name: str) -> NoReturn:
    """Legacy attachment routing is removed with the old sender path."""
    raise_legacy_notification_removed()


def resolve_report_attachment_path(
    output_dir: str, mode: str, report_kind: str = "full"
) -> NoReturn:
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
