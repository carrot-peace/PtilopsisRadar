# CR Semantic Event Clustering — Design (Exploratory R&D)

Design-only, **exploratory R&D** document. No runtime behavior changes are
proposed here. It records the motivation, the agreed direction, the coupling
points we must resolve, and how we resolve them. It introduces an *optional,
default-off* learned similarity signal into the deterministic CR clustering
layer, with a **per-phase kill-switch**. Implementation does not start until
this document is accepted, and even then only the final phase touches
[`cluster.py`](../trendradar/cr/cluster.py) — behind a flag that is off by
default.

This is a long-horizon track. It is deliberately scoped so that every phase
produces an independently verifiable artifact and can be abandoned without
leaving residue in the production path.

Companion: [`cr-a-event-lifecycle-design.md`](cr-a-event-lifecycle-design.md),
and the clustering source it modifies —
[`cluster.py`](../trendradar/cr/cluster.py),
[`entity_match.py`](../trendradar/cr/entity_match.py),
[`event_identity.py`](../trendradar/cr/event_identity.py).

> **Out of scope for this document:** the training-data corpus and the
> label-construction pipeline. Those live entirely in the separate encoder
> repository (see §4) and are tracked there, not here.

---

## 0. Problem statement

CR clustering today is **lexical**. [`_cluster_source_items`](../trendradar/cr/cluster.py)
groups source items by four conservative rules: exact normalized title (Rule 1),
exact URL (Rule 2), strong token / CJK-bigram overlap (Rule 3), and
cross-language latin/numeric entity overlap (Rule 4, see
[`entity_match.py`](../trendradar/cr/entity_match.py)). This is fully
deterministic and auditable, and it must stay that way as a property — but it
fails two real, observed ways:

1. **Cross-language alignment is brittle.** A Chinese hotlist title and the
   English RSS coverage of the same event only merge when they share a
   discriminative latin/numeric entity *that the dictionary already enumerates*.
   On a real US–Iran event, the only shared entity was `iran` (and `hormuz`),
   both correctly stop-listed as too common — so Rule 4's "≥2 shared, ≥2
   high-specificity" gate produced **zero** cross-source merges, even with the
   dictionary loaded. The Chinese and English coverage emphasized different
   facts (sanctions / MoU vs. oil prices), so there was no *second*
   discriminative bridge. The mechanism is wired and inert on exactly the case
   it was built for.

2. **Within-language fragmentation.** The same Chinese event, phrased
   differently across platforms, splits into several clusters because
   CJK-bigram overlap falls below the Rule 3 threshold. Each fragment is then
   scored alone, and several barely miss the alert line that the merged event
   would have cleared.

Underlying both: Rule 4's cross-language capability is outsourced to a
hand-maintained entity dictionary fed from production miss logs. This is an
**unbounded maintenance treadmill** that always lags newly emerging
names/events.

**Hypothesis.** A multilingual sentence-embedding similarity, used as a
*recall* signal on top of the existing lexical *precision/audit* rules, removes
the dictionary treadmill and handles paraphrase — without surrendering
determinism of the event-identity chain or the auditability the product
depends on.

---

## 1. Goals & non-goals

**Goals**

- Recall cross-language ("same event" across ZH hotlist ↔ EN RSS) and
  paraphrase merges that the lexical rules miss.
- Eliminate the per-entity dictionary-maintenance treadmill as the cross-language
  mechanism.
- Preserve the **deterministic event-identity chain** and **per-merge
  auditability**.
- Stay CPU-only and lean: no GPU at runtime, no heavy dependency added to the
  radar repo's hot path, no closed external service at runtime.

**Non-goals** (consistent with the product boundary in
[`README.md`](../README.md))

- **Not** a replacement of the lexical rules. They remain the precision floor
  and the audit trail.
- **Not** a runtime LLM making same-event or truth judgments. The runtime sees
  a frozen, local, deterministic encoder — not a generative model.
- **Not** a general-purpose model. The artifact is a small, single-purpose
  event-similarity encoder.
