# CR-A Explicit Local State File Input for Artifact Dry-Run (PR10h)

## 1. Purpose

PR10h lets an artifact-only CR runtime dry-run load a prior event state
snapshot from a caller-provided local JSON path.

The loaded snapshot is used only to render repeat-preview and cooldown-policy
evidence in Markdown / HTML artifacts when `include_cooldown_audit=True`.
It does not enforce cooldown, suppress dispatch, send Telegram, or persist any
state updates.

## 2. Why explicit path only

The path is explicit by design:

- no environment variable lookup
- no config.yaml integration
- no default state path
- no production enablement

The dry-run calls `load_cr_event_state_snapshot(path)` through the existing
explicit-path state-store boundary. In PR10h this was read-only. PR10j adds a
separate explicit next-state output path; it still does not make the prior path
a write-back path.

## 3. Missing vs malformed semantics

The local path is read only when all of these are true:

```text
include_cooldown_audit=True
cooldown_prior_snapshot is None
cooldown_prior_snapshot_path is provided
```

When `include_cooldown_audit=False`, the path is ignored entirely and no load
is attempted.

Load outcomes:

```text
missing file -> known empty prior state -> new / allow_new
malformed/schema mismatch -> state source failed -> not_evaluated
```

This distinction matters:

- a missing file means there is no prior history yet, so an empty snapshot is a
  valid prior state
- a malformed or schema-invalid file means the source failed, so the dry-run
  fails closed and does not claim an allow/cooldown verdict

`CRRuntimeDryRunResult.cooldown_prior_snapshot_load` records the structured
load result when a path was read. It is `None` when no local state path was
read.

## 4. Non-goals

- no state writes
- no state update persistence
- no default state path
- no environment variable integration
- no config.yaml integration
- no Telegram suppression
- no dispatch suppression
- no production cooldown enforcement
- no scheduler integration
- no bot commands
- no dashboard work

## 5. Handoff

PR10i adds artifact-only state transition preview, including load-result
metadata and in-memory next-state preview; see
[cr_state_transition_preview.md](cr_state_transition_preview.md).
PR10j adds explicit local-only next-state write-back for dry-runs; see
[cr_cooldown_local_state_writeback.md](cr_cooldown_local_state_writeback.md).
PR10k documents the full loop and closes PR10; see
[pr10_closure_cooldown_state_loop.md](pr10_closure_cooldown_state_loop.md).
Production integration remains intentionally separate.
