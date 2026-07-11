# CR-A Operator Runbook

Operator-facing runbook for the completed CR-A dispatch pipeline (A1–A7).

This document explains how to enable CR-A safely, run artifact / shadow / live
modes, verify `dispatch_plan` / `dispatch_receipts` / `deploy_trace`, understand
the no-send / not_configured / failed_transport / deferred states, operate
quiet-hours and the deferred flush, roll back safely, and run a local smoke
check without sending Telegram.

The companion document [`cr-a-rollback-guide.md`](cr-a-rollback-guide.md)
covers emergency stop and rollback in more depth. For the original Telegram
gate background, see [`cr_telegram_operator_guide.md`](cr_telegram_operator_guide.md).

> **Scope.** CR-A means current-report alerting. It is not daily report
> delivery, dashboard delivery, or a generic notification framework. The legacy
> notification path is removed and must not be reintroduced.

---

## 1. CR-A overview

CR-A is a four-plane chain. Each plane has one job and does not do another
plane's job:

```text
generation plane  ->  decision plane  ->  transport plane  ->  observability plane
   (CR pipeline)       (dispatch plan)      (sink / send)        (deploy trace)
```

```text
Plan decides.       dispatch_plan.json is the authoritative decision.
Receipt records.    dispatch_receipts.json records what execution did.
Deploy trace observes. deploy_trace/latest.json is a read-only observation.
Sink sends.         The Telegram sink only sends; it never re-decides.
State updates only after accepted live sends.
```

### No false success

Only an accepted live send is a success. The following are **not** success and
**must not** update successful dispatch state:

```text
not_configured            transport never attempted (no/partial sink config)
failed_transport          transport attempted, network/transport error
rejected                  sink reached, send rejected
deferred_quiet_hours      held in the deferred queue, not sent
skipped_deferred_queue_upsert  candidate rejected by queue conflict, not deferred
quiet_hours_config_error  invalid quiet-hours config, fails closed
skipped_deferred_queue_error  queue unreadable, fails closed
shadow_only / not_executed (artifact)  preview/artifact, never a send
```

Artifact and shadow modes never attempt a send and never mutate state.

---

## 2. Mode matrix

CR-A is controlled by `PTILOPSIS_CR_DISPATCH_MODE`. Invalid / unrecognized
values resolve to `off` (fail closed). `PTILOPSIS_CR_DRY_RUN=1` is a
compatibility alias for `artifact`; explicit `PTILOPSIS_CR_DISPATCH_MODE` wins.

| Capability | off | artifact | shadow | live |
| --- | --- | --- | --- | --- |
| Writes `dispatch_plan.json` | No | Yes | Yes | Yes |
| Writes `dispatch_receipts.json` | No | Yes | Yes | Yes |
| Writes `deploy_trace/latest.json` | No | Yes | Yes | Yes |
| Sends Telegram | No | No | No | Only if strict gates pass |
| Mutates successful dispatch state | No | No | No | Only on accepted send |
| Mutates deferred queue | No | No | No | Only under quiet-hours / flush |
| Safe for local dry run | Yes | Yes | Yes | No (can send) |

Expected semantics:

```text
off:
  CR-A does not run.  No artifacts, no send, no state, no queue.  Default.

artifact:
  CR-A runs.  Writes artifacts.  No send.  No state mutation.  No queue mutation.

shadow:
  CR-A runs.  Writes artifacts and plan preview.  No send.
  No state mutation.  No queue mutation.

live:
  CR-A runs.  May send only if strict Telegram gates pass.
  An accepted send mutates successful dispatch state.
  Quiet-hours may enqueue (defer) or flush the deferred queue.
```

> In `live` mode with `PTILOPSIS_CR_TELEGRAM_SEND` unset/off, the Telegram sink
> is never constructed: artifacts are written but nothing is sent. This is the
> recommended pre-send rehearsal of `live`.

---

## 3. Environment variables

### Dispatch / transport

