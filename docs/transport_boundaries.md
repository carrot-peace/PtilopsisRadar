# Transport Boundaries

Ptilopsis Radar has three explicit Telegram transport planes. They do not
share a fallback sender, report formatter, notification facade, or implicit
configuration path. Product adapters may share the low-level Telegram HTTP
implementation under `trendradar/telegram/`.

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
- Inbound subscription commands are confined to
  `trendradar/telegram/commands.py`; they have no HTTP or polling dependency.
- No generic receiver ACL, command ACL, or legacy `telegram_bot` surface.
- No Telegram transport inside report rendering, AI analysis, storage, or MCP
  configuration inspection.
- No generic notification, alert-cooldown, attachment, or channel configuration
  in `config/config.yaml`.

Low-level Telegram HTTP is confined to `trendradar/telegram/transport.py`.
Runtime use of the shared transport is confined to the CR sink, DR sink, and
deployment operator sender, plus the manual subscription poller. The poller is
not started by the production container yet. Tests enforce both the HTTP
implementation allowlist and the shared transport import-site allowlist,
together with the absence of prohibited generic runtime calls.
