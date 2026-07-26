# coding=utf-8
"""DR Telegram env sink factory."""

from __future__ import annotations

from collections.abc import Mapping

from trendradar.dr.telegram_sink import (
    DRTelegramSink,
    DRTelegramSinkConfig,
)
from trendradar.telegram.recipients import build_reader_recipient_provider
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


def dr_telegram_send_enabled(env: Mapping[str, str]) -> bool:
    return env.get("PTILOPSIS_DR_TELEGRAM_SEND") == "1"


def build_dr_telegram_sink_config_from_env(
    env: Mapping[str, str],
) -> DRTelegramSinkConfig | None:
    if not dr_telegram_send_enabled(env):
        return None

    transport = transport_config_from_env(env)

    parse_mode_raw = env.get("PTILOPSIS_DR_TELEGRAM_PARSE_MODE")
    parse_mode = parse_mode_raw.strip() if parse_mode_raw is not None else "HTML"
    if parse_mode == "":
        parse_mode = None

    attach_raw = env.get("PTILOPSIS_DR_TELEGRAM_ATTACH_HTML")
    attach_html = True if attach_raw is None or not attach_raw.strip() else _parse_bool_like(
        attach_raw, "PTILOPSIS_DR_TELEGRAM_ATTACH_HTML"
    )

    return DRTelegramSinkConfig(
        bot_token=transport.bot_token,
        recipients=build_reader_recipient_provider(env),
        api_base_url=transport.api_base_url,
        timeout_seconds=transport.timeout_seconds,
        parse_mode=parse_mode,
        attach_html=attach_html,
    )


def build_dr_telegram_sink_from_env(
    env: Mapping[str, str],
    *,
    http_client: TelegramHTTPClient | None = None,
) -> DRTelegramSink | None:
    config = build_dr_telegram_sink_config_from_env(env)
    if config is None:
        return None
    return DRTelegramSink(config=config, http_client=http_client)
