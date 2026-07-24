# CR Telegram Operator Guide

## 1. Purpose

This is the CR-A Telegram operator guide for Ptilopsis Radar.

CR-A means current-report alerting. This guide covers the CR-A dispatch mode
and Telegram delivery. It is not daily report delivery, dashboard delivery, or a
generic notification framework.

The current CR-A path is:

```text
runtime stats
-> CR dispatch mode gate
-> CR pipeline
-> dispatch plan
-> dispatch executor
-> Telegram env factory (live mode only)
-> Telegram sink (live mode only)
```

## 2. Dispatch modes

CR-A is controlled by `PTILOPSIS_CR_DISPATCH_MODE`:

```text
off       CR-A does not run.  Default.
artifact  CR-A runs.  Writes audit artifacts only.  No dispatch sink.
shadow    CR-A runs.  Writes audit artifacts and plan preview.  No dispatch sink.
live      CR-A runs.  May dispatch only with explicit CR Telegram gates.
```

Invalid or unrecognized values resolve to `off` (fail closed).

### Compatibility alias

`PTILOPSIS_CR_DRY_RUN=1` behaves like `artifact` mode. This is a compatibility
alias for existing deployments. When both `PTILOPSIS_CR_DISPATCH_MODE` and
`PTILOPSIS_CR_DRY_RUN=1` are set, the explicit `PTILOPSIS_CR_DISPATCH_MODE`
wins.

## 3. Safety model

Default behavior sends nothing.

Telegram dispatch requires the `live` dispatch mode plus the Telegram send gate:

```text
PTILOPSIS_CR_DISPATCH_MODE=live
PTILOPSIS_CR_TELEGRAM_SEND=1
TELEGRAM_BOT_TOKEN=<token>
TELEGRAM_OWNER_CHAT_IDS=<owner-private-chat-id>
```

The supported operator states are:

```text
PTILOPSIS_CR_DISPATCH_MODE unset or off:
  normal runtime, no CR-A, no Telegram sink

PTILOPSIS_CR_DISPATCH_MODE=artifact:
  CR artifacts are written, no dispatch sink, no send

PTILOPSIS_CR_DISPATCH_MODE=shadow:
  CR artifacts and plan preview are written, no dispatch sink, no send

PTILOPSIS_CR_DISPATCH_MODE=live and TELEGRAM_SEND unset/off:
  CR artifacts are written, Telegram sink is not constructed, no send

PTILOPSIS_CR_DISPATCH_MODE=live and TELEGRAM_SEND=1:
  Telegram sink is constructed from env; dispatch occurs only if CRDispatchPlan is ready
```

Only the exact runtime gates above enable the live path. Leaving any gate
unset preserves the no-send default.

## 4. Environment variables

| Variable | Required? | Default | Meaning |
| --- | --- | --- | --- |
| `PTILOPSIS_CR_DISPATCH_MODE` | No | `off` | CR-A dispatch mode: `off`, `artifact`, `shadow`, or `live`. Invalid values resolve to `off`. |
| `PTILOPSIS_CR_DRY_RUN` | No (compat alias) | unset | Set to `1` as a compatibility alias for `artifact` mode. Prefer `PTILOPSIS_CR_DISPATCH_MODE`. |
| `PTILOPSIS_CR_TELEGRAM_SEND` | Required for live Telegram dispatch | unset/off | Set to `1` to enable Telegram sink construction in `live` mode. Any unset/off value keeps Telegram disabled. |
| `TELEGRAM_BOT_TOKEN` | Required only when Telegram send is enabled | none | Shared Telegram bot token. Do not put real tokens in docs, commits, PRs, issues, or logs. |
| `TELEGRAM_OWNER_CHAT_IDS` | Required only when Telegram send is enabled | none | Comma-separated private Owner chat IDs. Active subscribers are added from the subscription store. |
| `TELEGRAM_API_BASE_URL` | No | `https://api.telegram.org` | Shared Telegram API base URL. |
| `TELEGRAM_TIMEOUT_SECONDS` | No | `10.0` | Shared positive request timeout in seconds. |
| `PTILOPSIS_CR_TELEGRAM_ATTACH_HTML` | No | `true` | Send the generated CR HTML after accepted text. |
| `PTILOPSIS_CR_TELEGRAM_PARSE_MODE` | No | `None` | Optional Telegram parse mode. When omitted or blank, no parse mode is sent. |
| `PTILOPSIS_CR_TELEGRAM_DISABLE_WEB_PAGE_PREVIEW` | No | `true` | Optional boolean-like value controlling Telegram web page previews. When omitted, inherits the `CRTelegramSinkConfig` default. |

`PTILOPSIS_CR_DISPATCH_MODE` controls whether CR-A runs and in what capacity.
`PTILOPSIS_CR_TELEGRAM_SEND=1` enables Telegram sink construction in `live`
mode. The shared Bot token and explicit Owner IDs are required only when
Telegram send is enabled.
Optional values inherit the shared transport defaults.

## 5. Example: artifact mode

```bash
PTILOPSIS_CR_DISPATCH_MODE=artifact python3 -m trendradar
```

This writes CR Markdown and HTML audit artifacts. It does not send Telegram
messages.

Using the compatibility alias:

```bash
PTILOPSIS_CR_DRY_RUN=1 python3 -m trendradar
```

## 6. Example: live mode with Telegram

```bash
PTILOPSIS_CR_DISPATCH_MODE=live \
PTILOPSIS_CR_TELEGRAM_SEND=1 \
TELEGRAM_BOT_TOKEN="<telegram-bot-token>" \
TELEGRAM_OWNER_CHAT_IDS="<owner-private-chat-id>" \
python3 -m trendradar
```

Use a private Telegram test chat first. Do not commit real tokens, and do not
paste real tokens into PRs, issues, or logs. When Telegram send is enabled,
invalid required or optional environment values fail fast before dispatch.

## 7. Dispatch semantics

At runtime, the CR dry-run hook builds the CR pipeline from runtime stats and
writes audit artifacts. The dispatch plan then selects CR-A candidates, and the
dispatch executor submits only the planned messages.

The Telegram sink does not re-score, re-decide, or re-render CR content. It
submits the message text produced by the existing CR dispatch plan and then
the generated HTML attachment. Suppressed candidates remain non-pushable.
Existing cooldown, quiet-hours, deferred queue, and accepted-state semantics
remain upstream of this adapter.

## 8. Known limitations

- no failed-delivery replay queue
- no subscriber administration commands
- no config.yaml integration
- no token rotation helper
- no Telegram formatting policy beyond current text payload

## 9. Recommended operator workflow

```text
1. Run artifact mode and inspect Markdown/HTML artifacts.
2. Use a private Telegram test chat.
3. Switch to live mode with TELEGRAM_SEND=1 for a controlled test.
4. Disable TELEGRAM_SEND or switch back to artifact after verification.
5. Move to PR10 state/cooldown hardening before unattended operation.
```

## 10. PR9 closure note

PR9 closes the minimum viable CR-A Telegram path.
Production hardening belongs to PR10:
state, dedupe, cooldown, persistence, retry/backoff, and operator UX.
