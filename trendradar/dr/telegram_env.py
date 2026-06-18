# coding=utf-8
"""DR Telegram env sink factory."""

from __future__ import annotations

from collections.abc import Mapping

from trendradar.dr.telegram_sink import (
    DRTelegramHTTPClient,
    DRTelegramSink,
    DRTelegramSinkConfig,
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

    bot_token = env.get("PTILOPSIS_DR_TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token:
        raise ValueError("PTILOPSIS_DR_TELEGRAM_BOT_TOKEN is required")

    chat_id = env.get("PTILOPSIS_DR_TELEGRAM_CHAT_ID", "").strip()
    if not chat_id:
        raise ValueError("PTILOPSIS_DR_TELEGRAM_CHAT_ID is required")

    api_base_url = (
        env.get("PTILOPSIS_DR_TELEGRAM_API_BASE_URL", "").strip()
        or DRTelegramSinkConfig.api_base_url  # type: ignore[attr-defined]
    )

    timeout_raw = env.get("PTILOPSIS_DR_TELEGRAM_TIMEOUT_SECONDS")
    if timeout_raw is None:
        timeout_seconds = DRTelegramSinkConfig.timeout_seconds  # type: ignore[attr-defined]
    else:
        try:
            timeout_seconds = float(timeout_raw.strip())
        except (TypeError, ValueError):
            raise ValueError(
                "PTILOPSIS_DR_TELEGRAM_TIMEOUT_SECONDS must be a positive number"
            )
        if timeout_seconds <= 0:
            raise ValueError(
                "PTILOPSIS_DR_TELEGRAM_TIMEOUT_SECONDS must be a positive number"
            )

    parse_mode_raw = env.get("PTILOPSIS_DR_TELEGRAM_PARSE_MODE")
    parse_mode = parse_mode_raw.strip() if parse_mode_raw is not None else "HTML"
    if parse_mode == "":
        parse_mode = None

    attach_raw = env.get("PTILOPSIS_DR_TELEGRAM_ATTACH_HTML")
    attach_html = True if attach_raw is None else _parse_bool_like(
        attach_raw, "PTILOPSIS_DR_TELEGRAM_ATTACH_HTML"
    )

    return DRTelegramSinkConfig(
        bot_token=bot_token,
        chat_id=chat_id,
        api_base_url=api_base_url,
        timeout_seconds=timeout_seconds,
        parse_mode=parse_mode,
        attach_html=attach_html,
    )


def build_dr_telegram_sink_from_env(
    env: Mapping[str, str],
    *,
    http_client: DRTelegramHTTPClient | None = None,
) -> DRTelegramSink | None:
    config = build_dr_telegram_sink_config_from_env(env)
    if config is None:
        return None
    return DRTelegramSink(config=config, http_client=http_client)
