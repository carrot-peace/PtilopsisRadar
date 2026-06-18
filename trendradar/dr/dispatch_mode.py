# coding=utf-8
"""DR dispatch mode resolution."""

from __future__ import annotations

from collections.abc import Mapping


DR_DISPATCH_OFF = "off"
DR_DISPATCH_ARTIFACT = "artifact"
DR_DISPATCH_LIVE = "live"

_VALID_MODES = frozenset(
    {DR_DISPATCH_OFF, DR_DISPATCH_ARTIFACT, DR_DISPATCH_LIVE}
)


def resolve_dr_dispatch_mode(env: Mapping[str, str]) -> str:
    """Resolve DR dispatch mode from explicit environment gate."""
    raw = (env.get("PTILOPSIS_DR_DISPATCH_MODE") or DR_DISPATCH_OFF).strip().lower()
    if raw not in _VALID_MODES:
        print(f"[DR] Invalid PTILOPSIS_DR_DISPATCH_MODE={raw!r}; using off")
        return DR_DISPATCH_OFF
    return raw
