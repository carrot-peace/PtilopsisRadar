# coding=utf-8
"""Fail-closed helpers for the removed Legacy Push package.

See docs/legacy_push_removal_plan.md for the CR-New migration plan.
"""


REMOVED_MESSAGE = (
    "Legacy notification push has been removed. "
    "Use CR-New dispatch plan with explicit operator gates. "
    "See docs/legacy_push_removal_plan.md for migration details."
)


class LegacyNotificationRemovedError(RuntimeError):
    """Legacy notification push has been removed."""


def raise_legacy_notification_removed(*args, **kwargs):
    """Raise the canonical Legacy Push removal error for old public APIs."""
    raise LegacyNotificationRemovedError(REMOVED_MESSAGE)
