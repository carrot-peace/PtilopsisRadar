# CR-A Cooldown Audit Assembly (PR10e)

## 1. Purpose

PR10e assembles the existing PR10a/b/c/d primitives — event identity, prior
state, repeat preview, and cooldown policy — into a single audit-only context.

It makes it easy for artifacts and future *audit-only* dry-runs to show, per
candidate: what the event is, how it relates to prior state, what a cooldown
policy would decide, and what the next-state entry *would* be.

The assembly is observability-only and intentionally inert. It does not enforce
cooldown, does not suppress dispatch, does not read or write state files, does
not touch Telegram, and does not integrate runtime/config. The proposed
state-update entries are computed in memory only and are never written here.

## 2. Relationship to PR10a / PR10b / PR10c / PR10d

```text
PR10a: What event is this?
PR10b: How does this event relate to prior state?
PR10c: Where does prior state come from?
PR10d: What would a cooldown policy decide?
PR10e: How are these pieces assembled into audit evidence?
```

PR10e adds no new identity, state, preview, or policy logic of its own. It only
wires the existing pieces together:

- event identity from [cr_event_identity_evidence.md](cr_event_identity_evidence.md)
- repeat preview from [cr_repeat_preview.md](cr_repeat_preview.md)
- state snapshot / proposed entries from
  [cr_event_state_snapshot.md](cr_event_state_snapshot.md)
- cooldown policy from [cr_cooldown_policy.md](cr_cooldown_policy.md)

## 3. What the audit context contains

`build_cr_cooldown_audit_context(candidates, *, prior_snapshot=None,
policy=None, seen_at=None)` returns a `CRCooldownAuditContext` with:

- `candidates`: one `CRCooldownAuditCandidate` per input candidate, in input
  order. Each holds:
  - `event_identity` — PR10a `CREventIdentity`
  - `repeat_preview` — PR10b `CRRepeatPreview`
  - `cooldown_decision` — PR10d `CRCooldownDecision`
  - `state_update` — a *proposed* PR10c `CREventStateEntry` (never written)
- `seen_event_states`: the prior snapshot converted to the in-memory shape that
  `CRMarkdownRenderConfig` / `CRHTMLRenderConfig` already accept, so callers can
  render repeat-preview and cooldown-preview evidence without re-deriving it.
- `state_updates`: the proposed next-state entries in input order.

Semantics:

- `prior_snapshot is None` → repeat preview is `not_evaluated`, cooldown
  decision is `not_evaluated`, and `seen_event_states` is empty.
- `prior_snapshot` provided → it is converted to `seen_event_states`, each
  candidate's repeat preview is built against it, and each preview is mapped to
  a cooldown decision under `policy`.

A proposed next-state entry is built for every candidate using the explicit
`seen_at` string; no timestamp is generated internally.

### Rendering

Because the renderers already accept `seen_event_states`,
`include_repeat_preview`, `include_cooldown_decision`, and `cooldown_policy`
(added in PR10b/PR10d), PR10e requires no renderer changes. A caller passes
`context.seen_event_states` straight into a render config:

```python
context = build_cr_cooldown_audit_context(candidates, prior_snapshot=snapshot)
cfg = CRMarkdownRenderConfig(
    include_repeat_preview=True,
    include_cooldown_decision=True,
    seen_event_states=context.seen_event_states,
)
```

Default render configs still show neither repeat preview nor cooldown preview,
and the CR-A Telegram text renderer is unaffected.

## 4. Non-goals

- no Telegram suppression
- no dispatch suppression
- no runtime integration
- no state file read/write
- no config.yaml integration
- no environment variable integration
- no production enforcement

## 5. Handoff

PR10f wires this context into the runtime dry-run artifact path behind an
opt-in, artifact-only flag; see
[cr_cooldown_artifact_wiring.md](cr_cooldown_artifact_wiring.md). PR10g lets the
caller supply an explicit in-memory prior snapshot so the artifacts show real
repeat / cooldown decisions; see
[cr_cooldown_prior_snapshot_input.md](cr_cooldown_prior_snapshot_input.md).
PR10i uses the context's proposed `state_updates` to render an artifact-only
next-state preview; see
[cr_state_transition_preview.md](cr_state_transition_preview.md).
Production enforcement (actually suppressing dispatch, writing state, or reading
a clock) still requires a separate, gated PR.
