# Legacy Push Removal and Generation/CR Separation Plan

## Status

This document is the canonical plan for removing Legacy Push while preserving
artifact generation and CR-New.

Current status before PR-A:

- Legacy Push is still live and reachable from normal runtime.
- Generation still has one dirty dependency on
  `NotificationDispatcher.translate_content` before PR-B.
- `trendradar/notification/` must not be deleted before PR-B.
- CR-New Canary / Shadow is allowed later behind explicit gates.
- Production Push is out of this series and requires a future separate design.

This document is intentionally a plan and policy boundary. PR-0 does not change
runtime push behavior, notification code, translation code, or CR Telegram
behavior.

## Boundaries

### Generation Plane

Generation Plane includes data collection, statistics, AI analysis, artifact
content translation, HTML rendering, dashboard rendering, Daily Report
rendering, and local artifact writing.

Policy:

- It may collect data, compute stats, run AI analysis, translate artifact
  content, and render HTML / dashboard / Daily Report / artifacts.
- It must not import `trendradar.notification` after PR-B.
- It must not call `dispatch_all`.
- It must not call `send_to_telegram`.
- It must not POST to Telegram.
- It must not trigger Transport.

### Legacy Push

Legacy Push includes:

- `_send_notification_if_needed`
- `dispatch_all`
- `send_to_telegram`
- old Telegram fallback
- old `--test-notification` dispatch path
- old multi-channel compatibility facade

Policy:

- It must be removed from normal runtime.
- It must not fallback-send.
- It must not silently no-op as success.
- It must not return success-shaped `True` when nothing was sent.
- It must eventually be fail-closed or deleted.
- It is not a degraded path.
- It is not a compatibility path.

### CR-New

CR-New includes:

- CR candidates
- CR decisions
- CR dispatch plan
- CR dispatch executor
- CR Telegram env sink
- CR local cooldown state loop

Policy:

- It is the only future push-capable path.
- It must remain explicitly gated.
- CR Telegram requires explicit gates.
- Canary / Shadow is not Production Push.
- Production Push is a future separate design.
- There is no default state path.
- There is no implicit env/config state path.
- Structured receipts are required for dispatch execution.

## Why Legacy Push Must Be Removed

Legacy Push must be removed because it mixes runtime control, content selection,
fallback behavior, Transport, and success semantics in one old path.

Known problems:

- Normal runtime can still reach Legacy Push before PR-A.
- Old Telegram fallback can still send fallback text.
- No-send paths can still look like success.
- The sender performs content selection, fallback, POST, and success handling.
- The old `--test-notification` path validates fallback behavior instead of the
  intended future push path.
- `report_data` is still built and transformed, but it no longer reliably drives
  the real Telegram body.

The removal must be fail-closed runtime removal, not silent disablement.

## PR Series

### PR-0: Documentation and Guard Scaffolding

Purpose:

- Establish this canonical plan.
- Add guard-test scaffolding that keeps the current suite green.
- Record current known violations without pretending the system is already
  clean.

Scope:

- Add this document.
- Add lightweight source/doc guard tests that are enforceable now.
- Add documented or expected-failure placeholders for guards that are known to
  fail before PR-A / PR-B / PR-C.

Out of scope:

- Runtime behavior changes.
- Push behavior changes.
- Notification package deletion.
- Translation migration.
- CR behavior changes.
- Production Push.

Changed areas:

- `docs/`
- test scaffolding under `tests/`
- minimal README pointer if needed.

Hard acceptance criteria:

- This document exists.
- It defines Generation Plane, Legacy Push, and CR-New boundaries.
- It defines PR-0 through PR-F.
- It states that PR-A must be fail-closed removal, not silent disablement.
- It states that PR-B must move translation out of notification.
- It states the PR-C1 / PR-C2 split.
- It states that DR v2 is Artifact-only.
- It states that CR-New Canary / Shadow is not Production Push.
- It states that Production Push is a future separate design.
- The full test suite remains green.

Rollback notes:

- Revert the documentation and guard scaffolding only. No runtime rollback is
  needed because PR-0 has no runtime behavior change.

### PR-A: Disconnect Legacy Push From Runtime

Purpose:

- Make normal current / incremental / daily runtime unable to call Legacy Push.

Scope:

- Stop normal runtime from calling `_send_notification_if_needed`.
- Stop normal runtime from calling `dispatch_all`.
- Stop normal runtime from calling `send_to_telegram`.
- Stop `schedule.push`, `once_push`, and `ENABLE_NOTIFICATION` from triggering
  Legacy Push.
