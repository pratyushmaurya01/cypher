"""Stage 5 RAG pipeline tests.

Tests for:
- CodeChunk creation and ChromaDB serialization
- chunk_repository() on sample_repo
- GeminiEmbeddingProvider (mocked API)
- ChromaStore upsert, query isolation, deletion
- GeminiClient.understand_query() JSON parsing and sanitization
- GraphRetriever (mocked Neo4j)
- VectorRetriever (mocked ChromaStore + embedder)
- HybridRetriever RRF math
- ContextBuilder (mocked SourceCodeService)
- RAGService (mocked end-to-end)
- Chat API endpoint: auth, repo isolation, 503 without key
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sample_py(tmp_path: Path, content: str = "", filename: str = "app.py") -> Path:
    f = tmp_path / filename
    f.write_text(content, encoding="utf-8")
    return f


# ---------------------------------------------------------------------------
# 1. CodeChunk & chunk_repository
# ---------------------------------------------------------------------------

class TestCodeChunk:
    def test_codechunk_creation(self):
        from cypher.vectorstore.chunker import CodeChunk
        chunk = CodeChunk(
            repository_id="repo_test",
            file_path="users/views.py",
            symbol_name="LoginView",
            qualified_name="users.views.LoginView",
            symbol_type="class",
            start_line=10,
            end_line=50,
            source_code="class LoginView:\n    pass\n",
            embed_text="class LoginView (class) in users/views.py\nclass LoginView:\n    pass\n",
        )
        assert chunk.chunk_id  # should be auto-generated hash
        assert chunk.content_hash
        assert chunk.start_line == 10

    def test_codechunk_to_chroma_document(self):
        from cypher.vectorstore.chunker import CodeChunk
        chunk = CodeChunk(
            repository_id="repo_xyz",
            file_path="app/models.py",
            symbol_name="User",
            qualified_name="app.models.User",
            symbol_type="class",
            start_line=5,
            end_line=20,
            source_code="class User(Model):\n    pass\n",
            embed_text="class User in app/models.py",
        )
        doc = chunk.to_chroma_document()
        assert doc["id"] == chunk.chunk_id
        assert doc["document"] == chunk.embed_text
        meta = doc["metadata"]
        assert meta["repository_id"] == "repo_xyz"
        assert meta["file_path"] == "app/models.py"
        assert meta["start_line"] == 5
        assert meta["content_hash"] == chunk.content_hash

    def test_chunk_repository_on_temp_project(self, tmp_path):
        from cypher.vectorstore.chunker import chunk_repository

        # Create a mini Python project
        (tmp_path / "models.py").write_text(
            "class MyModel:\n    '''A model.'''\n    field = None\n\n"
            "def helper():\n    return 42\n",
            encoding="utf-8",
        )
        (tmp_path / "views.py").write_text(
            "def index(request):\n    return 'hello'\n",
            encoding="utf-8",
        )

        chunks = chunk_repository(tmp_path, "repo_tmp")
        assert len(chunks) >= 3  # MyModel, helper, index
        types = {c.symbol_type for c in chunks}
        assert "class" in types
        assert "function" in types
        for c in chunks:
            assert c.repository_id == "repo_tmp"
            assert c.start_line > 0
            assert c.source_code.strip()

    def test_chunk_repository_skips_pycache(self, tmp_path):
        from cypher.vectorstore.chunker import chunk_repository

        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        (pycache / "cached.py").write_text("def should_skip(): pass\n")
        (tmp_path / "real.py").write_text("def real_func(): pass\n")

        chunks = chunk_repository(tmp_path, "repo_cache")
        names = [c.symbol_name for c in chunks]
        assert "should_skip" not in names
        assert "real_func" in names

    def test_chunk_repository_on_sample_repo(self):
        """Integration: chunk the sample_repo that ships with the project."""
        sample = Path("sample_repo")
        if not sample.exists():
            pytest.skip("sample_repo not present in working directory")

        from cypher.vectorstore.chunker import chunk_repository
        chunks = chunk_repository(sample, "repo_sample")
        assert len(chunks) > 0
        file_paths = {c.file_path for c in chunks}
        # sample_repo should have views.py, models.py etc.
        py_files = [p for p in file_paths if p.endswith(".py")]
        assert len(py_files) > 0


# ---------------------------------------------------------------------------
# 2. GeminiEmbeddingProvider (mocked)
# ---------------------------------------------------------------------------

class TestGeminiEmbeddingProvider:
    def _mock_genai(self, vectors):
        """Return a mock genai module that returns the given vectors."""
        mock = MagicMock()
        mock.embed_content.return_value = {"embedding": vectors}
        return mock

    def test_embed_single_text(self):
        fake_vector = [0.1] * 768
        with patch.dict("sys.modules", {"google.generativeai": self._mock_genai([fake_vector])}):
            with patch("cypher.config.get_settings") as mock_settings:
                mock_settings.return_value.gemini_api_key = "fake-key"
                mock_settings.return_value.gemini_embedding_model = "text-embedding-004"
                mock_settings.return_value.gemini_embedding_dimensions = 768

                from cypher.embeddings.gemini_embedding import GeminiEmbeddingProvider
                # Reset the module to pick up mock
                import importlib
                import cypher.embeddings.gemini_embedding as mod
                importlib.reload(mod)

                provider = mod.GeminiEmbeddingProvider.__new__(mod.GeminiEmbeddingProvider)
                provider._api_key = "fake-key"
                provider._model = "text-embedding-004"
                provider._dimensions = 768
                provider._genai = self._mock_genai([fake_vector])

                result = provider.embed(["hello world"])
                assert len(result) == 1
                assert len(result[0]) == 768

    def test_embed_query(self):
        fake_vector = [0.5] * 768
        mock_genai = MagicMock()
        mock_genai.embed_content.return_value = {"embedding": fake_vector}

        from cypher.embeddings.gemini_embedding import GeminiEmbeddingProvider
        provider = GeminiEmbeddingProvider.__new__(GeminiEmbeddingProvider)
        provider._api_key = "fake-key"
        provider._model = "text-embedding-004"
        provider._dimensions = 768
        provider._genai = mock_genai

        result = provider.embed_query("what is login view?")
        assert isinstance(result, list)
        assert len(result) == 768

    def test_embed_queries_multiple(self):
        fake_vector = [0.3] * 768
        mock_genai = MagicMock()
        mock_genai.embed_content.return_value = {"embedding": fake_vector}

        from cypher.embeddings.gemini_embedding import GeminiEmbeddingProvider
        provider = GeminiEmbeddingProvider.__new__(GeminiEmbeddingProvider)
        provider._api_key = "fake-key"
        provider._model = "text-embedding-004"
        provider._dimensions = 768
        provider._genai = mock_genai

        results = provider.embed_queries(["query 1", "query 2", "query 3"])
        assert len(results) == 3
        assert all(len(v) == 768 for v in results)


# ---------------------------------------------------------------------------
# 3. ChromaStore — upsert, query isolation, deletion
# ---------------------------------------------------------------------------

class TestChromaStore:
    def _make_chunks(self, repo_id: str, n: int = 3):
        from cypher.vectorstore.chunker import CodeChunk
        chunks = []
        for i in range(n):
            c = CodeChunk(
                repository_id=repo_id,
                file_path=f"file_{i}.py",
                symbol_name=f"func_{i}",
                qualified_name=f"module.func_{i}",
                symbol_type="function",
                start_line=i * 10 + 1,
                end_line=i * 10 + 9,
                source_code=f"def func_{i}(): return {i}\n",
                embed_text=f"function func_{i} in file_{i}.py",
            )
            chunks.append(c)
        return chunks

    def _make_embeddings(self, n: int, dims: int = 4) -> list[list[float]]:
        import random
        random.seed(42)
        return [[random.random() for _ in range(dims)] for _ in range(n)]

    def test_upsert_and_query(self, tmp_path):
        with patch("cypher.config.get_settings") as mock_settings:
            mock_settings.return_value.chroma_persist_dir = str(tmp_path / "chroma")

            from cypher.vectorstore.chroma_store import ChromaStore
            store = ChromaStore(persist_dir=str(tmp_path / "chroma"))

            chunks = self._make_chunks("repo_A", 3)
            embeddings = self._make_embeddings(3)
            stats = store.upsert_chunks("repo_A", chunks, embeddings, "text-embedding-004")
            assert stats["inserted"] == 3
            assert stats["skipped"] == 0

    def test_idempotent_upsert_skips_unchanged(self, tmp_path):
        from cypher.vectorstore.chroma_store import ChromaStore
        store = ChromaStore(persist_dir=str(tmp_path / "chroma"))
        chunks = self._make_chunks("repo_idem", 2)
        embeddings = self._make_embeddings(2)

        stats1 = store.upsert_chunks("repo_idem", chunks, embeddings, "text-embedding-004")
        assert stats1["inserted"] == 2

        # Second upsert — same chunks, same hash → should skip
        stats2 = store.upsert_chunks("repo_idem", chunks, embeddings, "text-embedding-004")
        assert stats2["skipped"] == 2
        assert stats2["inserted"] == 0

    def test_repository_isolation_query(self, tmp_path):
        """Querying repo_A should not return repo_B results."""
        from cypher.vectorstore.chroma_store import ChromaStore
        store = ChromaStore(persist_dir=str(tmp_path / "chroma"))

        chunks_a = self._make_chunks("repo_A", 2)
        embeds_a = self._make_embeddings(2)
        store.upsert_chunks("repo_A", chunks_a, embeds_a, "text-embedding-004")

        chunks_b = self._make_chunks("repo_B", 2)
        embeds_b = self._make_embeddings(2)
        store.upsert_chunks("repo_B", chunks_b, embeds_b, "text-embedding-004")

        query_vec = [0.5, 0.5, 0.5, 0.5]
        results = store.query("repo_A", query_vec, top_k=10)
        for r in results:
            assert r["metadata"].get("repository_id") == "repo_A"

    def test_delete_repository(self, tmp_path):
        from cypher.vectorstore.chroma_store import ChromaStore
        store = ChromaStore(persist_dir=str(tmp_path / "chroma"))

        chunks = self._make_chunks("repo_del", 2)
        embeddings = self._make_embeddings(2)
        store.upsert_chunks("repo_del", chunks, embeddings, "text-embedding-004")

        store.delete_repository("repo_del")
        stats = store.collection_stats("repo_del")
        assert stats["indexed"] is False

    def test_collection_stats(self, tmp_path):
        from cypher.vectorstore.chroma_store import ChromaStore
        store = ChromaStore(persist_dir=str(tmp_path / "chroma"))
        # Non-existent repo → not indexed
        stats = store.collection_stats("nonexistent_repo_xyz")
        assert stats["indexed"] is False
        assert stats["chunk_count"] == 0


# ---------------------------------------------------------------------------
# 4. GeminiClient — query understanding parsing and sanitization
# ---------------------------------------------------------------------------

class TestGeminiClient:
    def _make_client(self, mock_response_text: str):
        """Build a GeminiClient with mocked model client."""
        from cypher.llm.gemini_llm import GeminiClient
        client = GeminiClient.__new__(GeminiClient)
        client._api_key = "fake-key"
        client._model = "gemini-2.0-flash"

        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = mock_response_text
        mock_model.generate_content.return_value = mock_response
        client._model_client = mock_model
        return client

    def test_understand_query_valid_json(self):
        payload = {
            "intent": "locate_symbol",
            "language": "english",
            "entities": ["LoginView"],
            "keywords": ["login", "view", "authentication"],
            "search_queries": ["How does LoginView work?"],
            "retrieval": {"vector": True, "graph": True},
            "graph_search": {
                "entity_types": ["Class", "Function"],
                "relationship_types": ["CALLS", "IMPORTS"],
                "direction": "both",
                "max_depth": 2,
            },
            "is_deterministic": False,
        }
        client = self._make_client(json.dumps(payload))
        from cypher.schemas.rag import QueryUnderstanding
        result = client.understand_query("How does login work?")
        assert isinstance(result, QueryUnderstanding)
        assert result.intent == "locate_symbol"
        assert result.entities == ["LoginView"]

    def test_understand_query_sanitizes_max_depth(self):
        """max_depth > 3 should be capped to 3 by sanitizer."""
        payload = {
            "intent": "impact_analysis",
            "language": "hindi",
            "entities": ["User"],
            "keywords": ["user"],
            "search_queries": ["User model impact"],
            "retrieval": {"vector": True, "graph": True},
            "graph_search": {
                "entity_types": ["Class"],
                "relationship_types": ["CALLS"],
                "direction": "both",
                "max_depth": 99,  # should be capped
            },
            "is_deterministic": False,
        }
        client = self._make_client(json.dumps(payload))
        result = client.understand_query("User model change impact")
        assert result.graph_search.max_depth <= 3

    def test_understand_query_strips_invalid_relationship_types(self):
        """LLM-invented relationship types should be stripped."""
        payload = {
            "intent": "generic_search",
            "language": "english",
            "entities": [],
            "keywords": [],
            "search_queries": ["find something"],
            "retrieval": {"vector": True, "graph": True},
            "graph_search": {
                "entity_types": ["Function"],
                "relationship_types": ["CALLS", "FAKE_RELATIONSHIP", "MALICIOUS"],
                "direction": "both",
                "max_depth": 2,
            },
            "is_deterministic": False,
        }
        client = self._make_client(json.dumps(payload))
        result = client.understand_query("find something")
        assert "FAKE_RELATIONSHIP" not in result.graph_search.relationship_types
        assert "MALICIOUS" not in result.graph_search.relationship_types
        assert "CALLS" in result.graph_search.relationship_types

    def test_understand_query_caps_search_queries(self):
        """search_queries > 5 should be truncated to 5."""
        payload = {
            "intent": "generic_search",
            "language": "english",
            "entities": [],
            "keywords": [],
            "search_queries": [f"query {i}" for i in range(10)],  # 10 queries
            "retrieval": {"vector": True, "graph": True},
            "graph_search": {
                "entity_types": ["Function"],
                "relationship_types": ["CALLS"],
                "direction": "both",
                "max_depth": 2,
            },
            "is_deterministic": False,
        }
        client = self._make_client(json.dumps(payload))
        result = client.understand_query("test")
        assert len(result.search_queries) <= 5

    def test_understand_query_invalid_json_raises(self):
        from cypher.llm.gemini_llm import GeminiClient, GeminiLLMError
        client = self._make_client("not valid json {{{{")
        with pytest.raises(GeminiLLMError, match="invalid JSON"):
            client.understand_query("test")


# ---------------------------------------------------------------------------
# 5. GraphRetriever (mocked Neo4j client)
# ---------------------------------------------------------------------------

class TestGraphRetriever:
    def _make_neo4j_mock(self, rows: list[dict]) -> MagicMock:
        mock = MagicMock()
        mock.execute_query.return_value = rows
        return mock

    def _make_understanding(
        self,
        intent: str = "locate_symbol",
        entities: list[str] | None = None,
        rel_types: list[str] | None = None,
        direction: str = "both",
        depth: int = 2,
    ):
        from cypher.schemas.rag import GraphSearchConfig, QueryUnderstanding, RetrievalConfig
        return QueryUnderstanding(
            intent=intent,
            language="english",
            entities=entities or [],
            keywords=[],
            search_queries=["test"],
            retrieval=RetrievalConfig(vector=True, graph=True),
            graph_search=GraphSearchConfig(
                entity_types=["Function", "Class"],
                relationship_types=rel_types or ["CALLS"],
                direction=direction,
                max_depth=depth,
            ),
        )

    def test_retrieve_returns_graph_results(self):
        rows = [
            {
                "entity_id": "e1",
                "qualified_name": "users.views.LoginView",
                "file_path": "users/views.py",
                "start_line": 10,
                "end_line": 50,
                "symbol_type": "Class",
            }
        ]
        mock_client = self._make_neo4j_mock(rows)
        from cypher.retrieval.graph_retriever import GraphRetriever
        from cypher.schemas.rag import GraphResult

        gr = GraphRetriever(mock_client)
        understanding = self._make_understanding(entities=["LoginView"])
        results = gr.retrieve(understanding, "repo_test")
        assert isinstance(results, list)
        assert all(isinstance(r, GraphResult) for r in results)

    def test_retrieve_respects_top_k(self):
        rows = [
            {
                "entity_id": f"e{i}",
                "qualified_name": f"module.func_{i}",
                "file_path": f"file_{i}.py",
                "start_line": i,
                "end_line": i + 5,
                "symbol_type": "Function",
            }
            for i in range(20)
        ]
        mock_client = self._make_neo4j_mock(rows)
        from cypher.retrieval.graph_retriever import GraphRetriever

        gr = GraphRetriever(mock_client)
        understanding = self._make_understanding(entities=["some_func"])
        results = gr.retrieve(understanding, "repo_test", top_k=5)
        assert len(results) <= 5

    def test_retrieve_handles_neo4j_error_gracefully(self):
        mock_client = MagicMock()
        mock_client.execute_query.side_effect = Exception("connection refused")

        from cypher.retrieval.graph_retriever import GraphRetriever
        gr = GraphRetriever(mock_client)
        understanding = self._make_understanding(entities=["LoginView"])
        # Should NOT raise — errors logged and return empty list
        results = gr.retrieve(understanding, "repo_test")
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# 6. VectorRetriever (mocked)
# ---------------------------------------------------------------------------

class TestVectorRetriever:
    def _make_chroma_mock(self, hits: list[dict]) -> MagicMock:
        mock = MagicMock()
        mock.query.return_value = hits
        return mock

    def _make_embedder_mock(self, vectors: list[list[float]]) -> MagicMock:
        mock = MagicMock()
        mock.embed_queries.return_value = vectors
        return mock

    def _make_understanding(self, queries: list[str]):
        from cypher.schemas.rag import GraphSearchConfig, QueryUnderstanding, RetrievalConfig
        return QueryUnderstanding(
            intent="generic_search",
            language="english",
            entities=[],
            keywords=[],
            search_queries=queries,
            retrieval=RetrievalConfig(vector=True, graph=True),
            graph_search=GraphSearchConfig(),
        )

    def test_retrieve_returns_vector_results(self):
        hits = [
            {
                "chunk_id": "chunk_1",
                "score": 0.9,
                "document": "def login(): pass",
                "metadata": {
                    "repository_id": "repo_A",
                    "file_path": "views.py",
                    "symbol_name": "login",
                    "qualified_name": "app.views.login",
                    "start_line": 1,
                    "end_line": 10,
                },
            }
        ]
        mock_store = self._make_chroma_mock(hits)
        mock_embedder = self._make_embedder_mock([[0.1] * 4])

        from cypher.retrieval.vector_retriever import VectorRetriever
        from cypher.schemas.rag import VectorResult

        vr = VectorRetriever(mock_store, mock_embedder)
        understanding = self._make_understanding(["how does login work?"])
        results = vr.retrieve(understanding, "repo_A")
        assert isinstance(results, list)
        assert all(isinstance(r, VectorResult) for r in results)

    def test_retrieve_cross_repo_isolation(self):
        """Results with wrong repository_id metadata must be filtered out."""
        hits = [
            {
                "chunk_id": "chunk_evil",
                "score": 0.99,
                "document": "evil code",
                "metadata": {
                    "repository_id": "repo_B",   # WRONG repo!
                    "file_path": "evil.py",
                    "symbol_name": "evil_func",
                    "qualified_name": "evil.func",
                    "start_line": 1,
                    "end_line": 5,
                },
            }
        ]
        mock_store = self._make_chroma_mock(hits)
        mock_embedder = self._make_embedder_mock([[0.1] * 4])

        from cypher.retrieval.vector_retriever import VectorRetriever
        vr = VectorRetriever(mock_store, mock_embedder)
        understanding = self._make_understanding(["something"])
        results = vr.retrieve(understanding, "repo_A")
        # Evil chunk from repo_B must NOT appear in results for repo_A
        ids = [r.chunk_id for r in results]
        assert "chunk_evil" not in ids

    def test_retrieve_handles_embedding_error(self):
        mock_store = MagicMock()
        mock_embedder = MagicMock()
        mock_embedder.embed_queries.side_effect = Exception("API quota exceeded")

        from cypher.retrieval.vector_retriever import VectorRetriever
        vr = VectorRetriever(mock_store, mock_embedder)
        understanding = self._make_understanding(["test"])
        results = vr.retrieve(understanding, "repo_test")
        assert results == []


# ---------------------------------------------------------------------------
# 7. HybridRetriever — RRF fusion math
# ---------------------------------------------------------------------------

class TestHybridRetriever:
    def _make_graph_result(self, file: str, start: int, end: int, qname: str = "") -> "GraphResult":
        from cypher.schemas.rag import GraphResult
        return GraphResult(
            entity_id="e1",
            qualified_name=qname or f"module.{file}_{start}",
            file_path=file,
            start_line=start,
            end_line=end,
            symbol_type="Function",
            score=1.0,
        )

    def _make_vector_result(self, file: str, start: int, end: int, qname: str = "") -> "VectorResult":
        from cypher.schemas.rag import VectorResult
        return VectorResult(
            chunk_id=f"{file}:{start}:{end}",
            file_path=file,
            symbol_name=qname.split(".")[-1] if qname else file,
            qualified_name=qname or f"module.{file}_{start}",
            start_line=start,
            end_line=end,
            score=0.1,
        )

    def test_rrf_score_formula(self):
        from cypher.retrieval.hybrid_retriever import _rrf_score
        # rank 1 should have score 1/(60+1) = ~0.0164
        s1 = _rrf_score(1)
        s2 = _rrf_score(2)
        assert s1 > s2
        assert abs(s1 - 1 / 61) < 1e-9

    def test_fuse_graph_only(self):
        from cypher.retrieval.hybrid_retriever import fuse
        graph = [
            self._make_graph_result("a.py", 1, 10),
            self._make_graph_result("b.py", 20, 30),
        ]
        result = fuse(graph, [], max_evidence=5)
        assert len(result) == 2
        # First item should have higher RRF score
        assert result[0].rrf_score > result[1].rrf_score

    def test_fuse_vector_only(self):
        from cypher.retrieval.hybrid_retriever import fuse
        vector = [
            self._make_vector_result("x.py", 5, 15),
            self._make_vector_result("y.py", 100, 120),
        ]
        result = fuse([], vector, max_evidence=5)
        assert len(result) == 2
        assert result[0].source == "vector"

    def test_fuse_hybrid_boosts_shared_items(self):
        """Item appearing in both graph and vector lists should get a higher RRF score."""
        from cypher.retrieval.hybrid_retriever import fuse

        # Same file/lines in both lists → should be "hybrid" and boosted
        shared_file, shared_start, shared_end = "shared.py", 10, 30
        graph = [
            self._make_graph_result(shared_file, shared_start, shared_end, "mod.shared"),
            self._make_graph_result("only_graph.py", 1, 5),
        ]
        vector = [
            self._make_vector_result(shared_file, shared_start, shared_end, "mod.shared"),
            self._make_vector_result("only_vector.py", 50, 60),
        ]
        result = fuse(graph, vector, max_evidence=10)
        shared = next(
            (r for r in result if r.file_path == shared_file), None
        )
        assert shared is not None
        assert shared.source == "hybrid"
        # Hybrid item should have higher score than graph-only or vector-only
        graph_only = next(r for r in result if r.file_path == "only_graph.py")
        assert shared.rrf_score > graph_only.rrf_score

    def test_fuse_respects_max_evidence(self):
        from cypher.retrieval.hybrid_retriever import fuse
        graph = [self._make_graph_result(f"g{i}.py", i, i + 5) for i in range(10)]
        vector = [self._make_vector_result(f"v{i}.py", i * 10, i * 10 + 5) for i in range(10)]
        result = fuse(graph, vector, max_evidence=5)
        assert len(result) <= 5


# ---------------------------------------------------------------------------
# 8. ContextBuilder (mocked SourceCodeService)
# ---------------------------------------------------------------------------

class TestContextBuilder:
    def _make_evidence(self, file: str, start: int, end: int, source: str = "graph"):
        from cypher.schemas.rag import FusedEvidence
        return FusedEvidence(
            dedup_key=f"{file}:{start}:{end}",
            file_path=file,
            symbol_name=file.replace(".py", ""),
            qualified_name=f"module.{file.replace('.py', '')}",
            symbol_type="Function",
            start_line=start,
            end_line=end,
            rrf_score=0.9,
            source=source,
        )

    def test_build_context_happy_path(self, tmp_path):
        from cypher.retrieval.context_builder import build_context

        # Create a real file in a tmp directory
        (tmp_path / "views.py").write_text(
            "def login(request):\n    return 'ok'\n",
            encoding="utf-8",
        )
        evidence = [self._make_evidence("views.py", 1, 2)]
        context_str, citations = build_context(evidence, tmp_path, "repo_test")

        assert "views.py" in context_str
        assert "login" in context_str
        assert len(citations) == 1
        assert citations[0].file_path == "views.py"
        assert "login" in citations[0].snippet

    def test_build_context_skips_missing_files(self, tmp_path):
        from cypher.retrieval.context_builder import build_context

        evidence = [self._make_evidence("nonexistent.py", 1, 10)]
        context_str, citations = build_context(evidence, tmp_path, "repo_test")
        assert len(citations) == 0
        assert "No code evidence" in context_str

    def test_build_context_respects_budget(self, tmp_path):
        from cypher.retrieval.context_builder import build_context

        big_code = "x = 1\n" * 2000   # ~12000 chars
        (tmp_path / "big.py").write_text(big_code, encoding="utf-8")
        evidence = [self._make_evidence("big.py", 1, 2000)]

        context_str, citations = build_context(
            evidence, tmp_path, "repo_test", max_chars=500
        )
        assert len(context_str) < 2000  # should be truncated


# ---------------------------------------------------------------------------
# 9. RAGService (end-to-end with mocks)
# ---------------------------------------------------------------------------

class TestRAGService:
    def _mock_settings(self, enabled: bool = True):
        mock = MagicMock()
        mock.rag_enabled = enabled
        mock.rag_graph_top_k = 5
        mock.rag_vector_top_k = 5
        mock.rag_max_evidence = 8
        mock.rag_context_max_tokens = 3000
        mock.gemini_embedding_model = "text-embedding-004"
        mock.is_development = True
        return mock

    def test_index_repository_disabled_when_no_key(self, tmp_path):
        from cypher.services.rag_service import RAGService

        with patch("cypher.services.rag_service.get_settings") as ms:
            ms.return_value = self._mock_settings(enabled=False)
            svc = RAGService()
            result = svc.index_repository("repo_test", 1, tmp_path)
            assert result.get("status") == "disabled"

    def test_answer_raises_when_rag_disabled(self, tmp_path):
        from cypher.services.rag_service import RAGService, RAGServiceError

        with patch("cypher.services.rag_service.get_settings") as ms:
            ms.return_value = self._mock_settings(enabled=False)
            svc = RAGService()
            with pytest.raises(RAGServiceError, match="not enabled"):
                svc.answer("test", "repo_test", 1, MagicMock(), tmp_path)

    def test_answer_raises_when_snapshot_missing(self, tmp_path):
        from cypher.services.rag_service import RAGService, RAGServiceError

        with patch("cypher.services.rag_service.get_settings") as ms:
            ms.return_value = self._mock_settings(enabled=True)
            svc = RAGService()
            missing_path = tmp_path / "does_not_exist"
            with pytest.raises(RAGServiceError, match="snapshot not found"):
                svc.answer("test", "repo_test", 1, MagicMock(), missing_path)

    def test_delete_index_does_not_raise(self):
        from cypher.services.rag_service import RAGService

        with patch("cypher.services.rag_service.ChromaStore") as mock_store_cls:
            mock_store_cls.return_value.delete_repository.side_effect = Exception("not found")
            svc = RAGService()
            # Should NOT raise — delete is non-fatal
            svc.delete_index("repo_xyz")


# ---------------------------------------------------------------------------
# 10. Chat API endpoint
# ---------------------------------------------------------------------------

class TestChatEndpoint:
    """Test the /api/v1/chat/{repository_id} endpoint."""

    def test_chat_returns_503_when_rag_disabled(self, client, auth_headers, test_repo):
        """If GEMINI_API_KEY is not configured, chat must return 503."""
        with patch("cypher.api.v1.chat.get_settings") as ms:
            ms.return_value.rag_enabled = False
            ms.return_value.is_development = True
            response = client.post(
                f"/api/v1/chat/{test_repo}",
                headers=auth_headers,
                json={"question": "How does login work?"},
            )
            assert response.status_code == 503

    def test_chat_requires_authentication(self, client, test_repo):
        """Unauthenticated requests must return 401."""
        response = client.post(
            f"/api/v1/chat/{test_repo}",
            json={"question": "How does login work?"},
        )
        assert response.status_code == 401

    def test_chat_returns_403_for_wrong_user(self, client, test_repo, other_auth_headers):
        """A user who does not own the repo must get 403."""
        with patch("cypher.api.v1.chat.get_settings") as ms:
            ms.return_value.rag_enabled = True
        response = client.post(
            f"/api/v1/chat/{test_repo}",
            headers=other_auth_headers,
            json={"question": "How does login work?"},
        )
        assert response.status_code in (403, 404)

    def test_chat_returns_404_for_nonexistent_repo(self, client, auth_headers):
        """Non-existent repository must return 404."""
        with patch("cypher.api.v1.chat.get_settings") as ms:
            ms.return_value.rag_enabled = True
        response = client.post(
            "/api/v1/chat/repo_nonexistent_xyz",
            headers=auth_headers,
            json={"question": "How does login work?"},
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# RAG-specific pytest fixtures
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from cypher.db.models import Base, RepositoryMetadata, User
from cypher.db.session import get_db
from cypher.main import create_app


@pytest.fixture()
def db_session():
    """Create an isolated in-memory SQLite database for the test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db_session):
    """TestClient that uses isolated in-memory DB and mocked Neo4j without triggering live lifespan."""
    app = create_app()
    # Disable lifespan execution in TestClient by avoiding context manager entry
    app.dependency_overrides[get_db] = lambda: db_session

    mock_instance = MagicMock()
    mock_instance.verify_connectivity.return_value = True

    test_client = TestClient(app, raise_server_exceptions=True)
    test_client.app.state.neo4j_client = mock_instance
    yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(db_session):
    """Auth headers for primary test user (direct token generation, bypassing slow bcrypt)."""
    from cypher.core.security import create_access_token
    user = User(
        email="alice@test.com",
        hashed_password="mock_hashed_password",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    token = create_access_token(subject=user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def test_repo(auth_headers, db_session, tmp_path):
    """Create and register an analyzed test repository owned by alice."""
    user = db_session.query(User).filter(User.email == "alice@test.com").first()
    repo_id = "repo_test_rag_123"
    snapshot = tmp_path / "test_snapshot"
    snapshot.mkdir(parents=True, exist_ok=True)
    (snapshot / "views.py").write_text("def login(): pass\n", encoding="utf-8")

    record = RepositoryMetadata(
        repository_id=repo_id,
        owner_id=user.id if user else 1,
        name="test_repo",
        storage_path=str(snapshot),
        status="analyzed",
        current_version=1,
    )
    db_session.add(record)
    db_session.commit()
    return repo_id


@pytest.fixture
def other_auth_headers(db_session):
    """Auth headers for a second (non-owner) user."""
    from cypher.core.security import create_access_token
    user = User(
        email="bob@test.com",
        hashed_password="mock_hashed_password",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    token = create_access_token(subject=user.id)
    return {"Authorization": f"Bearer {token}"}
