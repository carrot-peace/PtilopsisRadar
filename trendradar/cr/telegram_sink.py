# coding=utf-8
"""
CR Telegram dispatch adapter.

A Telegram-specific implementation of the PR9m ``CRDispatchSink`` boundary.
It can submit a planned :class:`CRDispatchMessage` to Telegram's send-message
endpoint when explicitly injected by the caller.

The adapter is wired into the CR runtime only when live dispatch mode and the
CR-specific Telegram send gate are both enabled.  Nothing sends by default.
There is no rate limiting, repeat-suppression state, retry / backoff, or
scheduled runtime sending.

Telegram HTTP details live in :mod:`trendradar.telegram.transport`; this module
retains only CR configuration and receipt semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from trendradar.cr.dispatch_executor import CRDispatchReceipt
from trendradar.cr.dispatch_plan import CRDispatchMessage
from trendradar.telegram.transport import (
    DEFAULT_API_BASE_URL,
    TelegramHTTPClient,
    TelegramHTTPResponse,
    TelegramTransport,
    TelegramTransportConfig,
    UrllibTelegramHTTPClient,
)


CRTelegramHTTPResponse = TelegramHTTPResponse
CRTelegramHTTPClient = TelegramHTTPClient
CRUrllibTelegramHTTPClient = UrllibTelegramHTTPClient


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CRTelegramSinkConfig:
    """Configuration for the Telegram dispatch sink.

    ``bot_token`` is excluded from ``repr`` so it does not leak into logs or
    tracebacks.  Validation happens at construction time.
    """

    bot_token: str = field(repr=False)
    chat_id: str
    api_base_url: str = DEFAULT_API_BASE_URL
    timeout_seconds: float = 10.0
    parse_mode: str | None = None
    disable_web_page_preview: bool = True
    transport_config: TelegramTransportConfig = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not self.chat_id:
            raise ValueError("chat_id must be non-empty")
        object.__setattr__(
            self,
            "transport_config",
            TelegramTransportConfig(
                bot_token=self.bot_token,
                api_base_url=self.api_base_url,
                timeout_seconds=self.timeout_seconds,
            ),
        )


def _sanitize_telegram_detail(raw: str, config: CRTelegramSinkConfig) -> str:
    """Produce a short, secret-free detail string.

    Redacts the bot token and chat id (defensive — Telegram descriptions do not
    normally echo them) and truncates to a small length.
    """
    cleaned = raw.replace(config.bot_token, "***")
    if config.chat_id:
        cleaned = cleaned.replace(config.chat_id, "***")
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > 80:
        cleaned = cleaned[:77] + "..."
    return cleaned


# ---------------------------------------------------------------------------
# Sink
# ---------------------------------------------------------------------------


@dataclass
class CRTelegramSink:
    """Telegram-specific dispatch sink (implements ``CRDispatchSink``).

    Submits a planned message through the shared Telegram transport.
    The sink never mutates the message, re-checks eligibility, re-renders text,
    or recomputes dispatch decisions.  Transport exceptions from the HTTP
    client propagate (v0.1).
    """

    config: CRTelegramSinkConfig
    http_client: TelegramHTTPClient | None = None
    transport: TelegramTransport = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.transport = TelegramTransport(
            self.config.transport_config,
            http_client=self.http_client,
        )

    def submit(
        self, message: CRDispatchMessage, *, message_index: int
    ) -> CRDispatchReceipt:
        response = self.transport.send_message(
            chat_id=self.config.chat_id,
            text=message.text,
            parse_mode=self.config.parse_mode,
            disable_web_page_preview=self.config.disable_web_page_preview,
        )
        return self._receipt_from_response(response, message, message_index)

    def _receipt_from_response(
        self,
        response: TelegramHTTPResponse,
        message: CRDispatchMessage,
        message_index: int,
    ) -> CRDispatchReceipt:
        if 200 <= response.status_code < 300:
            if response.ok:
                return self._receipt(
                    message_index, message,
                    accepted=True, status="accepted", detail="telegram_ok",
                )
            description = response.description
            detail = _sanitize_telegram_detail(
                f"telegram_rejected:{description}" if description
                else "telegram_rejected",
                self.config,
            )
            return self._receipt(
                message_index, message,
                accepted=False, status="rejected", detail=detail,
            )

        # Non-2xx HTTP response — token never included in the detail.
        return self._receipt(
            message_index, message,
            accepted=False, status="http_error",
            detail=f"http_{response.status_code}",
        )

    def _receipt(
        self,
        message_index: int,
        message: CRDispatchMessage,
        *,
        accepted: bool,
        status: str,
        detail: str,
    ) -> CRDispatchReceipt:
        return CRDispatchReceipt(
            message_index=message_index,
            accepted=accepted,
            status=status,
            detail=detail,
            candidate_count=message.candidate_count,
            run_label=message.run_label,
        )