- Remove or fail-close old `--test-notification`.
- Update runtime status logs so they do not imply Legacy Push will send.

Out of scope:

- Deleting `trendradar/notification/`.
- Moving translation.
- Enabling CR-New Production Push.

Changed areas:

- Runtime entry and CLI notification handling.
- Legacy notification tests that currently assert old behavior.
- Minimal docs/config comments that advertise removed runtime push.

Hard acceptance criteria:

- No normal runtime path can reach `dispatch_all`.
- No normal runtime path can reach `send_to_telegram`.
- `--test-notification` cannot send Telegram through the legacy path.
- No fallback Telegram is reachable from normal runtime.
- No-send does not return success-shaped `True`.
- The removal is fail-closed and explicit, not silent disablement.

Rollback notes:

- Reverting PR-A restores Legacy Push reachability and must be treated as
  restoring a known unsafe path.

### PR-B: Extract Generation Translation

Purpose:

- Remove the dirty Generation Plane dependency on
  `NotificationDispatcher.translate_content`.

Scope:

- Move artifact content translation into a generation-owned module, preferably
  `trendradar/report/translation.py`.
- Preserve translation behavior for HTML / dashboard / report artifacts.
- Let Generation Plane construct/use translation without constructing
  `NotificationDispatcher`.

Out of scope:

- Push behavior changes.
- Notification package deletion.
- CR Telegram behavior.

Changed areas:

- Generation translation helper.
- App context wiring for translation.
- Translation parity tests.

Hard acceptance criteria:

- Generation Plane no longer imports `trendradar.notification`.
- Artifact translation behavior is preserved.
- No Transport code moves into the new translation module.

Rollback notes:

- Reverting PR-B restores the dirty dependency and blocks PR-C2 deletion.

### PR-C1: Fail-Closed Legacy Notification Stub

Purpose:

- Convert Legacy Push into an explicitly failed path while any old imports are
  being cleaned.

Scope:

- Replace callable Legacy Push surfaces with fail-closed behavior.
- Keep only an explicit removal error if transitional imports require it.
- Remove or block sender/fallback behavior.

Out of scope:

- Full package deletion if imports remain.
- Generation translation migration, which must already be complete.
- Production Push.

Changed areas:

- Legacy notification facade.
- Tests that currently expect old positive exports or fallback sends.
- Docs/config references to old push behavior.

Hard acceptance criteria:

- No callable legacy sender remains.
- No callable legacy dispatcher remains.
- No fallback Telegram remains.
- No compatibility facade can send.
- No legacy API returns success-shaped `True` for no-send.

Rollback notes:

- Reverting PR-C1 reopens Legacy Push surfaces and must be treated as a push
  safety regression.

### PR-D: Daily Report v2 Artifact-only

Purpose:

- Rebuild Daily Report as an artifact product, not a Legacy Push product.

Scope:

- Render DR v2 artifacts.
- Add explicit schema and renderer guards.
- Keep DR independent of Transport.

Out of scope:

- DR Telegram sending.
- Reusing Legacy Push.
- Reusing CR Telegram sink for DR.
- Production Push.

Changed areas:

- DR schema / renderer.
- DR tests.
- Artifact-only docs.

Hard acceptance criteria:

- DR v2 does not call `send_to_telegram`.
- DR v2 does not call `dispatch_all`.
- DR v2 does not import `trendradar.notification`.
- DR v2 emits artifacts only.
- Any future DR push requires a separate explicit DR dispatch plan and gate.

Rollback notes:

- Reverting PR-D restores the previous DR artifact behavior only. It must not
  restore Legacy Push.

### PR-C2: Delete Legacy Notification Package

Purpose:

- Delete the old notification package after runtime and generation no longer
  need it.

Scope:

- Delete legacy dispatcher, sender, fallback, and stale compatibility surfaces.
- Move any still-needed pure helpers out of `trendradar/notification/` before
  deletion.
- Remove or rewrite legacy-positive tests and docs.

Out of scope:

- New push behavior.
- CR Production Push.
- DR push.

Changed areas:

- `trendradar/notification/`
- legacy notification tests.
- docs/config references.

Hard acceptance criteria:

- Source grep shows no required imports of `trendradar.notification`.
- `NotificationDispatcher`, `dispatch_all`, and `send_to_telegram` are not
  required by runtime, Generation Plane, DR, or CR-New.
- No generated artifacts are committed.

Rollback notes:

