# CR-A Cooldown Audit Artifact-Only Wiring (PR10f)

## 1. Purpose

PR10f wires the PR10e cooldown audit assembly into the CR runtime *dry-run*
artifact path. It lets a local artifact dry-run optionally include cooldown
audit evidence in the Markdown / HTML audit documents.

It is observability-only and inert: it enforces nothing, suppresses nothing,
reads no prior state file, and writes no state.

## 2. What it shows

When enabled, the Markdown / HTML audit artifacts additionally render, per
candidate:

- Repeat Preview (PR10b)
- Cooldown Policy Preview (PR10d)

and the dry-run result exposes a `cooldown_audit` context (PR10e) holding the
event identity, repeat preview, cooldown decision, and a **proposed** next-state
entry per candidate. The proposed state updates exist in memory only — they are
never written.

Because this first wiring reads no prior snapshot (`prior_snapshot=None`), the
render config passes no prior `seen_event_states`, so both the rendered evidence
and the context report `not_evaluated`. That is expected and proves the
end-to-end wiring is inert and safe. A meaningful same-level-repeat → cooldown
example is exercised by feeding a synthetic in-memory snapshot directly into
`build_cr_cooldown_audit_context` and the render configs (no state file).

## 3. Default behavior

Disabled by default. `include_cooldown_audit=False` is the default on
`build_and_write_cr_runtime_dry_run`, and default artifact output is unchanged
byte-for-byte. The CR-A Telegram text and the dispatch plan are unaffected
whether the flag is on or off.

Enable it explicitly:

```python
result = build_and_write_cr_runtime_dry_run(
    hotlist_stats=...,
    run_label="...",
    artifact_config=...,
    include_cooldown_audit=True,          # opt-in, artifact-only
    cooldown_policy=CRCooldownPolicy(),   # optional; defaults applied
)
# result.cooldown_audit is the PR10e CRCooldownAuditContext (in memory only)
```

## 4. Non-goals

- no Telegram suppression
- no dispatch suppression
- no production cooldown enforcement
- no state file read/write
- no config.yaml integration
- no environment variable gate for this behavior
- no production runtime behavior change

## 5. Handoff

A future PR may add an explicit local-only prior-snapshot input for dry-run
artifact experiments (still in memory, still no production persistence) so that
audit artifacts can show real `same_level_repeat` / `meaningful_escalation`
evidence. Production enforcement (suppressing dispatch, writing state, reading a
clock) still requires a separate, explicitly gated PR.
