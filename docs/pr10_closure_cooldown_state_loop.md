# PR10 Closure — Local Cooldown State Loop

## PR10 Scope Completed

| PR | Function |
|---|---|
| PR10a | Event identity evidence — normalized title, candidate ID, event key version in artifacts |
| PR10b | Repeat preview evidence — prior-seen status (`new` / `same_level_repeat` / `meaningful_escalation`) in artifacts |
| PR10c | Event state snapshot boundary — explicit model for seen event states with schema validation |
| PR10d | Cooldown policy decision layer — `allow_new` / `cooldown` / `allow_escalation` decisions |
| PR10e | Cooldown audit assembly — in-memory audit context from presented candidates |
| PR10f | Artifact-only cooldown audit wiring — opt-in cooldown evidence in Markdown/HTML artifacts |
| PR10g | Explicit in-memory prior snapshot input — caller-provided snapshot for real cooldown decisions |
| PR10h | Explicit local state file input — read-only load from caller-provided JSON path |
| PR10i | State transition preview in artifacts — load status, proposed updates, in-memory next snapshot |
| PR10j | Explicit local state write-back — caller-provided output path for next-state persistence |

## Final Capability

PR10 now supports:

```text
event identity evidence in artifacts
repeat preview (new / same_level_repeat / meaningful_escalation)
cooldown policy preview (allow_new / cooldown / allow_escalation)
event state snapshot model with schema validation
explicit local state file input (read-only)
state transition preview in artifacts
explicit local dry-run write-back
operator-validated local cooldown loop
```

The full loop:

```text
caller-provided prior path
→ load prior state snapshot
→ evaluate candidates against prior state
→ render cooldown evidence in artifacts
→ build next-state snapshot
→ write next state to caller-provided output path
→ next run uses that output as prior
```

## Final Boundary

Still no:

```text
production cooldown enforcement
Telegram suppression
dispatch suppression
default state path
env/config state path
scheduler integration
bot commands
dashboard work
```

## Smoke Evidence

Development-machine smoke passed on 2026-06-12.

Test suite: 982 CR tests, all green.

Validated loop:

```text
Run 1 (missing prior):
  prior load: loaded=False, error=None
  artifact: new / allow_new
  next state file: written with 1 entry

Run 2 (prior = Run 1 output):
  prior load: loaded=True, error=None
  artifact: same_level_repeat / cooldown
  next state file: written with same entry

Malformed prior:
  prior load: loaded=False, error="malformed event state JSON: JSONDecodeError"
  artifact: not_evaluated / suppressed
  next state file: not written (suppressed)
```

CR-A text and dispatch plan remained identical across all runs — no leakage
of cooldown evidence into Telegram or dispatch paths.

Generated files were local ephemeral temp paths under
`/tmp/ptilopsis-pr10-state-loop.*`.

## Recommended Next Phase

PR11 should focus on:

- operator ergonomics (CLI wrapper for local cooldown loop)
- hard-gated production state path config
- production enforcement dry-run shadow mode
- Telegram/dispatch suppression only after shadow validation

Immediate enforcement is not recommended. The local loop validates the
mechanism; production integration requires separate gated PRs.
