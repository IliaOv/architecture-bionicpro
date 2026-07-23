"""Валидация Bearer-токена Keycloak (RS256) и извлечение идентичности.

Ресурс-сервер проверяет подпись локально по публичному ключу (JWKS) без
похода в Keycloak на каждый запрос. Идентичность пользователя берётся
исключительно из токена — клиент не может подменить, чей отчёт запрашивается.
"""

from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from .config import settings

_bearer = HTTPBearer(auto_error=False)
_jwks = PyJWKClient(settings.jwks_uri)


@dataclass
class Principal:
    username: str
    subject: str
    roles: set[str]


def _decode(token: str) -> dict:
    try:
        signing_key = _jwks.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
        )
    if claims.get("iss") not in settings.allowed_issuers:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Untrusted issuer"
        )
    return claims


async def current_principal(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    """Требует валидный Bearer-токен. Неаутентифицированный запрос → 401."""
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No bearer token"
        )
    claims = _decode(creds.credentials)
    username = claims.get("preferred_username")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No username in token"
        )
    roles = set(claims.get("realm_access", {}).get("roles", []))

    # RBAC: доступ к отчётности только для соответствующих ролей.
    if settings.report_roles_set and roles.isdisjoint(settings.report_roles_set):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No report access role",
        )
    return Principal(username=username, subject=claims.get("sub", ""), roles=roles)