- **Not** a fact-checking or "event has occurred" judgment of any kind.

---

## 2. Design constraints

- **Identity-chain determinism is load-bearing.** `event_key` is already
  derived from the normalized title
  ([`event_identity.py`](../trendradar/cr/event_identity.py)) and is **decoupled
  from clustering**. This must remain true: a learned similarity may change
  *which titles group*, but it must never feed the identity key or the cooldown
  state. Cross-hardware float drift may then at most reshuffle a grouping; it
  can never corrupt cooldown / dedup state.
- **Auditability.** Every merge must remain explainable. A cosine threshold is
  not self-explaining, so embedding-driven merges must log provenance (the
  triggering signal and the nearest-neighbor title).
- **Fail-open.** Missing model or missing inference dependency must degrade to
  today's lexical behavior, mirroring the graceful degradation already used when
  the entity dictionary is absent
  ([`entity_match.py`](../trendradar/cr/entity_match.py)).
- **CPU-only CI.** Inference runs in the existing GitHub Actions environment
  (2–4 vCPU, no GPU). Per-run title volume is small (hundreds), so brute-force
  pairwise cosine is acceptable; no ANN index is required.
- **Lean radar repo.** The radar repo must not gain `torch` /
  `sentence-transformers` / training dependencies. Only a thin inference path
  (ONNX runtime + tokenizer) may enter, and only behind the feature flag.

---

## 3. Decision summary

**Direction:** a *hybrid* clusterer. A small, bespoke, **distilled** multilingual
bi-encoder provides a semantic similarity signal used for **recall**; the
existing lexical rules (1–4) are retained as the **precision anchor and audit
layer**. The encoder is built and trained in a **separate repository** and
consumed by the radar as a frozen ONNX artifact behind a default-off flag.

Why bespoke-and-distilled rather than the obvious alternatives:

| Alternative | Why rejected (as the primary path) |
|---|---|
| Tune lexical rules / expand dictionary only | Cannot generalize cross-language without enumerating every entity; the treadmill remains. Addresses symptoms, not structure. |
| Off-the-shelf multilingual encoder, frozen | Viable, and used as the **teacher** (§5). But its notion of "similar" is generic topical similarity, which over-merges same-entity-different-event pairs — the radar's worst failure mode. It also carries a large general vocabulary that wastes the inference budget. |
| Train a student **from scratch** | Cross-lingual alignment needs massive pretraining data we do not have; from-scratch yields a model with no ZH↔EN transfer. |
| Distill from a **closed commercial API** at runtime or for embeddings | Adds an external runtime dependency and a ToS surface. Avoided by construction: the teacher is an **open-weight** model run locally. |

The chosen path — **distill an open-weight multilingual teacher into a small,
vocabulary-pruned student, then contrastively fine-tune the student toward the
"same event" relation** — is the only option that simultaneously gives a small
inference footprint, working cross-lingual transfer, and a decision boundary we
control.

---

## 4. Architecture

Two repositories, with a deliberately thin boundary.

```
PtilopsisRadar (this repo — stays lean)
  __main__ → adapter → build_cr_candidates(config)
                              │
                              ▼
                  _cluster_source_items          ← the single integration point
                    Rule 1 exact title  ┐
                    Rule 2 exact URL     │ existing lexical layer  [KEEP]
                    Rule 3 token overlap │ = precision anchor + audit
                    Rule 4 entity match  ┘
                    Rule 5 embedding sim ≥ θ      ← NEW (recall layer, default-off)
                              │ import/model missing → skip Rule 5, behave as today
                              ▼ lazy import
         ┌──────────────────────────────────────────────┐
         │ ptilopsis-event-encoder (separate repo, thin) │  deps: onnxruntime + tokenizers
         │   embed(titles) → vectors                     │  artifact: model.onnx (~20MB) + tokenizer
         │   same_event_score(a, b) → float              │
         └──────────────────────────────────────────────┘
                              ▲ GitHub Release artifact
  ── training side (separate repo; isolated from radar; torch lives only here) ──
   corpus → labels(out of scope here) → distill(open-weight teacher)
          → contrastive fine-tune → eval(human gold) → export ONNX int8 → Release
```

