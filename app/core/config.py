from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "fraude-back"
    app_env: str = "development"
    api_v1_str: str = "/api/v1"
    app_base_url: str = "http://127.0.0.1:8000"
    database_url: str = "postgresql+psycopg2://fraude_user:fraude_pass@localhost:5432/fraude_back"
    sqlalchemy_echo: bool = False
    gmail_client_secret_file: str = "credentials.json"
    gmail_token_file: str = "token.json"
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

    @property
    def gmail_keywords_list(self) -> list[str]:
        return [keyword.strip() for keyword in self.gmail_keywords.split(",") if keyword.strip()]


def get_settings() -> Settings:
    return Settings()
