from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    sarvam_api_key: str = ""
    anthropic_api_key: str = ""
    embedding_model_name: str = "BAAI/bge-small-en-v1.5"
    faiss_index_path: str = "backend/cache/faiss_index"
    audio_cache_dir: str = "backend/cache/audio"
    db_path: str = "backend/data/clinic.db"
    allowed_origins: str = "http://localhost:8000"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=str(REPO_ROOT / ".env"), extra="ignore")


settings = Settings()
