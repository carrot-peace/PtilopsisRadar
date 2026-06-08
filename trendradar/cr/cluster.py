# coding=utf-8
"""
CR deterministic topic clustering.

Builds topic-level CRCandidate objects from CRPrimitiveRecord input.
Uses stdlib-only deterministic normalization and conservative merge rules.

Does NOT score, decide, or render.

Design reference: PR9c.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Dict, List, Optional, Sequence, Set

from trendradar.cr.models import (
    CRClusterConfig,
    CRCandidate,
    CRPrimitiveRecord,
    CRSourceItem,
)


# ---------------------------------------------------------------------------
# Text normalization helpers (stdlib only)
# ---------------------------------------------------------------------------

# Common punctuation pattern (ASCII + common CJK punctuation).
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)

# Collapse runs of whitespace to a single space.
_WS_RE = re.compile(r"\s+", re.UNICODE)

# CJK Unified Ideographs range (subset covering common Chinese/Japanese).
_CJK_RE = re.compile(
    r"[一-鿿㐀-䶿\U00020000-\U0002a6df"
    r"\U0002a700-\U0002b73f\U0002b740-\U0002b81f\U0002b820-\U0002ceaf]"
)


def normalize_topic_text(text: str) -> str:
    """Normalize a title string for deterministic comparison.

    Steps:
      1. NFKC unicode normalization.
      2. Lowercase.
      3. Remove common punctuation.
      4. Collapse whitespace.

    Empty or whitespace-only input returns "".
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def extract_topic_tokens(text: str) -> Set[str]:
    """Extract normalized tokens from a title string.

    For English / digit text: split on whitespace for word tokens.
    For CJK text: use 2-char (bigram) sliding window per contiguous CJK run.
    Mixed text produces both word tokens and CJK bigrams.

    Returns an empty set for empty or whitespace-only input.
    """
    normalized = normalize_topic_text(text)
    if not normalized:
        return set()

    tokens: Set[str] = set()

    # Split into segments: CJK runs vs non-CJK runs.
    segments = re.split(r"((?:[一-鿿㐀-䶿\U00020000-\U0002a6df\U0002a700-\U0002b73f\U0002b740-\U0002b81f\U0002b820-\U0002ceaf])+)", normalized)

    for segment in segments:
        if not segment:
            continue
        if _CJK_RE.match(segment[0]):
            # CJK run: extract bigrams.
            if len(segment) >= 2:
                for i in range(len(segment) - 1):
                    tokens.add(segment[i : i + 2])
            elif len(segment) == 1:
                tokens.add(segment)
        else:
            # Non-CJK: split on whitespace for word tokens.
            for word in segment.split():
                if word:
                    tokens.add(word)

    return tokens


