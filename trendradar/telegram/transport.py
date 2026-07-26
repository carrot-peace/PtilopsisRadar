# coding=utf-8
"""Low-level Telegram Bot API transport shared by product adapters."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from functools import cached_property
from typing import Mapping, Protocol, runtime_checkable


DEFAULT_API_BASE_URL = "https://api.telegram.org"
DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class TelegramHTTPResponse:
    status_code: int
    body: str

    @cached_property
    def _decoded_json_object(self) -> dict[str, object]:
        try:
            value = json.loads(self.body)
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def json_object(self) -> dict[str, object]:
        return dict(self._decoded_json_object)

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300 and self.json_object().get("ok") is True


@runtime_checkable
class TelegramHTTPClient(Protocol):
    def post_json(
        self,
        url: str,
        payload: Mapping[str, object],
        *,
        timeout_seconds: float,
    ) -> TelegramHTTPResponse:
        ...


@dataclass
class UrllibTelegramHTTPClient:
    def post_json(
        self,
        url: str,
        payload: Mapping[str, object],
        *,
        timeout_seconds: float,
    ) -> TelegramHTTPResponse:
        request = urllib.request.Request(
            url,
            data=json.dumps(dict(payload)).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                status = int(getattr(response, "status", None) or response.getcode())
                body = response.read().decode("utf-8", errors="replace")
                return TelegramHTTPResponse(status, body)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return TelegramHTTPResponse(int(exc.code), body)


@dataclass(frozen=True)
class TelegramTransportConfig:
    bot_token: str = field(repr=False)
    api_base_url: str = DEFAULT_API_BASE_URL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not self.bot_token:
            raise ValueError("bot_token must be non-empty")
        if not self.api_base_url:
            raise ValueError("api_base_url must be non-empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


@dataclass
class TelegramTransport:
    config: TelegramTransportConfig
    http_client: TelegramHTTPClient | None = None
    _default_http_client: TelegramHTTPClient | None = field(
        default=None,
        init=False,
        repr=False,
    )

    @property
    def client(self) -> TelegramHTTPClient:
        if self.http_client is not None:
            return self.http_client
        if self._default_http_client is None:
            self._default_http_client = UrllibTelegramHTTPClient()
        return self._default_http_client

    def endpoint(self, method: str) -> str:
        return (
            f"{self.config.api_base_url.rstrip('/')}"
            f"/bot{self.config.bot_token}/{method}"
        )

    def send_message(
        self,
        *,
        chat_id: str,
        text: str,
        disable_web_page_preview: bool = True,
    ) -> TelegramHTTPResponse:
        return self.client.post_json(
            self.endpoint("sendMessage"),
            {
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": disable_web_page_preview,
            },
            timeout_seconds=self.config.timeout_seconds,
        )
