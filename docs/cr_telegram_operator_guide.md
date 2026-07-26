# CR Telegram Operator Guide

CR alerts are one of the two reader products delivered by the shared Telegram
Bot. CR owns its planning, cooldown, quiet-hours, receipts, and send gates; the
Bot identity and recipient registry are shared with DR.

## Safe defaults

Default behavior sends nothing. CR Telegram delivery requires both gates:

```text
PTILOPSIS_CR_DISPATCH_MODE=live
PTILOPSIS_CR_TELEGRAM_SEND=1
```

Other dispatch modes remain useful without delivery:

```text
off       CR does not run.
artifact  CR writes audit artifacts and never constructs a sink.
shadow    CR writes artifacts and a plan preview without sending.
live      CR may send only when the explicit send gate is also 1.
```

`PTILOPSIS_CR_DRY_RUN=1` remains a compatibility alias for `artifact`; an
explicit `PTILOPSIS_CR_DISPATCH_MODE` takes precedence.

## Shared Bot configuration

When CR sending is enabled, configure the canonical Bot identity:

```text
TELEGRAM_BOT_TOKEN=<bot-token>
TELEGRAM_OWNER_CHAT_IDS=<owner-private-chat-id>[,<another-owner-id>]
TELEGRAM_API_BASE_URL=https://api.telegram.org
TELEGRAM_TIMEOUT_SECONDS=10
```

The token and at least one Owner private chat ID are required. The API URL and
timeout are optional shared transport settings. The removed
`PTILOPSIS_CR_TELEGRAM_BOT_TOKEN`,
`PTILOPSIS_CR_TELEGRAM_CHAT_ID`,
`PTILOPSIS_CR_TELEGRAM_API_BASE_URL`, and
`PTILOPSIS_CR_TELEGRAM_TIMEOUT_SECONDS` variables are not fallbacks.

CR-specific Telegram presentation options remain:

| Variable | Default | Meaning |
| --- | --- | --- |
| `PTILOPSIS_CR_TELEGRAM_PARSE_MODE` | blank | Optional Telegram parse mode. |
| `PTILOPSIS_CR_TELEGRAM_DISABLE_WEB_PAGE_PREVIEW` | `true` | Whether link previews are disabled. |

Do not put real tokens in docs, commits, PRs, issues, or logs.

## Recipient behavior

Owners are fixed recipients and are always ordered before subscribers. When
subscriptions are enabled, active subscribers are appended from the persisted
registry and receive the same planned CR text. Recipient failures do not abort
later recipients. A partial delivery is recorded as `accepted_partial`.

Subscribers receive only CR/DR reader messages. Deployment notifications and
supervisor alerts remain Owner-only.

See [Telegram Subscription Operations](telegram-subscriptions.md) for token
issuance, subscriber commands, database configuration, and rollout.

## Safe enablement

```bash
# 1. Inspect artifacts without sending.
PTILOPSIS_CR_DISPATCH_MODE=artifact python3 -m trendradar

# 2. Rehearse live mode while the send gate is still off.
PTILOPSIS_CR_DISPATCH_MODE=live python3 -m trendradar

# 3. Configure the canonical Bot privately, then enable a controlled send.
export TELEGRAM_BOT_TOKEN="<bot-token>"
export TELEGRAM_OWNER_CHAT_IDS="<owner-private-chat-id>"
PTILOPSIS_CR_DISPATCH_MODE=live \
PTILOPSIS_CR_TELEGRAM_SEND=1 \
python3 -m trendradar
```

Verify `output/cr/latest/dispatch_plan.json` and
`output/cr/latest/dispatch_receipts.json`. An absent/invalid Bot configuration
must produce no sink, never a false success.

For unattended operation, also verify the existing CR input-health,
cooldown, quiet-hours, deferred queue, and lifecycle controls documented in
[CR-A Operator Runbook](cr-a-operator-runbook.md).
