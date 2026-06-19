# coding=utf-8
"""
CR cross-language entity matching (clustering Rule 4).

Deterministic, zero-runtime-AI extraction of latin/numeric entities from a
title, plus a high-specificity test.  Used by ``cluster.py`` to merge a
Chinese hotlist event with the English RSS coverage of the same event when
they share enough discriminative entities (proper nouns, scores, numbers,
model/product tokens).

The Chinese->English name table is loaded from a data file
(``config/cr_entity_dictionary.yaml``) so it can be maintained out-of-band
via PR without code changes.  Missing/malformed/null files degrade gracefully
to empty resources (clustering then behaves as if entity matching found
nothing — never raises).

Design reference: docs/scoring cross-language clustering gap; plan
buzzing-baking-moon (Rule 4, V3b).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Set

# NOTE: yaml is imported lazily inside the loader so this module (and the
# clustering import chain) does not hard-depend on PyYAML at import time.
# Missing PyYAML degrades to empty resources, same as a missing file.


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EntityResources:
    """Loaded entity-matching data.

    dictionary: Chinese substring -> single lowercased latin entity token.
    stoplist:   lowercased entities that are too high-frequency to be
                discriminative (do NOT count toward high-specificity).
    """

    dictionary: Dict[str, str] = field(default_factory=dict)
    stoplist: Set[str] = field(default_factory=set)


_EMPTY_RESOURCES = EntityResources()

# Module-level cache keyed by resolved file path.
_resources_cache: Dict[str, EntityResources] = {}

DEFAULT_DICTIONARY_FILENAME = "cr_entity_dictionary.yaml"


def load_entity_resources(config_dir: str = "config") -> EntityResources:
    """Load entity resources from ``<config_dir>/cr_entity_dictionary.yaml``.

    Mirrors ``core.loader._load_source_tiers_data``: missing file, malformed
    YAML, or null fields all degrade gracefully to empty resources (prints a
    warning, never raises).  Result is cached per resolved path.
    """
    path = Path(config_dir) / DEFAULT_DICTIONARY_FILENAME
    cache_key = str(path)
    if cache_key in _resources_cache:
        return _resources_cache[cache_key]

    resources = _load_entity_resources_uncached(path)
    _resources_cache[cache_key] = resources
    return resources


def _load_entity_resources_uncached(path: Path) -> EntityResources:
    if not path.exists():
        print(f"[实体词典] 未找到: {path}，跨语言实体匹配按空词典降级")
        return _EMPTY_RESOURCES

    try:
        import yaml
    except ImportError:
        print("[实体词典] PyYAML 不可用，跨语言实体匹配按空词典降级")
        return _EMPTY_RESOURCES

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:  # noqa: BLE001 - any parse error degrades gracefully
        print(f"[实体词典] 解析失败 ({e})，跨语言实体匹配按空词典降级")
        return _EMPTY_RESOURCES

    if not isinstance(data, dict):
        return _EMPTY_RESOURCES

    raw_dict = data.get("dictionary") or {}
    raw_stop = data.get("stoplist") or []

    dictionary: Dict[str, str] = {}
    if isinstance(raw_dict, dict):
        for zh, en in raw_dict.items():
            # v1: string values only.  Skip non-string (e.g. list) entries so a
            # future alias-list schema cannot silently inflate match counts.
            if isinstance(zh, str) and isinstance(en, str) and zh and en:
                dictionary[zh] = en.strip().lower()

    stoplist: Set[str] = set()
    if isinstance(raw_stop, list):
        stoplist = {s.strip().lower() for s in raw_stop if isinstance(s, str) and s.strip()}

    # Log counts on success too: a 0/0 load (e.g. wrong cwd) would otherwise make
    # cross-language matching silently ineffective.
    print(f"[实体词典] 加载成功: {path}（dictionary {len(dictionary)} 条, stoplist {len(stoplist)} 条）")
    return EntityResources(dictionary=dictionary, stoplist=stoplist)


def clear_entity_resources_cache() -> None:
    """Clear the module-level resource cache (for tests)."""
    _resources_cache.clear()


# ---------------------------------------------------------------------------
# Entity extraction
# ---------------------------------------------------------------------------

# News-template / common Title-Case sentence words + months + weekdays that
# title-case extraction would otherwise grab as bogus entities.  Distinct from
# the data-driven specificity stoplist (which holds real-but-too-common
# entities like "china"/"trump").
_EXTRACTION_STOPWORDS: Set[str] = {
    # news template words
    "live", "breaking", "video", "watch", "says", "said", "new", "update",
    "updates", "exclusive", "report", "reports", "opinion", "analysis",
    "latest", "news", "live updates",
    # ultra-common Title-Case sentence words
    "the", "and", "for", "with", "from", "after", "amid", "over", "what",
    "why", "how", "here", "this", "that", "more", "top", "into", "but",
    "not", "are", "was", "will", "has", "have", "amp",
    # months
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    # weekdays
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
}

# Score: e.g. 4-2, 1-1, 100-99
_SCORE_RE = re.compile(r"\d{1,3}-\d{1,3}")
# Amount: e.g. $2, $60, $2,000, $2.5
_AMOUNT_RE = re.compile(r"\$\d[\d,]*(?:\.\d+)?")
# Percentage: e.g. 49%, 12%  (numeric value filtered >= 2 below)
_PERCENT_RE = re.compile(r"\d+%")
# Candidate alnum run for model/product tokens: e.g. GLM-5.2, F-35, G7, HBM4E
_ALNUM_RUN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]*[A-Za-z0-9]")
# Standalone big number (3+ digits); years 1900-2100 excluded below
_BIGNUM_RE = re.compile(r"\d{3,}")
# Latin capitalized / CamelCase / all-caps word, >= 3 chars
_CAPWORD_RE = re.compile(r"[A-Z][A-Za-z]{2,}")


def _has_letter(s: str) -> bool:
    return any(c.isalpha() for c in s)


def _has_digit(s: str) -> bool:
    return any(c.isdigit() for c in s)


def extract_entities(title: str, dictionary: Dict[str, str]) -> Set[str]:
    """Extract lowercased latin/numeric entities from a RAW title.

    Operates on the raw title (NOT normalized text), because normalization
    strips punctuation and would destroy scores (1-1), amounts ($2) and
    model tokens (GLM-5.2).

    Entity classes:
      - score X-Y, amount $X, percentage X% (X>=2), big number (3+ digits,
        excluding years 1900-2100)
      - model/product tokens (letters + digits, e.g. GLM-5.2 / F-35 / G7 / HBM4E)
      - latin capitalized / CamelCase / all-caps words (>= 3 chars), minus
        extraction stopwords
      - dictionary substring hits (Chinese key present -> mapped latin token)

    Numeric/model tokens are masked out before capitalized-word scanning so a
    single concept (e.g. GLM-5.2) does not also yield its alphabetic prefix
    (GLM) as a separate entity.
    """
    if not title:
        return set()

    entities: Set[str] = set()
    work = title

    # 1. Amounts (mask).
    for m in _AMOUNT_RE.finditer(work):
        entities.add(m.group().replace(",", "").lower())
    work = _AMOUNT_RE.sub(" ", work)

    # 2. Scores (mask).
    for m in _SCORE_RE.finditer(work):
        entities.add(m.group())
    work = _SCORE_RE.sub(" ", work)

    # 3. Percentages, value >= 2 (mask).
    for m in _PERCENT_RE.finditer(work):
        num = m.group()[:-1]
        try:
            if int(num) >= 2:
                entities.add(m.group())
        except ValueError:
            pass
    work = _PERCENT_RE.sub(" ", work)

    # 4. Model / product tokens: alnum run with BOTH a letter and a digit (mask).
    model_spans = []
    for m in _ALNUM_RUN_RE.finditer(work):
        tok = m.group()
        if _has_letter(tok) and _has_digit(tok):
            entities.add(tok.lower())
            model_spans.append((m.start(), m.end()))
    if model_spans:
        chars = list(work)
        for start, end in model_spans:
            for i in range(start, end):
                chars[i] = " "
        work = "".join(chars)

    # 5. Big numbers (3+ digits), excluding years.
    for m in _BIGNUM_RE.finditer(work):
        tok = m.group()
        val = int(tok)
        if 1900 <= val <= 2100:
            continue
        entities.add(tok)

    # 6. Latin capitalized words (>= 3 chars), minus extraction stopwords.
    for m in _CAPWORD_RE.finditer(work):
        w = m.group().lower()
        if w not in _EXTRACTION_STOPWORDS:
            entities.add(w)

    # 7. Dictionary substring hits on the ORIGINAL title.
    for zh, en in dictionary.items():
        if zh in title:
            entities.add(en)

    return entities


def is_high_specificity(entity: str, stoplist: Set[str]) -> bool:
    """Return True when *entity* is discriminative enough to anchor a merge.

    Numeric / score / amount / percentage / model tokens (anything containing a
    digit, or a ``$``/``%`` marker) are inherently specific.  Latin proper
    nouns are specific unless they appear in the high-frequency *stoplist*.
    """
    if not entity:
        return False
    if _has_digit(entity) or entity.startswith("$") or entity.endswith("%"):
        return True
    return entity not in stoplist
