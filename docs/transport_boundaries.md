# Transport Boundaries

Ptilopsis Radar has three explicit Telegram transport planes. They do not
share a fallback sender, report formatter, notification facade, or implicit
configuration path.

## CR dispatch

CR owns its dispatch plan, receipts, cooldown state, Telegram configuration,
and sink under `trendradar/cr/`. Sending requires the CR dispatch mode and the
CR-specific Telegram send gate to be enabled explicitly.

## DR dispatch

DR owns a separate dispatch plan, receipts, formatter, Telegram configuration,
and sink under `trendradar/dr/`. Sending requires the DR dispatch mode and the
DR-specific Telegram send gate to be enabled explicitly. DR does not reuse the
CR sink.

## Deployment and operator alerts

Deployment notifications and supervisor alerts live under
`trendradar/deployment/`. They are owner-only operational messages, not report
delivery. The current deployment environment uses `TELEGRAM_BOT_TOKEN` with
`TELEGRAM_OWNER_CHAT_IDS`; `TELEGRAM_CHAT_ID` remains an owner compatibility
input for deployed installations.

## Prohibited paths

- No `trendradar.notification` package or multi-channel compatibility facade.
- No fallback from CR, DR, or artifact generation into another transport.
- No inbound Telegram bot, receiver ACL, or command ACL surface.
- No Telegram transport inside report rendering, AI analysis, storage, or MCP
  configuration inspection.
- No generic notification, alert-cooldown, attachment, or channel configuration
  in `config/config.yaml`.

Low-level Telegram HTTP is confined to the CR sink, DR sink, and deployment
operator sender. Tests enforce this allowlist and the absence of prohibited
generic runtime calls.