- Reverting PR-C2 restores deleted legacy code. It must not be used as a
  compatibility fallback.

### PR-E: CR-New Canary / Shadow

Purpose:

- Enable CR-New Canary / Shadow as the only future push-capable path.

Scope:

- Keep explicit CR Telegram gates.
- Use structured dispatch plans.
- Use structured receipts.
- Run canary/shadow only with operator intent.

Out of scope:

- Unattended Production Push.
- Default state paths.
- Implicit env/config state paths.
- DR push.
- Legacy Push fallback.

Changed areas:

- CR operator docs and canary workflow.
- CR dispatch tests if needed.
- Deployment notes for canary/shadow only.

Hard acceptance criteria:

- CR Telegram cannot send without explicit gates.
- `PTILOPSIS_CR_DRY_RUN=1` remains canary/shadow, not production.
- `PTILOPSIS_CR_TELEGRAM_SEND=1` remains CR-specific.
- Dispatch results include structured receipts.
- No default state path appears.
- No implicit env/config state path appears.

Rollback notes:

- Disable the explicit send gate and revert canary docs/config. No Legacy Push
  fallback may be restored.

### PR-F: Future Production Push Design

Purpose:

- Design Production Push after CR-New canary/shadow evidence exists.

Scope:

- Production gate design.
- State path policy.
- Cooldown/dedupe enforcement.
- Retry/backoff.
- Receipt persistence.
- Scheduler integration.
- Operator rollback/runbook.

Out of scope:

- This cleanup series.
- Legacy Push compatibility.
- DR push without its own dispatch plan.

Changed areas:

- Future design documents and implementation PRs only.

Hard acceptance criteria:

- Production Push has a separate explicit policy and implementation.
- Production Push does not use Legacy Push.
- Production Push does not use canary/dry-run naming as production semantics.

Rollback notes:

- Production rollback must disable the production gate without restoring Legacy
  Push.

## Hard Red Lines

These conditions are policy violations:

- Generation Plane imports `trendradar.notification`.
- DR calls `send_to_telegram`.
- Runtime calls `dispatch_all`.
- `--test-notification` sends Telegram through the legacy path.
- Fallback Telegram is reachable.
- No-send returns success.
- CR Telegram can send without both gates.
- A default state path appears.
- An implicit env/config state path appears.

## Deployment Gate By Stage

| Stage | Allowed | Not Allowed | Status |
|---|---|---|---|
| PR-0 | Documentation and guard scaffolding | Runtime behavior changes, push behavior changes | Yellow |
| PR-A | Normal runtime with Legacy Push disconnected | Legacy fallback, false success, legacy test send | Yellow |
| PR-B | Artifact translation independent of notification | Deleting notification before imports are clean | Yellow-Green |
| PR-C1 | Fail-closed Legacy Push stub | Callable legacy sender or dispatcher | Yellow-Green |
| PR-D | DR v2 Artifact-only | DR Telegram push, CR sink reuse, Legacy Push reuse | Green for artifacts |
| PR-C2 | Deleted legacy notification package | Compatibility fallback or restored legacy facade | Green if grep/tests clean |
| PR-E | CR-New Canary / Shadow with explicit gates | Production Push, default state path, implicit state path | Yellow |
| PR-F | Future Production Push design | Treating canary/dry-run as production | Not in this series |

## Test Strategy

PR-0 starts with low-disruption guard scaffolding. Later PRs must harden the
guards as the code becomes clean.

Test categories:

- Source guard tests for forbidden imports and calls.
- Fake transport tests proving no unintended Telegram POST occurs.
- Runtime no-dispatch tests for current / incremental / daily modes.
- Translation parity tests for moved artifact translation.
- DR renderer guard tests for Artifact-only behavior.
- CR env gate tests proving explicit gates are required.
- Docs/config grep checks for stale Legacy Push guidance.

Known-before-cleanup guard status:

- `normal runtime must not call dispatch_all` is expected to fail before PR-A.
- `normal runtime must not call send_to_telegram` is expected to fail before
  PR-A / PR-C.
- `Generation Plane must not import trendradar.notification` is expected to
  fail before PR-B.
- `fallback Telegram must be unreachable` is expected to fail before PR-C1.

## Final Policy

Legacy Push is not a degraded path.

Legacy Push is not a compatibility path.

Legacy Push must become unreachable, fail-closed, and eventually deleted.

CR-New is the only future push-capable path, and it remains gated, auditable,
and separate from Production Push until a future explicit production design is
approved.
