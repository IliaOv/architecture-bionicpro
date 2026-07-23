import json
import secrets
import time
from typing import Any, Optional

import redis.asyncio as redis

from .config import settings
from .crypto import decrypt, encrypt

_SESSION_PREFIX = "sess:"
_TOKEN_FIELDS = ("access_token", "refresh_token")


class SessionStore:
    """Распределённый кеш сессий: access/refresh хранятся в Redis в зашифрованном виде."""

    def __init__(self) -> None:
        self._redis = redis.from_url(settings.redis_url, decode_responses=True)

    async def create_session(self, data: dict) -> str:
        session_id = secrets.token_urlsafe(48)
        await self._save(session_id, data)
        return session_id

    async def get_session(self, session_id: str) -> Optional[dict]:
        raw = await self._redis.get(_SESSION_PREFIX + session_id)
        if not raw:
            return None
        return self._decrypt_tokens(json.loads(raw))

    async def update_session(self, session_id: str, data: dict) -> None:
        await self._save(session_id, data)

    async def delete_session(self, session_id: str) -> None:
        await self._redis.delete(_SESSION_PREFIX + session_id)

    async def rotate_session(self, old_session_id: str, data: dict) -> str:
        """Session fixation: новый session id, токены перепривязаны, старый id инвалидирован."""
        new_session_id = secrets.token_urlsafe(48)
        await self._save(new_session_id, data)
        await self._redis.delete(_SESSION_PREFIX + old_session_id)
        return new_session_id

    async def _save(self, session_id: str, data: dict) -> None:
        await self._redis.set(
            _SESSION_PREFIX + session_id,
            json.dumps(self._encrypt_tokens(data)),
            ex=settings.session_ttl_seconds,
        )

    @staticmethod
    def _encrypt_tokens(data: dict) -> dict[str, Any]:
        out = dict(data)
        for field in _TOKEN_FIELDS:
            if field in out and out[field] and not str(out[field]).startswith("enc:"):
                out[field] = "enc:" + encrypt(out[field])
        return out

    @staticmethod
    def _decrypt_tokens(data: dict) -> dict[str, Any]:
        out = dict(data)
        for field in _TOKEN_FIELDS:
            val = out.get(field)
            if isinstance(val, str) and val.startswith("enc:"):
                out[field] = decrypt(val[4:])
        return out


def now() -> int:
    return int(time.time())


store = SessionStore()