| Variable | Allowed values | Default behavior | Failure behavior |
| --- | --- | --- | --- |
| `PTILOPSIS_CR_DISPATCH_MODE` | `off`, `artifact`, `shadow`, `live` | Unset ⇒ `off`, CR-A does not run | Invalid value ⇒ resolves to `off` (fail closed) |
| `PTILOPSIS_CR_DRY_RUN` | `1` | Compatibility alias for `artifact` | Ignored when `PTILOPSIS_CR_DISPATCH_MODE` is set explicitly |
| `PTILOPSIS_CR_TELEGRAM_SEND` | `1` to enable, else off | Unset/off ⇒ sink not constructed, no send | Any non-`1` value keeps Telegram disabled |
| `PTILOPSIS_CR_TELEGRAM_BOT_TOKEN` | bot token string | Required only when send enabled | Missing/partial config ⇒ no send, **not** success |
| `PTILOPSIS_CR_TELEGRAM_CHAT_ID` | chat id string | Required only when send enabled | Missing/partial config ⇒ no send, **not** success |

### Quiet-hours

| Variable | Allowed values | Default behavior | Failure behavior |
| --- | --- | --- | --- |
| `PTILOPSIS_CR_QUIET_HOURS_ENABLED` | `1` to enable, else off | Unset/off ⇒ quiet-hours not evaluated | Any non-`1` value keeps quiet-hours off |
| `PTILOPSIS_CR_TIMEZONE` | IANA tz name | `Asia/Shanghai` | Unknown tz ⇒ `quiet_hours_config_error`, fails closed (no send) |
| `PTILOPSIS_CR_QUIET_HOURS_START` | `HH:MM` (24h) | `23:00` | Malformed ⇒ `quiet_hours_config_error`, fails closed |
| `PTILOPSIS_CR_QUIET_HOURS_END` | `HH:MM` (24h) | `08:00` | Malformed ⇒ `quiet_hours_config_error`, fails closed |
| `PTILOPSIS_CR_QUIET_HOURS_ALLOW_URGENT` | `1` to enable, else off | Unset/off ⇒ urgent does **not** bypass quiet-hours | Any non-`1` value keeps urgent bypass disabled |

Explicit guarantees:

```text
- Urgent bypass is DISABLED unless PTILOPSIS_CR_QUIET_HOURS_ALLOW_URGENT=1.
- Partial Telegram config (token or chat id missing) does NOT count as success.
- Invalid quiet-hours config fails closed: no send, no queue overwrite.
- start == end disables the window (no quiet-hours window active).
```

Do not put real tokens or chat ids in docs, commits, PRs, issues, or logs. Use
a private test chat first.

---

## 4. Safe enablement procedure

Roll out in order. Each step is reversible by returning to an earlier step. The
entrypoint is `python3 -m trendradar` (or `.venv/bin/python -m trendradar`).

```bash
# Step 1 — off / baseline. Confirm normal runtime with no CR-A.
PTILOPSIS_CR_DISPATCH_MODE=off python3 -m trendradar

# Step 2 — artifact mode. CR-A runs, writes artifacts, sends nothing.
PTILOPSIS_CR_DISPATCH_MODE=artifact python3 -m trendradar

# Step 3 — inspect the authoritative plan.
cat output/cr/latest/dispatch_plan.json

# Step 4 — inspect the receipts.
cat output/cr/latest/dispatch_receipts.json

# Step 5 — inspect the deploy trace observation.
cat output/meta/deploy_trace/latest.json

# Step 6 — shadow mode. Preview only, still no send.
PTILOPSIS_CR_DISPATCH_MODE=shadow python3 -m trendradar

# Step 7 — live mode with Telegram send DISABLED (rehearsal).
#          Artifacts written, sink never constructed, nothing sent.
PTILOPSIS_CR_DISPATCH_MODE=live python3 -m trendradar

# Step 8 — live mode with Telegram send ENABLED. Use a private test chat.
export PTILOPSIS_CR_TELEGRAM_BOT_TOKEN="<bot-token>"
export PTILOPSIS_CR_TELEGRAM_CHAT_ID="<chat-id>"
PTILOPSIS_CR_DISPATCH_MODE=live \
PTILOPSIS_CR_TELEGRAM_SEND=1 \
python3 -m trendradar

# Step 9 — enable quiet-hours.
export PTILOPSIS_CR_QUIET_HOURS_ENABLED=1
export PTILOPSIS_CR_TIMEZONE=Asia/Shanghai
export PTILOPSIS_CR_QUIET_HOURS_START=23:00
export PTILOPSIS_CR_QUIET_HOURS_END=08:00
export PTILOPSIS_CR_QUIET_HOURS_ALLOW_URGENT=1
PTILOPSIS_CR_DISPATCH_MODE=live PTILOPSIS_CR_TELEGRAM_SEND=1 python3 -m trendradar

# Step 10 — verify deferred queue and post-quiet flush.
cat output/cr/state/cr_deferred_dispatch_queue.json   # entries during quiet-hours
# Run again after quiet-hours end; accepted flush entries are removed.
PTILOPSIS_CR_DISPATCH_MODE=live PTILOPSIS_CR_TELEGRAM_SEND=1 python3 -m trendradar
```

