# coding=utf-8
"""
CR Telegram env sink factory (PR9o) v0.1.

Constructs a :class:`CRTelegramSink` from an explicit environment mapping
without wiring it into runtime execution.  This module does NOT send anything,
does NOT modify runtime behavior, and does NOT touch the real environment.

The factory accepts a ``Mapping[str, str]`` so tests can pass fake env dicts
without mutating ``os.environ``.

Design reference: PR9o.
"""

from __future__ import annotations

from collections.abc import Mapping

from trendradar.cr.telegram_sink import (
    CRTelegramSink,
    CRTelegramSinkConfig,
)
from trendradar.telegram.transport import TelegramHTTPClient


# ---------------------------------------------------------------------------
# Boolean-like parsing
# ---------------------------------------------------------------------------

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSY = frozenset({"0", "false", "no", "off"})


def _parse_bool_like(raw: str, env_key: str) -> bool:
    """Parse a boolean-like environment value.

    Accepts ``"1"``, ``"true"``, ``"yes"``, ``"on"`` (case-insensitive) as
    ``True`` and ``"0"``, ``"false"``, ``"no"``, ``"off"`` as ``False``.
    Raises :class:`ValueError` for any other value.
    """
    lower = raw.strip().lower()
    if lower in _TRUTHY:
        return True
    if lower in _FALSY:
        return False
    raise ValueError(f"{env_key} must be a boolean-like value")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def cr_telegram_send_enabled(env: Mapping[str, str]) -> bool:
    """Return ``True`` only when ``PTILOPSIS_CR_TELEGRAM_SEND`` is exactly ``"1"``.

    No whitespace stripping is applied to this flag — only the raw value ``"1"``
    enables the sink.
    """
    return env.get("PTILOPSIS_CR_TELEGRAM_SEND") == "1"


def build_cr_telegram_sink_config_from_env(
    env: Mapping[str, str],
) -> CRTelegramSinkConfig | None:
    """Build a :class:`CRTelegramSinkConfig` from an explicit env mapping.

    Returns ``None`` when sending is disabled.  Raises :class:`ValueError` when
    enabled but required fields are missing/blank or optional fields are
    invalid.

    No network calls.  No Telegram API calls.  No runtime side effects.
    """
    if not cr_telegram_send_enabled(env):
        return None

    # Required fields
    bot_token = env.get("PTILOPSIS_CR_TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token:
        raise ValueError("PTILOPSIS_CR_TELEGRAM_BOT_TOKEN is required")

    chat_id = env.get("PTILOPSIS_CR_TELEGRAM_CHAT_ID", "").strip()
    if not chat_id:
        raise ValueError("PTILOPSIS_CR_TELEGRAM_CHAT_ID is required")

    # Optional fields
    api_base_url_raw = env.get("PTILOPSIS_CR_TELEGRAM_API_BASE_URL")
    if api_base_url_raw is not None:
        api_base_url = api_base_url_raw.strip()
        if not api_base_url:
            raise ValueError("PTILOPSIS_CR_TELEGRAM_API_BASE_URL must be non-empty")
    else:
        api_base_url = CRTelegramSinkConfig.api_base_url  # type: ignore[attr-defined]

    timeout_raw = env.get("PTILOPSIS_CR_TELEGRAM_TIMEOUT_SECONDS")
    if timeout_raw is not None:
        try:
            timeout_seconds = float(timeout_raw.strip())
        except (ValueError, TypeError):
            raise ValueError(
                "PTILOPSIS_CR_TELEGRAM_TIMEOUT_SECONDS must be a positive number"
            )
        if timeout_seconds <= 0:
            raise ValueError(
                "PTILOPSIS_CR_TELEGRAM_TIMEOUT_SECONDS must be a positive number"
            )
    else:
        timeout_seconds = CRTelegramSinkConfig.timeout_seconds  # type: ignore[attr-defined]

    parse_mode_raw = env.get("PTILOPSIS_CR_TELEGRAM_PARSE_MODE")
    if parse_mode_raw is not None:
        parse_mode = parse_mode_raw.strip() or None
    else:
        parse_mode = None

    preview_raw = env.get("PTILOPSIS_CR_TELEGRAM_DISABLE_WEB_PAGE_PREVIEW")
    if preview_raw is not None:
        disable_web_page_preview = _parse_bool_like(
            preview_raw, "PTILOPSIS_CR_TELEGRAM_DISABLE_WEB_PAGE_PREVIEW"
        )
    else:
        disable_web_page_preview = True

    return CRTelegramSinkConfig(
        bot_token=bot_token,
        chat_id=chat_id,
        api_base_url=api_base_url,
        timeout_seconds=timeout_seconds,
        parse_mode=parse_mode,
        disable_web_page_preview=disable_web_page_preview,
    )


def build_cr_telegram_sink_from_env(
    env: Mapping[str, str],
    *,
    http_client: TelegramHTTPClient | None = None,
) -> CRTelegramSink | None:
    """Build a :class:`CRTelegramSink` from an explicit env mapping.

    Returns ``None`` when sending is disabled.  The optional ``http_client``
    is attached to the sink for transport injection (tests supply a fake).

    No network calls.  No Telegram API calls.  No runtime side effects.
    """
    config = build_cr_telegram_sink_config_from_env(env)
    if config is None:
        return None
    return CRTelegramSink(config=config, http_client=http_client)
