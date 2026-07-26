# coding=utf-8
"""Sequential Telegram delivery to an explicit recipient provider."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from trendradar.telegram.transport import TelegramTransport


_TRANSPORT_ERRORS = (ConnectionError, OSError, TimeoutError)


@dataclass(frozen=True)
class RecipientTarget:
    chat_id: str
    lifecycle_version: int | None = None


class RecipientProvider(Protocol):
    def get_targets(self) -> Sequence[RecipientTarget]:
        ...

    def mark_blocked(self, target: RecipientTarget) -> bool:
        ...


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
            self.text_failed_count > 0
            or self.document_failed_count > 0
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


def _unique_targets(
    provider: RecipientProvider,
) -> tuple[RecipientTarget, ...]:
    unique: dict[str, RecipientTarget] = {}
    for target in provider.get_targets():
        chat_id = str(target.chat_id).strip()
        if chat_id and chat_id not in unique:
            unique[chat_id] = RecipientTarget(
                chat_id=chat_id,
                lifecycle_version=target.lifecycle_version,
            )
    return tuple(unique.values())


def send_to_recipients(
    transport: TelegramTransport,
    provider: RecipientProvider,
    *,
    text: str,
    parse_mode: str | None,
    disable_web_page_preview: bool,
    document_path: Path | None = None,
    document_caption: str = "",
) -> TelegramFanoutSummary:
    """Deliver one rendered product message without aborting later recipients."""
    targets = _unique_targets(provider)
    text_accepted = 0
    text_failed = 0
    document_accepted = 0
    document_failed = 0
    blocked_chat_ids: set[str] = set()
    document_requested = document_path is not None
    document_exists = document_path is not None and document_path.is_file()

    for target in targets:
        try:
            text_response = transport.send_message(
                chat_id=target.chat_id,
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
            )
        except _TRANSPORT_ERRORS:
            text_failed += 1
            continue

        if not text_response.ok:
            text_failed += 1
            if text_response.status_code == 403:
                blocked_chat_ids.add(target.chat_id)
                provider.mark_blocked(target)
            continue
        text_accepted += 1

        if not document_requested:
            continue
        if not document_exists:
            document_failed += 1
            continue
        try:
            document_response = transport.send_document(
                chat_id=target.chat_id,
                file_path=document_path,
                caption=document_caption,
            )
        except _TRANSPORT_ERRORS:
            document_failed += 1
            continue
        if document_response.ok:
            document_accepted += 1
        else:
            document_failed += 1
            if document_response.status_code == 403:
                blocked_chat_ids.add(target.chat_id)
                provider.mark_blocked(target)

    return TelegramFanoutSummary(
        recipient_count=len(targets),
        text_accepted_count=text_accepted,
        text_failed_count=text_failed,
        document_accepted_count=document_accepted,
        document_failed_count=document_failed,
        blocked_count=len(blocked_chat_ids),
    )
