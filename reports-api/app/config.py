from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Keycloak / валидация токена (resource server, bearer-only) ---
    keycloak_internal_url: str = "http://keycloak:8080"
    keycloak_public_url: str = "http://localhost:8080"
    realm: str = "reports-realm"
    # Роли, дающие доступ к отчётности (business gate). Достаточно любой из них.
    report_roles: str = "prothetic_user,user,administrator"

    # --- ClickHouse (OLAP) ---
    clickhouse_host: str = "clickhouse"
    clickhouse_port: int = 8123
    clickhouse_user: str = "default"
    clickhouse_password: str = ""
    clickhouse_db: str = "reports"

    # Дефолтная глубина отчёта (суток) назад от watermark.
    default_window_days: int = 30

    # --- S3 (MinIO): кеш готовых отчётов ---
    s3_endpoint_url: str = "http://minio:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_region: str = "us-east-1"
    s3_bucket: str = "reports"

    # --- CDN (nginx перед MinIO): публичный адрес раздачи отчётов ---
    cdn_public_url: str = "http://localhost:8082"

    # Секрет для подписи (HMAC) ключей объектов — защита от перебора чужих URL.
    report_url_secret: str = "change-me-report-url-secret"

    @property
    def internal_issuer(self) -> str:
        return f"{self.keycloak_internal_url}/realms/{self.realm}"

    @property
    def public_issuer(self) -> str:
        return f"{self.keycloak_public_url}/realms/{self.realm}"

    @property
    def jwks_uri(self) -> str:
        return f"{self.internal_issuer}/protocol/openid-connect/certs"

    @property
    def allowed_issuers(self) -> set[str]:
        return {self.internal_issuer, self.public_issuer}

    @property
    def report_roles_set(self) -> set[str]:
        return {r.strip() for r in self.report_roles.split(",") if r.strip()}


settings = Settings()
