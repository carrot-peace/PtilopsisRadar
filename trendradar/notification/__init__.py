# coding=utf-8
"""
通知推送模块

提供多渠道通知推送功能，包括：
- 飞书、钉钉、企业微信
- Telegram、Slack
- Email、ntfy、Bark

模块结构：
- formatters: 内容格式转换
- renderer: 通知内容渲染
- senders: 消息发送器（各渠道发送函数）
- dispatcher: 多账号通知调度器
"""

from trendradar.notification.formatters import (
    strip_markdown,
)
from trendradar.notification.senders import (
    send_to_telegram,
)
from trendradar.notification.dispatcher import NotificationDispatcher

__all__ = [
    # 格式转换
    "strip_markdown",
    # 消息发送器
    "send_to_telegram",
    # 通知调度器
    "NotificationDispatcher",
]
