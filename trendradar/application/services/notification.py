"""Ordered post-analysis notification hooks with explicit failure policy."""

from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence


@dataclass(frozen=True, slots=True)
class AnalysisNotificationEvent:
    mode: str
    ai_result: Any
    html_file: Optional[str]
    schedule: Any


@dataclass(frozen=True, slots=True)
class NotificationHook:
    name: str
    handler: Callable[[Any], Any]
    predicate: Callable[[Any], bool] = lambda _event: True
    suppress_exceptions: bool = False


@dataclass(frozen=True, slots=True)
class NotificationHookResult:
    name: str
    status: str
    value: Any = None
    error: Optional[str] = None


class NotificationService:
    """Run registered hooks in order without hiding their failure contract."""

    def __init__(self, *, error_reporter: Optional[Callable] = None):
        self._error_reporter = error_reporter

    def notify(
        self,
        event: Any,
        hooks: Sequence[NotificationHook],
    ) -> tuple[NotificationHookResult, ...]:
        results = []
        for hook in hooks:
            if not hook.predicate(event):
                results.append(
                    NotificationHookResult(
                        name=hook.name,
                        status="skipped",
                    )
                )
                continue
            try:
                value = hook.handler(event)
            except Exception as exc:
                if not hook.suppress_exceptions:
                    raise
                if self._error_reporter is not None:
                    self._error_reporter(hook.name, exc)
                results.append(
                    NotificationHookResult(
                        name=hook.name,
                        status="failed",
                        error=str(exc),
                    )
                )
            else:
                results.append(
                    NotificationHookResult(
                        name=hook.name,
                        status="completed",
                        value=value,
                    )
                )
        return tuple(results)
