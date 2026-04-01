from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized environment-backed settings for Phase 2.

    This is intentionally additive: it can sit on top of the Phase 1 codebase
    without changing the external answer_question(question) contract.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_title: str = "CGI AIO Assistant"
    environment: str = "dev"

    database_url: str = "postgresql+psycopg2://streamlit:streamlit@db:5432/streamlitdb"
    postgres_user: str = "streamlit"
    postgres_password: str = "streamlit_pass"
    postgres_db: str = "streamlitdb"
    postgres_host: str = "db"
    postgres_port: int = 5432

    chroma_dir: str = "/app/vector_store"
    uploads_dir: str = "/app/uploads"
    doc_collection: str = "docs"
    golden_collection: str = "golden_queries"
    feedback_collection: str = "feedback_events"

    rag_enabled: bool = True
    rag_top_k: int = 4
    rag_chunk_size: int = 1200
    rag_chunk_overlap: int = 150
    answer_context_chars: int = 7000

    llm_provider: str = "openai"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "mistral"
    ollama_embedding_model: str = "nomic-embed-text"

    sql_default_limit: int = 50
    max_sql_rows: int = 200
    golden_match_min_score: float = 0.72

    use_langgraph_default: bool = False
    enable_langsmith_default: bool = False
    langsmith_api_key: str | None = None
    langsmith_project: str = "cgi-aio-phase2"
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_workspace_id: str | None = None
    langsmith_mask_inputs: bool = True
    langsmith_mask_outputs: bool = True
    langsmith_tags_csv: str = "cgi,aio,phase2"

    legacy_router_import: str | None = "backend.hybrid_qa"

    @property
    def chroma_path(self) -> Path:
        return Path(self.chroma_dir)

    @property
    def uploads_path(self) -> Path:
        return Path(self.uploads_dir)

    @property
    def langsmith_tags(self) -> list[str]:
        return [item.strip() for item in self.langsmith_tags_csv.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
