"""Vector retriever — queries ChromaDB with Gemini embeddings.

Each search query in ``understanding.search_queries`` is embedded
independently and the results are merged (dedup by chunk_id) before
returning the top-k unique chunks.
"""

from __future__ import annotations

import logging
import time

from cypher.embeddings.gemini_embedding import GeminiEmbeddingProvider
from cypher.schemas.rag import QueryUnderstanding, VectorResult
from cypher.vectorstore.chroma_store import ChromaStore

logger = logging.getLogger(__name__)


class VectorRetriever:
    """Retrieve code chunks from ChromaDB using semantic (embedding) search."""

    def __init__(
        self,
        chroma_store: ChromaStore,
        embedding_provider: GeminiEmbeddingProvider,
    ) -> None:
        self._store = chroma_store
        self._embedder = embedding_provider

    def retrieve(
        self,
        understanding: QueryUnderstanding,
        repository_id: str,
        top_k: int = 8,
    ) -> list[VectorResult]:
        """Embed each search query and return the top-k unique chunks.

        Multiple queries are run; results are merged and deduplicated by
        chunk_id.  The best (lowest-distance) score per chunk is kept.
        """
        start = time.monotonic()
        search_queries = understanding.search_queries
        if not search_queries:
            return []

        seen: dict[str, VectorResult] = {}   # chunk_id → best result

        try:
            query_vectors = self._embedder.embed_queries(search_queries)
        except Exception as exc:
            logger.warning("VectorRetriever: embedding failed: %s", exc)
            return []

        for q_vec in query_vectors:
            try:
                raw = self._store.query(
                    repository_id=repository_id,
                    query_vector=q_vec,
                    top_k=top_k,
                )
            except Exception as exc:
                logger.warning("VectorRetriever: ChromaDB query failed: %s", exc)
                continue

            for item in raw:
                chunk_id = item.get("chunk_id", item.get("id", ""))
                meta = item.get("metadata", {})
                # ChromaStore maps cosine distance → score [0,1] (higher = more similar)
                score = float(item.get("score", 0.0))
                # We use 1 - score as "distance" so lower values = better matches for ranking
                distance = 1.0 - score

                # Repo isolation double-check (defence in depth)
                if meta.get("repository_id") != repository_id:
                    logger.warning(
                        "VectorRetriever: cross-repo leak detected — "
                        "chunk repo=%s but query repo=%s; skipping",
                        meta.get("repository_id"),
                        repository_id,
                    )
                    continue

                result = VectorResult(
                    chunk_id=chunk_id,
                    file_path=meta.get("file_path", item.get("file_path", "")),
                    symbol_name=meta.get("symbol_name", item.get("symbol_name", "")),
                    qualified_name=meta.get("qualified_name", item.get("qualified_name", "")),
                    start_line=int(meta.get("start_line", item.get("start_line", 0))),
                    end_line=int(meta.get("end_line", item.get("end_line", 0))),
                    score=distance,
                    snippet=item.get("document", ""),
                )

                # Keep the result with the best (lowest) distance
                if chunk_id not in seen or distance < seen[chunk_id].score:
                    seen[chunk_id] = result

        # Sort by ascending distance (best match first) and return top_k
        ranked = sorted(seen.values(), key=lambda r: r.score)[:top_k]

        elapsed_ms = (time.monotonic() - start) * 1000
        logger.debug(
            "VectorRetriever found %d unique chunks in %.1f ms (repo=%s)",
            len(ranked), elapsed_ms, repository_id,
        )
        return ranked
