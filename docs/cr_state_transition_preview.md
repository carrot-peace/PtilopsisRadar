# CR-A Cooldown State Transition Artifact Preview (PR10i)

## Purpose

PR10i previews what the next CR-A event state snapshot would look like after an
artifact-only cooldown audit dry-run, without writing it.

It adds artifact visibility for:

- prior snapshot load status
- proposed per-candidate state update count
- next snapshot preview availability
- next snapshot entry count
- fail-closed state-source errors

The preview is in memory only. It is never persisted.

## Inputs

The state transition preview is built from:

- the effective prior snapshot used by cooldown audit rendering
- proposed state updates from `CRCooldownAuditContext.state_updates`
- prior load metadata from `CREventStateLoadResult` when a local path was read

The pure builder is `build_cr_event_state_transition_preview`.

## Semantics

```text
valid prior snapshot -> merged next snapshot preview
missing file -> known empty prior -> next snapshot preview from current updates
malformed/schema mismatch -> fail closed -> next snapshot preview suppressed
no prior supplied -> next snapshot preview from current updates
```

The preview uses `merge_cr_event_state_entries` to compute the next snapshot in
memory. Existing event keys are replaced by current proposed updates, and new
event keys are added.

Artifacts render summary metadata only. They do not dump raw snapshot JSON by
default.

## Non-goals

- no state write-back
- no persistence
- no production enforcement
- no Telegram suppression
- no dispatch suppression
- no default path
- no environment variable path
- no config.yaml path

## Handoff

PR10j adds explicit local-only write-back using a caller-provided output path;
see [cr_cooldown_local_state_writeback.md](cr_cooldown_local_state_writeback.md).
That remains separate because it crosses from preview-only artifact evidence
into opt-in local persistence.