def title_similarity(a: str, b: str) -> float:
    """Compute similarity between two titles.

    Metric: |tokens_a ∩ tokens_b| / min(|tokens_a|, |tokens_b|).

    This is a containment-style ratio: it approaches 1.0 when the smaller
    set is mostly contained in the larger one.  Conservative for clustering
    because it requires overlap proportional to the shorter title.

    Returns 0.0 when either token set is empty (safe for empty titles).
    """
    tokens_a = extract_topic_tokens(a)
    tokens_b = extract_topic_tokens(b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = len(tokens_a & tokens_b)
    min_size = min(len(tokens_a), len(tokens_b))
    if min_size == 0:
        return 0.0
    return intersection / min_size


# ---------------------------------------------------------------------------
# Union-Find (for deterministic clustering)
# ---------------------------------------------------------------------------


class _UnionFind:
    """Simple Union-Find with path compression."""

    def __init__(self) -> None:
        self._parent: Dict[int, int] = {}

    def find(self, x: int) -> int:
        if x not in self._parent:
            self._parent[x] = x
        if self._parent[x] != x:
            self._parent[x] = self.find(self._parent[x])
        return self._parent[x]

    def union(self, x: int, y: int) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            if rx < ry:
                self._parent[ry] = rx
            else:
                self._parent[rx] = ry


# ---------------------------------------------------------------------------
# Core clustering
# ---------------------------------------------------------------------------


def _cluster_source_items(
    source_items: Sequence[CRSourceItem],
    config: CRClusterConfig,
) -> List[List[CRSourceItem]]:
    """Group source items into topic clusters.

    Conservative merge rules (PR9c):
      1. Exact normalized title match → merge.
      2. Exact URL match (when both non-empty) → merge.
      3. Strong title token overlap (≥ min_shared_tokens AND
         similarity ≥ min_similarity) → merge.

    Anti-merge: same keyword_group alone does NOT merge unrelated titles.
    """
    items = list(source_items)
    n = len(items)
    if n == 0:
        return []

    # Pre-compute normalized data.
    norm_titles = [normalize_topic_text(it.title) for it in items]
    title_tokens = [extract_topic_tokens(it.title) for it in items]

    uf = _UnionFind()

    for i in range(n):
        for j in range(i + 1, n):
            # Rule 1: exact normalized title.
            if config.use_exact_title_match:
                if norm_titles[i] and norm_titles[i] == norm_titles[j]:
                    uf.union(i, j)
                    continue

            # Rule 2: exact URL match.
            if config.use_url_match:
                url_i = items[i].url
                url_j = items[j].url
                if url_i and url_j and url_i == url_j:
                    uf.union(i, j)
                    continue

            # Rule 3: strong title token overlap.
            tok_i = title_tokens[i]
            tok_j = title_tokens[j]
            if tok_i and tok_j:
                intersection_size = len(tok_i & tok_j)
                if intersection_size >= config.min_shared_tokens:
                    min_size = min(len(tok_i), len(tok_j))
                    sim = intersection_size / min_size if min_size > 0 else 0.0
                    if sim >= config.min_similarity:
                        uf.union(i, j)

    # Group by root.
    clusters: Dict[int, List[CRSourceItem]] = {}
    for i in range(n):
        root = uf.find(i)
        clusters.setdefault(root, []).append(items[i])

    return list(clusters.values())


def _source_type_priority(source_type: str) -> int:
    """Numeric priority for source type in display title selection.

    hotlist (0) < rss (1) < unknown (2).
    """
    if source_type == "hotlist":
        return 0
    if source_type == "rss":
        return 1
    return 2


def _item_sort_key(it: CRSourceItem) -> tuple:
    """Deterministic sort key for display title selection.

    Priority (all deterministic, no dependency on list position):
      1. source_type: hotlist before rss before unknown.
      2. current_rank: present (0, rank) before missing (1,).
      3. normalized_rank: present (0, rank) before missing (1,).
      4. count: higher is better (negated).
      5. normalized title (stable string tie-breaker).
      6. url (stable string tie-breaker).
      7. source_id (stable string tie-breaker).
      8. source_name (stable string tie-breaker).

    RSS pseudo-rank does NOT influence this key (RSS items always have
    current_rank=None, normalized_rank=None).
    """
    cr = it.current_rank
    nr = it.normalized_rank
    cr_key = (0, cr) if cr is not None else (1,)
    nr_key = (0, nr) if nr is not None else (1,)
    cnt = it.count if it.has_count else 0
    return (
        _source_type_priority(it.source_type),
        cr_key,
        nr_key,
        -cnt,
        normalize_topic_text(it.title),
        it.url or "",
        it.source_id or "",
        it.source_name or "",
    )


def _select_display_title(cluster: List[CRSourceItem]) -> str:
    """Select display title using a heat-first heuristic (no scoring).

    Fully deterministic — does NOT depend on input order.

    Priority:
      1. source_type: hotlist before rss before unknown.
      2. current_rank: smaller (better) rank wins.
      3. normalized_rank: smaller (better) rank wins.
      4. count: higher count wins.
      5. normalized title: lexicographic (stable tie-breaker).
      6. url: lexicographic (stable tie-breaker).
      7. source_id / source_name: stable tie-breakers.

    RSS pseudo-rank does NOT influence display title selection.
    """
    if not cluster:
        return ""
    best = min(cluster, key=_item_sort_key)
    return best.title


def _select_representative_url(cluster: List[CRSourceItem], display_title: str) -> Optional[str]:
    """Select representative URL, preferring the display title item's URL.

    Deterministic: when multiple items share display_title, picks the one
    with the lexicographically smallest URL.
    """
    # Prefer the URL of the display title item.
    matching_urls = sorted(
        it.url for it in cluster if it.title == display_title and it.url
    )
    if matching_urls:
        return matching_urls[0]
    # Fallback: any URL, sorted for determinism.
    all_urls = sorted(it.url for it in cluster if it.url)
    return all_urls[0] if all_urls else None


def _build_cluster_key(cluster: List[CRSourceItem]) -> str:
    """Build a deterministic cluster key from normalized titles and URLs.

    The key is stable regardless of input order or which item is selected
    as display title.
    """
    sig_titles = sorted(
        {normalize_topic_text(it.title) for it in cluster if it.title}
    )
    sig_urls = sorted({it.url for it in cluster if it.url})
    parts = sig_titles + sig_urls
    return "||".join(parts) if parts else "empty"


def _compute_candidate_id(cluster_key: str, salt: str = "pr9c") -> str:
    """Compute a deterministic candidate ID from the cluster key."""
    payload = f"{salt}:{cluster_key}".encode("utf-8")
    return hashlib.sha1(payload).hexdigest()[:12]


def build_candidate_from_cluster(
    cluster: List[CRSourceItem],
    config: CRClusterConfig,
    salt: str = "pr9c",
) -> CRCandidate:
    """Build a CRCandidate from a cluster of source items.

    Aggregates metadata, selects display title (heat-first), and
    computes deterministic candidate_id / cluster_key.
    """
    display_title = _select_display_title(cluster)
    representative_url = _select_representative_url(cluster, display_title)

    # Aggregate keyword_groups (deduplicated).
    all_kg: Set[str] = set()
    for it in cluster:
        if it.keyword_group:
            all_kg.add(it.keyword_group)
        if it.keyword_groups:
            all_kg.update(it.keyword_groups)

    # Aggregate source metadata (deduplicated, deterministic order).
    source_types = sorted({it.source_type for it in cluster})
    source_names = sorted(
        {it.source_name for it in cluster if it.source_name}
    )
    source_ids = sorted(
        {sid for it in cluster if it.source_id for sid in [it.source_id]}
    )
    feed_ids = sorted(
        {fid for it in cluster if it.feed_id for fid in [it.feed_id]}
    )

    has_hotlist = any(it.source_type == "hotlist" for it in cluster)
    has_rss = any(it.source_type == "rss" for it in cluster)

    if has_hotlist and has_rss:
        primary_source_type = "mixed"
    elif has_hotlist:
        primary_source_type = "hotlist"
    elif has_rss:
        primary_source_type = "rss"
    else:
        primary_source_type = "unknown"

    # Best ranks (hotlist only; RSS pseudo-rank excluded).
    best_normalized_rank: Optional[int] = None
    best_current_rank: Optional[int] = None
    for it in cluster:
        if it.source_type != "hotlist":
            continue
        if it.normalized_rank is not None:
            if best_normalized_rank is None or it.normalized_rank < best_normalized_rank:
                best_normalized_rank = it.normalized_rank
        if it.current_rank is not None:
            if best_current_rank is None or it.current_rank < best_current_rank:
                best_current_rank = it.current_rank

    # Deterministic ID.
    cluster_key = _build_cluster_key(cluster)
    candidate_id = _compute_candidate_id(cluster_key, salt=salt)

    return CRCandidate(
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        display_title=display_title,
        source_items=list(cluster),
        keyword_groups=sorted(all_kg),
        representative_url=representative_url,
        source_types=source_types,
        source_names=source_names,
        source_ids=source_ids,
        feed_ids=feed_ids,
        has_hotlist=has_hotlist,
        has_rss=has_rss,
        best_normalized_rank=best_normalized_rank,
        best_current_rank=best_current_rank,
        primary_source_type=primary_source_type,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_cr_candidates(
    primitive_records: Sequence[CRPrimitiveRecord],
    *,
    config: CRClusterConfig | None = None,
) -> List[CRCandidate]:
    """Build topic-level CRCandidate objects from primitive records.

    Flattens all source items from all primitive records, clusters them
    deterministically, and returns one CRCandidate per cluster.

    Args:
        primitive_records: Output of adapt_hotlist_stats / adapt_rss_stats.
        config: Clustering config.  Uses CRClusterConfig() defaults if None.

    Returns:
        List of CRCandidate, sorted by candidate_id for deterministic output.
    """
    if config is None:
        config = CRClusterConfig()

    # Flatten all source items from all primitive records.
    all_items: List[CRSourceItem] = []
    for record in primitive_records:
        all_items.extend(record.source_items)

    if not all_items:
        return []

    # Cluster.
    clusters = _cluster_source_items(all_items, config)

    # Build candidates.
    candidates = [build_candidate_from_cluster(c, config) for c in clusters]

    # Sort by candidate_id for deterministic output order.
    candidates.sort(key=lambda c: c.candidate_id)

    return candidates
