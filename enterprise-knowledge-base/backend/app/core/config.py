from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict
import os


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Enterprise Knowledge Base"
    debug: bool = False

    secret_key: str = "change-me-in-production-use-openssl-rand-hex-32"
    access_token_expire_minutes: int = 60 * 24

    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    chroma_path: str = "./data/chroma"
    upload_dir: str = "./data/uploads"

    max_upload_mb: int = 50

    # LLM / Embedding (OpenAI-compatible). Keys only from env — never returned to client.
    openai_api_base: str = "https://api.siliconflow.cn/v1"
    openai_api_key: str = os.getenv("SILICONFLOW_API_KEY")
    llm_model: str = "Qwen/Qwen3-Coder-30B-A3B-Instruct"

    embedding_model: str = "Qwen/Qwen3-Embedding-8B"

    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