**Tech-stack layers** (encoder repo, except the last row):

| Layer | Selection | Notes |
|---|---|---|
| Teacher | BGE-M3 / LaBSE (open weight, `sentence-transformers`) | Source of cross-lingual ability; used only during distillation. |
| Student | Small bi-encoder, ~4–6 layers × 256 dim, **pruned vocabulary** (ZH chars + EN news vocab + digits, ~40k) | ~15M params. The embedding table dominates a general small model (e.g. ~96M of E5-small's 118M is its 250k vocab); pruning the vocab is where most of the size win comes from. |
| Training | Stage A distillation (cosine/MSE to teacher embeddings, unlabeled pairs) → Stage B contrastive fine-tune (`MultipleNegativesRankingLoss` + hard negatives, labeled pairs) | Distillation transfers cross-lingual ability cheaply (no labels); contrastive fine-tune bends "topical" similarity into "same-event" similarity (the over-merge control point). A single rented GPU for a few hours suffices. |
| Evaluation | Human-checked gold set (§7) | Baseline to beat = the radar's own lexical `title_similarity` + Rule 4. |
| Packaging | PyTorch → ONNX → onnxruntime int8 | Fixed opset; rounded embeddings → reproducible. |
| Inference | `onnxruntime` (CPU) + `tokenizers` | **No torch.** This is the only thing the radar depends on. |
| Integration (radar) | Lazy-imported thin package; vectors → existing union-find | Per §8. |
| Training data & labels | **Out of scope for this document** | Constructed and versioned in the encoder repo. |

---

## 5. Model

- **Teacher.** An open-weight multilingual sentence encoder (BGE-M3 or LaBSE).
  Used only to produce target embeddings/similarities during distillation. Never
  shipped, never called at runtime.
- **Student.** A small bi-encoder with a pruned, task-specific vocabulary and a
  reduced depth/width, sized so the ONNX int8 artifact is ~20MB and inference of
  a few hundred short titles is sub-second on CI hardware.
- **Stage A — distillation (unlabeled).** Train the student to reproduce the
  teacher's embedding geometry over a large pool of unlabeled title pairs. This
  is where cross-lingual alignment is inherited, without any labels.
- **Stage B — contrastive fine-tune (labeled).** Using a labeled pair set whose
  label definition is the "same event" policy of §6 (the data-construction
  pipeline itself is out of scope here), pull same-event pairs together and push
  hard negatives — *same-entity-different-event* pairs in particular — apart.
  This stage is the lever against over-merging.
- **Export.** PyTorch → ONNX, int8-quantized, with a frozen tokenizer and a
  pinned decision threshold shipped alongside.

---

## 6. "Same event" policy v0

The single source of truth for the label definition, the evaluation gold
standard, and the hard-negative blueprint. **v0 — to be ratified**; verdicts
below are the starting proposal, not final.

| # | Boundary case | Verdict | Rationale |
|---|---|---|---|
| 1 | Same-language paraphrase of one event | SAME | Core merge. |
| 2 | Cross-language coverage of one event (ZH hotlist ↔ EN RSS) | SAME | The target capability. |
| 3 | Same named entity, **different** events (two unrelated Trump stories) | DIFFERENT | Primary hard negative; the over-merge trap. |
| 4 | Same topic, **opposite** outcome (deal reached vs. talks collapse) | DIFFERENT | Topical similarity ≠ same event. |
| 5 | Progress update of one ongoing event (toll 7 → 17) | SAME | Continuity of one event. (Policy choice — flag for review.) |
| 6 | Same event, different facet (casualty count vs. economic impact of one blast) | SAME | One event, multiple angles. |
| 7 | Roundup article mentioning the event among several | DIFFERENT | Must not let a roundup bridge distinct events (mirrors the existing Rule 4 anti-bridging intent). |
| 8 | Entity as subject vs. passing mention | DIFFERENT | Aboutness, not co-occurrence. |
| 9 | Recurring scheduled event, different instance (this week's match vs. last week's) | DIFFERENT | Distinct instances. |
| 10 | Generic category vs. specific instance | DIFFERENT | Different granularity. |

The hard part of this project is pinning these down precisely — the model only
fixes the boundary this policy draws. Cases 5 and 7 are the most consequential
and the most arguable.

---

## 7. Evaluation

- **Gold set.** A few hundred title pairs, **human-checked** against §6. Small
  by design — binary judgments on short titles — and the one place human review
  is non-negotiable, because train/eval labels from the same automated process
  would make accuracy self-confirming.
- **Metrics.**
  - Pairwise precision / recall / F1 at the decision threshold.
  - Clustering quality on held-out runs (B³ / pairwise-F1).
  - **Over-merge (false-merge) rate**, tracked as a first-class metric — it is
    the radar's worst failure mode (it manufactures phantom cross-source
    resonance) and is more dangerous than residual fragmentation.
