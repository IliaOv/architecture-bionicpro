import httpx
import jwt
from jwt import PyJWKClient

from .config import settings


class KeycloakClient:
    """Клиент к Keycloak: Authorization Code + PKCE, refresh, logout, userinfo, JWKS."""

    def __init__(self) -> None:
        self._jwks = PyJWKClient(settings.jwks_uri)

    async def exchange_code(
        self, code: str, code_verifier: str, redirect_uri: str
    ) -> dict:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": settings.client_id,
            "code_verifier": code_verifier,
        }
        if settings.client_secret:
            data["client_secret"] = settings.client_secret
        return await self._token_request(data)

    async def refresh(self, refresh_token: str) -> dict:
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": settings.client_id,
        }
        if settings.client_secret:
            data["client_secret"] = settings.client_secret
        return await self._token_request(data)

    async def logout(self, refresh_token: str) -> None:
        data = {
            "client_id": settings.client_id,
            "refresh_token": refresh_token,
        }
        if settings.client_secret:
            data["client_secret"] = settings.client_secret
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(settings.end_session_endpoint, data=data)
            # 204/200 — ок; невалидный refresh не должен ломать выход из приложения
            if resp.status_code >= 500:
                resp.raise_for_status()

    async def fetch_userinfo(self, access_token: str) -> dict:
        """Профиль (в т.ч. после Identity Brokering Яндекс ID)."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                settings.userinfo_endpoint,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            return resp.json()

    async def _token_request(self, data: dict) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(settings.token_endpoint, data=data)
            resp.raise_for_status()
            return resp.json()

    def decode_access_token(self, access_token: str) -> dict:
        signing_key = self._jwks.get_signing_key_from_jwt(access_token)
        return jwt.decode(
            access_token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_aud": False},
            issuer=settings.public_issuer,
        )

    @staticmethod
    def extract_user(claims: dict) -> dict:
        realm_roles = claims.get("realm_access", {}).get("roles", [])
        return {
            "sub": claims.get("sub"),
            "username": claims.get("preferred_username"),
            "email": claims.get("email"),
            "name": claims.get("name"),
            "roles": realm_roles,
            "idp": claims.get("identity_provider")
            or claims.get("idp")
            or "keycloak",
        }


keycloak = KeycloakClient()
