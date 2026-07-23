import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional

from .config import settings

_LOCK = threading.Lock()


class ProfileStore:
    """Локальная БД профилей (согласие + данные из IdP / Яндекс ID)."""

    def __init__(self) -> None:
        Path(settings.profile_db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(settings.profile_db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with _LOCK:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_profiles (
                    sub TEXT PRIMARY KEY,
                    username TEXT,
                    email TEXT,
                    display_name TEXT,
                    idp TEXT,
                    profile_json TEXT NOT NULL,
                    consent_granted INTEGER NOT NULL DEFAULT 0,
                    consent_at TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.commit()

    def get(self, sub: str) -> Optional[dict[str, Any]]:
        with _LOCK:
            row = self._conn.execute(
                "SELECT * FROM user_profiles WHERE sub = ?", (sub,)
            ).fetchone()
        return dict(row) if row else None

    def has_consent(self, sub: str) -> bool:
        row = self.get(sub)
        return bool(row and row["consent_granted"])

    def save_with_consent(self, *, sub: str, username: str, email: str | None,
                          display_name: str | None, idp: str, profile: dict) -> None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        with _LOCK:
            self._conn.execute(
                """
                INSERT INTO user_profiles
                  (sub, username, email, display_name, idp, profile_json,
                   consent_granted, consent_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(sub) DO UPDATE SET
                  username=excluded.username,
                  email=excluded.email,
                  display_name=excluded.display_name,
                  idp=excluded.idp,
                  profile_json=excluded.profile_json,
                  consent_granted=1,
                  consent_at=excluded.consent_at,
                  updated_at=excluded.updated_at
                """,
                (
                    sub,
                    username,
                    email,
                    display_name,
                    idp,
                    json.dumps(profile, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            self._conn.commit()


profiles = ProfileStore()
