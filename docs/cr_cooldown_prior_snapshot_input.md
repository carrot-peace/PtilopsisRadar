# CR-A Explicit Prior Snapshot Input for Artifact Dry-Run (PR10g)

## 1. Purpose

PR10g lets an artifact-only CR runtime dry-run accept an explicit, in-memory
prior event state snapshot, so the cooldown audit artifacts can show *real*
repeat / cooldown decisions instead of only `not_evaluated`.

It extends PR10f's artifact-only wiring from:

```text
prior_snapshot=None → repeat preview not_evaluated
```

to:

```text
caller-provided prior_snapshot → repeat preview + cooldown decision in artifacts
```

This PR is still artifact-only. It enforces nothing and changes neither
Telegram nor dispatch behavior.

## 2. The new parameter

`build_and_write_cr_runtime_dry_run` gains one optional keyword argument:

```python
cooldown_prior_snapshot: CREventStateSnapshot | None = None
```

Behavior:

- `include_cooldown_audit=False` → `cooldown_prior_snapshot` is **ignored**;
  default artifacts are unchanged and `cooldown_audit` is `None`.
- `include_cooldown_audit=True` and `cooldown_prior_snapshot=None` → identical
  to PR10f: repeat preview and cooldown decision render `not_evaluated`.
- `include_cooldown_audit=True` and `cooldown_prior_snapshot` provided → the
  snapshot is converted (a pure transform) to `seen_event_states`, threaded
  into the Markdown / HTML render configs, and passed to
  `build_cr_cooldown_audit_context`. The artifacts can then show
  `same_level_repeat` → `cooldown` or `meaningful_escalation` →
  `allow_escalation`, etc.

## 3. Artifact-only semantics

- The snapshot is **always caller-provided in memory**. It is never read from a
  file and never written to one.
- No on-disk event state layer is used; `state_store` is not imported.
- The CR-A Telegram text is byte-for-byte identical with and without a prior
  snapshot.
- The dispatch plan is unchanged.
- The proposed next-state entries in the resulting `cooldown_audit` context
  remain in memory only and are never persisted.
- Disabled by default — opt in via `include_cooldown_audit=True`.

Example:

```python
prior = CREventStateSnapshot(
    schema_version=CR_EVENT_STATE_SCHEMA_VERSION,
    entries=(
        CREventStateEntry(event_key="cr-event-v1:...", decision_level="watch"),
    ),
)
result = build_and_write_cr_runtime_dry_run(
    hotlist_stats=...,
    run_label="...",
    artifact_config=...,
    include_cooldown_audit=True,
    cooldown_prior_snapshot=prior,   # in memory only; no disk I/O
)
```

## 4. Relationship to PR10f

PR10f ([cr_cooldown_artifact_wiring.md](cr_cooldown_artifact_wiring.md)) wired
the PR10e audit assembly into the dry-run artifact path with `prior_snapshot`
fixed to `None`, proving the wiring was inert. PR10g keeps that wiring and the
same inert guarantees, but allows the caller to supply the prior snapshot
explicitly so the evidence becomes meaningful.

## 5. Non-goals

- no state file reads
- no state file writes
- no `state_store` integration
- no Telegram suppression
- no dispatch suppression
- no production cooldown enforcement
- no config.yaml integration
- no environment variable integration
- no scheduler integration

## 6. Handoff

A future PR may add an explicit *local file* input that loads a prior snapshot
from disk for dry-run experiments — that is intentionally a separate, gated
change because it crosses the in-memory boundary this PR preserves. Production
enforcement (suppressing dispatch, writing state, reading a clock) likewise
remains a separate, explicitly gated PR.
