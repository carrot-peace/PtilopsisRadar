# CR-A Event Identity Evidence (PR10a)

## 1. Purpose

PR10a adds **event identity evidence** to CR audit artifacts (Markdown and
HTML). It is observability-only: it exposes a stable, deterministic identity
for each candidate so that future PR10 work can reason about repeats and
escalation.

This PR does **not** enforce dedupe or cooldown, does not suppress dispatch,
does not persist state, and does not change Telegram behavior. It only makes
identity evidence visible in the audit trail.

See also the design input that motivated this work:
[pr10_design_input_run2.md](pr10_design_input_run2.md).

## 2. Run-2 motivation

Deployment Run-2 (true 90-minute artifact-only monitoring) produced the
evidence that drives this design:

- `candidate_id` is **not stable**: the Guangxi explosion candidate changed
  `candidate_id` from `6e204d8621b7` to `35a135d75a46` when the cluster gained
  a zhihu source.
- `cluster_key` **expanded** when the zhihu source joined the same event, so it
  is source-sensitive and too verbose to be a primary key.
- The **normalized title** stayed semantically stable across the run, so it is
  the most promising primary basis for event identity.
- Decision level was **dynamic** — the same event moved through:

  ```text
  watch -> watch -> urgent -> alert -> watch -> watch
  ```

  Future PR10 work must distinguish "same event, same level" from "same event,
  meaningful escalation".

## 3. Current event key strategy

Conceptually:

```text
event_key = normalized_title_key + supporting evidence
```

Technically, in `trendradar/cr/event_identity.py`:

- The **primary** `event_key` is derived from the normalized title only:
  `event_key = "cr-event-v1:" + sha256("cr-event-v1\x1f" + normalized_title)`.
  It is versioned and storage-safe (ASCII, no whitespace, no raw title text).
- `key_basis` is the string `normalized_title`.
- `candidate_id` is preserved **verbatim** as supporting evidence — never as
  primary identity.
- `cluster_key` is preserved only as a short **fingerprint** (supporting
  evidence). The raw, verbose `cluster_key` is never embedded in the identity
  section.
- Platform and source-URL sets are fingerprinted **order-insensitively**, so
  reordering or fragment noise does not change the fingerprint.

Because Run-2 showed `candidate_id` and `cluster_key` shift when source
evidence changes, **neither contributes to `event_key`**. Two observations of
the same titled event therefore share an `event_key` even when their
`candidate_id` or `cluster_key` differ — while the differing values remain
visible as evidence.

### What the evidence lets PR10b/c answer

- Is this the same event as before? → compare `event_key`.
- Did the event only repeat at the same level? → `event_key` stable + same
  decision level.
- Did the event escalate (watch → alert/urgent)? → `event_key` stable + level
  change.
- Is the `candidate_id` stable or only supporting evidence? → it is only
  evidence; compare against the stable `event_key`.

## 4. Limitations

- **Title variants** may still map to different `event_key`s. For example
  "广西兴安发生爆炸已致7死17伤" and "广西兴安爆炸致7死17伤" should probably be
  the same event, but naive normalization does not collapse them. Future work
  may need smarter normalization or fuzzy matching.
- Normalized-title identity is **not perfect** — it is the current best basis,
  not a final answer.
- **No dedupe / cooldown enforcement** yet — this is evidence only.
- **No persistence** yet — identity is recomputed per run, not stored.
- **No Telegram behavior change** — the CR-A text renderer is untouched.

## 5. PR10 handoff

Recommended next steps, building on this evidence:

- **PR10b**: use event identity evidence to *preview* repeats/escalation in
  artifacts (still observability; no suppression).
- **PR10c**: persist `event_key` state across runs (state boundary).
- **PR10d**: cooldown / escalation policy (the first actual enforcement layer),
  informed by the 30–60 minute cooldown range discussed in the Run-2 design
  input.
