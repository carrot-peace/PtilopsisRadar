"""Deterministic text matching primitives used by search and analytics."""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable
from difflib import SequenceMatcher


def sequence_similarity(
    first: str,
    second: str,
    *,
    case_sensitive: bool,
) -> float:
    """Return SequenceMatcher similarity with an explicit case policy."""
    if not case_sensitive:
        first = first.lower()
        second = second.lower()
    return SequenceMatcher(None, first, second).ratio()


def extract_keywords(
    text: str,
    *,
    min_length: int = 2,
    stopwords: Collection[str] = (),
    remove_bracketed: bool = False,
) -> list[str]:
    """Extract word tokens while preserving the caller's legacy policy."""
    text = re.sub(r"http[s]?://\S+", "", text)
    if remove_bracketed:
        text = re.sub(r"\[.*?\]", "", text)
    words = re.findall(r"\w+", text)
    return [
        word
        for word in words
        if len(word) >= min_length and word not in stopwords
    ]


def jaccard_similarity(
    first: Iterable[str],
    second: Iterable[str],
) -> float:
    """Return set-based Jaccard similarity for two token collections."""
    first_set = set(first)
    second_set = set(second)
    if not first_set or not second_set:
        return 0.0
    return len(first_set & second_set) / len(first_set | second_set)
