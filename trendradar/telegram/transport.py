# coding=utf-8
"""Low-level Telegram Bot API transport shared by product adapters."""

from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
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

    @property
    def description(self) -> str:
        value = self.json_object().get("description")
        return value if isinstance(value, str) else ""

    @property
    def result(self) -> object:
        return self.json_object().get("result")


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

    def post_multipart(
        self,
        url: str,
        *,
        fields: Mapping[str, object],
        file_field: str,
        file_path: Path,
        timeout_seconds: float,
        content_type: str | None = None,
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
        return self._open(request, timeout_seconds=timeout_seconds)

    def post_multipart(
        self,
        url: str,
        *,
        fields: Mapping[str, object],
        file_field: str,
        file_path: Path,
        timeout_seconds: float,
        content_type: str | None = None,
    ) -> TelegramHTTPResponse:
        boundary = f"----PtilopsisTelegram{uuid.uuid4().hex}"
        body_parts: list[bytes] = []
        for key, value in fields.items():
            body_parts.extend(
                (
                    f"--{boundary}\r\n".encode("ascii"),
                    (
                        f'Content-Disposition: form-data; name="{key}"'
                        "\r\n\r\n"
                    ).encode("utf-8"),
                    str(value).encode("utf-8"),
                    b"\r\n",
                )
            )
        resolved_content_type = content_type
        if resolved_content_type is None:
            resolved_content_type = (
                mimetypes.guess_type(file_path.name)[0]
                or "application/octet-stream"
            )
            if resolved_content_type.startswith("text/"):
                resolved_content_type = (
                    f"{resolved_content_type}; charset=utf-8"
                )
        body_parts.extend(
            (
                f"--{boundary}\r\n".encode("ascii"),
                (
                    f'Content-Disposition: form-data; name="{file_field}"; '
                    f'filename="{file_path.name}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {resolved_content_type}\r\n\r\n".encode("ascii"),
                file_path.read_bytes(),
                b"\r\n",
                f"--{boundary}--\r\n".encode("ascii"),
            )
        )
        request = urllib.request.Request(
            url,
            data=b"".join(body_parts),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        return self._open(request, timeout_seconds=timeout_seconds)

    @staticmethod
    def _open(
        request: urllib.request.Request,
        *,
        timeout_seconds: float,
    ) -> TelegramHTTPResponse:
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


def transport_config_from_env(
    env: Mapping[str, str],
) -> TelegramTransportConfig:
    bot_token = str(env.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")
    api_base_url = (
        str(env.get("TELEGRAM_API_BASE_URL") or "").strip()
        or DEFAULT_API_BASE_URL
    )
    timeout_raw = str(env.get("TELEGRAM_TIMEOUT_SECONDS") or "").strip()
    try:
        timeout_seconds = (
            float(timeout_raw) if timeout_raw else DEFAULT_TIMEOUT_SECONDS
        )
    except ValueError as exc:
        raise ValueError(
            "TELEGRAM_TIMEOUT_SECONDS must be a positive number"
        ) from exc
    return TelegramTransportConfig(
        bot_token=bot_token,
        api_base_url=api_base_url,
        timeout_seconds=timeout_seconds,
    )


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

    def _post_json(
        self,
        method: str,
        payload: Mapping[str, object],
        *,
        timeout_seconds: float | None = None,
    ) -> TelegramHTTPResponse:
        return self.client.post_json(
            self.endpoint(method),
            payload,
            timeout_seconds=(
                self.config.timeout_seconds
                if timeout_seconds is None
                else timeout_seconds
            ),
        )

    def send_message(
        self,
        *,
        chat_id: str,
        text: str,
        parse_mode: str | None = None,
        disable_web_page_preview: bool = True,
    ) -> TelegramHTTPResponse:
        payload: dict[str, object] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        return self._post_json("sendMessage", payload)

    def send_document(
        self,
        *,
        chat_id: str,
        file_path: Path,
        caption: str,
        content_type: str | None = None,
    ) -> TelegramHTTPResponse:
        return self.client.post_multipart(
            self.endpoint("sendDocument"),
            fields={"chat_id": chat_id, "caption": caption},
            file_field="document",
            file_path=file_path,
            timeout_seconds=self.config.timeout_seconds,
            content_type=content_type,
        )

    def get_updates(
        self,
        *,
        offset: int,
        timeout_seconds: int = 50,
    ) -> TelegramHTTPResponse:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        return self._post_json(
            "getUpdates",
            {
                "offset": offset,
                "timeout": timeout_seconds,
                "allowed_updates": ["message"],
            },
            timeout_seconds=max(
                self.config.timeout_seconds,
                float(timeout_seconds + 5),
            ),
        )

    def get_webhook_info(self) -> TelegramHTTPResponse:
        return self._post_json("getWebhookInfo", {})