Do not include real secrets anywhere. Use the placeholder `<bot-token>` /
`<chat-id>` examples above.

---

## 5. Verification checklist

### Successful live send

```text
[ ] output/cr/latest/dispatch_plan.json exists and parses
[ ] output/cr/latest/dispatch_receipts.json exists and parses
[ ] output/meta/deploy_trace/latest.json exists and parses
[ ] receipt status == accepted
[ ] receipt accepted == true
[ ] transport == telegram (live send path)
[ ] sink_ok == true
[ ] cr_dispatch_state.json updated (successful state advanced)
[ ] deferred queue is not unexpectedly growing
```

### No-send states (expected, not errors)

```text
artifact / shadow         -> no sink attempt, no state update
not_configured            -> no state update (no/partial sink config)
failed_transport          -> no state update (transport error)
deferred_quiet_hours      -> queue entry exists, no state update
skipped_deferred_queue_upsert -> no new/updated queue entry; inspect receipt detail
skipped_deferred_queue_error -> queue untouched, no send
quiet_hours_config_error  -> no send, no queue overwrite
```

The core invariant the smoke check enforces: **no receipt has
`accepted == true` unless its `status == accepted`.**

---

## 6. Receipt status guide

Statuses are emitted into `dispatch_receipts.json` (`receipts[].status`). Source
of truth: [`trendradar/cr/dispatch_receipt.py`](../trendradar/cr/dispatch_receipt.py).

| Status | Attempted? | Accepted? | State update? | Operator action |
| --- | --- | --- | --- | --- |
| `not_executed` | No | No | No | None. Artifact mode, no send by design. |
| `shadow_only` | No | No | No | None. Shadow preview, no send by design. |
| `skipped_no_candidate` | No | No | No | None. Nothing eligible to dispatch. |
| `skipped_suppress` | No | No | No | None. Candidate suppressed (e.g. empty text). |
| `skipped_cooldown` | No | No | No | None. Cooldown policy held the send. |
| `skipped_repeat` | No | No | No | None. Repeat policy held the send. |
| `skipped_state_error` | No | No | No | Investigate state file readability. |
| `not_configured` | No | No | No | Provide full Telegram token + chat id if a send was intended. |
| `accepted` | Yes | Yes | Yes | None. Successful send. |
| `rejected` | Yes | No | No | Inspect detail; check chat id / bot permissions. |
| `failed_transport` | Yes | No | No | Transient network/transport; will retry next run. |
| `failed_render` | No | No | No | Investigate message rendering. |
| `http_error` | Yes | No | No | Inspect HTTP status / Telegram API response. |
| `deferred_quiet_hours` | No | No | No | Queue insert/refresh was persisted; flushes after window. |
| `skipped_quiet_hours` | No | No | No | Expected; suppressed by quiet-hours policy. |
| `skipped_deferred_queue_upsert` | No | No | No | Candidate was not inserted/refreshed; inspect `deferred_upsert_reason`. |
| `skipped_deferred_queue_error` | No | No | No | Queue unreadable; back up + inspect queue file. |
| `quiet_hours_config_error` | No | No | No | Fix `PTILOPSIS_CR_TIMEZONE` / `START` / `END`. |
| `unknown` | varies | No | No | Investigate; should not occur in normal operation. |

