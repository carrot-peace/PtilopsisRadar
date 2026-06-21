# coding=utf-8
"""
CR-A event identity evidence (PR10a).

Pure, deterministic helpers that derive a stable *event identity* for a CR
candidate so that future PR10 work (dedupe / cooldown / escalation tracking)
has an observable basis to reason about.

This module is observability-only.  It does NOT enforce dedupe or cooldown,
does NOT suppress dispatch, does NOT persist state, and does NOT touch
Telegram.  It is intentionally pure:

  * no filesystem
  * no network
  * no environment
  * no Telegram
  * no storage
  * no timestamps
  * no randomness

Run-2 motivation (see docs/cr_event_identity_evidence.md):

  * ``candidate_id`` changed (``6e204d8621b7`` -> ``35a135d75a46``) when the
    cluster gained a new source, so it is NOT stable enough to be the primary
    identity key.
  * ``cluster_key`` grows when new sources/platforms join the same event, so
    it is source-sensitive and also unsuitable as the primary key.
  * The normalized title stayed semantically stable, so it is the current
    primary basis for event identity.

Strategy:

  * ``event_key`` is derived primarily from the normalized title.
  * ``candidate_id`` is preserved verbatim as *supporting evidence*.
  * ``cluster_key`` is preserved only as a short fingerprint (never the raw,
    verbose value) as *supporting evidence*.
  * platform/source evidence is fingerprinted, order-insensitively.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


CR_EVENT_IDENTITY_KEY_VERSION = "cr-event-v1"

# Length of the short hex fingerprints exposed as evidence.  Full digests are
# never required for evidence — a 16-hex-char prefix is plenty to observe
# change without embedding large raw values.
_FINGERPRINT_LEN = 16

# Collapse runs of any whitespace (incl. tabs/newlines) to a single space.
_WS_RE = re.compile(r"\s+", re.UNICODE)


# ---------------------------------------------------------------------------
# Inputs / outputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CREventIdentityInput:
    """Minimal pure input for deriving event identity.

    ``platforms`` and ``source_urls`` are treated as unordered sets of
    evidence — their order never affects the derived fingerprints.
    """

    title: str
    platforms: tuple[str, ...] = ()
    source_urls: tuple[str, ...] = ()
    candidate_id: str | None = None
    cluster_key: str | None = None


@dataclass(frozen=True)
class CREventIdentity:
    """Derived event identity evidence.

    ``event_key`` is the primary, storage-safe identity (versioned, derived
    from the normalized title).  Everything else is supporting evidence and
    must NOT be used as the primary identity on its own.
    """

    version: str
    event_key: str
    key_basis: str
    normalized_title: str
    title_fingerprint: str
    platform_fingerprint: str
    source_fingerprint: str
    candidate_id: str | None = None
    cluster_key_fingerprint: str | None = None


# ---------------------------------------------------------------------------
# Normalization helpers (stdlib only)
# ---------------------------------------------------------------------------


def normalize_cr_event_title(value: str) -> str:
    """Normalize a title into a stable, human-readable identity basis.

    Conservative on purpose — this is identity normalization, not semantic
    matching.  Steps:

      1. NFKC unicode normalization (folds full-width / compatibility forms).
      2. Collapse all whitespace runs (tabs/newlines included) to one space.
      3. Trim leading/trailing whitespace.
      4. ASCII-safe lowercasing (``str.lower`` leaves CJK untouched).

    Punctuation and semantic content are preserved — we deliberately do NOT
    strip punctuation or attempt fuzzy/NLP matching here.  Title variants such
    as "广西兴安发生爆炸已致7死17伤" vs "广西兴安爆炸致7死17伤" remain a known
    limitation for future PR10 work, not something this function over-fits to.

    Empty or whitespace-only input returns ``""``.
    """
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value)
    text = _WS_RE.sub(" ", text).strip()
    return text.lower()


def normalize_cr_event_url(value: str) -> str:
    """Normalize a URL for stable, order-insensitive fingerprinting.

    Steps (stdlib only, no network, no fetch):

      1. Trim surrounding whitespace.
      2. Split with :func:`urllib.parse.urlsplit`.
      3. Lowercase the scheme and host (netloc).
      4. Drop the fragment.

    The path/query are preserved as-is.  Inputs without a scheme/host (e.g. a
    bare token) are returned trimmed and unchanged in their path component.

    Empty or whitespace-only input returns ``""``.
    """
    if not value:
        return ""
    text = value.strip()
    if not text:
        return ""
    parts = urlsplit(text)
    normalized = urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, "")
    )
    return normalized


# ---------------------------------------------------------------------------
# Fingerprint helpers
# ---------------------------------------------------------------------------


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _short(digest: str) -> str:
    return digest[:_FINGERPRINT_LEN]


def _fingerprint_platforms(platforms: tuple[str, ...]) -> str:
    """Order-insensitive fingerprint of a platform/source-name set."""
    cleaned = sorted({p.strip().lower() for p in platforms if p and p.strip()})
    return _short(_sha256_hex("\n".join(cleaned)))


def _fingerprint_source_urls(source_urls: tuple[str, ...]) -> str:
    """Order-insensitive fingerprint of a normalized source-URL set.

    URLs are normalized first, then de-duplicated and sorted so that ordering
    and fragment noise never change the fingerprint.  Only the hash is kept —
    no raw URLs are embedded.
    """
    cleaned = sorted(
        {normalize_cr_event_url(u) for u in source_urls if u and u.strip()}
    )
    return _short(_sha256_hex("\n".join(cleaned)))


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def build_cr_event_identity_from_input(
    value: CREventIdentityInput,
) -> CREventIdentity:
    """Build :class:`CREventIdentity` from a pure input.

    The primary ``event_key`` is ``sha256(version + normalized_title)``,
    prefixed with the version for readability and storage safety.  Because
    Run-2 showed ``candidate_id`` and ``cluster_key`` shift when source
    evidence changes, neither contributes to ``event_key`` — they are kept
    only as supporting evidence.

    Deterministic: no timestamps, no randomness, no I/O.
    """
    normalized_title = normalize_cr_event_title(value.title)

    # Version is part of the hashed payload so different versions produce
    # different keys even for an identical title.
    title_digest = _sha256_hex(
        f"{CR_EVENT_IDENTITY_KEY_VERSION}\x1f{normalized_title}"
    )
    event_key = f"{CR_EVENT_IDENTITY_KEY_VERSION}:{title_digest}"

    candidate_id = value.candidate_id or None
    cluster_key_fingerprint = (
        _short(_sha256_hex(value.cluster_key)) if value.cluster_key else None
    )

    return CREventIdentity(
        version=CR_EVENT_IDENTITY_KEY_VERSION,
        event_key=event_key,
        key_basis="normalized_title",
        normalized_title=normalized_title,
        title_fingerprint=_short(_sha256_hex(normalized_title)),
        platform_fingerprint=_fingerprint_platforms(value.platforms),
        source_fingerprint=_fingerprint_source_urls(value.source_urls),
        candidate_id=candidate_id,
        cluster_key_fingerprint=cluster_key_fingerprint,
    )


def build_cr_event_identity_from_candidate(candidate: object) -> CREventIdentity:
    """Build :class:`CREventIdentity` from an actual CR candidate object.

    Reads attributes by name (never ``repr``) and does not mutate the
    candidate.  Expects a ``CRCandidate``-shaped object exposing
    ``display_title`` (required), and optionally ``candidate_id``,
    ``cluster_key``, ``source_names``, ``representative_url`` and
    ``source_items`` (each with a ``url``).

    Raises ``TypeError`` if the required ``display_title`` field is absent or
    is not a string.
    """
    title = getattr(candidate, "display_title", None)
    if not isinstance(title, str):
        raise TypeError(
            "candidate must expose a string 'display_title' field to derive "
            "event identity"
        )

    candidate_id = getattr(candidate, "candidate_id", None) or None
    cluster_key = getattr(candidate, "cluster_key", None) or None

    source_names = getattr(candidate, "source_names", None) or ()
    platforms = tuple(str(name) for name in source_names)

    urls: list[str] = []
    representative_url = getattr(candidate, "representative_url", None)
    if representative_url:
        urls.append(str(representative_url))
    for item in getattr(candidate, "source_items", None) or ():
        item_url = getattr(item, "url", None)
        if item_url:
            urls.append(str(item_url))

    return build_cr_event_identity_from_input(
        CREventIdentityInput(
            title=title,
            platforms=platforms,
            source_urls=tuple(urls),
            candidate_id=candidate_id,
            cluster_key=cluster_key,
        )
    )


def stable_event_key_for_candidate(pc: object) -> str:
    """Return the stable, title-derived event_key for a presented candidate.

    Accepts either a ``CRPresentedCandidate`` (reads ``pc.candidate``) or a
    raw ``CRCandidate``-shaped object directly.  Centralises the derivation
    so that cooldown enforcement and runtime state writes always use the
    same path.
    """
    return build_cr_event_identity_from_candidate(
        getattr(pc, "candidate", pc)
    ).event_key
