# coding=utf-8
"""Daily Report dispatch pipeline.

This package owns the DR push path.  It is intentionally separate from
Legacy Push and from the CR dispatch/Telegram modules.
"""

from trendradar.dr.dispatch_plan import (
    DRDispatchMessage,
    DRDispatchPlan,
    build_dr_dispatch_plan,
)
from trendradar.dr.dispatch_executor import (
    DRDispatchExecutionResult,
    DRDispatchReceipt,
    DRMemoryDispatchSink,
    DRNoopDispatchSink,
    execute_dr_dispatch_plan,
)
from trendradar.dr.dispatch_mode import (
    DR_DISPATCH_ARTIFACT,
    DR_DISPATCH_LIVE,
    DR_DISPATCH_OFF,
    resolve_dr_dispatch_mode,
)

__all__ = [
    "DRDispatchMessage",
    "DRDispatchPlan",
    "build_dr_dispatch_plan",
    "DRDispatchExecutionResult",
    "DRDispatchReceipt",
    "DRMemoryDispatchSink",
    "DRNoopDispatchSink",
    "execute_dr_dispatch_plan",
    "DR_DISPATCH_ARTIFACT",
    "DR_DISPATCH_LIVE",
    "DR_DISPATCH_OFF",
    "resolve_dr_dispatch_mode",
]