> A flushed deferred entry that is accepted reports `status == accepted` with
> `detail == "flushed_deferred"` and `source == "deferred_queue"`. The status
> vocabulary for flush entries is the same accepted/rejected/failed_transport/
> http_error set; "flushed_deferred" is a detail, not a status.

Every `deferred_quiet_hours` receipt represents an `inserted` or `refreshed`
upsert that was successfully persisted. A rejected upsert uses
`skipped_deferred_queue_upsert`; a queue save failure uses
`skipped_deferred_queue_error`, so neither can be mistaken for a durable deferral.

If actual emitted status names ever diverge from this table, treat
[`trendradar/cr/dispatch_receipt.py`](../trendradar/cr/dispatch_receipt.py) and
the flush path in
[`trendradar/cr/runtime_dry_run.py`](../trendradar/cr/runtime_dry_run.py) as
authoritative and update this table.

---

## 7. Quiet-hours / deferred queue runbook

How quiet-hours behaves:

```text
- Quiet-hours suppress immediate delivery during the configured window.
- An alert is deferred during quiet-hours (queued, not sent).
- An urgent message is deferred too, UNLESS urgent bypass is explicitly enabled.
- Urgent bypass accepted send updates successful state immediately.
- Urgent bypass that fails does NOT swallow the message; it queues for retry.
- A post-quiet live run flushes deferred messages one by one.
- Urgent deferred entries flush before alert entries.
- failed / not_configured / rejected flush entries remain queued.
- Accepted flush entries are removed from the queue.
```

Queue file:

```text
output/cr/state/cr_deferred_dispatch_queue.json
```

Operator warnings:

```text
- Do NOT manually edit the queue unless performing emergency rollback.
- Back up the queue before any manual deletion.
- A malformed queue fails closed (no send, queue not overwritten).
- Disabling quiet-hours (PTILOPSIS_CR_QUIET_HOURS_ENABLED=0) may leave queued
  entries stranded until a live run with the queue present drains them, or you
  perform a manual backup-and-clear. There is no automatic drain command.
```

This PR does not add a drain command; draining happens via normal post-quiet
`live` runs that flush accepted entries.

---

## 8. Rollback / emergency stop

See [`cr-a-rollback-guide.md`](cr-a-rollback-guide.md) for the full guide. Quick
reference:

```bash
export PTILOPSIS_CR_DISPATCH_MODE=off          # emergency stop: CR-A dispatch off
export PTILOPSIS_CR_TELEGRAM_SEND=0            # block live send even in live mode
export PTILOPSIS_CR_QUIET_HOURS_ENABLED=0      # stop quiet-hours deferral policy
export PTILOPSIS_CR_QUIET_HOURS_ALLOW_URGENT=0 # urgent no longer bypasses quiet-hours
```

---

## 9. Local smoke check (no Telegram)

A read-only smoke check validates the current artifacts without running CR or
sending anything. Documentation-only form:

```bash
# Each of these must parse as JSON; missing files are tolerated (no run yet).
python3 -c "import json,sys; json.load(open('output/cr/latest/dispatch_plan.json'))"
python3 -c "import json,sys; json.load(open('output/cr/latest/dispatch_receipts.json'))"
python3 -c "import json,sys; json.load(open('output/meta/deploy_trace/latest.json'))"
```

Scripted form (preferred — enforces the no-false-success invariant):

```bash
.venv/bin/python scripts/cr_a_smoke_check.py
```

The script is **read-only**: it sends no Telegram, runs no CR runtime, mutates
no state, and exits non-zero on malformed JSON or an invariant violation
(`accepted == true` with `status != accepted`). See
[`scripts/cr_a_smoke_check.py`](../scripts/cr_a_smoke_check.py).
