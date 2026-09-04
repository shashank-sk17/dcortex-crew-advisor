"""Environment-driven config for the ingestion pipeline. No hardcoded secrets."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "crew-ops-advisor-dataset"
DATA_DIR = DATASET_DIR / "data"
INTERNAL_DIR = DATASET_DIR / "internal"
SQL_DIR = Path(__file__).resolve().parents[1] / "sql"

EMBEDDING_DIM = 384
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"


@dataclass(frozen=True)
class Settings:
    database_url: str
    embedding_provider: str  # "local" (fastembed, default) | "openai"
    openai_api_key: str | None
    openai_embedding_model: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.environ.get(
                "DATABASE_URL",
                "postgresql://crewops:crewops@localhost:5433/crewops",
            ),
            embedding_provider=os.environ.get("EMBEDDING_PROVIDER", "local"),
            openai_api_key=os.environ.get("OPENAI_API_KEY"),
            openai_embedding_model=os.environ.get(
                "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"
            ),
        )
