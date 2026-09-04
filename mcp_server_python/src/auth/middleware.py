"""Principal derivation middleware — Path C (design §5, AD-C2).

Reads Trusted_Context_Headers injected by the Gateway Request_Interceptor and
derives the request principal. When no headers are present (SigV4 direct from
the developer proxy), the principal defaults to ``developer-sigv4``.

Implements Requirements R5.1, R5.2, R5.4.
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Trusted_Context_Header names, lowercased for case-insensitive lookup.
_HEADER_PRINCIPAL = "x-amzn-bedrock-agentcore-runtime-custom-principal"
_HEADER_SCOPE = "x-amzn-bedrock-agentcore-runtime-custom-scope"
_HEADER_BROKER_REQUEST_ID = "x-amzn-bedrock-agentcore-runtime-custom-brokerrequestid"

# Recognized scopes — default-deny anything outside this set (R5.4).
KNOWN_SCOPES: frozenset[str] = frozenset({
    "mcp/ci-readonly",
    "mcp/hpc-user",
    "developer-sigv4",
})

# The implicit principal when no Gateway headers are present (SigV4 direct).
_DEFAULT_PRINCIPAL = "developer-sigv4"
_DEFAULT_SCOPE = "developer-sigv4"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ForbiddenError(Exception):
    """Raised when the request scope is not recognized (default-deny, R5.4).

    Parameters
    ----------
    scope : str
        The unrecognized scope value.
    """

    def __init__(self, scope: str) -> None:
        self.scope = scope
        super().__init__(
            f"unrecognized scope {scope!r}; "
            f"known scopes: {', '.join(sorted(KNOWN_SCOPES))}"
        )


# ---------------------------------------------------------------------------
# PrincipalContext
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PrincipalContext:
    """Request-scoped principal identity derived from Trusted_Context_Headers.

    Attributes
    ----------
    principal : str
        The derived principal name (e.g. ``"ci-readonly"``, ``"hpc-user"``,
        ``"developer-sigv4"``).
    scope : str
        The OAuth scope or synthetic scope for the developer path.
    broker_request_id : str | None
        The Token_Broker request ID for audit attribution; ``None`` for the
        developer SigV4 path.
    """

    principal: str
    scope: str
    broker_request_id: str | None


# ---------------------------------------------------------------------------
# Principal derivation
# ---------------------------------------------------------------------------


def _get_header(headers: dict[str, str], name: str) -> str | None:
    """Case-insensitive header lookup.

    Parameters
    ----------
    headers : dict[str, str]
        The inbound request headers.
    name : str
        The lowercased canonical header name to search for.

    Returns
    -------
    str | None
        The header value, or ``None`` if absent.
    """
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None


def derive_principal(headers: dict[str, str]) -> PrincipalContext:
    """Derive the request principal from Trusted_Context_Headers.

    Implements the Path C §5 derivation logic:

    * If the ``Custom-Principal`` header is **absent**, the request came via
      SigV4 direct (no Gateway) → ``developer-sigv4`` with full tool access.
    * If the header is **present** but the ``Custom-Scope`` value is not in
      :data:`KNOWN_SCOPES` → raise :class:`ForbiddenError` (default-deny).
    * Otherwise → return the injected principal, scope, and broker_request_id.

    Parameters
    ----------
    headers : dict[str, str]
        The inbound HTTP request headers. Keys may be in any case.

    Returns
    -------
    PrincipalContext
        The derived principal context.

    Raises
    ------
    ForbiddenError
        If the scope is present but not recognized.
    """
    principal = _get_header(headers, _HEADER_PRINCIPAL)

    if principal is None:
        # SigV4 direct: no Gateway, no injected headers (R5.2).
        return PrincipalContext(
            principal=_DEFAULT_PRINCIPAL,
            scope=_DEFAULT_SCOPE,
            broker_request_id=None,
        )

    scope = _get_header(headers, _HEADER_SCOPE)

    if scope not in KNOWN_SCOPES:
        # Default-deny on unrecognized scope (R5.4).
        raise ForbiddenError(scope or "")

    broker_request_id = _get_header(headers, _HEADER_BROKER_REQUEST_ID)

    return PrincipalContext(
        principal=principal,
        scope=scope,
        broker_request_id=broker_request_id or None,
    )
