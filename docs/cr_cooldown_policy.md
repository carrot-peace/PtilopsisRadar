# CR-A Cooldown Policy Decision Layer (PR10d)

## 1. Purpose

PR10d defines the CR-A cooldown policy decision layer.

It answers a single question:

```text
Given current event state, a repeat preview, and a policy, what would the
cooldown decision be?
```

This is a **pure policy decision object only**. It computes what a cooldown
policy *would* decide for a candidate. It does not suppress dispatch, does not
enforce cooldown, does not read or write event state, and does not touch
Telegram. Actual enforcement (if ever) belongs to a later, explicitly gated PR.

## 2. Relationship to PR10a / PR10b / PR10c

PR10a — Event Identity:

```text
What event is this?
```

PR10b — Repeat Preview:

```text
How does this event relate to prior state?
```

PR10c — Event State Snapshot:

```text
Where does prior state come from?
```

PR10d — Cooldown Policy:

```text
What would a cooldown policy decide?
```

The cooldown policy consumes a PR10b
[repeat preview](cr_repeat_preview.md). The repeat preview in turn depends on
PR10a identity and the PR10c
[event state snapshot](cr_event_state_snapshot.md). PR10d adds no new state
source of its own.

## 3. Actions

The cooldown decision resolves to exactly one action:

- `not_evaluated`: no repeat preview was supplied, or the repeat preview was
  itself `not_evaluated` (no prior state snapshot). The policy declines to
  claim a verdict.
- `allow_new`: the event is new and new events are allowed by policy.
- `allow_escalation`: a meaningful escalation that bypasses cooldown by policy.
- `allow`: a deescalation that is allowed by policy (off by default).
- `cooldown`: the event would be inside the cooldown window under the policy.

## 4. Default policy

`CRCooldownPolicy` defaults:

- `same_level_cooldown_minutes = 240` (4 hours)
- `allow_meaningful_escalation = True`
- `allow_new_events = True`
- `allow_deescalation = False`

These map repeat preview statuses to actions as follows:

| Repeat status           | Default action      |
| ----------------------- | ------------------- |
| `not_evaluated`         | `not_evaluated`     |
| `new`                   | `allow_new`         |
| `same_event_repeat`     | `cooldown`          |
| `same_level_repeat`     | `cooldown`          |
| `meaningful_escalation` | `allow_escalation`  |
| `deescalation`          | `cooldown`          |

In words, under the default policy:

- same-level repeat cools down
- same-event repeat cools down
- new events are allowed
- meaningful escalation bypasses cooldown
- deescalation cools down by default

`cooldown_minutes` on the decision is populated only for `cooldown` actions and
reflects `policy.same_level_cooldown_minutes`. It is reported for audit; it is
not measured against any clock here.

## 5. Audit rendering (optional)

The Markdown and HTML audit renderers can optionally render a "Cooldown Policy
Preview" section. This is config-gated and disabled by default:

- `CRMarkdownRenderConfig.include_cooldown_decision` (default `False`)
- `CRHTMLRenderConfig.include_cooldown_decision` (default `False`)
- `cooldown_policy: CRCooldownPolicy | None` (default `None` → defaults used)

The cooldown preview only renders when repeat preview is already enabled, so it
reuses the preview the renderer already computed. The renderer does not read or
write state files, does not add hrefs or JavaScript, escapes all values, and
does not alter the CR-A Telegram text or the dispatch plan.

Example Markdown for a same-level repeat:

```markdown
#### Cooldown Policy Preview

- Action: `cooldown`
- Reason: same-level repeat is inside cooldown policy
- Repeat Status: `same_level_repeat`
- Cooldown Minutes: `240`
```

Example Markdown for a meaningful escalation:

```markdown
#### Cooldown Policy Preview

- Action: `allow_escalation`
- Reason: meaningful escalation bypasses cooldown preview
- Repeat Status: `meaningful_escalation`
```

## Deferred queue runtime

Deferred entries use a fixed 12-hour TTL measured from the first
`deferred_at`; refreshes update the body but do not extend that first timestamp.
Outside quiet hours, the queue is reconciled with the current candidates by
`event_key`: an overlapping event sends once with the current body, and its
queue entry is removed only after an accepted dispatch. Unmatched entries wait
for a later current candidate or expire; they are never sent independently.

## 6. Non-Goals

- no Telegram suppression
- no dispatch suppression
- no runtime integration
- no state read/write
- no config.yaml integration
- no environment variable integration
- no scheduler
- no production enablement

## 7. PR10e Handoff

PR10e assembles this policy with event identity, prior state, and repeat
preview into an audit-only context; see
[cr_cooldown_audit_assembly.md](cr_cooldown_audit_assembly.md). PR10f wires
that audit context into the dry-run artifact path (opt-in, artifact-only); see
[cr_cooldown_artifact_wiring.md](cr_cooldown_artifact_wiring.md). Actual
production enforcement (suppressing dispatch, mutating state, reading a clock)
must remain behind explicit gates.

Open questions for PR10e:

- where the wall-clock comparison against `cooldown_minutes` should live
- whether enforcement reads state before or after artifact generation
- how corrupted state should behave in an enforcement path
- which levels are eligible to reset or extend cooldown
