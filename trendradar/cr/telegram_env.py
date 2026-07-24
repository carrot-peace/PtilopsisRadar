# coding=utf-8
"""CR Telegram adapter configuration from the canonical Bot environment."""

from __future__ import annotations

from collections.abc import Mapping

from trendradar.cr.telegram_sink import CRTelegramSink, CRTelegramSinkConfig
from trendradar.telegram.subscriptions import build_reader_recipient_provider
from trendradar.telegram.transport import (
    TelegramHTTPClient,
    transport_config_from_env,
)


_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSY = frozenset({"0", "false", "no", "off"})


def _parse_bool_like(raw: str, env_key: str) -> bool:
    lower = raw.strip().lower()
    if lower in _TRUTHY:
        return True
    if lower in _FALSY:
        return False
    raise ValueError(f"{env_key} must be a boolean-like value")


def cr_telegram_send_enabled(env: Mapping[str, str]) -> bool:
    return env.get("PTILOPSIS_CR_TELEGRAM_SEND") == "1"


def build_cr_telegram_sink_config_from_env(
    env: Mapping[str, str],
) -> CRTelegramSinkConfig | None:
    if not cr_telegram_send_enabled(env):
        return None

    transport = transport_config_from_env(env)
    parse_mode_raw = env.get("PTILOPSIS_CR_TELEGRAM_PARSE_MODE")
    parse_mode = parse_mode_raw.strip() if parse_mode_raw is not None else None
    if not parse_mode:
        parse_mode = None

    preview_raw = env.get("PTILOPSIS_CR_TELEGRAM_DISABLE_WEB_PAGE_PREVIEW")
    disable_web_page_preview = (
        True
        if preview_raw is None
        else _parse_bool_like(
            preview_raw,
            "PTILOPSIS_CR_TELEGRAM_DISABLE_WEB_PAGE_PREVIEW",
        )
    )
    attach_raw = env.get("PTILOPSIS_CR_TELEGRAM_ATTACH_HTML")
    attach_html = (
        True
        if attach_raw is None or not attach_raw.strip()
        else _parse_bool_like(
            attach_raw,
            "PTILOPSIS_CR_TELEGRAM_ATTACH_HTML",
        )
    )
    return CRTelegramSinkConfig(
        bot_token=transport.bot_token,
        recipients=build_reader_recipient_provider(env),
        api_base_url=transport.api_base_url,
        timeout_seconds=transport.timeout_seconds,
        parse_mode=parse_mode,
        disable_web_page_preview=disable_web_page_preview,
        attach_html=attach_html,
    )


def build_cr_telegram_sink_from_env(
    env: Mapping[str, str],
    *,
    http_client: TelegramHTTPClient | None = None,
) -> CRTelegramSink | None:
    config = build_cr_telegram_sink_config_from_env(env)
    if config is None:
        return None
    return CRTelegramSink(config=config, http_client=http_client)
