# coding=utf-8
"""DR adapter for the shared Telegram transport."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from trendradar.dr.dispatch_executor import DRDispatchReceipt
from trendradar.dr.dispatch_plan import DRDispatchMessage
from trendradar.telegram.transport import (
    DEFAULT_API_BASE_URL,
    RecipientProvider,
    TelegramHTTPClient,
    TelegramTransport,
    TelegramTransportConfig,
    send_to_recipients,
)


@dataclass(frozen=True)
class DRTelegramSinkConfig:
    bot_token: str = field(repr=False)
    recipients: RecipientProvider = field(repr=False)
    api_base_url: str = DEFAULT_API_BASE_URL
    timeout_seconds: float = 10.0
    parse_mode: str | None = "HTML"
    attach_html: bool = True

    def __post_init__(self) -> None:
        TelegramTransportConfig(
            bot_token=self.bot_token,
            api_base_url=self.api_base_url,
            timeout_seconds=self.timeout_seconds,
        )


@dataclass
class DRTelegramSink:
    config: DRTelegramSinkConfig
    http_client: TelegramHTTPClient | None = None
    _transport: TelegramTransport | None = field(
        default=None, init=False, repr=False
    )

    def submit(
        self,
        message: DRDispatchMessage,
        *,
        message_index: int,
    ) -> DRDispatchReceipt:
        if self._transport is None:
            self._transport = TelegramTransport(
                TelegramTransportConfig(
                    bot_token=self.config.bot_token,
                    api_base_url=self.config.api_base_url,
                    timeout_seconds=self.config.timeout_seconds,
                ),
                http_client=self.http_client,
            )
        attach_document = self.config.attach_html and message.attach_html
        summary = send_to_recipients(
            self._transport,
            self.config.recipients,
            text=message.text,
            parse_mode=self.config.parse_mode,
            disable_web_page_preview=True,
            document_path=Path(message.html_path) if attach_document else None,
            document_caption="DR HTML",
        )
        if not summary.accepted:
            status = "text_rejected"
        elif summary.partial:
            status = "accepted_partial"
        else:
            status = "accepted"

        document_accepted: bool | None = None
        if attach_document and summary.text_accepted_count > 0:
            document_accepted = (
                summary.document_failed_count == 0
                and summary.document_accepted_count
                == summary.text_accepted_count
            )
        return DRDispatchReceipt(
            message_index=message_index,
            accepted=summary.accepted,
            status=status,
            detail=summary.detail(),
            run_label=message.run_label,
            date=message.date,
            text_accepted=summary.accepted,
            document_accepted=document_accepted,
            recipient_count=summary.recipient_count,
            text_accepted_count=summary.text_accepted_count,
            text_failed_count=summary.text_failed_count,
            document_accepted_count=summary.document_accepted_count,
            document_failed_count=summary.document_failed_count,
            blocked_count=summary.blocked_count,
        )
