"""Persistent ChromaDB vector store with repository-level tenant isolation.

Design decisions:
  - Each repository gets its own ChromaDB collection: ``cypher_repo_{repository_id}``
    This provides hard physical isolation — a query on one collection can never
    surface documents from another repository's collection.
  - Embeddings are stored alongside metadata so retrieval returns everything
    needed to build citations without additional DB round-trips.
  - Upsert is idempotent: existing chunks with unchanged content_hash are skipped.
  - Stale chunks (deleted or re-chunked symbols) are removed via set-difference.
  - If the embedding model changes, all chunks for that repo are re-indexed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ChromaDB collection name prefix — repo ID is appended
_COLLECTION_PREFIX = "cypher_repo_"


class ChromaStoreError(Exception):
    """Raised when ChromaDB operations fail."""


class ChromaStore:
    """Persistent ChromaDB client managing per-repository vector collections."""

    def __init__(self, persist_dir: str | None = None) -> None:
        from cypher.config import get_settings
        settings = get_settings()
        _dir = persist_dir or settings.chroma_persist_dir

        try:
            import chromadb  # type: ignore
            self._client = chromadb.PersistentClient(path=str(Path(_dir).resolve()))
            logger.info("ChromaDB initialized at: %s", _dir)
        except ImportError as exc:
            raise ChromaStoreError(
                "chromadb package is required. Run: pip install chromadb"
            ) from exc
        except Exception as exc:
            raise ChromaStoreError(f"ChromaDB initialization failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Collection helpers
    # ------------------------------------------------------------------

    def _collection_name(self, repository_id: str) -> str:
        # ChromaDB collection names must be [a-zA-Z0-9_-], 3-512 chars
        return f"{_COLLECTION_PREFIX}{repository_id}"

    def _get_or_create_collection(self, repository_id: str):
        """Return (or create) the collection for this repository."""
        name = self._collection_name(repository_id)
        return self._client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

    def _get_collection(self, repository_id: str):
        """Return existing collection or raise ChromaStoreError."""
        name = self._collection_name(repository_id)
        try:
            return self._client.get_collection(name=name)
        except Exception as exc:
            raise ChromaStoreError(
                f"Collection for repository '{repository_id}' does not exist. "
                "Index the repository first."
            ) from exc

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def upsert_chunks(
        self,
        repository_id: str,
        chunks,          # list[CodeChunk]
        embeddings: list[list[float]],
        embedding_model: str,
    ) -> dict[str, int]:
        """Idempotent upsert of code chunks with pre-computed embeddings.

        Skips unchanged chunks (matching content_hash).  Removes stale chunks
        (chunks present in DB but absent from the new index).  Flags re-index
        if embedding model changed.

        Returns dict with inserted, updated, skipped, deleted counts.
        """
        if len(chunks) != len(embeddings):
            raise ChromaStoreError(
                f"Chunk count ({len(chunks)}) != embedding count ({len(embeddings)})"
            )

        collection = self._get_or_create_collection(repository_id)

        # Fetch ALL existing chunk IDs and their content_hashes + embedding model
        existing_ids: set[str] = set()
        existing_hashes: dict[str, str] = {}
        existing_model: str = ""
        try:
            existing = collection.get(include=["metadatas"])
            for doc_id, meta in zip(existing["ids"], existing["metadatas"] or []):
                existing_ids.add(doc_id)
                existing_hashes[doc_id] = (meta or {}).get("content_hash", "")
                if not existing_model and meta:
                    existing_model = meta.get("embedding_model", "")
        except Exception:
            pass  # Empty collection

        # If embedding model changed, force full re-index by clearing hashes
        force_reindex = bool(existing_model and existing_model != embedding_model)
        if force_reindex:
            logger.warning(
                "Embedding model changed (%s → %s): forcing full re-index for repo %s",
                existing_model, embedding_model, repository_id,
            )

        new_ids = {chunk.chunk_id for chunk in chunks}
        stale_ids = existing_ids - new_ids

        inserted = updated = skipped = 0

        # Upsert in batches of 100
        for batch_start in range(0, len(chunks), 100):
            batch_chunks = chunks[batch_start : batch_start + 100]
            batch_embeds = embeddings[batch_start : batch_start + 100]

            ids, documents, metas, vecs = [], [], [], []
            for chunk, vector in zip(batch_chunks, batch_embeds):
                doc = chunk.to_chroma_document()
                doc["metadata"]["embedding_model"] = embedding_model

                old_hash = existing_hashes.get(chunk.chunk_id, "")
                if not force_reindex and old_hash == chunk.content_hash:
                    skipped += 1
                    continue

                ids.append(doc["id"])
                documents.append(doc["document"])
                metas.append(doc["metadata"])
                vecs.append(vector)

                if chunk.chunk_id in existing_ids:
                    updated += 1
                else:
                    inserted += 1

            if ids:
                collection.upsert(
                    ids=ids,
                    documents=documents,
                    metadatas=metas,
                    embeddings=vecs,
                )

        # Remove stale chunks
        deleted = 0
        if stale_ids:
            collection.delete(ids=list(stale_ids))
            deleted = len(stale_ids)
            logger.info("Deleted %d stale chunks for repo %s", deleted, repository_id)

        logger.info(
            "ChromaDB upsert complete: +%d inserted, %d updated, %d skipped, %d deleted",
            inserted, updated, skipped, deleted,
        )
        return {"inserted": inserted, "updated": updated, "skipped": skipped, "deleted": deleted}

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query(
        self,
        repository_id: str,
        query_vector: list[float],
        top_k: int = 8,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search within a repository's collection.

        Returns a list of dicts with keys:
            chunk_id, score, metadata, document, file_path, start_line, end_line.

        Repository isolation is enforced: collection is scoped to repository_id,
        and metadata is also checked.
        """
        try:
            collection = self._get_collection(repository_id)
        except ChromaStoreError:
            return []

        # Build where filter — always include repository_id guard
        base_where: dict[str, Any] = {"repository_id": {"$eq": repository_id}}
        if where:
            base_where.update(where)

        try:
            result = collection.query(
                query_embeddings=[query_vector],
                n_results=min(top_k, collection.count() or 1),
                where=base_where if collection.count() > 0 else None,
                include=["metadatas", "documents", "distances"],
            )
        except Exception as exc:
            logger.error("ChromaDB query failed: %s", exc)
            return []

        hits = []
        ids = result.get("ids", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        docs = result.get("documents", [[]])[0]
        distances = result.get("distances", [[]])[0]

        for doc_id, meta, doc, dist in zip(ids, metas, docs, distances):
            # Double-check repository isolation (defense in depth)
            if (meta or {}).get("repository_id") != repository_id:
                continue
            # Convert cosine distance [0,2] to similarity score [0,1]
            score = 1.0 - (dist / 2.0) if dist is not None else 0.0
            hits.append({
                "chunk_id": doc_id,
                "score": round(score, 4),
                "document": doc,
                "metadata": meta or {},
                "file_path": (meta or {}).get("file_path", ""),
                "symbol_name": (meta or {}).get("symbol_name", ""),
                "qualified_name": (meta or {}).get("qualified_name", ""),
                "symbol_type": (meta or {}).get("symbol_type", ""),
                "start_line": (meta or {}).get("start_line", 0),
                "end_line": (meta or {}).get("end_line", 0),
                "docstring": (meta or {}).get("docstring", ""),
                "signature": (meta or {}).get("signature", ""),
            })

        return hits

    # ------------------------------------------------------------------
    # Management
    # ------------------------------------------------------------------

    def delete_repository(self, repository_id: str) -> None:
        """Delete all indexed chunks for a repository (called on repo deletion)."""
        name = self._collection_name(repository_id)
        try:
            self._client.delete_collection(name=name)
            logger.info("Deleted ChromaDB collection: %s", name)
        except Exception as exc:
            logger.warning("Could not delete ChromaDB collection %s: %s", name, exc)

    def collection_stats(self, repository_id: str) -> dict[str, Any]:
        """Return basic statistics about the repository's vector collection."""
        try:
            collection = self._get_collection(repository_id)
            count = collection.count()
            return {"repository_id": repository_id, "chunk_count": count, "indexed": True}
        except ChromaStoreError:
            return {"repository_id": repository_id, "chunk_count": 0, "indexed": False}

    def get_indexed_chunk_count(self, repository_id: str) -> int:
        """Return number of indexed chunks for a repository (0 if not indexed)."""
        return self.collection_stats(repository_id).get("chunk_count", 0)
