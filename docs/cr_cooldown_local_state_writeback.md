# CR-A Explicit Local State Write-Back for Artifact Dry-Run (PR10j)

## Purpose

PR10j adds an explicit local next-state snapshot write-back option for CR-A
cooldown audit dry-runs.

It builds on:

- PR10h explicit local prior state file input
- PR10i in-memory state transition preview

The write-back persists only the transition preview's `next_snapshot`, and only
when the caller provides an explicit output path.

## Required Inputs

Both inputs are required for a write attempt:

```text
include_cooldown_audit=True
cooldown_next_snapshot_path=<explicit local path>
```

The output path is not inferred. The dry-run does not read it from an
environment variable, config file, scheduler setting, or default location.

## Write Semantics

```text
no path -> no write
audit disabled -> no write
next snapshot suppressed -> no write
valid next snapshot + explicit path -> write
```

Missing and malformed prior state remain distinct:

```text
missing prior file -> known empty prior state -> next state can be written
malformed/schema mismatch -> fail closed -> next state is suppressed and not written
```

`CRRuntimeDryRunResult.cooldown_next_snapshot_save` records the structured save
result when a write is attempted. It is `None` when no write was attempted.

## Boundaries

This is still a dry-run artifact feature. It does not alter CR-A text, dispatch
planning, dispatch execution, Telegram behavior, or cooldown enforcement.

The only filesystem write added here is through
`save_cr_event_state_snapshot(next_snapshot, cooldown_next_snapshot_path)` with
the caller-provided path.

## Non-Goals

- no default state path
- no environment variable state path
- no config.yaml state path
- no automatic write-back
- no production state persistence
- no Telegram suppression
- no dispatch suppression
- no production cooldown enforcement
- no scheduler integration
- no bot commands
- no dashboard work

## Handoff

PR10k documents the full local cooldown state loop and closes PR10; see
[pr10_closure_cooldown_state_loop.md](pr10_closure_cooldown_state_loop.md) and
[cr_local_cooldown_state_loop.md](cr_local_cooldown_state_loop.md).
