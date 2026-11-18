"""LangChain-native Gemini Embedding Provider.

Uses LangChain's GoogleGenerativeAIEmbeddings with the working model
`gemini-embedding-001` (3072 dimensions) to generate dense vector embeddings.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from cypher.config import get_settings

logger = logging.getLogger(__name__)


class GeminiEmbeddingError(Exception):
    """Raised when embedding generation fails."""


class GeminiEmbeddingProvider:
    """LangChain GoogleGenerativeAIEmbeddings provider."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()

        self._api_key = api_key or settings.gemini_api_key
        self._model = model or settings.gemini_embedding_model
        self._dimensions = settings.gemini_embedding_dimensions

        if not self._api_key:
            raise GeminiEmbeddingError(
                "GEMINI_API_KEY is not configured in .env."
            )

        try:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings

            self._client = GoogleGenerativeAIEmbeddings(
                model=self._model,
                google_api_key=self._api_key,
            )
            logger.info(
                "GeminiEmbeddingProvider (LangChain) initialized: model=%s, dimensions=%d",
                self._model,
                self._dimensions,
            )
        except Exception as exc:
            raise GeminiEmbeddingError(f"Embedding initialization failed: {exc}") from exc

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of documents for ChromaDB indexing."""
        if not texts:
            return []

        try:
            return self._client.embed_documents(texts)
        except Exception as exc:
            logger.error("LangChain embed_documents error: %s", exc)
            raise GeminiEmbeddingError(f"Embedding failed: {exc}") from exc

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        """Generate query embeddings for a list of questions."""
        if not texts:
            return []
        return [self.embed_query(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        """Generate a single query embedding using LangChain embed_query."""
        try:
            return self._client.embed_query(text)
        except Exception as exc:
            logger.error("LangChain embed_query error: %s", exc)
            raise GeminiEmbeddingError(f"Embedding failed: {exc}") from exc
