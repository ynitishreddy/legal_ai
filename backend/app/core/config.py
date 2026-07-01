from functools import lru_cache
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "ChronoLegal API"
    app_version: str = "1.0.0"
    debug: bool = True
    environment: str = "development"

    host: str = "0.0.0.0"
    port: int = 8000

    database_url: str = "postgresql://postgres:postgres@localhost:5432/chronolegal"

    secret_key: str = "change-this-to-a-secure-random-secret-key-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    upload_directory: str = "uploads"
    max_upload_size: int = 10 * 1024 * 1024  # 10MB default
    allowed_file_types: str = "application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,image/png,image/jpeg,image/jpg"

    # Phase 5.2 — OCR configuration
    tesseract_cmd: Optional[str] = None

    # Phase 6.1 — Embedding configuration
    embedding_model: str = "BAAI/bge-large-en-v1.5"
    embedding_dimension: int = 1024
    embedding_batch_size: int = 16
    embedding_max_retries: int = 3
    embedding_worker_timeout: int = 300
    embedding_max_queue_size: int = 1000
    embedding_gpu_enabled: bool = True
    embedding_model_version: str = "1.5"

    # Phase 6.2 — Qdrant configuration
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_api_key: Optional[str] = None
    qdrant_https: bool = False
    qdrant_collection_name: str = "chronolegal_embeddings"
    qdrant_upload_batch_size: int = 32
    qdrant_upload_timeout: int = 60
    qdrant_max_retries: int = 3

    # Phase 7.1 — LLM & RAG configuration
    default_llm_provider: str = "mock"  # openai, gemini, ollama, mock
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4"
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-1.5-pro"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"



    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
