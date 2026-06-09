# coding=utf-8
"""
CR deterministic decision layer.

Maps a CRScoreResult to a CRDecision (suppress / watch / alert / urgent)
using a CRDecisionPolicy.  Purely internal — does NOT implement delivery,
Telegram, report, archive, cooldown, dedupe, alert_state, or quiet-hour
runtime.

Design reference: PR9e.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

from trendradar.cr.scoring import CRScoreResult


# ---------------------------------------------------------------------------
# Decision level type + constants
# ---------------------------------------------------------------------------

CRDecisionLevel = Literal["suppress", "watch", "alert", "urgent"]

DECISION_SUPPRESS: CRDecisionLevel = "suppress"
DECISION_WATCH: CRDecisionLevel = "watch"
DECISION_ALERT: CRDecisionLevel = "alert"
DECISION_URGENT: CRDecisionLevel = "urgent"


# ---------------------------------------------------------------------------
# Decision Policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CRDecisionPolicy:
    """Policy that governs how scores map to decision levels and push flags.

    This is a function-parameter default only; it does NOT connect to
    the project runtime config (config.yaml).
    """

    policy_version: str = "cr-decision-v0.1"

    alert_threshold: float = 60.0
    urgent_threshold: float = 80.0

    suppress_overrides_all: bool = True

    alert_push_eligible: bool = True
    urgent_push_eligible: bool = True
    urgent_bypasses_quiet: bool = True

    watch_push_eligible: bool = False
    suppress_push_eligible: bool = False


DEFAULT_CR_DECISION_POLICY = CRDecisionPolicy()


# ---------------------------------------------------------------------------
# Decision result
# ---------------------------------------------------------------------------


@dataclass
class CRDecision:
    """Decision output for one CR candidate.

    Carries level, push flags, and provenance.  Does NOT carry any
    delivery / runtime mutation fields (sent, delivered, telegram_message_id,
    cooldown_applied, dedupe_applied, archived).
    """

    candidate_id: str
    cluster_key: str
    profile_version: str
    policy_version: str

    level: CRDecisionLevel = DECISION_WATCH
    total_score: float = 0.0

    push_eligible: bool = False
    bypasses_quiet: bool = False

    suppress_labels: list[str] = field(default_factory=list)
    trigger_reasons: list[str] = field(default_factory=list)

    score_result: CRScoreResult | None = None

    debug: dict[str, object] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Single-candidate decision
# ---------------------------------------------------------------------------


def apply_cr_decision(
    score_result: CRScoreResult,
    *,
    policy: CRDecisionPolicy | None = None,
    suppress_labels: list[str] | None = None,
) -> CRDecision:
    """Map a CRScoreResult to a CRDecision.

    Rules:
      1. If suppress_labels exist and policy.suppress_overrides_all → suppress.
      2. total_score >= urgent_threshold → urgent.
      3. total_score >= alert_threshold → alert.
      4. Otherwise → watch.

    Push flags are set from policy according to the resolved level.
    """
    if policy is None:
        policy = DEFAULT_CR_DECISION_POLICY

    labels = list(suppress_labels) if suppress_labels else []

    # --- Level ---
    if labels and policy.suppress_overrides_all:
        level: CRDecisionLevel = DECISION_SUPPRESS
    elif score_result.total_score >= policy.urgent_threshold:
        level = DECISION_URGENT
    elif score_result.total_score >= policy.alert_threshold:
        level = DECISION_ALERT
    else:
        level = DECISION_WATCH

    # --- Push flags ---
    if level == DECISION_SUPPRESS:
        push_eligible = False
        bypasses_quiet = False
    elif level == DECISION_WATCH:
        push_eligible = policy.watch_push_eligible
        bypasses_quiet = False
    elif level == DECISION_ALERT:
        push_eligible = policy.alert_push_eligible
        bypasses_quiet = False
    else:  # urgent
        push_eligible = policy.urgent_push_eligible
        bypasses_quiet = policy.urgent_bypasses_quiet

    # --- Trigger reasons: copy from score_result, add suppress reason, dedup ---
    reasons: list[str] = []
    seen: set[str] = set()
    for r in score_result.trigger_reasons:
        if r not in seen:
            seen.add(r)
            reasons.append(r)
    if labels:
        suppress_reason = "suppress_label"
        if suppress_reason not in seen:
            seen.add(suppress_reason)
            reasons.append(suppress_reason)

    # --- Debug ---
    debug: dict[str, object] = {
        "alert_threshold": policy.alert_threshold,
        "urgent_threshold": policy.urgent_threshold,
        "suppress_overrides_all": policy.suppress_overrides_all,
    }

    return CRDecision(
        candidate_id=score_result.candidate_id,
        cluster_key=score_result.cluster_key,
        profile_version=score_result.profile_version,
        policy_version=policy.policy_version,
        level=level,
        total_score=score_result.total_score,
        push_eligible=push_eligible,
        bypasses_quiet=bypasses_quiet,
        suppress_labels=labels,
        trigger_reasons=reasons,
        score_result=score_result,
        debug=debug,
    )


# ---------------------------------------------------------------------------
# Batch helper
# ---------------------------------------------------------------------------


def decide_cr_candidates(
    score_results: list[CRScoreResult],
    *,
    policy: CRDecisionPolicy | None = None,
    suppress_labels_by_candidate_id: dict[str, list[str]] | None = None,
) -> list[CRDecision]:
    """Apply decision policy to a batch of score results.

    Preserves input order.  Does NOT sort, filter, or mutate.
    """
    if suppress_labels_by_candidate_id is None:
        suppress_labels_by_candidate_id = {}

    decisions: list[CRDecision] = []
    for sr in score_results:
        labels = suppress_labels_by_candidate_id.get(sr.candidate_id)
        decisions.append(
            apply_cr_decision(sr, policy=policy, suppress_labels=labels)
        )
    return decisions


# ---------------------------------------------------------------------------
# Observability helper
# ---------------------------------------------------------------------------


def count_high_score_suppressed(
    decisions: list[CRDecision],
    *,
    urgent_threshold: float = 80.0,
) -> int:
    """Count suppressed decisions whose total_score >= urgent_threshold.

    Useful for observability (e.g. HTML/Markdown "suppressed high-score"
    counter).  Does NOT generate any presentation output.
    """
    count = 0
    for d in decisions:
        if d.level == DECISION_SUPPRESS and d.total_score >= urgent_threshold:
            count += 1
    return count
