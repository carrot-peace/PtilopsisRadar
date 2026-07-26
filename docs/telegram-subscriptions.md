# Telegram Subscription Operations

## Scope

The subscription Bot provides a small read-only authorization flow for CR/DR
reader messages:

- Owners are fixed recipients.
- An Owner can issue a one-time Token that expires after 15 minutes.
- A user redeems the Token in a private Bot chat and becomes an active
  subscriber.
- Subscribers receive CR/DR pushes but cannot publish content or run
  operational commands.
- Deployment and supervisor alerts remain Owner-only.

## Configuration

One Bot identity is shared by Owner alerts, CR/DR delivery, and subscription
commands:

```text
TELEGRAM_BOT_TOKEN=<bot-token>
TELEGRAM_OWNER_CHAT_IDS=<owner-private-chat-id>[,<another-owner-id>]
TELEGRAM_API_BASE_URL=https://api.telegram.org
TELEGRAM_TIMEOUT_SECONDS=10
```

Enable inbound commands only after Owner delivery has been verified:

```text
PTILOPSIS_TELEGRAM_SUBSCRIPTIONS_ENABLED=1
PTILOPSIS_TELEGRAM_SUBSCRIPTION_DB_PATH=output/meta/telegram-subscriptions.sqlite3
```

The default database path is inside the persisted `output` volume. The
subscription feature is enabled only by the exact value `1`.

## User flow

1. The user opens the Bot and sends `/start`. Telegram does not let a Bot
   initiate an arbitrary private conversation.
2. An Owner sends `/token` in the Owner's private chat.
3. The Owner gives the returned one-time Token to the user out of band.
4. The user sends `/subscribe <token>` within 15 minutes.
5. `/unsubscribe` stops future CR/DR delivery. Resubscribing requires a new
   Token.

The Bot accepts commands only from a positive private chat whose chat ID
matches the sender user ID. Group messages, channel messages, Bots, and
non-command text are ignored. Owners cannot unsubscribe.

Tokens are random, stored only as SHA-256 hashes, consumed atomically, and
expire after 900 seconds. `/start` reactivates a subscriber previously marked
blocked after a Telegram 403, but does not reactivate a user who explicitly
unsubscribed.

## Polling runtime

The Docker cron container starts `python -m trendradar.telegram.poller` beside
supercronic only when subscriptions are enabled. GitHub Actions can send DR
through the canonical Bot secrets but does not run the inbound poller.

Long polling refuses to start when:

- Telegram reports an active webhook;
- another poller owns the database lock;
- the Bot token or Owner list is missing;
- Telegram returns an authentication or polling conflict response.

Transient transport failures retry with bounded exponential backoff. If either
the poller or supercronic exits in the Docker container, the peer process is
terminated and the container exits instead of remaining falsely healthy.

## Delivery and blocked recipients

Owners are delivered first, then active subscribers in stable order. Duplicate
chat IDs are sent once, with Owner status taking precedence. A failure for one
recipient does not abort later recipients.

When Telegram returns 403 for a subscriber, the registry marks the exact
versioned subscription lifecycle as blocked. A stale delivery cannot block a
newly reactivated subscription.

## Migration and rollout

The per-pipeline Bot credentials were removed:

```text
PTILOPSIS_CR_TELEGRAM_BOT_TOKEN
PTILOPSIS_CR_TELEGRAM_CHAT_ID
PTILOPSIS_CR_TELEGRAM_API_BASE_URL
PTILOPSIS_CR_TELEGRAM_TIMEOUT_SECONDS
PTILOPSIS_DR_TELEGRAM_BOT_TOKEN
PTILOPSIS_DR_TELEGRAM_CHAT_ID
PTILOPSIS_DR_TELEGRAM_API_BASE_URL
PTILOPSIS_DR_TELEGRAM_TIMEOUT_SECONDS
```

Move the existing Bot token to `TELEGRAM_BOT_TOKEN`, put the intended private
Owner IDs in `TELEGRAM_OWNER_CHAT_IDS`, and use the shared API URL and timeout
only when overrides are required.

Roll out in this order:

1. Keep subscriptions disabled.
2. Verify Owner-only CR and DR delivery with the canonical Bot variables.
3. Enable subscriptions and recreate the Docker container.
4. Verify `/start`, `/token`, one test redemption, CR/DR delivery, and
   `/unsubscribe`.
5. Confirm the SQLite database and lock live under persisted storage and that
   subscribers never receive deployment or supervisor alerts.
