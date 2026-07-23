from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    keycloak_internal_url: str = "http://keycloak:8080"
    keycloak_public_url: str = "http://localhost:8080"
    realm: str = "reports-realm"

    client_id: str = "reports-frontend"
    client_secret: str = ""
    oidc_scope: str = "openid profile email"

    frontend_url: str = "http://localhost:3000"
    oidc_redirect_uri: str = "http://localhost:3000/callback"
    reports_api_url: str = "http://reports-api:8080"

    redis_url: str = "redis://redis:6379/0"
    session_cookie_name: str = "sid"
    # Сессия > access_token (120 с): нужно для refresh без повторного логина.
    session_ttl_seconds: int = 1800
    # Задание требует Secure. На http://localhost современные браузеры принимают Secure-cookie.
    cookie_secure: bool = True
    cookie_samesite: str = "lax"

    # Шифрование refresh/access в Redis (Fernet из этого секрета).
    token_encryption_key: str = "bionicpro-dev-token-key-change-in-prod"

    # Локальная БД профилей (согласие + данные Яндекс/IdP).
    profile_db_path: str = "/data/profiles.db"

    # UserInfo Keycloak (профиль после брокеринга Яндекс ID).
    @property
    def userinfo_endpoint(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/userinfo"

    @property
    def issuer(self) -> str:
        return f"{self.keycloak_internal_url}/realms/{self.realm}"

    @property
    def public_issuer(self) -> str:
        return f"{self.keycloak_public_url}/realms/{self.realm}"

    @property
    def token_endpoint(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/token"

    @property
    def jwks_uri(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/certs"

    @property
    def end_session_endpoint(self) -> str:
        # Server-to-server revoke refresh_token — только internal URL (из контейнера
        # localhost:8080 недоступен / это не Keycloak).
        return f"{self.issuer}/protocol/openid-connect/logout"

    @property
    def public_end_session_endpoint(self) -> str:
        # Браузерный logout (сброс SSO-cookie Keycloak).
        return f"{self.public_issuer}/protocol/openid-connect/logout"


settings = Settings()
