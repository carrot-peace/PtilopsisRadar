# coding=utf-8
"""
CR-A dispatch mode resolution (PR-CR-A1).

Pure, side-effect-free helpers that resolve the CR-A runtime dispatch mode
from an explicit environment mapping.

This module does NOT run CR-A, does NOT send Telegram, does NOT read
``os.environ``, and does NOT modify runtime behavior.

The four dispatch modes are:

  off       — CR-A does not run.
  artifact  — CR-A runs; writes audit artifacts only; no dispatch sink.
  shadow    — CR-A runs; writes audit artifacts and plan preview; no dispatch
              sink.
  live      — CR-A runs; may execute dispatch only when the explicit CR
              Telegram send gate is also enabled.

Resolution priority:

  1. ``PTILOPSIS_CR_DISPATCH_MODE`` — explicit, wins over everything.
  2. ``PTILOPSIS_CR_DRY_RUN=1`` — compatibility alias, maps to ``artifact``.
  3. default — ``off``.

Invalid or unrecognized values resolve to ``off`` (fail closed).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

# ---------------------------------------------------------------------------
# Mode type
# ---------------------------------------------------------------------------

CRDispatchMode = Literal["off", "artifact", "shadow", "live"]

_VALID_MODES: frozenset[str] = frozenset({"off", "artifact", "shadow", "live"})

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_cr_dispatch_mode(env: Mapping[str, str]) -> CRDispatchMode:
    """Resolve the CR-A dispatch mode from an explicit environment mapping.

    Parameters
    ----------
    env:
        An explicit mapping of environment variables (e.g. ``os.environ``
        or a test dict).  Never reads the real environment directly.

    Returns
    -------
    CRDispatchMode
        One of ``"off"``, ``"artifact"``, ``"shadow"``, ``"live"``.

    Resolution rules
    ----------------
    1. If ``PTILOPSIS_CR_DISPATCH_MODE`` is set to a valid value, return it.
    2. If ``PTILOPSIS_CR_DISPATCH_MODE`` is set to an invalid value, return
       ``"off"`` (fail closed).
    3. If ``PTILOPSIS_CR_DRY_RUN`` is exactly ``"1"``, return ``"artifact"``
       (compatibility alias).
    4. Otherwise return ``"off"``.
    """
    dispatch_raw = env.get("PTILOPSIS_CR_DISPATCH_MODE")
    if dispatch_raw is not None:
        dispatch_val = dispatch_raw.strip().lower()
        if dispatch_val in _VALID_MODES:
            return dispatch_val  # type: ignore[return-value]
        # Invalid value — fail closed.
        return "off"

    # Compatibility alias: PTILOPSIS_CR_DRY_RUN=1 → artifact.
    if env.get("PTILOPSIS_CR_DRY_RUN") == "1":
        return "artifact"

    return "off"
