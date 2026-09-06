"""Operator authentication dependency enforcing token validation per TRD-SEC-3."""

import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.config.models import AppConfig

security = HTTPBearer(auto_error=False)


def get_expected_token(request: Request) -> str:
    """Retrieve expected operator token from application configuration."""
    config = getattr(request.app.state, "config", None)
    if isinstance(config, AppConfig):
        return str(config.api.operator_token.get_secret_value())
    # Fallback to default configured token if config not attached
    return "operator-secret-token"


async def verify_operator_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)] = None,
    x_operator_token: Annotated[str | None, Header(alias="X-Operator-Token")] = None,
) -> str:
    """Verify operator authentication token via Bearer auth or X-Operator-Token header.

    Args:
        request: Incoming FastAPI Request.
        credentials: Optional Bearer authorization credentials.
        x_operator_token: Optional custom header for operator token.

    Returns:
        str: Verified operator identity/token label.

    Raises:
        HTTPException: 401 Unauthorized if token is missing or invalid.
    """
    token: str | None = None
    if credentials is not None and credentials.scheme.lower() == "bearer":
        token = credentials.credentials
    elif x_operator_token is not None and x_operator_token.strip():
        token = x_operator_token.strip()

    if not token:
        msg = (
            "Missing operator authorization token. "
            "Provide 'Authorization: Bearer <token>' or 'X-Operator-Token'."
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=msg,
            headers={"WWW-Authenticate": "Bearer"},
        )

    expected_token = get_expected_token(request)

    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(token.encode("utf-8"), expected_token.encode("utf-8")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid operator authorization token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return f"operator-{token[:4]}...[REDACTED]" if len(token) >= 4 else "operator-auth"
