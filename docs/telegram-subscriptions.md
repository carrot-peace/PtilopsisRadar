# Telegram Subscription Operations

## Configuration

One Bot configuration is shared by CR, DR, operator alerts, and the
subscription Bot:

```text
TELEGRAM_BOT_TOKEN=<bot-token>
TELEGRAM_OWNER_CHAT_IDS=<owner-private-chat-id>[,<another-owner-id>]
TELEGRAM_API_BASE_URL=https://api.telegram.org
TELEGRAM_TIMEOUT_SECONDS=10
```

Enable the inbound Bot only after Owner delivery has been verified:

```text
PTILOPSIS_TELEGRAM_SUBSCRIPTIONS_ENABLED=1
PTILOPSIS_TELEGRAM_SUBSCRIPTION_DB_PATH=output/meta/telegram-subscriptions.sqlite3
```

The database resides under the persisted `output` volume. The Bot uses
`getUpdates`; startup fails if a webhook is configured or another poller holds
the database lock.

## User flow

1. The user opens the Bot and presses Start. Telegram does not allow a Bot to
   initiate an arbitrary private conversation.
2. An Owner sends `/token` in the Owner's private chat with the Bot.
3. The Owner gives the returned one-time Token to the user out of band.
4. The user sends `/subscribe <token>` within 15 minutes.
5. `/unsubscribe` stops future CR/DR delivery. Resubscribing requires a new
   Token.

Tokens are random, stored only as SHA-256 hashes, expire after exactly 900
seconds, and are consumed atomically. `/start` reactivates a subscriber
previously marked blocked after a Telegram 403, but does not reactivate a user
who explicitly unsubscribed.

## Rollout and migration

Replace the removed per-pipeline credentials with the shared variables above:

- move the existing Bot token to `TELEGRAM_BOT_TOKEN`;
- move the intended private Owner chat IDs to `TELEGRAM_OWNER_CHAT_IDS`;
- use `TELEGRAM_API_BASE_URL` and `TELEGRAM_TIMEOUT_SECONDS` for shared
  transport overrides.

Deploy first with subscriptions disabled and verify CR/DR Owner delivery.
Then enable subscriptions and verify `/start`, `/token`, one test subscription,
CR/DR text plus HTML, and `/unsubscribe`. Subscribers never receive deployment
or supervisor alerts.
