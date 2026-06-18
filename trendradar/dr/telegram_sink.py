# coding=utf-8
"""DR Telegram dispatch sink.

Telegram transport for the DR pipeline only.  This module does not import or
reuse CR Telegram code and is only reachable through explicit DR env gates.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from trendradar.dr.dispatch_executor import DRDispatchReceipt
from trendradar.dr.dispatch_plan import DRDispatchMessage


@dataclass(frozen=True)
class DRTelegramSinkConfig:
    bot_token: str = field(repr=False)
    chat_id: str
    api_base_url: str = "https://api.telegram.org"
    timeout_seconds: float = 10.0
    parse_mode: str | None = "HTML"
    attach_html: bool = True

    def __post_init__(self) -> None:
        if not self.bot_token:
            raise ValueError("bot_token must be non-empty")
        if not self.chat_id:
            raise ValueError("chat_id must be non-empty")
        if not self.api_base_url:
            raise ValueError("api_base_url must be non-empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


@dataclass(frozen=True)
class DRTelegramHTTPResponse:
    status_code: int
    body: str


@runtime_checkable
class DRTelegramHTTPClient(Protocol):
    def post_json(
        self,
        url: str,
        payload: dict[str, object],
        *,
        timeout_seconds: float,
    ) -> DRTelegramHTTPResponse:
        ...

    def post_multipart(
        self,
        url: str,
        *,
        fields: dict[str, object],
        file_field: str,
        file_path: Path,
        timeout_seconds: float,
    ) -> DRTelegramHTTPResponse:
        ...


@dataclass
class DRUrllibTelegramHTTPClient:
    def post_json(
        self,
        url: str,
        payload: dict[str, object],
        *,
        timeout_seconds: float,
    ) -> DRTelegramHTTPResponse:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body = response.read().decode("utf-8", errors="replace")
                status_code = getattr(response, "status", None) or response.getcode()
                return DRTelegramHTTPResponse(int(status_code), body)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return DRTelegramHTTPResponse(int(exc.code), body)

    def post_multipart(
        self,
        url: str,
        *,
        fields: dict[str, object],
        file_field: str,
        file_path: Path,
        timeout_seconds: float,
    ) -> DRTelegramHTTPResponse:
        boundary = "----PtilopsisDRBoundary"
        body_parts: list[bytes] = []
        for key, value in fields.items():
            body_parts.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                    str(value).encode("utf-8"),
                    b"\r\n",
                ]
            )
        filename = file_path.name
        body_parts.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{file_field}"; '
                    f'filename="{filename}"\r\n'
                ).encode(),
                b"Content-Type: text/html; charset=utf-8\r\n\r\n",
                file_path.read_bytes(),
                b"\r\n",
                f"--{boundary}--\r\n".encode(),
            ]
        )
        data = b"".join(body_parts)
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body = response.read().decode("utf-8", errors="replace")
                status_code = getattr(response, "status", None) or response.getcode()
                return DRTelegramHTTPResponse(int(status_code), body)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return DRTelegramHTTPResponse(int(exc.code), body)


def _endpoint(config: DRTelegramSinkConfig, method: str) -> str:
    return f"{config.api_base_url.rstrip('/')}/bot{config.bot_token}/{method}"


def build_telegram_send_message_payload(
    message: DRDispatchMessage,
    config: DRTelegramSinkConfig,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "chat_id": config.chat_id,
        "text": message.text,
        "disable_web_page_preview": True,
    }
    if config.parse_mode:
        payload["parse_mode"] = config.parse_mode
    return payload


def build_telegram_send_document_fields(
    message: DRDispatchMessage,
    config: DRTelegramSinkConfig,
) -> dict[str, object]:
    return {
        "chat_id": config.chat_id,
        "caption": "DR HTML",
    }


def _response_ok(response: DRTelegramHTTPResponse) -> bool:
    if not (200 <= response.status_code < 300):
        return False
    try:
        data = json.loads(response.body)
    except (TypeError, ValueError):
        return False
    return isinstance(data, dict) and data.get("ok") is True


def _description(response: DRTelegramHTTPResponse) -> str:
    try:
        data = json.loads(response.body)
    except (TypeError, ValueError):
        return ""
    if isinstance(data, dict) and isinstance(data.get("description"), str):
        return data["description"]
    return ""


def _sanitize(raw: str, config: DRTelegramSinkConfig) -> str:
    cleaned = raw.replace(config.bot_token, "***")
    cleaned = cleaned.replace(config.chat_id, "***")
    cleaned = " ".join(cleaned.split())
    return cleaned[:77] + "..." if len(cleaned) > 80 else cleaned


@dataclass
class DRTelegramSink:
    config: DRTelegramSinkConfig
    http_client: DRTelegramHTTPClient | None = None

    def submit(
        self, message: DRDispatchMessage, *, message_index: int
    ) -> DRDispatchReceipt:
        client = self.http_client or DRUrllibTelegramHTTPClient()

        text_response = client.post_json(
            _endpoint(self.config, "sendMessage"),
            build_telegram_send_message_payload(message, self.config),
            timeout_seconds=self.config.timeout_seconds,
        )
        if not _response_ok(text_response):
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
                doc_response = client.post_multipart(
                    _endpoint(self.config, "sendDocument"),
                    fields=build_telegram_send_document_fields(message, self.config),
                    file_field="document",
                    file_path=html_path,
                    timeout_seconds=self.config.timeout_seconds,
                )
                document_accepted = _response_ok(doc_response)
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

    def _detail(self, stage: str, response: DRTelegramHTTPResponse) -> str:
        desc = _description(response)
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
