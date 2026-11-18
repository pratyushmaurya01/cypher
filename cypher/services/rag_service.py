"""RAG Service — orchestrates the full end-to-end hybrid RAG pipeline.

Pipeline for each chat request:
  1. Validate repository access (done at API layer; service also verifies snapshot exists).
  2. GeminiClient.understand_query()  → QueryUnderstanding
  3. If is_deterministic: use direct Neo4j queries, skip vector/LLM.
  4. Parallel retrieval:
       a. GraphRetriever.retrieve()   → list[GraphResult]
       b. VectorRetriever.retrieve()  → list[VectorResult]
  5. hybrid_retriever.fuse()          → list[FusedEvidence]
  6. context_builder.build()          → (context_str, citations)
  7. GeminiClient.generate_answer()   → Markdown string
  8. Return ChatResponse.

Indexing:
  - index_repository(): called after successful analysis.
  - delete_index(): called on repository deletion.

Security:
  - Repository-level isolation is enforced at API layer (verify_repository_access)
    and double-checked inside ChromaStore.query and VectorRetriever.
  - Graph queries are parameterized and bounded.
  - Gemini is never used to generate Cypher.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from cypher.config import get_settings
from cypher.graph.neo4j_client import Neo4jClient
from cypher.llm.gemini_llm import GeminiClient, GeminiLLMError
from cypher.retrieval import context_builder, hybrid_retriever
from cypher.retrieval.graph_retriever import GraphRetriever
from cypher.retrieval.vector_retriever import VectorRetriever
from cypher.schemas.rag import (
    ChatResponse,
    QueryUnderstanding,
    RetrievalDiagnostics,
    SourceCitation,
)
from cypher.vectorstore.chroma_store import ChromaStore

logger = logging.getLogger(__name__)


class RAGServiceError(Exception):
    """Raised when the RAG pipeline encounters a non-recoverable error."""


class RAGService:
    """Orchestrates Cypher's hybrid RAG pipeline."""

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def index_repository(
        self,
        repository_id: str,
        owner_id: int | str,
        snapshot_dir: Path,
    ) -> dict[str, int | str]:
        """Chunk and embed a repository's source code, then upsert into ChromaDB.

        This is idempotent: unchanged chunks (same content_hash) are skipped.
        Re-indexes automatically if the configured embedding model has changed.

        Args:
            repository_id: Unique repo identifier (used as ChromaDB collection key).
            owner_id:       Repository owner — used only for log messages.
            snapshot_dir:   Absolute path to the repository snapshot on disk.

        Returns:
            Dict with keys: inserted, updated, skipped, deleted, total_chunks.
        """
        settings = get_settings()
        if not settings.rag_enabled:
            logger.info("RAG indexing skipped (GEMINI_API_KEY not configured).")
            return {"status": "disabled"}

        from cypher.embeddings.gemini_embedding import GeminiEmbeddingProvider
        from cypher.vectorstore.chunker import chunk_repository

        logger.info(
            "Starting RAG indexing for repo=%s owner=%s snapshot=%s",
            repository_id, owner_id, snapshot_dir,
        )
        t0 = time.monotonic()

        # 1. Chunk the repository source code
        try:
            chunks = chunk_repository(snapshot_dir, repository_id)
        except Exception as exc:
            raise RAGServiceError(f"Chunking failed: {exc}") from exc

        if not chunks:
            logger.warning("No chunks found in %s — skipping indexing.", snapshot_dir)
            return {"status": "empty", "total_chunks": 0}

        logger.info("Chunked %d code segments from repo=%s", len(chunks), repository_id)

        # 2. Embed chunks using Gemini
        try:
            embedder = GeminiEmbeddingProvider()
            embed_texts = [c.embed_text for c in chunks]
            embeddings = embedder.embed(embed_texts)
        except Exception as exc:
            raise RAGServiceError(f"Embedding failed: {exc}") from exc

        # 3. Upsert into ChromaDB
        try:
            store = ChromaStore()
            stats = store.upsert_chunks(
                repository_id=repository_id,
                chunks=chunks,
                embeddings=embeddings,
                embedding_model=settings.gemini_embedding_model,
            )
        except Exception as exc:
            raise RAGServiceError(f"ChromaDB upsert failed: {exc}") from exc

        elapsed = time.monotonic() - t0
        logger.info(
            "RAG indexing complete for repo=%s in %.1fs: %s",
            repository_id, elapsed, stats,
        )
        stats["total_chunks"] = len(chunks)
        return stats

    def delete_index(self, repository_id: str) -> None:
        """Remove the ChromaDB vector collection for a repository.

        Called when a repository is deleted.  Non-fatal if collection doesn't exist.
        """
        try:
            ChromaStore().delete_repository(repository_id)
        except Exception as exc:
            logger.warning(
                "RAGService.delete_index: failed to delete ChromaDB for repo=%s: %s",
                repository_id, exc,
            )

    # ------------------------------------------------------------------
    # Question Answering
    # ------------------------------------------------------------------

    def answer(
        self,
        question: str,
        repository_id: str,
        owner_id: int | str,
        neo4j_client: Neo4jClient,
        snapshot_dir: Path,
    ) -> ChatResponse:
        """Run the full hybrid RAG pipeline and return a grounded ChatResponse.

        Args:
            question:       User's natural-language question (English/Hindi/Hinglish).
            repository_id:  Repo to query (access already verified at API layer).
            owner_id:       Used for logging only.
            neo4j_client:   Connected Neo4j client for graph retrieval.
            snapshot_dir:   Path to repository snapshot for source code retrieval.

        Returns:
            ChatResponse with answer Markdown, source citations, and diagnostics.

        Raises:
            RAGServiceError: for config errors (no API key, snapshot missing).
            GeminiLLMError:  propagated if Gemini API calls fail.
        """
        settings = get_settings()
        if not settings.rag_enabled:
            raise RAGServiceError(
                "RAG is not enabled. Set GEMINI_API_KEY in .env to use chat features."
            )

        if not snapshot_dir.exists():
            raise RAGServiceError(
                f"Repository snapshot not found at {snapshot_dir}. "
                "Re-upload and analyze the repository."
            )

        pipeline_start = time.monotonic()
        diagnostics = RetrievalDiagnostics()

        # Run through LangGraph StateGraph workflow
        from cypher.rag_graph.graph import rag_pipeline_graph
        from cypher.rag_graph.state import RAGState

        initial_state: RAGState = {
            "question": question,
            "repository_id": repository_id,
            "owner_id": owner_id,
            "snapshot_dir": snapshot_dir,
            "neo4j_client": neo4j_client,
            "start_time": pipeline_start,
            "diagnostics": diagnostics,
            "graph_results": [],
            "vector_results": [],
            "fused_evidence": [],
            "citations": [],
            "final_answer": "",
        }

        try:
            final_state = rag_pipeline_graph.invoke(initial_state)
        except GeminiLLMError:
            raise
        except Exception as exc:
            logger.error("LangGraph execution failed: %s", exc, exc_info=True)
            raise RAGServiceError(f"RAG workflow execution failed: {exc}") from exc

        diagnostics.total_latency_ms = (time.monotonic() - pipeline_start) * 1000

        understanding = final_state.get("understanding")
        intent = understanding.intent if understanding else "overview"

        return ChatResponse(
            repository_id=repository_id,
            question=question,
            intent=intent,
            answer=final_state.get("final_answer", ""),
            sources=final_state.get("citations", []),
            retrieval_diagnostics=diagnostics,
        )

    # ------------------------------------------------------------------
    # Deterministic fast-path
    # ------------------------------------------------------------------

    def _handle_deterministic(
        self,
        question: str,
        understanding: QueryUnderstanding,
        repository_id: str,
        neo4j_client: Neo4jClient,
        snapshot_dir: Path,
        start_time: float,
        diagnostics: RetrievalDiagnostics,
    ) -> ChatResponse:
        """Answer a deterministic question (e.g. 'list all models') using direct Neo4j queries."""
        from cypher.graph.queries import find_entities

        intent = understanding.intent
        entity_types = understanding.graph_search.entity_types or ["Class", "Function"]

        graph_start = time.monotonic()
        all_results = []
        for etype in entity_types:
            rows = find_entities(neo4j_client, repository_id, kind=etype, limit=50)
            all_results.extend(rows)
        diagnostics.graph_latency_ms = (time.monotonic() - graph_start) * 1000
        diagnostics.graph_entities_found = len(all_results)

        if not all_results:
            diagnostics.total_latency_ms = (time.monotonic() - start_time) * 1000
            return _empty_response(
                question, repository_id, understanding,
                f"No {', '.join(entity_types)} entities found in this repository.",
                diagnostics,
            )

        # Build a simple formatted list as the answer
        lines = [f"## {intent.replace('_', ' ').title()}\n"]
        for row in all_results:
            kind = row.get("kind", "?")
            qname = row.get("qualified_name", "?")
            fp = row.get("file_path", "?")
            ln = row.get("line", "?")
            lines.append(f"- **{kind}** `{qname}` — `{fp}` (line {ln})")

        answer_md = "\n".join(lines)
        diagnostics.total_latency_ms = (time.monotonic() - start_time) * 1000

        return ChatResponse(
            repository_id=repository_id,
            question=question,
            intent=understanding.intent,
            answer=answer_md,
            sources=[],
            retrieval_diagnostics=diagnostics,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_response(
    question: str,
    repository_id: str,
    understanding: QueryUnderstanding,
    message: str,
    diagnostics: RetrievalDiagnostics,
) -> ChatResponse:
    return ChatResponse(
        repository_id=repository_id,
        question=question,
        intent=understanding.intent,
        answer=message,
        sources=[],
        retrieval_diagnostics=diagnostics,
    )