- **Baseline.** The current lexical clusterer (`title_similarity` + Rule 4),
  measured on the same gold set, so any model must demonstrably beat what we
  already have.
- **Threshold calibration.** θ is chosen on the gold set against the
  precision/over-merge trade-off, not picked a priori.

---

## 8. Integration into PtilopsisRadar

There is exactly **one** integration point, and the entire downstream
(candidate build, `cluster_key`, `candidate_id`, `event_key`, cooldown) is
untouched.

**8.1 The seam.** Add a "Rule 5" to
[`_cluster_source_items`](../trendradar/cr/cluster.py):

1. Once per run, batch-embed all source-item titles (one encoder call).
2. In the existing pairwise loop, after Rules 1–4, add:
   `cosine(i, j) ≥ θ → union(i, j)`.
   Volume is small, so the brute-force O(n²) pass is acceptable.

**8.2 Config.** Extend
[`CRClusterConfig`](../trendradar/cr/models.py) in the existing flag style,
all defaulting to off / no-op:

- `use_embedding_match: bool = False`
- `embedding_threshold: float` — θ for a corroborated merge.
- `embedding_high_threshold: float` — a stricter θ above which an embedding
  merge may fire **alone**; between the two thresholds a corroborating lexical
  signal is required. This is the precision guard against over-merge.
- `embedding_backend = None` — injected encoder; `None` → lexical-only.

**8.3 Hybrid precision guard.** Rule 5 supplies recall; Rules 1–4 remain the
precision anchor. A merge that fires only on embedding similarity in the
`[threshold, high_threshold)` band must be corroborated by a lexical signal
(shared tokens / entity) or be rejected. This keeps the lexical layer as a
brake on the model's generic-similarity over-merges.

**8.4 Fail-open.** The backend is lazy-imported. Missing package or missing
model → Rule 5 is skipped and clustering is **byte-identical to today**. This
matches the existing dictionary-absent degradation in
[`entity_match.py`](../trendradar/cr/entity_match.py).

**8.5 Determinism & identity safety.** `event_key` stays title-derived and is
never fed by the embedding. The worst a nondeterministic embedding can do is
change a grouping; it cannot corrupt cooldown/dedup state. The shipped model is
frozen, θ is fixed, and embeddings are rounded.

**8.6 Audit.** Each merge records which rule fired and, for Rule 5, the
nearest-neighbor title and score — restoring the explanation chain the lexical
rules give for free.

**8.7 Second (optional) seam.** Cross-evidence RSS admission
([`select_cross_evidence_rss`](../trendradar/cr/cross_evidence_ingest.py))
currently admits on entity overlap with the hotlist pool. It can *additionally*
admit on embedding similarity to the pool, improving cross-language recall,
reusing the same backend. Independently flagged; not required for the core
integration.

---

## 9. Determinism & auditability posture

