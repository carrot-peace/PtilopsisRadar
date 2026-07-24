# coding=utf-8
"""Single low-level Telegram Bot API boundary.

Product pipelines keep their own planning and receipt semantics.  This module
owns the HTTP details shared by CR, DR, operator alerts, and the inbound bot.
"""

from __future__ import annotations

import json
import mimetypes
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence, runtime_checkable


DEFAULT_API_BASE_URL = "https://api.telegram.org"
DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class TelegramHTTPResponse:
    status_code: int
    body: str

    def json_object(self) -> dict[str, object]:
        try:
            value = json.loads(self.body)
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

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
    ) -> TelegramHTTPResponse:
        ...


@dataclass
class UrllibTelegramHTTPClient:
    """Standard-library Bot API client.

    HTTP errors are returned as responses so callers can classify Telegram
    errors.  Connection, timeout, and filesystem failures propagate.
    """

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
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        body_parts.extend(
            (
                f"--{boundary}\r\n".encode("ascii"),
                (
                    f'Content-Disposition: form-data; name="{file_field}"; '
                    f'filename="{file_path.name}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {content_type}\r\n\r\n".encode("ascii"),
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
    max_requests_per_second: float = 20.0

    def __post_init__(self) -> None:
        if not self.bot_token:
            raise ValueError("bot_token must be non-empty")
        if not self.api_base_url:
            raise ValueError("api_base_url must be non-empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_requests_per_second <= 0:
            raise ValueError("max_requests_per_second must be positive")


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
    if timeout_raw:
        try:
            timeout_seconds = float(timeout_raw)
        except ValueError as exc:
            raise ValueError(
                "TELEGRAM_TIMEOUT_SECONDS must be a positive number"
            ) from exc
        if timeout_seconds <= 0:
            raise ValueError(
                "TELEGRAM_TIMEOUT_SECONDS must be a positive number"
            )
    else:
        timeout_seconds = DEFAULT_TIMEOUT_SECONDS
    return TelegramTransportConfig(
        bot_token=bot_token,
        api_base_url=api_base_url,
        timeout_seconds=timeout_seconds,
    )


@dataclass
class TelegramTransport:
    config: TelegramTransportConfig
    http_client: TelegramHTTPClient | None = None
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _last_request_at: float | None = field(default=None, init=False, repr=False)

    @property
    def client(self) -> TelegramHTTPClient:
        return self.http_client or UrllibTelegramHTTPClient()

    def endpoint(self, method: str) -> str:
        return (
            f"{self.config.api_base_url.rstrip('/')}"
            f"/bot{self.config.bot_token}/{method}"
        )

    def post_json(
        self,
        method: str,
        payload: Mapping[str, object],
        *,
        timeout_seconds: float | None = None,
    ) -> TelegramHTTPResponse:
        self._rate_limit()
        return self.client.post_json(
            self.endpoint(method),
            payload,
            timeout_seconds=timeout_seconds or self.config.timeout_seconds,
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
        return self.post_json("sendMessage", payload)

    def send_document(
        self,
        *,
        chat_id: str,
        file_path: Path,
        caption: str,
    ) -> TelegramHTTPResponse:
        self._rate_limit()
        return self.client.post_multipart(
            self.endpoint("sendDocument"),
            fields={"chat_id": chat_id, "caption": caption},
            file_field="document",
            file_path=file_path,
            timeout_seconds=self.config.timeout_seconds,
        )

    def get_updates(
        self,
        *,
        offset: int,
        timeout_seconds: int = 50,
    ) -> TelegramHTTPResponse:
        return self.post_json(
            "getUpdates",
            {
                "offset": offset,
                "timeout": timeout_seconds,
                "allowed_updates": ["message"],
            },
            timeout_seconds=max(
                self.config.timeout_seconds, float(timeout_seconds + 5)
            ),
        )

    def get_webhook_info(self) -> TelegramHTTPResponse:
        return self.post_json("getWebhookInfo", {})

    def _rate_limit(self) -> None:
        interval = 1.0 / self.config.max_requests_per_second
        now = self.monotonic()
        if self._last_request_at is not None:
            remaining = interval - (now - self._last_request_at)
            if remaining > 0:
                self.sleep(remaining)
                now = self.monotonic()
        self._last_request_at = now


class RecipientProvider(Protocol):
    def get_chat_ids(self) -> Sequence[str]:
        ...

    def mark_blocked(self, chat_id: str) -> None:
        ...


@dataclass(frozen=True)
class StaticRecipientProvider:
    chat_ids: tuple[str, ...]

    def get_chat_ids(self) -> Sequence[str]:
        return self.chat_ids

    def mark_blocked(self, chat_id: str) -> None:
        return None


@dataclass(frozen=True)
class TelegramFanoutSummary:
    recipient_count: int
    text_accepted_count: int
    text_failed_count: int
    document_accepted_count: int
    document_failed_count: int
    blocked_count: int

    @property
    def accepted(self) -> bool:
        return self.text_accepted_count > 0

    @property
    def partial(self) -> bool:
        return self.accepted and (
            self.text_failed_count > 0 or self.document_failed_count > 0
        )

    def detail(self) -> str:
        return (
            f"recipients={self.recipient_count},"
            f"text_ok={self.text_accepted_count},"
            f"text_failed={self.text_failed_count},"
            f"document_ok={self.document_accepted_count},"
            f"document_failed={self.document_failed_count},"
            f"blocked={self.blocked_count}"
        )


def send_to_recipients(
    transport: TelegramTransport,
    recipients: RecipientProvider,
    *,
    text: str,
    parse_mode: str | None,
    disable_web_page_preview: bool,
    document_path: Path | None = None,
    document_caption: str = "",
) -> TelegramFanoutSummary:
    """Sequentially deliver one product message and aggregate the outcome."""
    chat_ids = tuple(dict.fromkeys(str(value) for value in recipients.get_chat_ids()))
    text_ok = 0
    text_failed = 0
    document_ok = 0
    document_failed = 0
    blocked: set[str] = set()

    document_requested = document_path is not None
    document_exists = document_path is not None and document_path.is_file()

    for chat_id in chat_ids:
        try:
            text_response = transport.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
            )
        except (ConnectionError, OSError, TimeoutError):
            text_failed += 1
            continue
        if not text_response.ok:
            text_failed += 1
            if text_response.status_code == 403:
                blocked.add(chat_id)
                recipients.mark_blocked(chat_id)
            continue
        text_ok += 1

        if not document_requested:
            continue
        if not document_exists:
            document_failed += 1
            continue
        try:
            document_response = transport.send_document(
                chat_id=chat_id,
                file_path=document_path,
                caption=document_caption,
            )
        except (ConnectionError, OSError, TimeoutError):
            document_failed += 1
            continue
        if document_response.ok:
            document_ok += 1
        else:
            document_failed += 1
            if document_response.status_code == 403:
                blocked.add(chat_id)
                recipients.mark_blocked(chat_id)

    return TelegramFanoutSummary(
        recipient_count=len(chat_ids),
        text_accepted_count=text_ok,
        text_failed_count=text_failed,
        document_accepted_count=document_ok,
        document_failed_count=document_failed,
        blocked_count=len(blocked),
    )
