"""Service-to-service auth for Phase 0.

Single bearer token from the environment (compose-injected). User-facing
OIDC via Keycloak replaces this for interactive endpoints in Phase 1 —
object-level RBAC (spec §5.2) is enforced server-side there. All control
plane endpoints require this token; there is no anonymous surface.
"""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

_bearer = HTTPBearer(auto_error=False)


def require_token(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> None:
    if creds is None or creds.credentials != settings.internal_api_token:
        raise HTTPException(status_code=401, detail="invalid or missing token")
