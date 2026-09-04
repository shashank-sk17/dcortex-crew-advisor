"""Pluggable embedder. Default is local/offline (fastembed, no API key, no
network dependency once the model is cached) -- matches this project's
"deliberately boring" stack philosophy (README §11) and needs zero extra
credentials for a hackathon. OpenAI is available as a drop-in swap for
production quality if EMBEDDING_PROVIDER=openai is set.

Whichever provider is used, output dimension MUST equal config.EMBEDDING_DIM
(384) -- that's what every vector(384) column in 002_schema_vector.sql expects.
"""
from __future__ import annotations

from typing import Protocol

from . import config


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class LocalEmbedder:
    """fastembed, ONNX-based, no torch, no API key. Model weights are
    downloaded once from Hugging Face and cached under ~/.cache/fastembed."""

    def __init__(self, model_name: str = config.EMBEDDING_MODEL) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model_name)
        self.dim = config.EMBEDDING_DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = [v.tolist() for v in self._model.embed(texts)]
        _assert_dim(vectors, self.dim)
        return vectors


class OpenAIEmbedder:
    def __init__(self, api_key: str, model: str) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self._model = model
        # text-embedding-3-small is 1536-dim by default; truncate to
        # config.EMBEDDING_DIM via the API's `dimensions` param so it still
        # fits the vector(384) columns without a schema change.
        self.dim = config.EMBEDDING_DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = self._client.embeddings.create(
            model=self._model, input=texts, dimensions=self.dim
        )
        vectors = [d.embedding for d in resp.data]
        _assert_dim(vectors, self.dim)
        return vectors


def _assert_dim(vectors: list[list[float]], expected_dim: int) -> None:
    for v in vectors:
        if len(v) != expected_dim:
            raise ValueError(
                f"Embedder returned {len(v)}-dim vector, expected {expected_dim} "
                f"(config.EMBEDDING_DIM). Update EMBEDDING_DIM and every "
                f"vector(N) column in ingestion/sql/002_schema_vector.sql if "
                f"you change embedding model/provider."
            )


def get_embedder(settings: config.Settings) -> Embedder:
    if settings.embedding_provider == "local":
        return LocalEmbedder()
    if settings.embedding_provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError(
                "EMBEDDING_PROVIDER=openai requires OPENAI_API_KEY to be set."
            )
        return OpenAIEmbedder(settings.openai_api_key, settings.openai_embedding_model)
    raise ValueError(
        f"Unknown EMBEDDING_PROVIDER={settings.embedding_provider!r}; "
        f"expected 'local' or 'openai'."
    )
