# Telegram Transport Boundaries

Ptilopsis Radar uses one Telegram Bot identity and one low-level Bot API
transport under `trendradar/telegram/`. CR, DR, operator alerts, and inbound
commands share that HTTP boundary but keep separate business policies.

## Product delivery

- CR retains its dispatch plan, cooldown, quiet-hours, deferred queue, and
  receipt lifecycle under `trendradar/cr/`.
- DR retains its formatter, dispatch plan, attachment policy, and once-period
  dedupe under `trendradar/dr/`.
- CR and DR deliver to the deduplicated union of explicit Owners and active
  subscribers. Text success drives accepted state; attachment failures are
  partial failures.

## Operator delivery

Deployment and supervisor alerts remain Owner-only. Subscribers never receive
operational messages. Command authority also comes only from
`TELEGRAM_OWNER_CHAT_IDS`; there is no legacy chat-id fallback.

## Subscription commands

The private-chat Bot supports `/start`, `/help`, Owner-only `/token`,
`/subscribe <token>`, and `/unsubscribe`. Subscription state, hashed one-time
tokens, and the processed update offset live in the dedicated SQLite store.
The Bot ignores groups, channels, ordinary text, and mismatched sender/chat
identities.

## Enforced constraints

- Low-level Telegram HTTP exists only in
  `trendradar/telegram/transport.py`.
- There is no generic multi-channel notification facade and no fallback from
  CR or DR into operator delivery.
- Report rendering, AI analysis, MCP configuration, and general storage do not
  call Telegram.
- `config/config.yaml` contains no generic notification or Telegram ACL
  sections.
