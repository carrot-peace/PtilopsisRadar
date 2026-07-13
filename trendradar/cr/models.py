# coding=utf-8
"""
CR primitive data models.

These are adapter-level representations of existing repository stats.
They are NOT topic-level CR Candidates (that is PR9c's job).

Design reference: docs/Ptilopsis_Radar_Push_System_Design.md v0.4.1 §8.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Literal, Optional

if TYPE_CHECKING:
    # Type-only import: keeps the data-model layer free of a runtime dependency
    # on the entity-matching loader / YAML logic.
    from trendradar.cr.entity_match import EntityResources
    from trendradar.cr.input_health import CRInputHealth


# ---------------------------------------------------------------------------
# Rank sentinel constants
# ---------------------------------------------------------------------------

RANK_SENTINELS = {0, 99}


def is_visible_rank(raw_rank: Optional[int]) -> bool:
    """Return True when *raw_rank* is a visible (non-sentinel, positive) rank.

    Single source of truth for rank visibility used by both ``_classify_rank``
    and adapter helpers (``_count_visible_observations``,
    ``_derive_previous_observation``).

    Rules (design §8.3):
      None → False
      0 → False
      99 → False
      negative → False
      positive non-sentinel integer → True
    """
    if raw_rank is None:
        return False
    return raw_rank > 0 and raw_rank not in RANK_SENTINELS


def _classify_rank(raw_rank: Optional[int]) -> tuple[Optional[int], bool, str]:
    """Normalize a raw rank into (normalized_rank, is_visible, rank_sentinel).

    Delegates visibility check to :func:`is_visible_rank` so that sentinel
    semantics are defined in exactly one place.
    """
    if raw_rank is None:
        return None, False, "missing"
    if raw_rank == 0:
        return None, False, "zero"
    if raw_rank == 99:
        return None, False, "ninety_nine"
    if raw_rank < 0:
        return None, False, "missing"
    return raw_rank, is_visible_rank(raw_rank), "none"


# ---------------------------------------------------------------------------
# CRSourceItem
# ---------------------------------------------------------------------------


@dataclass
class CRSourceItem:
    """One observable item (title) from a stats group, normalized for CR.

    Design reference: §8.1, §8.2, §8.3, §8.4, §8.5, §8.6, §8.7, §8.8.
    """

    # -- identity --
    source_type: Literal["hotlist", "rss", "unknown"] = "unknown"
    source_id: Optional[str] = None
    feed_id: Optional[str] = None
    source_name: str = ""
    title: str = ""
    url: Optional[str] = None

    # -- keyword group linkage (PR9b: single group, may expand in PR9c) --
    keyword_group: Optional[str] = None
    keyword_groups: Optional[List[str]] = None

    # -- newness --
    is_new: Optional[bool] = None
    is_new_semantics: Literal[
        "new_titles_detection",
        "incremental_first_crawl",
        "unknown",
    ] = "unknown"

    # -- rank (hotlist only; RSS rank is pseudo-rank) --
    raw_rank: Optional[int] = None
    # normalized_rank: best (min) visible rank across all observations.
    #   Primitive representative rank.  NOT the latest observation rank.
    normalized_rank: Optional[int] = None
    is_visible: bool = False
    rank_sentinel: Literal["none", "zero", "ninety_nine", "missing"] = "missing"

    # -- rank timeline --
    rank_timeline: List[dict] = field(default_factory=list)
    has_rank_timeline: bool = False
    has_reliable_rank_timeline: bool = False
    visible_observation_count: int = 0

    # -- previous observation (derived from reliable rank_timeline only) --
    previous_observation_exists: bool = False
    previous_observation_visible: bool = False
    previous_visible_rank: Optional[int] = None
    # current_rank: latest observation rank from reliable rank_timeline.
    #   Falls back to normalized_rank when no reliable timeline exists.
    #   Distinct from normalized_rank (best representative rank).
    current_rank: Optional[int] = None
    rank_delta: Optional[int] = None  # previous_visible_rank - current_rank; positive = improved

    # -- time signals --
    first_time: Optional[str] = None
    last_time: Optional[str] = None
    has_time_signals: bool = False
    time_signals_synthetic: bool = False
    run_time_inferred: bool = False

    # -- first crawl of day --
    first_crawl_of_day: Optional[bool] = None

    # -- count --
    count: Optional[int] = None
    has_count: bool = False
    count_semantics: Literal[
        "crawl_count",
        "rss_item_count",
        "group_count",
        "unknown",
    ] = "unknown"

    # -- RSS metadata (pass-through, not for rank scoring) --
    published_at: Optional[str] = None
    summary: Optional[str] = None
    author: Optional[str] = None
    cross_evidence_admitted: bool = False
    # Entity extraction cached by cross-evidence admission for Rule 4 reuse.
    # None means clustering must extract from the title; an empty set is valid.
    precomputed_entities: Optional[frozenset[str]] = None
    observed_in_current_run: bool = False
    # True only for an item observed in the current run from a source that
    # failed in the immediately preceding recorded run and has now recovered.
    observed_after_ingest_gap: bool = False


# ---------------------------------------------------------------------------
# CRPrimitiveRecord
# ---------------------------------------------------------------------------


@dataclass
class CRPrimitiveRecord:
    """Adapter-level grouping of source items, still keyword-group based.

    This is NOT a topic-level CR Candidate.  PR9c builds true Candidates
    by clustering primitive records.

    Design reference: §5.2.
    """

    keyword_group: Optional[str] = None
    keyword_groups: List[str] = field(default_factory=list)
    source_items: List[CRSourceItem] = field(default_factory=list)
    primary_title: Optional[str] = None
    representative_url: Optional[str] = None
    record_source: Literal[
        "hotlist_stats",
        "rss_stats",
        "mixed",
        "unknown",
    ] = "unknown"


# ---------------------------------------------------------------------------
# CRRunContext
# ---------------------------------------------------------------------------


@dataclass
class CRRunContext:
    """Run-level context passed into the adapter.

    Design reference: §8.7.
    """

    mode: Literal["current", "incremental", "daily", "unknown"] = "unknown"
    run_time: Optional[str] = None
    first_crawl_of_day: Optional[bool] = None
    observed_item_identities: frozenset[str] = field(default_factory=frozenset)
    input_health: "CRInputHealth | None" = None


# ---------------------------------------------------------------------------
# CRCandidate
# ---------------------------------------------------------------------------


@dataclass
class CRCandidate:
    """Topic-level information cluster built by PR9c.

    A candidate aggregates multiple source items that refer to the same topic.
    It is NOT a scored result (PR9d) and NOT a decision (PR9e).

    Design reference: PR9c clustering.
    """

    # -- identity (deterministic) --
    candidate_id: str = ""
    cluster_key: str = ""

    # -- display --
    display_title: str = ""

    # -- aggregated items --
    source_items: List[CRSourceItem] = field(default_factory=list)

    # -- aggregated metadata --
    keyword_groups: List[str] = field(default_factory=list)
    representative_url: Optional[str] = None
    source_types: List[str] = field(default_factory=list)
    source_names: List[str] = field(default_factory=list)
    source_ids: List[str] = field(default_factory=list)
    feed_ids: List[str] = field(default_factory=list)

    # -- source composition flags --
    has_hotlist: bool = False
    has_rss: bool = False
    primary_source_type: Literal["hotlist", "rss", "mixed", "unknown"] = "unknown"

    # -- rank aggregates (hotlist only; RSS pseudo-rank excluded) --
    best_normalized_rank: Optional[int] = None
    best_current_rank: Optional[int] = None


# ---------------------------------------------------------------------------
# CRClusterConfig
# ---------------------------------------------------------------------------


@dataclass
class CRClusterConfig:
    """Lightweight config for PR9c clustering.

    This is a function-parameter default only; it does NOT connect to
    the project runtime config (config.yaml).
    """

    min_shared_tokens: int = 2
    min_similarity: float = 0.55
    use_url_match: bool = True
    use_exact_title_match: bool = True

    # --- Rule 4: cross-language latin/numeric entity overlap (V3b) ---
    # When enabled, a Chinese hotlist item and an English RSS item that share
    # >= entity_min_shared_total entities (of which >= entity_min_high_specificity
    # are high-specificity) are merged.  Also switches _build_cluster_key to a
    # hotlist-first canonical key so merged (mixed) clusters do not drift as RSS
    # items churn in/out of the window.
    use_entity_match: bool = True
    entity_min_shared_total: int = 2
    entity_min_high_specificity: int = 2
    # None -> load the cached default resources from config/cr_entity_dictionary.yaml.
    # Tests may pass an in-memory EntityResources to avoid file/cache coupling.
    entity_resources: "EntityResources | None" = None

    # --- Cross-evidence RSS ingestion (admission funnel; see cross_evidence_ingest) ---
    # cross_evidence_rss_enabled / window / max_per_topic govern RSS admission in the
    # runtime layer; drop_unmerged_rss governs the post-clustering filter in pipeline.py.
    cross_evidence_rss_enabled: bool = True
    cross_evidence_window_hours: float = 36.0
    cross_evidence_max_per_topic: Optional[int] = None
    drop_unmerged_rss: bool = False
