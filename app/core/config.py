from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "fraude-back"
    app_env: str = "development"
    api_v1_str: str = "/api/v1"
    database_url: str = "postgresql+psycopg2://fraude_user:fraude_pass@localhost:5432/fraude_back"
    sqlalchemy_echo: bool = False
    enable_schema_sync: bool = False
    gmail_client_secret_file: str = "/app/credentials.json"
    gmail_token_file: str = "/app/token.json"
    gmail_download_dir: str = "storage/gmail_attachments"
    gmail_watch_topic: str = ""
    gmail_keywords: str = "SINIESTRO,RECLAMO"
    gmail_query_hours_back: int = 48
    gmail_max_results: int = 50
    enable_pdf_ocr: bool = True

    @property
    def gmail_keywords_list(self) -> list[str]:
        return [keyword.strip() for keyword in self.gmail_keywords.split(",") if keyword.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
