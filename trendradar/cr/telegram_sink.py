# coding=utf-8
"""
CR Telegram dispatch sink / external channel boundary (PR9n) v0.1.

A Telegram-specific implementation of the PR9m ``CRDispatchSink`` boundary.
It can submit a planned :class:`CRDispatchMessage` to Telegram's send-message
endpoint when explicitly injected by the caller.

This PR adds the sink module only.  It is NOT wired into the CR runtime or
default dispatch execution — nothing sends by default.  There is no
configuration wiring, no rate limiting, no repeat-suppression state, no
retry / backoff, and no scheduled runtime sending.

Secrecy: the bot token is never placed into a :class:`CRDispatchReceipt`
detail, never embedded in an exception this module raises, and is excluded from
the config ``repr``.

Uses the standard library only (``json`` + ``urllib``).  No third-party HTTP
dependency.  Tests inject a fake HTTP client and never touch the network.

Design reference: PR9n.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from trendradar.cr.dispatch_executor import CRDispatchReceipt
from trendradar.cr.dispatch_plan import CRDispatchMessage


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
    api_base_url: str = "https://api.telegram.org"
    timeout_seconds: float = 10.0
    parse_mode: str | None = None
    disable_web_page_preview: bool = True

    def __post_init__(self) -> None:
        if not self.bot_token:
            raise ValueError("bot_token must be non-empty")
        if not self.chat_id:
            raise ValueError("chat_id must be non-empty")
        if not self.api_base_url:
            raise ValueError("api_base_url must be non-empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


# ---------------------------------------------------------------------------
# HTTP transport
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CRTelegramHTTPResponse:
    """A minimal HTTP response (status + raw body text)."""

    status_code: int
    body: str


@runtime_checkable
class CRTelegramHTTPClient(Protocol):
    """Transport abstraction so tests can inject a fake client."""

    def post_json(
        self,
        url: str,
        payload: dict[str, object],
        *,
        timeout_seconds: float,
    ) -> CRTelegramHTTPResponse:
        ...


@dataclass
class CRUrllibTelegramHTTPClient:
    """Standard-library HTTP client using :mod:`urllib.request`.

    Posts a JSON body with ``Content-Type: application/json``.  Non-2xx
    responses (e.g. HTTP 400 from Telegram) are returned as a
    :class:`CRTelegramHTTPResponse` so the sink can classify them; genuine
    transport failures (connection errors, timeouts) propagate.  No retry or
    backoff in this PR.
    """

    def post_json(
        self,
        url: str,
        payload: dict[str, object],
        *,
        timeout_seconds: float,
    ) -> CRTelegramHTTPResponse:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=timeout_seconds
            ) as response:
                body = response.read().decode("utf-8", errors="replace")
                status_code = getattr(response, "status", None) or response.getcode()
                return CRTelegramHTTPResponse(
                    status_code=int(status_code), body=body
                )
        except urllib.error.HTTPError as exc:
            # An HTTP-level error response (4xx/5xx) is still a response we can
            # classify — read its body and return it rather than raising.
            body = exc.read().decode("utf-8", errors="replace")
            return CRTelegramHTTPResponse(status_code=int(exc.code), body=body)


# ---------------------------------------------------------------------------
# Payload / URL / detail helpers
# ---------------------------------------------------------------------------


def build_telegram_send_message_url(config: CRTelegramSinkConfig) -> str:
    """Build the Telegram ``sendMessage`` endpoint URL.

    Trailing slashes on ``api_base_url`` are trimmed.  The bot token is part of
    the URL path; this URL is never placed into a receipt detail.
    """
    base = config.api_base_url.rstrip("/")
    return f"{base}/bot{config.bot_token}/sendMessage"


def build_telegram_send_message_payload(
    message: CRDispatchMessage,
    config: CRTelegramSinkConfig,
) -> dict[str, object]:
    """Build the ``sendMessage`` JSON payload from a planned message.

    Does not mutate ``message``.  ``parse_mode`` is included only when
    configured (non-None); web-preview suppression reflects config.
    """
    payload: dict[str, object] = {
        "chat_id": config.chat_id,
        "text": message.text,
        "disable_web_page_preview": config.disable_web_page_preview,
    }
    if config.parse_mode is not None:
        payload["parse_mode"] = config.parse_mode
    return payload


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


def _extract_description(body: str) -> str:
    """Best-effort extraction of Telegram's ``description`` from a JSON body."""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return ""
    if isinstance(data, dict):
        desc = data.get("description")
        if isinstance(desc, str):
            return desc
    return ""


def _response_is_ok(body: str) -> bool:
    """Return True only when the JSON body has ``ok: true``."""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return False
    return isinstance(data, dict) and data.get("ok") is True


# ---------------------------------------------------------------------------
# Sink
# ---------------------------------------------------------------------------


@dataclass
class CRTelegramSink:
    """Telegram-specific dispatch sink (implements ``CRDispatchSink``).

    Submits a planned message to Telegram via an injected ``http_client``; when
    none is supplied, a stdlib :class:`CRUrllibTelegramHTTPClient` is used.
    The sink never mutates the message, re-checks eligibility, re-renders text,
    or recomputes dispatch decisions.  Transport exceptions from the HTTP
    client propagate (v0.1).
    """

    config: CRTelegramSinkConfig
    http_client: CRTelegramHTTPClient | None = None

    def submit(
        self, message: CRDispatchMessage, *, message_index: int
    ) -> CRDispatchReceipt:
        client = self.http_client or CRUrllibTelegramHTTPClient()
        url = build_telegram_send_message_url(self.config)
        payload = build_telegram_send_message_payload(message, self.config)

        response = client.post_json(
            url, payload, timeout_seconds=self.config.timeout_seconds
        )
        return self._receipt_from_response(response, message, message_index)

    def _receipt_from_response(
        self,
        response: CRTelegramHTTPResponse,
        message: CRDispatchMessage,
        message_index: int,
    ) -> CRDispatchReceipt:
        if 200 <= response.status_code < 300:
            if _response_is_ok(response.body):
                return self._receipt(
                    message_index, message,
                    accepted=True, status="accepted", detail="telegram_ok",
                )
            description = _extract_description(response.body)
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
