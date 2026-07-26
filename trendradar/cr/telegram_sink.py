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
from typing import Protocol, cast, runtime_checkable

from trendradar.cr.dispatch_executor import CRDispatchReceipt
from trendradar.cr.dispatch_plan import CRDispatchMessage
from trendradar.telegram.fanout import RecipientProvider, send_to_recipients
from trendradar.telegram.transport import (
    DEFAULT_API_BASE_URL,
    TelegramHTTPClient,
    TelegramHTTPResponse,
    TelegramTransport,
    TelegramTransportConfig,
    UrllibTelegramHTTPClient,
)


CRTelegramHTTPResponse = TelegramHTTPResponse


@runtime_checkable
class CRTelegramHTTPClient(Protocol):
    def post_json(
        self,
        url: str,
        payload: dict[str, object],
        *,
        timeout_seconds: float,
    ) -> TelegramHTTPResponse:
        ...


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
    recipients: RecipientProvider = field(repr=False)
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
        object.__setattr__(
            self,
            "transport_config",
            TelegramTransportConfig(
                bot_token=self.bot_token,
                api_base_url=self.api_base_url,
                timeout_seconds=self.timeout_seconds,
            ),
        )

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
    http_client: CRTelegramHTTPClient | None = None
    transport: TelegramTransport = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.transport = TelegramTransport(
            self.config.transport_config,
            http_client=cast(TelegramHTTPClient | None, self.http_client),
        )

    def submit(
        self, message: CRDispatchMessage, *, message_index: int
    ) -> CRDispatchReceipt:
        summary = send_to_recipients(
            self.transport,
            self.config.recipients,
            text=message.text,
            parse_mode=self.config.parse_mode,
            disable_web_page_preview=self.config.disable_web_page_preview,
        )
        if not summary.accepted:
            status = "rejected"
        elif summary.partial:
            status = "accepted_partial"
        else:
            status = "accepted"
        return self._receipt(
            message_index,
            message,
            accepted=summary.accepted,
            status=status,
            detail=summary.detail(),
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
