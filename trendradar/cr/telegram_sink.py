# coding=utf-8
"""CR adapter for the shared Telegram transport."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from trendradar.cr.dispatch_executor import CRDispatchReceipt
from trendradar.cr.dispatch_plan import CRDispatchMessage
from trendradar.telegram.transport import (
    DEFAULT_API_BASE_URL,
    RecipientProvider,
    TelegramHTTPClient,
    TelegramTransport,
    TelegramTransportConfig,
    send_to_recipients,
)


@dataclass(frozen=True)
class CRTelegramSinkConfig:
    bot_token: str = field(repr=False)
    recipients: RecipientProvider = field(repr=False)
    api_base_url: str = DEFAULT_API_BASE_URL
    timeout_seconds: float = 10.0
    parse_mode: str | None = None
    disable_web_page_preview: bool = True
    attach_html: bool = True

    def __post_init__(self) -> None:
        TelegramTransportConfig(
            bot_token=self.bot_token,
            api_base_url=self.api_base_url,
            timeout_seconds=self.timeout_seconds,
        )


@dataclass
class CRTelegramSink:
    config: CRTelegramSinkConfig
    http_client: TelegramHTTPClient | None = None
    _transport: TelegramTransport | None = field(
        default=None, init=False, repr=False
    )

    def submit(
        self,
        message: CRDispatchMessage,
        *,
        message_index: int,
    ) -> CRDispatchReceipt:
        if self._transport is None:
            self._transport = TelegramTransport(
                TelegramTransportConfig(
                    bot_token=self.config.bot_token,
                    api_base_url=self.config.api_base_url,
                    timeout_seconds=self.config.timeout_seconds,
                ),
                http_client=self.http_client,
            )
        document_path = (
            Path(message.html_path)
            if self.config.attach_html and message.html_path
            else None
        )
        summary = send_to_recipients(
            self._transport,
            self.config.recipients,
            text=message.text,
            parse_mode=self.config.parse_mode,
            disable_web_page_preview=self.config.disable_web_page_preview,
            document_path=document_path,
            document_caption="CR HTML",
        )
        if not summary.accepted:
            status = "rejected"
        elif summary.partial:
            status = "accepted_partial"
        else:
            status = "accepted"
        return CRDispatchReceipt(
            message_index=message_index,
            accepted=summary.accepted,
            status=status,
            detail=summary.detail(),
            candidate_count=message.candidate_count,
            run_label=message.run_label,
            recipient_count=summary.recipient_count,
            text_accepted_count=summary.text_accepted_count,
            text_failed_count=summary.text_failed_count,
            document_accepted_count=summary.document_accepted_count,
            document_failed_count=summary.document_failed_count,
            blocked_count=summary.blocked_count,
        )
