# CR Telegram Operator Guide

## 1. Purpose

This is the CR-A Telegram operator guide for Ptilopsis Radar.

CR-A means current-report alerting. This guide covers Telegram delivery for the
CR dry-run hook only. It is not daily report delivery, dashboard delivery, or a
generic notification framework.

The current CR-A MVP path is:

```text
runtime stats
-> existing CR dry-run hook
-> CR pipeline
-> dispatch plan
-> dispatch executor
-> Telegram env factory
-> Telegram sink
```

## 2. Safety model

Default behavior sends nothing.

Telegram dispatch requires both gates:

```text
PTILOPSIS_CR_DRY_RUN=1
PTILOPSIS_CR_TELEGRAM_SEND=1
```

The supported operator states are:

```text
CR_DRY_RUN unset/off:
  normal runtime, no CR dry-run hook, no Telegram sink

CR_DRY_RUN=1 and TELEGRAM_SEND unset/off:
  CR artifacts are written, Telegram sink is not constructed, no send

CR_DRY_RUN=1 and TELEGRAM_SEND=1:
  Telegram sink is constructed from env; dispatch occurs only if CRDispatchPlan is ready
```

Only the exact runtime gates above enable the current path. Leaving either gate
unset preserves the no-send default.

## 3. Environment variables

| Variable | Required? | Default | Meaning |
| --- | --- | --- | --- |
| `PTILOPSIS_CR_DRY_RUN` | Required to enter the CR dry-run hook | unset/off | Set to `1` to enable the CR dry-run hook. Without it, the normal runtime does not enter the CR dry-run path and cannot construct the CR Telegram sink. |
| `PTILOPSIS_CR_TELEGRAM_SEND` | Required to construct the Telegram sink inside the dry-run hook | unset/off | Set to `1` to enable Telegram sink construction. Any unset/off value keeps Telegram disabled. |
| `PTILOPSIS_CR_TELEGRAM_BOT_TOKEN` | Required only when Telegram send is enabled | none | Telegram bot token used by the CR Telegram sink. Do not put real tokens in docs, commits, PRs, issues, or logs. |
| `PTILOPSIS_CR_TELEGRAM_CHAT_ID` | Required only when Telegram send is enabled | none | Telegram chat id used by the CR Telegram sink. Use a private test chat first. |
| `PTILOPSIS_CR_TELEGRAM_API_BASE_URL` | No | `https://api.telegram.org` | Optional Telegram API base URL. When omitted, inherits the `CRTelegramSinkConfig` default. |
| `PTILOPSIS_CR_TELEGRAM_TIMEOUT_SECONDS` | No | `10.0` | Optional positive request timeout in seconds. When omitted, inherits the `CRTelegramSinkConfig` default. |
| `PTILOPSIS_CR_TELEGRAM_PARSE_MODE` | No | `None` | Optional Telegram parse mode. When omitted or blank, no parse mode is sent. |
| `PTILOPSIS_CR_TELEGRAM_DISABLE_WEB_PAGE_PREVIEW` | No | `true` | Optional boolean-like value controlling Telegram web page previews. When omitted, inherits the `CRTelegramSinkConfig` default. |

`PTILOPSIS_CR_DRY_RUN=1` enables the CR dry-run hook.
`PTILOPSIS_CR_TELEGRAM_SEND=1` enables Telegram sink construction inside that
hook. Token and chat id are required only when Telegram send is enabled.
Optional values inherit `CRTelegramSinkConfig` defaults.

## 4. Example: artifact-only dry run

```bash
PTILOPSIS_CR_DRY_RUN=1 python3 -m trendradar
```

This writes CR Markdown and HTML audit artifacts. It does not send Telegram
messages because `PTILOPSIS_CR_TELEGRAM_SEND` is not enabled.

## 5. Example: Telegram-enabled dry run

```bash
PTILOPSIS_CR_DRY_RUN=1 \
PTILOPSIS_CR_TELEGRAM_SEND=1 \
PTILOPSIS_CR_TELEGRAM_BOT_TOKEN="<telegram-bot-token>" \
PTILOPSIS_CR_TELEGRAM_CHAT_ID="<telegram-chat-id>" \
python3 -m trendradar
```

Use a private Telegram test chat first. Do not commit real tokens, and do not
paste real tokens into PRs, issues, or logs. When Telegram send is enabled,
invalid required or optional environment values fail fast before dispatch.

## 6. Dispatch semantics

At runtime, the CR dry-run hook builds the CR pipeline from runtime stats and
writes audit artifacts. The dispatch plan then selects CR-A candidates, and the
dispatch executor submits only the planned messages.

The Telegram sink does not re-score, re-decide, or re-render CR content. It
submits the message text produced by the existing CR dispatch plan. Suppressed
candidates remain non-pushable. No dedupe, cooldown, or alert-state persistence
exists yet.

## 7. Known limitations

- no dedupe
- no cooldown
- no alert-state persistence
- no retry/backoff
- no config.yaml integration
- no token rotation helper
- no Telegram formatting policy beyond current text payload
- transport exception sanitization remains future hardening

## 8. Recommended operator workflow

```text
1. Run artifact-only dry run.
2. Inspect Markdown/HTML artifacts.
3. Use a private Telegram test chat.
4. Enable Telegram send only for a controlled test.
5. Disable TELEGRAM_SEND after verification unless actively testing.
6. Move to PR10 state/cooldown hardening before unattended operation.
```

## 9. PR9 closure note

PR9 closes the minimum viable CR-A Telegram path.
Production hardening belongs to PR10:
state, dedupe, cooldown, persistence, retry/backoff, and operator UX.
