"""Transport-aware serialization of public MCP results."""

from __future__ import annotations

import copy
import json
from typing import Any

from .context import get_request_context


_MASKED_ERROR_CODES = {
    "INTERNAL_ERROR",
    "REQUEST_ERROR",
    "BATCH_ERROR",
}


def _mask_internal_error(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload

    error = payload.get("error")
    if isinstance(error, str):
        payload["error"] = "服务内部错误"
    elif isinstance(error, dict) and error.get("code") in _MASKED_ERROR_CODES:
        payload["error"] = {
            "code": error["code"],
            "message": "服务内部错误",
            "suggestion": "请检查服务日志获取详细信息",
        }

    for key, value in list(payload.items()):
        if key != "error":
            payload[key] = _mask_internal_error(value)
    return payload


def json_response(result: Any) -> str:
    """Serialize a result, masking internal details for untrusted transports."""
    context = get_request_context()
    payload = result
    if not context.expose_error_details:
        payload = _mask_internal_error(copy.deepcopy(result))
    return json.dumps(payload, ensure_ascii=False, indent=2)
