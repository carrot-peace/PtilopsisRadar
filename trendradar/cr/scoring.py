# coding=utf-8
"""
CR deterministic scoring layer.

Implements v0.1 scoring for Growth Raw, Current Heat, and weak
Cross-Evidence.  Does NOT implement decision policy, delivery, or
runtime integration.

Design reference: PR9d.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Union

from trendradar.cr.models import CRCandidate, CRSourceItem
from trendradar.cr.input_health import (
    CRInputHealth,
    collection_coverage_summary,
)

if TYPE_CHECKING:
    from trendradar.core.source_tiers import SourceTierResolver


# ---------------------------------------------------------------------------
# Source identity helper (avoids double-counting source_id + source_name)
# ---------------------------------------------------------------------------


def _source_identity(item: CRSourceItem) -> str:
    """Return a canonical identity string for one source item.

    Each CRSourceItem contributes at most one identity.  Namespace-prefixed
    by source_type so that hotlist and rss sources with the same name
    remain distinct.

    Empty identity (no usable id/name) returns "".
    """
    if item.source_type == "hotlist":
        key = item.source_id or item.source_name or ""
        return f"hotlist:{key}" if key else ""
    if item.source_type == "rss":
        key = item.feed_id or item.source_name or ""
        return f"rss:{key}" if key else ""
    key = item.source_id or item.feed_id or item.source_name or ""
    return f"unknown:{key}" if key else ""


def _distinct_source_count(candidate: CRCandidate) -> int:
    """Count distinct source identities across all source items.

    Uses :func:`_source_identity` so that source_id and source_name
    from the same item are never double-counted.
    """
    identities = {_source_identity(it) for it in candidate.source_items}
    identities.discard("")
    return len(identities)


def _candidate_source_tiers(
    candidate: CRCandidate,
    resolver: "SourceTierResolver | None",
) -> tuple[str, ...]:
    """Resolve distinct known A/B/C/D tiers for a candidate."""
    if resolver is None:
        return ()
    tiers: set[str] = set()
    for item in candidate.source_items:
        source_key = (
            item.feed_id
            if item.source_type == "rss"
            else item.source_id
        ) or item.source_name
        tier = resolver.tier_of(source_key or "")
        if tier == "unknown" and item.source_name != source_key:
            tier = resolver.tier_of(item.source_name)
        if tier in {"A", "B", "C", "D"}:
            tiers.add(tier)
    return tuple(sorted(tiers))


def _tier_evidence_strength(tiers: tuple[str, ...]) -> str:
    """Classify known tier breadth as weak, moderate, or strong."""
    tier_set = set(tiers)
    if (
        tier_set & {"A", "B"}
        and tier_set & {"C", "D"}
    ) or len(tier_set) >= 3:
        return "strong"
    if len(tier_set) >= 2:
        return "moderate"
    return "weak"


def _compute_evidence_multiplier(
    candidate: CRCandidate,
    profile: CRScoringProfile,
) -> tuple[float, str]:
    """Compute the B2-lite evidence multiplier for a candidate.

    Returns (multiplier, reason).  The multiplier modulates ``heat_score``
    so that cross-source / cross-platform evidence raises the final score
    while single-source-only events are gently dampened.

    Rules:
      - hotlist+RSS co-occurrence OR >= 3 distinct sources → strong (1.10)
      - >= 2 distinct sources → moderate (1.00)
      - otherwise → single (0.88)
    """
    tiers = _candidate_source_tiers(
        candidate, profile.source_tier_resolver
    )
    if tiers:
        strength = _tier_evidence_strength(tiers)
        tier_label = ",".join(tiers)
        if strength == "strong":
            return (
                profile.evidence_multiplier_strong,
                f"strong_cross_tier_evidence:{tier_label}",
            )
        if strength == "moderate":
            return (
                profile.evidence_multiplier_moderate,
                f"moderate_cross_tier_evidence:{tier_label}",
            )
        return (
            profile.evidence_multiplier_single,
            f"same_tier_echo:{tier_label}",
        )

    distinct_sources = _distinct_source_count(candidate)
    has_hotlist_rss = bool(candidate.has_hotlist and candidate.has_rss)

    if has_hotlist_rss or distinct_sources >= 3:
        return profile.evidence_multiplier_strong, "strong_cross_evidence"
    if distinct_sources >= 2:
        return profile.evidence_multiplier_moderate, "moderate_cross_evidence"
    return profile.evidence_multiplier_single, "single_source_no_cross_evidence"


# ---------------------------------------------------------------------------
# Scoring Profile
# ---------------------------------------------------------------------------


LEGACY_CR_SCORING_PROFILE_VERSION = "cr-score-v1.1"
TIERED_CR_SCORING_PROFILE_VERSION = "cr-score-v1.2-tiered"


@dataclass(frozen=True)
class CRScoringProfile:
    """Scoring profile with caps and thresholds.

    This is a function-parameter default only; it does NOT connect to
    the project runtime config (config.yaml).
    """

    profile_version: str = LEGACY_CR_SCORING_PROFILE_VERSION

    alert_threshold: float = 60.0
    urgent_threshold: float = 80.0

    heat_cap: float = 80.0
    cross_evidence_cap: float = 20.0
    total_cap: float = 100.0

    growth_raw_cap: float = 60.0
    current_heat_raw_cap: float = 50.0

    cross_layer_raw_cap: float = 15.0
    background_support_raw_cap: float = 10.0

    background_support_enabled: bool = False

    # --- B2-lite evidence multiplier (v1.1) ---
    evidence_multiplier_enabled: bool = True
    evidence_multiplier_single: float = 0.88
    evidence_multiplier_moderate: float = 1.00
    evidence_multiplier_strong: float = 1.10
    cross_evidence_bonus_factor: float = 0.25
    cross_evidence_bonus_cap: float = 5.0

    # --- ABCD source-tier evidence (falls back to legacy when unset) ---
    source_tier_resolver: "SourceTierResolver | None" = None

    # --- Collection coverage correction (opt-in) ---
    coverage_penalty_enabled: bool = False
    coverage_penalty_threshold: float = 0.67
    coverage_penalty_factor: float = 0.85


DEFAULT_CR_SCORING_PROFILE = CRScoringProfile()


# ---------------------------------------------------------------------------
# Score Models
# ---------------------------------------------------------------------------


@dataclass
class CRComponentScore:
    """Score for a single scoring component."""

    name: str
    raw_score: float = 0.0
    capped_score: float = 0.0
    cap: float = 0.0
    reasons: list[str] = field(default_factory=list)
    debug: dict[str, object] = field(default_factory=dict)


@dataclass
class CRScoreResult:
    """Aggregated score result for a CR candidate."""

    candidate_id: str
    cluster_key: str
    profile_version: str

    growth_raw: CRComponentScore = field(
        default_factory=lambda: CRComponentScore(name="growth_raw")
    )
    current_heat_raw: CRComponentScore = field(
        default_factory=lambda: CRComponentScore(name="current_heat_raw")
    )
    heat: CRComponentScore = field(
        default_factory=lambda: CRComponentScore(name="heat")
    )

    cross_layer_raw: CRComponentScore = field(
        default_factory=lambda: CRComponentScore(name="cross_layer_raw")
    )
    background_support_raw: CRComponentScore = field(
        default_factory=lambda: CRComponentScore(name="background_support_raw")
    )
    cross_evidence: CRComponentScore = field(
        default_factory=lambda: CRComponentScore(name="cross_evidence")
    )

    total_score: float = 0.0
    trigger_reasons: list[str] = field(default_factory=list)
    coverage_warning: str | None = None
    debug: dict[str, object] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Utility Helpers
# ---------------------------------------------------------------------------


def clamp_score(value: float, cap: float) -> float:
    """Clamp *value* to [0, cap].

    Rules:
      negative → 0
      over cap → cap
      normal → unchanged
      NaN / inf / -inf → raise ValueError
    """
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"Non-finite score value: {value}")
    if value < 0:
        return 0.0
    if value > cap:
        return cap
    return value


def make_component_score(
    name: str,
    raw_score: float,
    cap: float,
    *,
    reasons: list[str] | None = None,
    debug: dict[str, object] | None = None,
) -> CRComponentScore:
    """Build a CRComponentScore with clamping applied.

    Copies *reasons* and *debug* to avoid mutable-default leakage.
    """
    capped = clamp_score(raw_score, cap)
    return CRComponentScore(
        name=name,
        raw_score=raw_score,
        capped_score=capped,
        cap=cap,
        reasons=list(reasons) if reasons else [],
        debug=dict(debug) if debug else {},
    )


# ---------------------------------------------------------------------------
# Growth Raw v0.1  (item-level helpers)
# ---------------------------------------------------------------------------


def _score_item_rank_movement(item: CRSourceItem) -> tuple[float, dict[str, object]]:
    """Score rank movement for a single source item.

    Returns (score, debug_dict).  Score range: 0–30.
    """
    debug: dict[str, object] = {"rule": "none", "score": 0.0}

    # Gate: hotlist with reliable timeline and current_rank.
    if item.source_type != "hotlist":
        return 0.0, debug
    if not item.has_reliable_rank_timeline:
        return 0.0, debug
    if item.current_rank is None:
        return 0.0, debug

    rank = item.current_rank

    def _entry_bucket(r: int) -> float:
        if r <= 3:
            return 30.0
        if r <= 10:
            return 27.0
        if r <= 20:
            return 23.0
        if r <= 50:
            return 15.0
        if r <= 100:
            return 8.0
        return 3.0

    # --- First-ever entry ---
    if not item.previous_observation_exists:
        score = _entry_bucket(rank)
        # Single-observation decay.
        if item.visible_observation_count <= 1 and item.count is not None and item.count <= 1:
            score *= 0.7
        debug = {"rule": "first_entry", "rank": rank, "base": _entry_bucket(rank), "score": score}
        return score, debug

    # --- Re-entry ---
    if not item.previous_observation_visible:
        score = _entry_bucket(rank)
        debug = {"rule": "re_entry", "rank": rank, "score": score}
        return score, debug

    # --- Rank improvement ---
    if (
        item.previous_visible_rank is not None
        and item.rank_delta is not None
        and item.rank_delta > 0
    ):
        delta = item.rank_delta
        score = 0.0
        if delta >= 50 and rank <= 20:
            score = 28.0
        elif delta >= 30 and rank <= 20:
            score = 25.0
        elif delta >= 20:
            score = 21.0
        elif delta >= 10:
            score = 15.0
        elif delta >= 5:
            score = 9.0

        # Visibility gate.
        if rank > 100:
            score = min(score, 6.0)
        elif rank > 50:
            score = min(score, 12.0)

        debug = {"rule": "rank_improvement", "delta": delta, "rank": rank, "score": score}
        return score, debug

    # --- Stable high rank ---
    if rank <= 10:
        debug = {"rule": "stable_top10", "rank": rank, "score": 3.0}
        return 3.0, debug
    if rank <= 20:
        debug = {"rule": "stable_top20", "rank": rank, "score": 2.0}
        return 2.0, debug

    debug = {"rule": "stable_below_top20", "rank": rank, "score": 0.0}
    return 0.0, debug


def _score_item_new_burst(item: CRSourceItem, single_source: bool) -> tuple[float, dict[str, object]]:
    """Score new-burst for a single source item.

    Returns (score, debug_dict).  Score range: 0–15.
    """
    debug: dict[str, object] = {"rule": "none", "score": 0.0}

    # Gate.
    if item.source_type != "hotlist":
        return 0.0, debug
    if item.first_crawl_of_day is True:
        return 0.0, debug
    if item.is_new is not True:
        return 0.0, debug
    if item.is_new_semantics != "new_titles_detection":
        return 0.0, debug
    if item.current_rank is None:
        return 0.0, debug

    rank = item.current_rank

    if rank <= 3:
        score = 13.0
    elif rank <= 10:
        score = 12.0
    elif rank <= 20:
        score = 10.0
    elif rank <= 50:
        score = 7.0
    elif rank <= 100:
        score = 4.0
    else:
        score = 2.0

    # Low-base dampening.
    dampened = False
    if single_source and rank > 100:
        score *= 0.65
        dampened = True
    elif single_source and rank > 50:
        score *= 0.8
        dampened = True

    debug = {
        "rule": "new_burst",
        "rank": rank,
        "single_source": single_source,
        "dampened": dampened,
        "score": score,
    }
    return score, debug


def _score_item_recency_momentum(item: CRSourceItem) -> tuple[float, dict[str, object]]:
    """Score recency momentum for a single source item.

    Returns (score, debug_dict).  Score range: 0–10 (or 0–3 if synthetic).
    """
    debug: dict[str, object] = {"rule": "none", "score": 0.0}

    if not item.has_time_signals:
        debug = {"rule": "no_time_signals", "score": 0.0}
        return 0.0, debug

    synthetic_cap = 3.0 if item.time_signals_synthetic else 10.0

    score = 0.0
    rule = "none"

    if item.is_new is True and not item.first_crawl_of_day:
        score = 8.0
        rule = "new_not_first_crawl"
    elif item.first_time and item.last_time:
        score = 4.0
        rule = "both_times"
    elif item.first_time or item.last_time:
        score = 2.0
        rule = "one_time"

    score = min(score, synthetic_cap)

    debug = {
        "rule": rule,
        "time_signals_synthetic": item.time_signals_synthetic,
        "run_time_inferred": item.run_time_inferred,
        "synthetic_cap": synthetic_cap,
        "score": score,
    }
    return score, debug


def _score_item_weak_persistence(item: CRSourceItem) -> tuple[float, dict[str, object]]:
    """Score weak persistence for a single source item.

    Returns (score, debug_dict).  Score range: 0–5.
    """
    debug: dict[str, object] = {"rule": "none", "score": 0.0}

    # Gate: currently visible hotlist item.
    if item.source_type != "hotlist":
        return 0.0, debug
    if item.current_rank is None:
        return 0.0, debug

    rank = item.current_rank

    # With reliable timeline.
    if item.has_reliable_rank_timeline:
        voc = item.visible_observation_count
        score = 0.0
        if voc >= 3 and rank <= 20:
            score = 5.0
        elif voc >= 3 and rank <= 50:
            score = 4.0
        elif voc >= 2 and rank <= 50:
            score = 3.0
        elif voc >= 2 and rank <= 100:
            score = 2.0
        debug = {
            "rule": "timeline",
            "visible_observation_count": voc,
            "rank": rank,
            "score": score,
        }
        return score, debug

    # Count fallback.
    if item.has_count and item.count is not None:
        count = item.count
        score = 0.0
        if count >= 5:
            score = 3.0
        elif count >= 3:
            score = 2.0
        elif count >= 2:
            score = 1.0
        # Count fallback cap = 3 (already enforced by max score 3).
        debug = {"rule": "count_fallback", "count": count, "rank": rank, "score": score}
        return score, debug

    debug = {"rule": "no_data", "score": 0.0}
    return 0.0, debug


# ---------------------------------------------------------------------------
# Growth Raw v0.1  (candidate-level aggregation)
# ---------------------------------------------------------------------------


def score_growth_raw(
    candidate: CRCandidate,
    *,
    profile: CRScoringProfile | None = None,
) -> CRComponentScore:
    """Score Growth Raw for a candidate.

    Aggregation: max across items for each sub-component, then sum.
    Range: 0–profile.growth_raw_cap (default 60).
    """
    if profile is None:
        profile = DEFAULT_CR_SCORING_PROFILE

    items = candidate.source_items
    single_source = len(candidate.source_names) <= 1 and len(candidate.source_items) == 1

    # Compute per-item scores.
    _zero_debug: dict[str, object] = {"rule": "none", "score": 0.0}
    best_rm: tuple[float, dict, CRSourceItem | None] = (0.0, _zero_debug, None)
    best_nb: tuple[float, dict, CRSourceItem | None] = (0.0, _zero_debug, None)
    best_rec: tuple[float, dict, CRSourceItem | None] = (0.0, _zero_debug, None)
    best_wp: tuple[float, dict, CRSourceItem | None] = (0.0, _zero_debug, None)

    for item in items:
        rm_s, rm_d = _score_item_rank_movement(item)
        if rm_s > best_rm[0]:
            best_rm = (rm_s, rm_d, item)

        nb_s, nb_d = _score_item_new_burst(item, single_source)
        if nb_s > best_nb[0]:
            best_nb = (nb_s, nb_d, item)

        rec_s, rec_d = _score_item_recency_momentum(item)
        if rec_s > best_rec[0]:
            best_rec = (rec_s, rec_d, item)

        wp_s, wp_d = _score_item_weak_persistence(item)
        if wp_s > best_wp[0]:
            best_wp = (wp_s, wp_d, item)

    def _item_label(item: CRSourceItem | None) -> dict[str, object]:
        if item is None:
            return {}
        return {
            "title": item.title,
            "source_name": item.source_name,
            "source_id": item.source_id,
        }

    raw = best_rm[0] + best_nb[0] + best_rec[0] + best_wp[0]

    debug = {
        "rank_movement": {**best_rm[1], "max_item": _item_label(best_rm[2])},
        "new_burst": {**best_nb[1], "max_item": _item_label(best_nb[2])},
        "recency_momentum": {**best_rec[1], "max_item": _item_label(best_rec[2])},
        "weak_persistence": {**best_wp[1], "max_item": _item_label(best_wp[2])},
    }

    reasons: list[str] = []
    if best_rm[0] > 0:
        reasons.append(f"rank_movement={best_rm[0]:.1f}")
    if best_nb[0] > 0:
        reasons.append(f"new_burst={best_nb[0]:.1f}")
    if best_rec[0] > 0:
        reasons.append(f"recency_momentum={best_rec[0]:.1f}")
    if best_wp[0] > 0:
        reasons.append(f"weak_persistence={best_wp[0]:.1f}")

    return make_component_score(
        "growth_raw",
        raw,
        profile.growth_raw_cap,
        reasons=reasons,
        debug=debug,
    )


# ---------------------------------------------------------------------------
# Current Heat v0.1
# ---------------------------------------------------------------------------


def score_current_heat_raw(
    candidate: CRCandidate,
    *,
    profile: CRScoringProfile | None = None,
) -> CRComponentScore:
    """Score Current Heat Raw for a candidate.

    Sub-components:
      - Best Rank Heat: 0–30
      - Source Coverage Heat: 0–12
      - Item Count Heat: 0–8
    Range: 0–profile.current_heat_raw_cap (default 50).
    """
    if profile is None:
        profile = DEFAULT_CR_SCORING_PROFILE

    reasons: list[str] = []
    debug: dict[str, object] = {}

    # --- Best Rank Heat (0-30) ---
    best_rank = candidate.best_current_rank
    if best_rank is None:
        best_rank = candidate.best_normalized_rank

    if best_rank is not None:
        if best_rank <= 3:
            rank_heat = 30.0
        elif best_rank <= 10:
            rank_heat = 26.0
        elif best_rank <= 20:
            rank_heat = 22.0
        elif best_rank <= 50:
            rank_heat = 16.0
        elif best_rank <= 100:
            rank_heat = 10.0
        else:
            rank_heat = 4.0
        reasons.append(f"best_rank_heat={rank_heat:.0f}(rank={best_rank})")
    else:
        rank_heat = 0.0
        reasons.append("best_rank_heat=0(no_rank)")

    debug["best_rank_heat"] = {
        "best_current_rank": candidate.best_current_rank,
        "best_normalized_rank": candidate.best_normalized_rank,
        "used_rank": best_rank,
        "score": rank_heat,
    }

    # --- Source Coverage Heat (0-12) ---
    coverage_count = _distinct_source_count(candidate)
    if coverage_count >= 4:
        coverage_heat = 12.0
    elif coverage_count == 3:
        coverage_heat = 8.0
    elif coverage_count == 2:
        coverage_heat = 5.0
    elif coverage_count >= 1:
        coverage_heat = 2.0
    else:
        coverage_heat = 0.0

    reasons.append(f"source_coverage_heat={coverage_heat:.0f}(n={coverage_count})")
    debug["source_coverage_heat"] = {
        "coverage_count": coverage_count,
        "score": coverage_heat,
    }

    # --- Item Count Heat (0-8) ---
    item_count = len(candidate.source_items)
    if item_count >= 4:
        item_heat = 8.0
    elif item_count == 3:
        item_heat = 5.0
    elif item_count == 2:
        item_heat = 3.0
    elif item_count >= 1:
        item_heat = 1.0
    else:
        item_heat = 0.0

    reasons.append(f"item_count_heat={item_heat:.0f}(n={item_count})")
    debug["item_count_heat"] = {
        "item_count": item_count,
        "score": item_heat,
    }

    raw = rank_heat + coverage_heat + item_heat
    debug["raw_total"] = raw

    return make_component_score(
        "current_heat_raw",
        raw,
        profile.current_heat_raw_cap,
        reasons=reasons,
        debug=debug,
    )


# ---------------------------------------------------------------------------
# Cross-Layer Raw v0.1
# ---------------------------------------------------------------------------


def score_cross_layer_raw(
    candidate: CRCandidate,
    *,
    profile: CRScoringProfile | None = None,
) -> CRComponentScore:
    """Score Cross-Layer Raw for a candidate.

    With a source-tier resolver, sub-components use distinct A/B/C/D tiers.
    Without one, the legacy hotlist/RSS format proxy remains as fallback.
    Range: 0–profile.cross_layer_raw_cap (default 15).
    """
    if profile is None:
        profile = DEFAULT_CR_SCORING_PROFILE

    reasons: list[str] = []
    debug: dict[str, object] = {}

    tiers = _candidate_source_tiers(
        candidate, profile.source_tier_resolver
    )
    if tiers:
        strength = _tier_evidence_strength(tiers)
        tier_count = len(tiers)
        co_score = 7.0 if strength == "strong" else (
            4.0 if strength == "moderate" else 0.0
        )
        diversity_score = 4.0 if tier_count >= 2 else 0.0
        if tier_count >= 4:
            count_support = 4.0
        elif tier_count == 3:
            count_support = 2.0
        elif tier_count == 2:
            count_support = 1.0
        else:
            count_support = 0.0
        reasons.append(
            f"tier_corroboration={co_score:.0f}"
            f"(strength={strength},tiers={','.join(tiers)})"
        )
        reasons.append(
            f"tier_diversity={diversity_score:.0f}(n={tier_count})"
        )
        reasons.append(
            f"tier_count_support={count_support:.0f}(n={tier_count})"
        )
        debug["tier_evidence"] = {
            "tiers": list(tiers),
            "strength": strength,
            "corroboration_score": co_score,
            "diversity_score": diversity_score,
            "count_support": count_support,
        }
    else:
        # Legacy format-based fallback for callers without tier configuration.
        if candidate.has_hotlist and candidate.has_rss:
            co_score = 7.0
            reasons.append("hotlist_rss_cooccurrence=7")
        else:
            co_score = 0.0
        debug["hotlist_rss_cooccurrence"] = co_score

        pst = candidate.primary_source_type
        if pst == "mixed":
            diversity_score = 4.0
            reasons.append("source_diversity=4(mixed)")
        elif pst in ("hotlist", "rss"):
            diversity_score = 1.0
            reasons.append(f"source_diversity=1({pst})")
        else:
            diversity_score = 0.0
        debug["source_type_diversity"] = {
            "primary": pst,
            "score": diversity_score,
        }

        coverage_count = _distinct_source_count(candidate)
        if coverage_count >= 4:
            count_support = 4.0
        elif coverage_count == 3:
            count_support = 2.0
        elif coverage_count == 2:
            count_support = 1.0
        else:
            count_support = 0.0

        reasons.append(
            f"source_count_support={count_support:.0f}(n={coverage_count})"
        )
        debug["source_count_support"] = {
            "coverage_count": coverage_count,
            "score": count_support,
        }

    raw = co_score + diversity_score + count_support
    debug["raw_total"] = raw

    return make_component_score(
        "cross_layer_raw",
        raw,
        profile.cross_layer_raw_cap,
        reasons=reasons,
        debug=debug,
    )


# ---------------------------------------------------------------------------
# Score Combination
# ---------------------------------------------------------------------------


def _to_component_score(
    value: Union[CRComponentScore, float, None],
    name: str,
    cap: float,
) -> CRComponentScore:
    """Convert a float or None to a CRComponentScore, or return as-is."""
    if value is None:
        return CRComponentScore(name=name, cap=cap)
    if isinstance(value, (int, float)):
        return make_component_score(name, float(value), cap)
    return value


def combine_cr_scores(
    candidate: CRCandidate,
    *,
    profile: CRScoringProfile | None = None,
    growth_raw: CRComponentScore | float | None = None,
    current_heat_raw: CRComponentScore | float | None = None,
    cross_layer_raw: CRComponentScore | float | None = None,
    background_support_raw: CRComponentScore | float | None = None,
    trigger_reasons: list[str] | None = None,
    debug: dict[str, object] | None = None,
    input_health: CRInputHealth | None = None,
) -> CRScoreResult:
    """Combine component scores into a final CRScoreResult.

    Combination rules:
      heat = clamp(growth_raw + current_heat_raw, heat_cap)
      cross_evidence = clamp(cross_layer_raw + background_support_raw, cross_evidence_cap)
      total = clamp(heat + cross_evidence, total_cap)
    """
    if profile is None:
        profile = DEFAULT_CR_SCORING_PROFILE

    growth_raw_cs = _to_component_score(growth_raw, "growth_raw", profile.growth_raw_cap)
    current_heat_raw_cs = _to_component_score(current_heat_raw, "current_heat_raw", profile.current_heat_raw_cap)
    cross_layer_raw_cs = _to_component_score(cross_layer_raw, "cross_layer_raw", profile.cross_layer_raw_cap)

    # Background support: disabled → zero.
    if profile.background_support_enabled:
        bg_cs = _to_component_score(background_support_raw, "background_support_raw", profile.background_support_raw_cap)
    else:
        bg_cs = CRComponentScore(name="background_support_raw", cap=profile.background_support_raw_cap)

    # Heat combination.
    heat_raw = growth_raw_cs.capped_score + current_heat_raw_cs.capped_score
    heat_cs = make_component_score("heat", heat_raw, profile.heat_cap)

    # Cross-evidence combination.
    cross_ev_raw = cross_layer_raw_cs.capped_score + bg_cs.capped_score
    cross_ev_cs = make_component_score("cross_evidence", cross_ev_raw, profile.cross_evidence_cap)

    # Total — B2-lite or legacy.
    heat_score = heat_cs.capped_score
    cross_evidence_score = cross_ev_cs.capped_score

    coverage = (
        collection_coverage_summary(input_health)
        if input_health is not None
        else None
    )
    coverage_ratio = coverage["ratio"] if coverage is not None else None
    penalty_applied = bool(
        profile.coverage_penalty_enabled
        and coverage_ratio is not None
        and coverage_ratio < profile.coverage_penalty_threshold
    )
    penalty_factor = (
        max(0.0, min(1.0, profile.coverage_penalty_factor))
        if penalty_applied
        else 1.0
    )
    if penalty_applied:
        heat_score *= penalty_factor
        cross_evidence_score *= penalty_factor
        heat_cs.capped_score = heat_score
        cross_ev_cs.capped_score = cross_evidence_score
        heat_cs.reasons.append(
            f"collection_coverage_penalty={penalty_factor:.2f}"
        )
        cross_ev_cs.reasons.append(
            f"collection_coverage_penalty={penalty_factor:.2f}"
        )

    coverage_debug = {
        "collection_coverage": coverage_ratio,
        "configured_sources": coverage["configured"] if coverage else 0,
        "successful_sources": coverage["successful"] if coverage else 0,
        "failed_sources": coverage["failed"] if coverage else 0,
        "penalty_enabled": profile.coverage_penalty_enabled,
        "penalty_threshold": profile.coverage_penalty_threshold,
        "penalty_factor": penalty_factor,
        "penalty_applied": penalty_applied,
    }
    heat_cs.debug["collection_coverage"] = coverage_debug
    cross_ev_cs.debug["collection_coverage"] = coverage_debug

    if profile.evidence_multiplier_enabled:
        # B2-lite: heat × multiplier + small cross-evidence bonus.
        multiplier, multiplier_reason = _compute_evidence_multiplier(candidate, profile)
        small_cross_bonus = min(
            cross_evidence_score * profile.cross_evidence_bonus_factor,
            profile.cross_evidence_bonus_cap,
        )
        total_raw = heat_score * multiplier + small_cross_bonus
        total_score = clamp_score(total_raw, profile.total_cap)
    else:
        # Legacy: heat + cross_evidence (additive).
        multiplier = 1.0
        multiplier_reason = "disabled"
        small_cross_bonus = 0.0
        total_raw = heat_score + cross_evidence_score
        total_score = clamp_score(total_raw, profile.total_cap)

    # Merge trigger_reasons: component reasons + explicit, deduplicated, deterministic order.
    all_reasons: list[str] = []
    seen: set[str] = set()
    for src in [
        growth_raw_cs.reasons,
        current_heat_raw_cs.reasons,
        cross_layer_raw_cs.reasons,
        bg_cs.reasons,
        trigger_reasons or [],
    ]:
        for r in src:
            if r not in seen:
                seen.add(r)
                all_reasons.append(r)

    # Debug: evidence multiplier observability.
    source_tiers = _candidate_source_tiers(
        candidate, profile.source_tier_resolver
    )
    evidence_multiplier_debug: dict[str, object] = {
        "enabled": profile.evidence_multiplier_enabled,
        "multiplier": multiplier,
        "reason": multiplier_reason,
        "heat_score": heat_score,
        "cross_evidence_score": cross_evidence_score,
        "small_cross_bonus": small_cross_bonus,
        "cross_evidence_bonus_factor": profile.cross_evidence_bonus_factor,
        "cross_evidence_bonus_cap": profile.cross_evidence_bonus_cap,
        "adjusted_total_score": total_score,
        "source_tiers": list(source_tiers),
        "basis": (
            "source_tiers"
            if source_tiers
            else "legacy_source_format"
        ),
    }
    if profile.evidence_multiplier_enabled:
        evidence_multiplier_debug["legacy_total_score"] = clamp_score(
            heat_score + cross_evidence_score, profile.total_cap,
        )

    merged_debug: dict[str, object] = {
        "profile_version": profile.profile_version,
        "heat_raw": heat_raw,
        "cross_evidence_raw": cross_ev_raw,
        "total_raw": total_raw,
        "evidence_multiplier": evidence_multiplier_debug,
        "collection_coverage": coverage_debug,
    }
    if debug:
        merged_debug.update(debug)

    return CRScoreResult(
        candidate_id=candidate.candidate_id,
        cluster_key=candidate.cluster_key,
        profile_version=profile.profile_version,
        growth_raw=growth_raw_cs,
        current_heat_raw=current_heat_raw_cs,
        heat=heat_cs,
        cross_layer_raw=cross_layer_raw_cs,
        background_support_raw=bg_cs,
        cross_evidence=cross_ev_cs,
        total_score=total_score,
        trigger_reasons=all_reasons,
        coverage_warning=(coverage["warning"] if coverage else None),
        debug=merged_debug,
    )


# ---------------------------------------------------------------------------
# Top-level scoring entry point
# ---------------------------------------------------------------------------


def score_cr_candidate(
    candidate: CRCandidate,
    *,
    profile: CRScoringProfile | None = None,
    input_health: CRInputHealth | None = None,
) -> CRScoreResult:
    """Score a single CRCandidate using v0.1 deterministic scoring.

    Returns a CRScoreResult with all component scores and total.
    Does NOT make any decision (no alert/urgent/suppress/watch).
    """
    if profile is None:
        profile = DEFAULT_CR_SCORING_PROFILE

    growth = score_growth_raw(candidate, profile=profile)
    current_heat = score_current_heat_raw(candidate, profile=profile)
    cross_layer = score_cross_layer_raw(candidate, profile=profile)

    return combine_cr_scores(
        candidate,
        profile=profile,
        growth_raw=growth,
        current_heat_raw=current_heat,
        cross_layer_raw=cross_layer,
        input_health=input_health,
        debug={
            "candidate_id": candidate.candidate_id,
            "profile_version": profile.profile_version,
        },
    )
