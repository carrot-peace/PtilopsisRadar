# coding=utf-8
"""DR Telegram dispatch sink.

Telegram transport for the DR pipeline only.  This module does not import or
reuse CR Telegram code and is only reachable through explicit DR env gates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from trendradar.dr.dispatch_executor import DRDispatchReceipt
from trendradar.dr.dispatch_plan import DRDispatchMessage
from trendradar.telegram.transport import (
    DEFAULT_API_BASE_URL,
    TelegramHTTPClient,
    TelegramHTTPResponse,
    TelegramTransport,
    TelegramTransportConfig,
)


@dataclass(frozen=True)
class DRTelegramSinkConfig:
    bot_token: str = field(repr=False)
    chat_id: str
    api_base_url: str = DEFAULT_API_BASE_URL
    timeout_seconds: float = 10.0
    parse_mode: str | None = "HTML"
    attach_html: bool = True

    def __post_init__(self) -> None:
        if not self.chat_id:
            raise ValueError("chat_id must be non-empty")
        TelegramTransportConfig(
            bot_token=self.bot_token,
            api_base_url=self.api_base_url,
            timeout_seconds=self.timeout_seconds,
        )


def _sanitize(raw: str, config: DRTelegramSinkConfig) -> str:
    cleaned = raw.replace(config.bot_token, "***")
    cleaned = cleaned.replace(config.chat_id, "***")
    cleaned = " ".join(cleaned.split())
    return cleaned[:77] + "..." if len(cleaned) > 80 else cleaned


@dataclass
class DRTelegramSink:
    config: DRTelegramSinkConfig
    http_client: TelegramHTTPClient | None = None

    def submit(
        self, message: DRDispatchMessage, *, message_index: int
    ) -> DRDispatchReceipt:
        transport = TelegramTransport(
            TelegramTransportConfig(
                bot_token=self.config.bot_token,
                api_base_url=self.config.api_base_url,
                timeout_seconds=self.config.timeout_seconds,
            ),
            http_client=self.http_client,
        )
        text_response = transport.send_message(
            chat_id=self.config.chat_id,
            text=message.text,
            parse_mode=self.config.parse_mode,
            disable_web_page_preview=True,
        )
        if not text_response.ok:
            return self._receipt(
                message,
                message_index,
                accepted=False,
                status="text_rejected",
                detail=self._detail("text", text_response),
                text_accepted=False,
                document_accepted=None,
            )

        document_accepted: bool | None = None
        if self.config.attach_html and message.attach_html:
            html_path = Path(message.html_path)
            if html_path.exists():
                doc_response = transport.send_document(
                    chat_id=self.config.chat_id,
                    file_path=html_path,
                    caption="DR HTML",
                    content_type="text/html; charset=utf-8",
                )
                document_accepted = doc_response.ok
                if not document_accepted:
                    return self._receipt(
                        message,
                        message_index,
                        accepted=True,
                        status="accepted_document_failed",
                        detail=self._detail("document", doc_response),
                        text_accepted=True,
                        document_accepted=False,
                    )
            else:
                document_accepted = False
                return self._receipt(
                    message,
                    message_index,
                    accepted=True,
                    status="accepted_document_missing",
                    detail="html_missing",
                    text_accepted=True,
                    document_accepted=False,
                )

        return self._receipt(
            message,
            message_index,
            accepted=True,
            status="accepted",
            detail="telegram_ok",
            text_accepted=True,
            document_accepted=document_accepted,
        )

    def _detail(self, stage: str, response: TelegramHTTPResponse) -> str:
        desc = response.description
        raw = f"{stage}_http_{response.status_code}"
        if desc:
            raw = f"{raw}:{desc}"
        return _sanitize(raw, self.config)

    @staticmethod
    def _receipt(
        message: DRDispatchMessage,
        message_index: int,
        *,
        accepted: bool,
        status: str,
        detail: str,
        text_accepted: bool,
        document_accepted: bool | None,
    ) -> DRDispatchReceipt:
        return DRDispatchReceipt(
            message_index=message_index,
            accepted=accepted,
            status=status,
            detail=detail,
            run_label=message.run_label,
            date=message.date,
            text_accepted=text_accepted,
            document_accepted=document_accepted,
        )
