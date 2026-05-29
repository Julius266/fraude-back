import os

from pydantic_settings import BaseSettings, SettingsConfigDict

_LOCAL_APP_BASE_URLS = {"http://127.0.0.1:8000", "http://localhost:8000"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "fraude-back"
    app_env: str = "development"
    api_v1_str: str = "/api/v1"
    app_base_url: str = "http://127.0.0.1:8000"
    frontend_url: str = "http://localhost:3000"
    # Can be set directly via DATABASE_URL env var; otherwise assembled from POSTGRES_* parts.
    database_url: str = ""
    postgres_user: str = "fraude_user"
    postgres_password: str = "fraude_pass"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "fraude_back"
    sqlalchemy_echo: bool = False

    @property
    def resolved_database_url(self) -> str:
        """Return DATABASE_URL if explicitly set, otherwise assemble from POSTGRES_* parts."""
        if self.database_url:
            return self.database_url
        # Neon and other cloud Postgres providers require SSL
        ssl_suffix = "?sslmode=require" if self.postgres_host != "localhost" else ""
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}{ssl_suffix}"
        )
    gmail_client_secret_file: str = "credentials.json"
    gmail_token_file: str = "token.json"
    gmail_oauth_redirect_uri: str = "http://127.0.0.1:8000/api/v1/gmail/auth/callback"
    gmail_download_dir: str = "storage/gmail_attachments"
    gmail_watch_topic: str = ""
    gmail_keywords: str = "SINIESTRO,RECLAMO"
    gmail_query_hours_back: int = 48
    gmail_max_results: int = 50
    enable_pdf_ocr: bool = True
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1"
    embedding_model: str = "text-embedding-3-small"
    chat_model: str = ""
    chat_k_results: int = 8
    chat_max_history: int = 10
    chat_session_ttl_seconds: int = 1800
    fraud_rules_examples_file: str = "reglas_fraude_ejemplos.md"
    allowed_origins: str = "http://localhost:3000"
    cors_origin_regex: str = ""

    @property
    def resolved_app_base_url(self) -> str:
        explicit = self.app_base_url.strip().rstrip("/")
        if explicit and explicit not in _LOCAL_APP_BASE_URLS:
            return explicit
        railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip().rstrip("/")
        if railway_domain:
            return f"https://{railway_domain}"
        return explicit or "http://127.0.0.1:8000"

    @property
    def resolved_gmail_oauth_redirect_uri(self) -> str:
        explicit = self.gmail_oauth_redirect_uri.strip()
        if explicit and "127.0.0.1" not in explicit and "localhost" not in explicit:
            return explicit
        return f"{self.resolved_app_base_url}{self.api_v1_str}/gmail/auth/callback"

    @property
    def cors_origin_regex_pattern(self) -> str | None:
        explicit = self.cors_origin_regex.strip()
        if explicit:
            return explicit
        if self.app_env == "production":
            return r"https://.*\.vercel\.app"
        return None

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def gmail_keywords_list(self) -> list[str]:
        return [keyword.strip() for keyword in self.gmail_keywords.split(",") if keyword.strip()]


def get_settings() -> Settings:
    return Settings()
