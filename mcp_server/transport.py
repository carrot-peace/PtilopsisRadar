"""HTTP exposure, authentication, and environment policy helpers."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os

from fastmcp.server.auth import AccessToken, TokenVerifier


TRUE_VALUES = {"1", "true", "yes", "on"}


def environment_flag(name: str, *, default: bool = False) -> bool:
    """Read one strict boolean environment flag."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(
        f"{name} must be one of: "
        "1/0, true/false, yes/no, on/off"
    )


def is_loopback_host(host: str) -> bool:
    """Return whether a bind or publish host is limited to this machine."""
    normalized = host.strip().lower().strip("[]")
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


class BearerTokenVerifier(TokenVerifier):
    """Verify one deployment token without retaining its plaintext value."""

    def __init__(self, token: str):
        token = token.strip()
        if not token:
            raise ValueError("MCP HTTP bearer token cannot be empty")
        super().__init__(required_scopes=[])
        self._token_digest = hashlib.sha256(token.encode()).digest()

    async def verify_token(self, token: str) -> AccessToken | None:
        candidate = hashlib.sha256(token.encode()).digest()
        if not hmac.compare_digest(candidate, self._token_digest):
            return None
        return AccessToken(
            token=token,
            client_id="ptilopsis-radar-http",
            scopes=["mcp:read"],
        )


def validate_http_exposure(
    *,
    bind_host: str,
    publish_host: str | None,
    bearer_token: str | None,
    allow_insecure_public: bool,
) -> None:
    """Reject accidental unauthenticated exposure beyond loopback."""
    exposed_host = publish_host or bind_host
    if (
        not is_loopback_host(exposed_host)
        and not (bearer_token or "").strip()
        and not allow_insecure_public
    ):
        raise ValueError(
            "Refusing unauthenticated public MCP HTTP exposure on "
            f"{exposed_host!r}; set MCP_HTTP_BEARER_TOKEN or explicitly "
            "opt in with MCP_HTTP_ALLOW_INSECURE_PUBLIC=true"
        )