This track introduces a neural component into a layer whose stated value is
determinism and explainability. The reconciliation is explicit:

- **Determinism is preserved where it is load-bearing** (the identity/cooldown
  chain) by construction — `event_key` is title-derived and never sees the
  embedding. Clustering itself tolerates negligible nondeterminism because it
  does not feed identity.
- **Mitigations:** frozen ONNX model pinned by version; fixed opset; int8;
  rounded embedding outputs; fixed θ.
- **Auditability is preserved** by keeping the lexical rules as the primary,
  self-explaining merge path and by logging provenance for every
  embedding-driven merge.

---

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| **Over-merge** (phantom resonance) — worse than fragmentation for a radar | Hybrid precision guard (§8.3); over-merge tracked as a first-class metric (§7); contrastive hard negatives (§5). |
| Threshold miscalibration | θ chosen on the human gold set against the over-merge trade-off, not a priori. |
| Determinism drift across hardware | Identity keys never touch the embedding; frozen model + rounding (§9). |
| Dependency weight in the radar repo | Only `onnxruntime` + tokenizer enter, lazily, behind the flag; torch/training stay in the encoder repo. |
| The maintenance treadmill merely **moves** (dictionary → hard-negative set) | Accepted: the hard-negative set generalizes (unlike per-entity dictionary entries) and is curated against an explicit policy (§6). |
| Low absolute volume → low payoff | Framed as low-frequency / high-unit-value: a single correctly detected cross-source resonance on a suppressed event is the product's reason to exist. Phase gates (§11) let us abandon early if the gold-set lift is not real. |

---

## 11. Phased roadmap

Each phase yields an independently verifiable artifact; only the last touches
the production clusterer, behind a default-off flag.

- **Phase 0 — baseline & policy.** Ratify the §6 policy; build the human gold
  set; measure the **current lexical** clusterer's precision / recall /
  over-merge on it. *Go/no-go: do we even know how much we're missing?* No
  model, no radar change.
- **Phase 1 — teacher ceiling.** In the encoder repo, evaluate the **frozen
  teacher** on the gold set vs. the lexical baseline. *Go/no-go: is the semantic
  lift real?* Does not touch the radar.
- **Phase 2 — student.** Distill + contrastively fine-tune the small student;
  export ONNX; gate the encoder repo's CI on a gold-set regression. *Go/no-go:
  does the student retain the teacher's lift at ~20MB?*
- **Phase 3 — radar integration.** Add Rule 5 behind `use_embedding_match`
  (default off). Run in shadow for several cycles, compare against the lexical
  path, confirm over-merge is controlled, then enable. **Only this phase touches
  [`cluster.py`](../trendradar/cr/cluster.py).**

---

## 12. Open questions

- Teacher selection (BGE-M3 vs. LaBSE vs. an E5 variant) — decided empirically
  in Phase 1.
- Encoder-artifact distribution: a thin pip-installable inference package vs. a
  vendored ONNX file pulled from a GitHub Release in CI.
- Exact threshold policy (single θ vs. the two-threshold guard of §8.3) — tuned
  in Phase 0/3.
- Where per-merge audit provenance is persisted (existing CR audit artifacts vs.
  a new field).
- Whether the optional second seam (§8.7) ships with the core or later.

---

## 13. References

- [`cluster.py`](../trendradar/cr/cluster.py) — the clusterer this design
  extends (Rules 1–4, union-find, candidate build).
- [`entity_match.py`](../trendradar/cr/entity_match.py) — Rule 4 and the
  graceful-degradation pattern Rule 5 mirrors.
- [`event_identity.py`](../trendradar/cr/event_identity.py) — title-derived
  `event_key`; the reason the identity chain is safe.
- [`models.py`](../trendradar/cr/models.py) — `CRClusterConfig`.
- [`cross_evidence_ingest.py`](../trendradar/cr/cross_evidence_ingest.py) — the
  optional second integration seam.
- [`README.md`](../README.md) — product boundary that bounds the non-goals.
