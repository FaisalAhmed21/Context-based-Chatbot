

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(

        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    groq_api_key: str = ""
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    llm_provider: str = "groq"
    llm_fallback_provider: str = "gemini"
    llm_model: str = "openai/gpt-oss-20b"
    llm_fallback_model: str = "gemini-3.6-flash"

    embedding_provider: str = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    pdf_parser: str = "auto"

    hybrid_enabled: bool = True
    rerank_enabled: bool = True
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"

    relevance_threshold: float = 0.35

    rerank_threshold: float = -5.0

    groundedness_enabled: bool = True

    agentic_enabled: bool = True
    hyde_enabled: bool = False

    graphrag_enabled: bool = True
    contextual_retrieval_llm: bool = True

    use_langgraph: bool = False

    auth_enabled: bool = False
    google_client_id: str = ""
    auth_jwt_secret: str = ""
    auth_token_days: int = 14
    log_level: str = "INFO"

    database_url: str = "sqlite+aiosqlite:///./ragchatbot.db"

    qdrant_url: str = ""
    qdrant_api_key: str = ""
    qdrant_path: str = "./qdrant_data"
    qdrant_collection: str = "document_chunks"
    redis_url: str = "redis://localhost:6379/0"

    backend_cors_origins: str = "http://localhost:3000"
    upload_dir: str = "./uploads"
    max_upload_mb: int = 50

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.backend_cors_origins.split(",") if o.strip()]

@lru_cache
def get_settings() -> Settings:
    return Settings()
