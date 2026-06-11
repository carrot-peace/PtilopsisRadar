# PR9 CR-A MVP Closure

## 1. Status

PR9 is complete as the minimum viable CR-A Telegram path.

This means the path exists and is manually/operator gated. It does not mean
production hardening is complete. Default behavior remains no-send.

## 2. Final PR9 chain

```text
runtime stats
-> CR dry-run hook
-> CR pipeline
-> CR-A dispatch plan
-> dispatch executor
-> Telegram env factory
-> Telegram sink
```

- Runtime stats: existing runtime hotlist and RSS stats provide the source
  material for CR.
- CR dry-run hook: explicitly gated runtime bridge that converts stats into CR
  primitives and writes audit artifacts.
- CR pipeline: assembles clustering, scoring, decision, presentation, and audit
  rendering.
- CR-A dispatch plan: selects push-eligible CR-A candidates and builds planned
  messages.
- Dispatch executor: submits only messages already present in the dispatch
  plan to an injected sink.
- Telegram env factory: constructs a Telegram sink from explicit environment
  values only when the Telegram send gate is enabled.
- Telegram sink: sends planned CR-A message text to Telegram when constructed
  and invoked by the executor.

## 3. PR9 component map

| Component | Purpose | Sends anything? | Runtime-facing? |
| --- | --- | --- | --- |
| CR primitive adapter | Converts runtime-shaped hotlist/RSS stats into CR primitive records. | No | Yes, through the dry-run hook |
| CR clustering | Groups primitive records into topic-level CR candidates. | No | Indirectly, through the CR pipeline |
| CR scoring | Computes deterministic CR component and total scores. | No | Indirectly, through the CR pipeline |
| CR decision policy | Classifies candidates and marks push eligibility. | No | Indirectly, through the CR pipeline |
| CR presentation | Prepares selected candidates and CR-A text payloads. | No | Indirectly, through the CR pipeline |
| Markdown audit renderer | Renders local Markdown audit output. | No | Indirectly, through artifact writing |
| HTML audit renderer | Renders local HTML audit output. | No | Indirectly, through artifact writing |
| CR artifact writer | Writes CR Markdown/HTML audit artifacts. | No | Yes, through the dry-run hook |
| Offline pipeline assembly | Connects adapter-independent CR stages into one offline pipeline. | No | Indirectly, through the dry-run hook |
| Runtime dry-run hook | Bridges runtime stats to the CR pipeline and artifact writer behind `PTILOPSIS_CR_DRY_RUN=1`. | No by default; can execute against an injected sink | Yes |
| CR-A dispatch plan | Builds planned CR-A dispatch messages from pipeline output. | No | Indirectly, through the dry-run hook |
| Dispatch executor / sink boundary | Executes a ready plan against a supplied sink boundary. | Only through the supplied sink | Indirectly, through injected runtime use |
| Telegram sink boundary | Implements Telegram submission for already planned messages. | Yes, only when constructed and invoked | Indirectly, through env-gated injection |
| Telegram env sink factory | Builds Telegram sink/config from env when `PTILOPSIS_CR_TELEGRAM_SEND=1`. | No | Yes, inside the dry-run hook |
| Env-gated runtime injection | Lazily injects the Telegram sink into the CR dry-run hook behind both gates. | Enables send only when both gates are set and a ready plan exists | Yes |
| Telegram operator guide | Documents operator usage, safety gates, examples, and limitations. | No | Operator-facing documentation |

## 4. Safety gates

Telegram dispatch remains behind both gates:

```text
PTILOPSIS_CR_DRY_RUN=1
PTILOPSIS_CR_TELEGRAM_SEND=1
```

`PTILOPSIS_CR_DRY_RUN=1` is required to enter the CR dry-run hook.
`PTILOPSIS_CR_TELEGRAM_SEND=1` is required to construct Telegram sink.
Missing either gate means no Telegram send. Invalid Telegram env with send
enabled fails fast. No config.yaml integration exists yet.

## 5. Current operator mode

The supported mode is:

```text
operator-triggered / explicitly env-gated dry-run path
```

Artifact-only dry run is the safe default. Telegram-enabled dry run should be
tested in a private chat first. This path is not intended for unattended
production operation yet.

## 6. What PR9 deliberately does NOT include

- dedupe
- cooldown
- alert-state persistence
- storage-backed state
- retry/backoff
- transport exception sanitization hardening
- config.yaml wiring
- token rotation helper
- Telegram formatting policy
- dashboard integration
- bot commands
- notification facade integration
- automatic production scheduling

## 7. Known risks

- Telegram sink uses stdlib transport; transport exceptions may still expose
  URL-shaped context if surfaced raw, so production hardening should sanitize
  transport exceptions.
- No dedupe/cooldown/state means repeated eligible runs can repeatedly send.
- Env-gated live Telegram path is suitable for controlled testing, not
  unattended production.
- PR body discipline has been inconsistent; future PRs should include explicit
  scope, files, tests, and boundary confirmation.
- Some tests in earlier PRs are source-inspection tests; they guard boundaries
  but do not replace integration tests.

## 8. PR10 handoff

PR10 should start with hardening, not new surface area.

Recommended PR10 sequence:

```text
PR10a: CR-A alert state model / state-key design
PR10b: dedupe and cooldown decision layer
PR10c: state persistence boundary
PR10d: retry/backoff and transport-error sanitization
PR10e: production operator config / controlled runtime enablement
PR10f: end-to-end guarded integration tests
```

Do not implement these in PR9r.

## 9. Closure checklist

- [x] CR artifacts can be written
- [x] CR-A candidates can be selected
- [x] dispatch plan can be built
- [x] dispatch plan can be executed against injected sink
- [x] Telegram sink exists
- [x] Telegram sink can be built from env
- [x] runtime dry-run hook can inject Telegram sink behind gates
- [x] operator guide exists
- [ ] dedupe/cooldown/state exists
- [ ] production unattended operation is recommended

## 10. Close statement

PR9 should be considered closed after this document lands.
Further production work belongs to PR10.
