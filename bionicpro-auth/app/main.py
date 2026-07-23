from typing import Optional
from urllib.parse import quote

import httpx
from fastapi import Cookie, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import settings
from .keycloak_client import keycloak
from .profile_store import profiles
from .session_store import now, store

app = FastAPI(title="bionicpro-auth", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PkceCallbackBody(BaseModel):
    code: str
    state: str
    code_verifier: str = Field(min_length=43, max_length=128)
    redirect_uri: str


class ConsentBody(BaseModel):
    accepted: bool


def _set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_id,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite,
    )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/auth/callback")
async def pkce_callback(body: PkceCallbackBody) -> Response:
    """Обмен authorization code + PKCE → токены только на BFF; наружу — session cookie."""
    if body.redirect_uri != settings.oidc_redirect_uri:
        raise HTTPException(status_code=400, detail="Invalid redirect_uri")

    try:
        tokens = await keycloak.exchange_code(
            body.code, body.code_verifier, body.redirect_uri
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Token exchange failed: {exc.response.text}",
        ) from exc

    if "refresh_token" not in tokens:
        raise HTTPException(
            status_code=500,
            detail="Keycloak не вернул refresh_token — проверьте Standard Flow / client",
        )

    claims = keycloak.decode_access_token(tokens["access_token"])
    user = keycloak.extract_user(claims)
    session_data = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "access_expires_at": now() + int(tokens["expires_in"]),
        "user": user,
    }
    session_id = await store.create_session(session_data)

    response = JSONResponse(
        {
            "status": "authenticated",
            "session_id": session_id,
            "user": user,
            "consent_required": not profiles.has_consent(user["sub"]),
        }
    )
    _set_session_cookie(response, session_id)
    return response


@app.post("/auth/logout")
async def logout(sid: Optional[str] = Cookie(default=None)) -> Response:
    """Инвалидирует сессию BFF. Ошибка Keycloak не блокирует выход."""
    if sid:
        session = await store.get_session(sid)
        if session:
            try:
                await keycloak.logout(session["refresh_token"])
            except Exception:  # noqa: BLE001 — локальный выход важнее revoke у IdP
                pass
            await store.delete_session(sid)
    response = JSONResponse(
        {
            "status": "logged_out",
            # Браузер должен сбросить SSO Keycloak, иначе Login сразу вернёт в сессию IdP.
            "keycloak_logout_url": (
                f"{settings.public_end_session_endpoint}"
                f"?client_id={settings.client_id}"
                f"&post_logout_redirect_uri={quote(settings.frontend_url, safe='')}"
            ),
        }
    )
    _clear_session_cookie(response)
    return response


async def _require_session(sid: Optional[str]) -> tuple[str, dict]:
    if not sid:
        raise HTTPException(status_code=401, detail="No session")
    session = await store.get_session(sid)
    if session is None:
        raise HTTPException(status_code=401, detail="Session expired")
    return sid, session


async def _ensure_fresh_access_token(session: dict) -> dict:
    """Протухший access_token обновляется через refresh_token в Keycloak."""
    if session["access_expires_at"] - now() > 5:
        return session
    try:
        tokens = await keycloak.refresh(session["refresh_token"])
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=401, detail="Refresh failed")
    claims = keycloak.decode_access_token(tokens["access_token"])
    session["access_token"] = tokens["access_token"]
    session["refresh_token"] = tokens.get("refresh_token", session["refresh_token"])
    session["access_expires_at"] = now() + int(tokens["expires_in"])
    session["user"] = keycloak.extract_user(claims)
    return session


async def _rotate(old_sid: str, session: dict, response: Response) -> str:
    """Ротация session id (anti session fixation): новый id в cookie и в теле ответа."""
    new_sid = await store.rotate_session(old_sid, session)
    _set_session_cookie(response, new_sid)
    response.headers["X-Session-Id"] = new_sid
    response.headers["X-Session-Rotated"] = "1"
    return new_sid


@app.get("/api/me")
async def me(response: Response, sid: Optional[str] = Cookie(default=None)) -> dict:
    old_sid, session = await _require_session(sid)
    session = await _ensure_fresh_access_token(session)
    new_sid = await _rotate(old_sid, session, response)
    user = session["user"]
    return {
        "authenticated": True,
        "session_id": new_sid,
        "user": user,
        "consent_required": not profiles.has_consent(user["sub"]),
    }


@app.post("/api/consent")
async def grant_consent(
    body: ConsentBody,
    response: Response,
    sid: Optional[str] = Cookie(default=None),
) -> dict:
    """Задача 6: явное согласие на использование данных профиля + сохранение в БД."""
    if not body.accepted:
        raise HTTPException(status_code=400, detail="Consent rejected")

    old_sid, session = await _require_session(sid)
    session = await _ensure_fresh_access_token(session)
    user = session["user"]

    # Профиль из Keycloak UserInfo (атрибуты после Identity Brokering / Яндекс ID).
    try:
        profile = await keycloak.fetch_userinfo(session["access_token"])
    except httpx.HTTPStatusError:
        profile = {
            "sub": user["sub"],
            "preferred_username": user.get("username"),
            "email": user.get("email"),
            "name": user.get("name"),
        }

    idp = user.get("idp") or profile.get("identity_provider") or "keycloak"
    profiles.save_with_consent(
        sub=user["sub"],
        username=user.get("username") or profile.get("preferred_username") or "",
        email=user.get("email") or profile.get("email"),
        display_name=user.get("name") or profile.get("name"),
        idp=idp,
        profile=profile,
    )

    new_sid = await _rotate(old_sid, session, response)
    return {
        "status": "consent_granted",
        "session_id": new_sid,
        "profile": profile,
        "idp": idp,
    }


@app.get("/api/profile")
async def get_profile(
    response: Response, sid: Optional[str] = Cookie(default=None)
) -> dict:
    old_sid, session = await _require_session(sid)
    session = await _ensure_fresh_access_token(session)
    new_sid = await _rotate(old_sid, session, response)
    row = profiles.get(session["user"]["sub"])
    if not row or not row["consent_granted"]:
        raise HTTPException(status_code=404, detail="Profile not saved (consent required)")
    return {
        "session_id": new_sid,
        "sub": row["sub"],
        "username": row["username"],
        "email": row["email"],
        "display_name": row["display_name"],
        "idp": row["idp"],
        "profile": __import__("json").loads(row["profile_json"]),
    }


@app.api_route("/api/reports", methods=["GET", "POST"])
async def reports(request: Request, sid: Optional[str] = Cookie(default=None)):
    old_sid, session = await _require_session(sid)
    session = await _ensure_fresh_access_token(session)

    async with httpx.AsyncClient(timeout=30) as client:
        upstream = await client.request(
            method=request.method,
            url=f"{settings.reports_api_url}/reports",
            headers={"Authorization": f"Bearer {session['access_token']}"},
            content=await request.body(),
        )

    response = Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"),
    )
    await _rotate(old_sid, session, response)
    return response
